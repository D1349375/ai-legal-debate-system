"""即時查全國法規資料庫：依法規名稱與條號查單條條文，或依關鍵字搜條文內容。

官網單條頁面網址有固定規律(LawSingle.aspx?pcode=<法規代碼>&flno=<條號>)，缺的只是
「法規名稱 → pcode」對照。對照表來自 scripts/build_law_index.py 從法務部開放資料建立的
corpus/statutes/law_index.json(全部中文法律與命令，含已廢止者)；條文本身一律即時回官網抓，
不讀本地快取，理由同 verify.py：快取不是權威來源。

關鍵字搜尋分兩層(2026-11-01 實測)：整合查詢(Law/LawSearchResult.aspx?cur=Ld)只列出「哪些法規的條文含此詞」，
要看條文須再對個別法規做條文檢索(LawClass/LawSearchContent.aspx?pcode=)。

本模組只負責查條文給人看，不是查證閘門——查證引擎(verify.py)支援哪些法規仍由
STATUTE_PCODES 決定，這裡查得到不代表書狀引用已 published。
"""
import difflib
import functools
import html as html_module
import json
import os
import re
import time
import urllib.parse
import urllib.request

from engine.verify import (
    DEFAULT_TIMEOUT, STATUTE_PCODES, STATUTES_DIR,
    _fetch_article_page, _network_call, _parse_article_html,
)

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
    查證引擎既有的簡稱(如「勞基法」)也認得，回傳時換成官方全名。"""
    index = load_law_index() if index is None else index
    name = law_name.strip()
    if name in index:
        return {'law_name': name, **index[name]}
    pcode = STATUTE_PCODES.get(name)
    if pcode:
        official = next((n for n, e in index.items() if e['pcode'] == pcode), name)
        entry = index.get(official, {'pcode': pcode, 'level': None, 'abandoned': False, 'modified_date': None})
        return {'law_name': official, **entry}
    return None


def suggest_laws(law_name, index=None, limit=5):
    """名稱打錯或不完整時給候選：先列包含輸入字串的現行法規，再補字形相近者。"""
    index = load_law_index() if index is None else index
    name = law_name.strip()
    contains = sorted((n for n, e in index.items() if name and name in n and not e['abandoned']), key=len)
    close = difflib.get_close_matches(name, [n for n, e in index.items() if not e['abandoned']], n=limit, cutoff=0.5)
    return list(dict.fromkeys(contains[:limit] + close))[:limit]


def lookup_article(law_name, article_no, timeout=DEFAULT_TIMEOUT, index=None):
    common = {'law_name': law_name, 'article_no': article_no}
    flno = normalize_article_no(article_no)
    if flno is None:
        return {**common, 'status': 'invalid_article_no', 'reason': '條號格式應如 33、191之2 或 191-2'}
    law = resolve_law(law_name, index)
    if law is None:
        return {**common, 'status': 'unknown_law', 'suggestions': suggest_laws(law_name, index),
                'reason': '法規名稱索引查無此名稱；請用官方全名，或重跑 scripts/build_law_index.py 更新索引'}
    common = {**law, 'article_no': flno}
    attempts = 0
    for attempt in range(2):
        if attempt:
            time.sleep(1.5)
        fetched, _, error = _network_call(lambda: _fetch_article_page(law['pcode'], flno, timeout=timeout))
        attempts += 1
        if error:
            return {**common, 'status': 'network_error', 'reason': error, 'attempts': attempts}
        html, url = fetched
        # 條號不存在時官網回的是沒有法規內容區塊的空殼頁，不會寫「查無資料」(2026-11-01 實測)；
        # 但同日也遇過一次存在的條文(民法第191條之2)回空殼頁、重抓即正常，所以重查一次才下結論。
        if '查無資料' in html or 'law-reg-content' in html:
            break
    if '查無資料' in html or 'law-reg-content' not in html:
        return {**common, 'status': 'not_found', 'url': url, 'attempts': attempts,
                'reason': '官網查無此條（已重查確認），可能條號有誤或該條已刪除'}
    text = _parse_article_html(html, flno) or _parse_plain_article(html, flno)
    if text is None:
        return {**common, 'status': 'unrecognized_page', 'url': url, 'attempts': attempts,
                'reason': '官網頁面有法規內容但無法辨認條文排版，不代表條文不存在，請開連結確認'}
    return {**common, 'status': 'found', 'url': url, 'text': text, 'attempts': attempts}


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
    articles = parse_content_search(_get_law_page(url, timeout))
    return {'law_name': law['law_name'], 'pcode': law['pcode'], 'url': url,
            'abandoned': law.get('abandoned', False), 'articles': articles}


def search_statutes(keyword, law_name=None, max_laws=3, timeout=DEFAULT_TIMEOUT, index=None, gap=1.0):
    """依關鍵字搜條文內容。

    指定 law_name：只搜該法規，回傳命中條文。
    未指定：先列出條文含此詞的法規，再對前 max_laws 部做條文檢索(官網列表順序，非相關度)。
    → {'status': 'found'|'unknown_law'|'network_error', 'keyword', 'total_laws', 'laws', 'expanded'}
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
        listing = parse_law_list(_get_law_page(url, timeout))
        expanded = []
        for law in listing['laws'][:max_laws]:
            time.sleep(gap)
            expanded.append(_content_search({**law, **(resolve_law(law['law_name'], index) or {})}, keyword, timeout))
    except (OSError, TimeoutError) as error:
        return {**common, 'status': 'network_error', 'reason': f'全國法規資料庫連線失敗（{error}），不代表查無條文'}
    return {**common, 'status': 'found', 'url': url, 'total_laws': listing['total'], 'laws': listing['laws'], 'expanded': expanded}
