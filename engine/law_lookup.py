"""即時查全國法規資料庫：依法規名稱與條號查單條條文，或依關鍵字搜條文內容。

官網單條頁面網址有固定規律(LawSingle.aspx?pcode=<法規代碼>&flno=<條號>)，缺的只是
「法規名稱 → pcode」對照。對照表來自 scripts/build_law_index.py 從法務部開放資料建立的
corpus/statutes/law_index.json(全部中文法律與命令，含已廢止者)；條文本身一律即時回官網抓，
不讀 corpus/statutes/*.txt 的舊版法典。查過的條文進 engine/retrieval_cache.py 的快取(7 天有效)。

關鍵字搜尋分兩層(2026-11-01 實測)：整合查詢(Law/LawSearchResult.aspx?cur=Ld)只列出「哪些法規的條文含此詞」，
要看條文須再對個別法規做條文檢索(LawClass/LawSearchContent.aspx?pcode=)。

本模組也是查證引擎(verify.py)的法規名稱來源：索引裡的法規都能查證，但查得到條文不代表書狀引用已 published。
"""
import difflib
import functools
import html as html_module
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_TIMEOUT = 20
STATUTES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'corpus', 'statutes')
NETWORK_ERRORS = (urllib.error.URLError, TimeoutError, ssl.SSLError, ConnectionError, OSError)
RETRY_GAP = 1.5
LAW_INDEX_PATH = os.path.join(STATUTES_DIR, 'law_index.json')
LAW_SITE = "https://law.moj.gov.tw"
MAX_EXPANDED_LAWS = 5
_LAW_LINK_RE = re.compile(r'id="hlkLawLink"[^>]*title="([^"]+)"[^>]*pcode=([A-Za-z0-9]+)[^>]*>.*?</a>\s*'
                          r'(?:\(\s*民國\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日\s*\))?', re.S)
_LAW_TOTAL_RE = re.compile(r'共\s*([0-9,]+)\s*筆')
_CONTENT_ROW_RE = re.compile(r'flno=([0-9-]+)[^"]*">\s*第\s*[0-9-]+\s*條\s*</a>(.*?)(?=<div class="row">|\Z)', re.S)

# 條號接受「33」「第33條」「191之2」「191-2」「第191條之2」等寫法，統一成官網 flno 的「N-M」格式。
_ARTICLE_RE = re.compile(r'(?:第\s*)?([0-9]+)\s*(?:條)?\s*(?:(?:之|-)\s*([0-9]+))?')
# 單一字串「民法第191條之2」:須有「第…條」才拆，避免法規名稱本身含數字時誤切。
_COMBINED_RE = re.compile(r'(.+?)\s*第\s*([0-9]+)\s*條\s*(?:之\s*([0-9]+))?')

# 書狀與判決常用的簡稱 → 官方全名(索引只有全名)。查證引擎與判決法條擷取共用。
ALIASES = {
    "刑法": "中華民國刑法",
    "勞基法": "勞動基準法",
    "消保法": "消費者保護法",
    "個資法": "個人資料保護法",
    "民訴法": "民事訴訟法",
    "刑訴法": "刑事訴訟法",
    "公平法": "公平交易法",
    "證交法": "證券交易法",
    "國賠法": "國家賠償法",
    "勞退條例": "勞工退休金條例",
    "強執法": "強制執行法",
    "家事法": "家事事件法",
    "公寓大廈條例": "公寓大廈管理條例",
    "消債條例": "消費者債務清理條例",
    "道交條例": "道路交通管理處罰條例",
}


def _network_call(call):
    """區分連線失敗與查無：→ (結果, 嘗試次數, 錯誤訊息)。"""
    try:
        return call(), 1, None
    except NETWORK_ERRORS as error:
        return None, 1, str(error)


def with_retry(call, gap=RETRY_GAP):
    """連線失敗重試一次；第二次仍失敗時照常拋出。"""
    try:
        return call()
    except NETWORK_ERRORS:
        time.sleep(gap)
        return call()


def _fetch_article_page(pcode, article_no, timeout=DEFAULT_TIMEOUT):
    url = f"{LAW_SITE}/LawClass/LawSingle.aspx?pcode={pcode}&flno={article_no}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8"), url


def _parse_article_html(html, article_no):
    """單條頁面 → 條文文字；頁面沒有條文區塊時回 None。"""
    start = html.find('<div class="law-article">')
    if start == -1:
        return None
    end = html.find('<div class="clearfix">', start)
    if end == -1:
        end = start + 3000
    fragment = html[start:end]
    fragment = re.sub(r'<div[^>]*>', '\n', fragment)
    fragment = re.sub(r'</div>', '\n', fragment)
    fragment = re.sub(r'<[^>]+>', '', fragment)
    lines = [l.strip() for l in fragment.split('\n') if l.strip()]
    return f"第 {article_no} 條\n" + '\n'.join(lines)


def normalize_article_no(text):
    m = _ARTICLE_RE.fullmatch(str(text).strip())
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2)}" if m.group(2) else m.group(1)


def split_query(parts):
    """CLI 參數 → (法規名稱, 條號)。接受「民法 33」「民法 第191條之2」或單一「民法第191條之2」。"""
    if len(parts) >= 2:
        return parts[0].strip(), ''.join(parts[1:])
    m = _COMBINED_RE.fullmatch(parts[0].strip()) if parts else None
    if not m:
        return None
    return m.group(1), m.group(2) + (f"之{m.group(3)}" if m.group(3) else '')


@functools.lru_cache(maxsize=None)
def load_law_index(path=LAW_INDEX_PATH):
    if not os.path.isfile(path):
        return {}
    with open(path, encoding='utf-8') as f:
        return json.load(f)['laws']


def resolve_law(law_name, index=None):
    """→ {law_name, pcode, level, abandoned, modified_date}，查無回 None。
    簡稱(ALIASES，如「勞基法」)也認得，回傳時換成官方全名。"""
    index = load_law_index() if index is None else index
    name = law_name.strip()
    name = name if name in index else ALIASES.get(name)
    return {'law_name': name, **index[name]} if name in index else None


def known_law_names(index=None):
    """→ 引用中可能出現的法規名稱集合(官方全名＋簡稱)，供引用解析找「最長的法規名稱」。"""
    index = load_law_index() if index is None else index
    return set(index) | {alias for alias, name in ALIASES.items() if name in index}


def suggest_laws(law_name, index=None, limit=5):
    """名稱打錯或不完整時給候選：先列包含輸入字串的現行法規，再補字形相近者。"""
    index = load_law_index() if index is None else index
    name = law_name.strip()
    contains = sorted((n for n, e in index.items() if name and name in n and not e['abandoned']), key=len)
    close = difflib.get_close_matches(name, [n for n, e in index.items() if not e['abandoned']], n=limit, cutoff=0.5)
    return list(dict.fromkeys(contains[:limit] + close))[:limit]


def fetch_article(pcode, flno, timeout=DEFAULT_TIMEOUT):
    """上網抓單條 → {'status': found|not_found|unrecognized_page, 'url', 'text', 'attempts'}。
    連線失敗重試一次，仍失敗時拋出網路例外(由呼叫端決定用快取或回報無法檢索)。"""
    attempts = 0
    for attempt in range(2):
        if attempt:
            time.sleep(RETRY_GAP)
        try:
            html, url = _fetch_article_page(pcode, flno, timeout=timeout)
        except NETWORK_ERRORS:
            attempts += 1
            if attempts >= 2:
                raise
            continue
        attempts += 1
        # 條號不存在時官網回的是沒有法規內容區塊的空殼頁，不會寫「查無資料」(2026-11-01 實測)；
        # 但同日也遇過一次存在的條文(民法第191條之2)回空殼頁、重抓即正常，所以重查一次才下結論。
        if '查無資料' in html or 'law-reg-content' in html:
            break
    if '查無資料' in html or 'law-reg-content' not in html:
        return {'status': 'not_found', 'url': url, 'attempts': attempts,
                'reason': '官網查無此條（已重查確認），可能條號有誤或該條已刪除'}
    text = _parse_article_html(html, flno) or _parse_plain_article(html, flno)
    if text is None:
        return {'status': 'unrecognized_page', 'url': url, 'attempts': attempts,
                'reason': '官網頁面有法規內容但無法辨認條文排版，不代表條文不存在，請開連結確認'}
    return {'status': 'found', 'url': url, 'text': text, 'attempts': attempts}


def lookup_article(law_name, article_no, timeout=DEFAULT_TIMEOUT, index=None, snapshot=None):
    """經快取查單條(engine/retrieval_cache.py)；status 另有 invalid_article_no、unknown_law、retrieval_unavailable。"""
    from engine import retrieval_cache
    common = {'law_name': law_name, 'article_no': article_no}
    flno = normalize_article_no(article_no)
    if flno is None:
        return {**common, 'status': 'invalid_article_no', 'reason': '條號格式應如 33、191之2 或 191-2'}
    law = resolve_law(law_name, index)
    if law is None:
        return {**common, 'status': 'unknown_law', 'suggestions': suggest_laws(law_name, index),
                'reason': '法規名稱索引查無此名稱；請用官方全名，或重跑 scripts/build_law_index.py 更新索引'}
    common = {**law, 'article_no': flno}
    try:
        return {**common, **retrieval_cache.get_article(law, flno, snapshot=snapshot, timeout=timeout)}
    except retrieval_cache.RetrievalUnavailable as error:
        return {**common, 'status': 'retrieval_unavailable', 'reason': str(error)}


def _parse_plain_article(html, article_no):
    """已廢止法規的條文不用 law-article 排版，而是 <div class="text-pre"> 純文字(如動員戡亂時期臨時條款)。"""
    blocks = re.findall(r'<div class="text-pre">(.*?)</div>', html, re.S)
    lines = [line.strip() for block in blocks for line in html_module.unescape(re.sub(r'<[^>]+>', '', block)).splitlines()]
    lines = [line for line in lines if line]
    return f"第 {article_no} 條\n" + '\n'.join(lines) if lines else None


def _get_law_page(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def parse_law_list(html):
    """整合查詢「法條內容」頁 → {'total', 'laws': [{law_name, pcode, modified_date}]}(第一頁，最多 20 部)。"""
    m = _LAW_TOTAL_RE.search(html)
    laws = []
    for link in _LAW_LINK_RE.finditer(html):
        y, mo, d = link.group(3), link.group(4), link.group(5)
        modified = f"{int(y) + 1911}{int(mo):02d}{int(d):02d}" if y else None
        laws.append({'law_name': html_module.unescape(link.group(1)), 'pcode': link.group(2), 'modified_date': modified})
    return {'total': int(m.group(1).replace(',', '')) if m else len(laws), 'laws': laws}


def parse_content_search(html):
    """單一法規條文檢索頁 → [{article_no, text}]，text 為整條條文(一項一行，已去除命中標記)。"""
    articles = []
    for row in _CONTENT_ROW_RE.finditer(html):
        lines = [html_module.unescape(re.sub(r'<[^>]+>', '', line)).strip()
                 for line in re.findall(r'<div class="line-[^"]*">(.*?)</div>', row.group(2), re.S)]
        articles.append({'article_no': row.group(1), 'text': '\n'.join(line for line in lines if line)})
    return articles


def _content_search(law, keyword, timeout):
    url = f"{LAW_SITE}/LawClass/LawSearchContent.aspx?pcode={law['pcode']}&kw={urllib.parse.quote(keyword)}"
    articles = parse_content_search(with_retry(lambda: _get_law_page(url, timeout)))
    return {'law_name': law['law_name'], 'pcode': law['pcode'], 'url': url,
            'abandoned': law.get('abandoned', False), 'articles': articles}


def search_statutes(keyword, law_name=None, max_laws=3, timeout=DEFAULT_TIMEOUT, index=None, gap=1.0):
    """依關鍵字搜條文內容。

    指定 law_name：只搜該法規，回傳命中條文。
    未指定：先列出條文含此詞的法規，再對前 max_laws 部做條文檢索(官網列表順序，非相關度)。
    → {'status': 'found'|'unknown_law'|'retrieval_unavailable', 'keyword', 'total_laws', 'laws', 'expanded'}
    搜尋結果不進快取(總筆數與順序會變)；連線失敗重試一次仍失敗才回 retrieval_unavailable。
    """
    keyword = (keyword or '').strip()
    if not keyword:
        raise ValueError('請提供關鍵字')
    if not 1 <= max_laws <= MAX_EXPANDED_LAWS:
        raise ValueError(f'展開法規數須介於 1～{MAX_EXPANDED_LAWS}')
    common = {'keyword': keyword, 'law_name': law_name}
    try:
        if law_name:
            law = resolve_law(law_name, index)
            if law is None:
                return {**common, 'status': 'unknown_law', 'suggestions': suggest_laws(law_name, index),
                        'reason': '法規名稱索引查無此名稱；請用官方全名'}
            return {**common, 'status': 'found', 'total_laws': 1, 'laws': [law], 'expanded': [_content_search(law, keyword, timeout)]}
        url = f"{LAW_SITE}/Law/LawSearchResult.aspx?cur=Ld&ty=ONEBAR&kw={urllib.parse.quote(keyword)}"
        listing = parse_law_list(with_retry(lambda: _get_law_page(url, timeout)))
        expanded = []
        for law in listing['laws'][:max_laws]:
            time.sleep(gap)
            expanded.append(_content_search({**law, **(resolve_law(law['law_name'], index) or {})}, keyword, timeout))
    except NETWORK_ERRORS as error:
        return {**common, 'status': 'retrieval_unavailable', 'reason': f'全國法規資料庫連線失敗（{error}），不代表查無條文'}
    return {**common, 'status': 'found', 'url': url, 'total_laws': listing['total'], 'laws': listing['laws'], 'expanded': expanded}
