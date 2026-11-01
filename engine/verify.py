"""法規/判例引用查證(對應實作規劃 1.3，比照 Startup Guide 的 draft→fact_checked→published)。

權威來源固定：法規查 law.moj.gov.tw(全國法規資料庫)；判例查優先比對本地種子語料庫
(corpus/judgments，加速路徑)，未命中則即時查證司法院裁判書查詢系統 FJUD
(judgment.judicial.gov.tw，2026-08-09 新增，不再受限於本地 1,088 筆語料庫範圍)。
快取(corpus/)只是比對用的加速層，不是權威來源本身——統條文一律回頭比對官網原文，
不直接信任快取內容。

FJUD 查證機制(2026-08-09 實測確認可行)：FJUD 為 ASP.NET WebForms 應用，搜尋須先 GET
首頁取得 __VIEWSTATE/__VIEWSTATEGENERATOR/__EVENTVALIDATION，再以完整裁判案號字串
(如「115年度台上字第1037號」)POST 回 default.aspx 觸發搜尋，回應中會附一個查詢結果頁連結
(qryresultlst.aspx?ty=JUDBOOK&q=<token>)，GET 該連結取得結果列表，其中 data.aspx 連結的
id 參數即為完整 JID(格式與本地語料庫檔名、司法院裁判書開放 API 之 JID 一致，如
「TPSV,115,台上,1037,20260722,1」)。單一裁判字號通常只會命中一筆，若命中多筆則逐一比對
JID 內嵌的年度/案號/字別/字號是否與查證目標完全一致，避免誤採其他相近案號。
"""
import http.client
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

FJUD_BASE = "https://judgment.judicial.gov.tw/FJUD"
_FJUD_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9",
}

CORPUS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'corpus')
STATUTES_DIR = os.path.join(CORPUS_DIR, 'statutes')
JUDGMENTS_DIR = os.path.join(CORPUS_DIR, 'judgments')

# 五部 Phase 1 MVP 民事側法規的官方 pcode(全國法規資料庫)，見 corpus/statutes/*_source.json
# 民事訴訟法(2026-08-08 依 legal-debate skill 端到端測試發現新增：舉證責任等程序法引用在
# 民事案件攻防中極常見，原五部實體法規清單未涵蓋，導致機械查證閘門持續擋下合理引用）
STATUTE_PCODES = {
    "民法": "B0000001",
    "公司法": "J0080001",
    "勞動基準法": "N0030001",
    "勞基法": "N0030001",
    "消費者保護法": "J0170001",
    "刑法": "C0000001",
    "民事訴訟法": "B0010001",
    # 2026-10-28 商工規則「合併解散」需引用第24條(消滅公司訴訟由存續公司承受)而新增，無本地快取
    "企業併購法": "J0080041",
    # 2026-11-01 依實跑引用補上；pcode 已對全國法規資料庫標題核對，無本地快取
    "銀行法": "G0380001",
    "民法債編施行法": "B0000003",
    "民事訴訟法施行法": "B0010002",
}

# 條號後可接「之N」子條文寫法(如「民法第191條之2」「第227條之1」)——2026-08-08 依端到端測試
# 發現此前版本只抓「第191條」丟掉「之2」，導致查證引擎誤把「191條之2」驗證成「191條」本身
# (兩者是完全不同的條文，前者為汽車駕駛人責任，後者為工作物所有人責任)，卻回傳 published，
# 是比查不到更危險的靜默誤判。法規全文資料庫(law.moj.gov.tw)的 flno 參數對子條文採「N-M」格式
# (如 flno=191-2)，故子條文號需轉換後才能查對正確條文。
_ARTICLE_PATTERN = r'第\s*([0-9]+(?:-[0-9]+)?)\s*條(?:\s*之\s*([0-9]+))?'
STATUTE_CITATION_RE = re.compile(
    '(' + '|'.join(sorted(STATUTE_PCODES, key=len, reverse=True)) + ')' + _ARTICLE_PATTERN
)
# 不在 STATUTE_PCODES 的法規仍要解析成法條，查證時回 unknown_law；否則會顯示「無法解析」，像是引用寫錯。
UNSUPPORTED_STATUTE_RE = re.compile(r'([一-鿿]{2,20}?(?:法|條例|規則|細則|辦法|通則))' + _ARTICLE_PATTERN)
# 舊版條文只比對現行條文會驗錯版本，查得到現行條文也不算查證通過。
_HISTORICAL_MARK = r'修正前|舊法|舊版|歷史版本'
HISTORICAL_STATUTE_RE = re.compile(
    _HISTORICAL_MARK + r'|[0-9]{2,4}\s*年(?:度)?(?:版)?[^第]{0,25}(?:法|條例)|[0-9]{2,4}\s*年(?:度)?版')
# 草稿文字裡緊接在法規名稱前的版本說明；抽取引用時要連同法條一起保留。
HISTORICAL_PREFIX_RE = re.compile(r'(?:' + _HISTORICAL_MARK + r'|[0-9]{2,4}\s*年(?:度)?(?:版)?(?:修正)?(?:之)?)\s*$')
# 字別(台上/台簡抗/台抗等)原為列舉白名單，2026-08-09 端到端測試發現本地語料庫實際涵蓋
# 台上/台再/台抗/台簡上/台簡抗/台簡聲/台聲共7種字別，列舉版只認得3種，其餘4種(尤其常見的
# 「台簡上」)一律 unparseable，等同於機械查證閘門會擋下所有引用該字別判例的合法引用——
# 跟先前「之N子條文」是同一類「白名單漏掉真實存在的變體」錯誤，故改為結構化比對(以「台」
# 開頭、後接1-3個非數字非空白字元)，不再逐一列舉，避免未來出現新字別時重蹈覆轍。
JUDGMENT_CITATION_RE = re.compile(r'(最高法院)?\s*([0-9]{2,3})年度(台[^\s字0-9]{1,3})字第\s*([0-9]+)\s*號')


def parse_citation(citation_text):
    m = STATUTE_CITATION_RE.search(citation_text)
    if m:
        article_no = m.group(2)
        if m.group(3):
            article_no = f"{article_no}-{m.group(3)}"
        return {"type": "statute", "law_name": m.group(1), "article_no": article_no}
    m = JUDGMENT_CITATION_RE.search(citation_text)
    if m:
        return {"type": "judgment", "jyear": m.group(2), "jcase": m.group(3), "jno": m.group(4)}
    m = UNSUPPORTED_STATUTE_RE.search(citation_text)
    if m:
        article_no = f"{m.group(2)}-{m.group(3)}" if m.group(3) else m.group(2)
        return {"type": "statute", "law_name": m.group(1), "article_no": article_no}
    return {"type": "unknown"}


def is_historical_statute(citation_text):
    return parse_citation(citation_text)["type"] == "statute" and bool(HISTORICAL_STATUTE_RE.search(citation_text))


HISTORICAL_NOTE = "引用的是舊版條文，查證引擎只比對現行條文，無法確認當時內容；請律師另行核對"
DEFAULT_TIMEOUT = 20
FJUD_MAX_PAGES = 10
_NETWORK_ERRORS = (OSError, http.client.HTTPException)  # URLError、逾時與 SSL 錯誤都是 OSError


class FjudSearchIncomplete(Exception):
    """FJUD 搜尋沒有跑完(取不到查詢欄位或超過頁數上限)。沒看完不等於查無，不得回報 not_found。"""


def _fetch_single_article(pcode, article_no, timeout=DEFAULT_TIMEOUT):
    url = f"https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode={pcode}&flno={article_no}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        html = resp.read().decode("utf-8")
    if "查無資料" in html:
        return None, url
    start = html.find('<div class="law-article">')
    if start == -1:
        return None, url
    end = html.find('<div class="clearfix">', start)
    if end == -1:
        end = start + 3000
    fragment = html[start:end]
    fragment = re.sub(r'<div[^>]*>', '\n', fragment)
    fragment = re.sub(r'</div>', '\n', fragment)
    fragment = re.sub(r'<[^>]+>', '', fragment)
    lines = [l.strip() for l in fragment.split('\n') if l.strip()]
    text = f"第 {article_no} 條\n" + '\n'.join(lines)
    return text, url


def verify_statute_citation(law_name, article_no, timeout=DEFAULT_TIMEOUT):
    pcode = STATUTE_PCODES.get(law_name)
    if pcode is None:
        return {"status": "unknown_law", "law_name": law_name, "article_no": article_no}
    try:
        live_text, url = _fetch_single_article(pcode, article_no, timeout=timeout)
    except _NETWORK_ERRORS as e:
        return {"status": "verification_failed", "reason": str(e), "law_name": law_name,
                "article_no": article_no}
    if live_text is None:
        return {"status": "not_found", "law_name": law_name, "article_no": article_no,
                "primary_source_url": url,
                "note": "官網查無此條，可能條號有誤或該條已刪除"}
    return {"status": "published", "law_name": law_name, "article_no": article_no,
            "primary_source_url": url, "matched_text": live_text}


def _fjud_extract_hidden_fields(html):
    def extract(name):
        m = re.search(r'id="' + name + r'"[^>]*value="([^"]*)"', html)
        return m.group(1) if m else ""
    return {
        "__VIEWSTATE": extract("__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": extract("__VIEWSTATEGENERATOR"),
        "__EVENTVALIDATION": extract("__EVENTVALIDATION"),
    }


def _fjud_next_page(list_html):
    m = re.search(r'id="hlNext"[^>]*href="([^"]+)"', list_html)
    return urllib.parse.urljoin(f"{FJUD_BASE}/", m.group(1).replace("&amp;", "&")) if m else None


def _fjud_search(citation_query, timeout=DEFAULT_TIMEOUT, is_target=None):
    """搜尋 FJUD，回傳讀到的 JID 清單(可能為空、一筆、或多筆)，is_target 命中時提早停止。

    搜尋是關鍵字比對，真正的字號不一定排在前面：105年度台簡上字第33號共 50 筆結果，它排在第 3 頁，
    2026-11-01 前只讀第一頁，因而把存在的判決誤判為查無。所以依法院層級排序並讀完所有頁。
    """
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
    req = urllib.request.Request(f"{FJUD_BASE}/default.aspx", headers=_FJUD_HEADERS)
    with opener.open(req, timeout=timeout) as resp:
        home_html = resp.read().decode("utf-8")
    hidden = _fjud_extract_hidden_fields(home_html)
    if not hidden["__VIEWSTATE"]:
        raise FjudSearchIncomplete("司法院首頁取不到查詢欄位")
    data = dict(hidden)
    data.update({
        "judtype": "JUDBOOK",
        "whosub": "0",
        "txtKW": citation_query,
        "ctl00$cp_content$btnSimpleQry": "送出查詢",
    })
    body = urllib.parse.urlencode(data).encode("utf-8")
    headers2 = dict(_FJUD_HEADERS)
    headers2.update({
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": f"{FJUD_BASE}/default.aspx",
        "Origin": "https://judgment.judicial.gov.tw",
    })
    req2 = urllib.request.Request(f"{FJUD_BASE}/default.aspx", data=body, headers=headers2)
    with opener.open(req2, timeout=timeout) as resp2:
        search_html = resp2.read().decode("utf-8")
    m = re.search(r'qryresultlst\.aspx\?ty=JUDBOOK&(?:amp;)?q=([0-9a-f]+)', search_html)
    if not m:
        return []
    token = m.group(1)
    time.sleep(1.5)  # 緊接著發第二個請求容易被拒，實測需短暫延遲(見 corpus/COLLECTION_LOG.md 類似教訓)
    list_url = f"{FJUD_BASE}/qryresultlst.aspx?ty=JUDBOOK&q={token}&sort=LG"
    referer = f"{FJUD_BASE}/default.aspx"
    jids = []
    for page in range(1, FJUD_MAX_PAGES + 1):
        req3 = urllib.request.Request(list_url, headers={**_FJUD_HEADERS, "Referer": referer})
        with opener.open(req3, timeout=timeout) as resp3:
            list_html = resp3.read().decode("utf-8")
        raw_ids = re.findall(r'data\.aspx\?ty=JD&(?:amp;)?id=([^"&]+)', list_html)
        page_jids = [urllib.parse.unquote(raw_id) for raw_id in raw_ids]
        jids += page_jids
        next_url = _fjud_next_page(list_html)
        if not next_url or (is_target and any(is_target(j) for j in page_jids)):
            return jids
        referer, list_url = list_url, next_url
        time.sleep(1.5)
    raise FjudSearchIncomplete(f"搜尋結果超過 {FJUD_MAX_PAGES} 頁，沒有看完")


def _jid_matches(jid, jyear, jcase, jno):
    parts = jid.split(",")
    return len(parts) >= 4 and parts[0] == "TPSV" and parts[1] == jyear and parts[2] == jcase and parts[3] == jno


def multiple_documents_note(count):
    return f"此字號有 {count} 份文件，查證只確認字號存在，請律師確認引用的是哪一份"


def verify_judgment_citation(jyear, jcase, jno, timeout=DEFAULT_TIMEOUT):
    prefix = f"TPSV,{jyear},{jcase},{jno},"
    if not os.path.isdir(JUDGMENTS_DIR):
        candidates = []
    else:
        candidates = sorted(f for f in os.listdir(JUDGMENTS_DIR) if f.startswith(prefix) and f.endswith('.txt'))
    if candidates:
        path = os.path.join(JUDGMENTS_DIR, candidates[0])
        with open(path, encoding='utf-8') as f:
            content = f.read()
        result = {"status": "published", "jyear": jyear, "jcase": jcase, "jno": jno,
                  "source_file": path, "matched_text": content[:200], "verified_via": "local_corpus"}
        if len(candidates) > 1:
            result["candidates"] = candidates
            result["note"] = multiple_documents_note(len(candidates))
        return result

    # 本地語料庫未命中，退而求其次即時查證 FJUD(不再直接回報 not_in_phase1_seed_corpus 了事)。
    citation_query = f"{jyear}年度{jcase}字第{jno}號"
    try:
        jids = _fjud_search(citation_query, timeout=timeout,
                            is_target=lambda j: _jid_matches(j, jyear, jcase, jno))
    except (*_NETWORK_ERRORS, FjudSearchIncomplete) as e:
        return {"status": "verification_failed", "jyear": jyear, "jcase": jcase, "jno": jno,
                "reason": str(e), "note": "FJUD 即時查證未完成(連線失敗或結果沒有看完)，非查無此判決，可重試"}

    matched = [j for j in jids if _jid_matches(j, jyear, jcase, jno)]
    if not matched:
        return {"status": "not_found", "jyear": jyear, "jcase": jcase, "jno": jno,
                "fjud_query": citation_query, "fjud_raw_hits": jids,
                "note": "FJUD 即時查證查無此裁判字號，可能字號有誤，或非最高法院裁判(本查證僅涵蓋TPSV前綴/最高法院)"}
    jid = matched[0]
    url = f"{FJUD_BASE}/data.aspx?ty=JD&id={urllib.parse.quote(jid)}&ot=in"
    return {"status": "published", "jyear": jyear, "jcase": jcase, "jno": jno,
            "primary_source_url": url, "jid": jid, "verified_via": "fjud_live",
            "note": "僅確認裁判字號存在且可由律師自行點開原文核對，未涵蓋裁判全文之實質內容比對"}


def verify_citations(citation_texts, timeout=DEFAULT_TIMEOUT):
    results = []
    for citation_text in citation_texts:
        parsed = parse_citation(citation_text)
        if is_historical_statute(citation_text):
            result = {"status": "version_unverified", "law_name": parsed["law_name"], "article_no": parsed["article_no"],
                      "note": HISTORICAL_NOTE}
        elif parsed["type"] == "statute":
            result = verify_statute_citation(parsed["law_name"], parsed["article_no"], timeout=timeout)
        elif parsed["type"] == "judgment":
            result = verify_judgment_citation(parsed["jyear"], parsed["jcase"], parsed["jno"], timeout=timeout)
        else:
            result = {"status": "unparseable"}
        result["citation_text"] = citation_text
        result["source_type"] = parsed["type"] if parsed["type"] != "unknown" else None
        results.append(result)
    return results


if __name__ == "__main__":
    import sys
    # Windows console 預設 cp950/gbk 會把中文或罕見 unicode 字元打成亂碼或直接 crash，
    # orchestrator 依賴 stdout，強制 UTF-8(同 DebateSystem/main.py 的既有作法)。
    if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    for r in verify_citations(sys.argv[1:]):
        print(json.dumps(r, ensure_ascii=False, indent=2))
