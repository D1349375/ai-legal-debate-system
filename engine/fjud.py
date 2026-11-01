"""司法院裁判書查詢系統(FJUD，judgment.judicial.gov.tw)的連線與頁面解析。

FJUD 為 ASP.NET WebForms 應用：搜尋須先 GET 表單頁取得 __VIEWSTATE 等隱藏欄位，再 POST 回同一頁，
回應中附查詢結果頁連結(qryresultlst.aspx?ty=JUDBOOK&q=<token>)，GET 該連結取得每頁 20 筆的列表，
翻頁用同一 token 加 page=N。列表每列有 JID、裁判字號(含判決／裁定)、內容大小、裁判日期、案由與命中片段。

- 簡易搜尋(default.aspx 的 txtKW)：是全文搜尋，拿裁判字號去搜會先命中「內文引用該字號」的其他法院裁判
  (2026-11-01 實測「111年度台上字第1069號」第一頁 20 筆全是刑事地院)，所以查證改用進階搜尋的字號欄位。
- 進階搜尋(Default_AD.aspx)：可限定法院(jud_court，最高法院 TPS)、類別(jud_sys，民事 V)、裁判字號
  (jud_year/jud_case/jud_no)、全文關鍵字(jud_kw，多詞以 & 連接為 AND)、案由(jud_title)、裁判期間(民國年月日)、
  內容大小下限(KbStart)。沒有相關度排序，預設依日期新到舊。
- 全文頁(data.aspx?ty=JD&id=<JID>)：全文在巢狀的 <div class="htmlcontent"> 內(舊版頁面為 text-pre)，
  須依 div 層級取完整區塊；2026-11-01 前的版本用非貪婪比對到第一個 </div> 為止，只取得標題 8 個字。

連續請求間隔 REQUEST_GAP 秒：緊接著發第二個請求容易被拒(見 corpus/COLLECTION_LOG.md)，也是體諒網站負荷。
"""
import html as html_module
import re
import time
import urllib.parse
import urllib.request

FJUD_BASE = "https://judgment.judicial.gov.tw/FJUD"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9",
}
DEFAULT_TIMEOUT = 20
REQUEST_GAP = 1.5
SUPREME_COURT = "TPS"
CIVIL = "V"

_TOKEN_RE = re.compile(r'qryresultlst\.aspx\?ty=JUDBOOK&(?:amp;)?q=([0-9a-f]+)')
_ROW_RE = re.compile(
    r'href="data\.aspx\?ty=JD&(?:amp;)?id=([^"&]+)&(?:amp;)?ot=in">(.*?)</a>\s*(?:（(\d+)K）)?\s*</td>\s*'
    r'<td[^>]*>\s*([0-9.]+)\s*</td>\s*<td[^>]*>(.*?)</td>', re.S)
_SNIPPET_RE = re.compile(r'class="tdCut">(.*?)</td>', re.S)
_TOTAL_RE = re.compile(r'共\s*([0-9,]+)\s*筆\s*\.?\s*現在第\s*\d+\s*/\s*(\d+)\s*頁')


def _text(fragment):
    return html_module.unescape(re.sub(r'<[^>]+>', '', fragment or '')).strip()


class Session:
    """帶 cookie 的連線，並保證相鄰請求至少間隔 REQUEST_GAP 秒。"""

    def __init__(self, timeout=DEFAULT_TIMEOUT, gap=REQUEST_GAP):
        self.timeout, self.gap, self._last = timeout, gap, None
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())

    def _open(self, url, data=None, referer=None):
        if self._last is not None:
            wait = self.gap - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
        headers = dict(HEADERS)
        if referer:
            headers["Referer"] = referer
        if data is not None:
            headers.update({"Content-Type": "application/x-www-form-urlencoded",
                            "Origin": "https://judgment.judicial.gov.tw"})
            data = urllib.parse.urlencode(data).encode("utf-8")
        try:
            with self._opener.open(urllib.request.Request(url, data=data, headers=headers), timeout=self.timeout) as resp:
                return resp.read().decode("utf-8")
        finally:
            self._last = time.monotonic()

    def get(self, url, referer=None):
        return self._open(url, referer=referer)

    def post(self, url, data, referer=None):
        return self._open(url, data=data, referer=referer)


def extract_hidden_fields(html):
    def extract(name):
        m = re.search(r'id="' + name + r'"[^>]*value="([^"]*)"', html)
        return m.group(1) if m else ""
    return {name: extract(name) for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION")}


def _submit(session, form_page, fields):
    """送出 FJUD 表單，回傳查詢 token；查無結果時官方不給結果頁連結，回 None。"""
    url = f"{FJUD_BASE}/{form_page}"
    data = dict(extract_hidden_fields(session.get(url)))
    data.update(fields)
    m = _TOKEN_RE.search(session.post(url, data, referer=url))
    return m.group(1) if m else None


def _list_url(token, page):
    return f"{FJUD_BASE}/qryresultlst.aspx?ty=JUDBOOK&q={token}" + (f"&sort=DS&page={page}" if page > 1 else "")


def simple_search(query, timeout=DEFAULT_TIMEOUT):
    """簡易(全文)搜尋第一頁 → JID 清單。不適合拿來查特定字號，見檔頭說明。"""
    session = Session(timeout)
    token = _submit(session, "default.aspx", {"judtype": "JUDBOOK", "whosub": "0", "txtKW": query,
                                               "ctl00$cp_content$btnSimpleQry": "送出查詢"})
    if token is None:
        return []
    return [row["jid"] for row in parse_result_page(session.get(_list_url(token, 1), referer=f"{FJUD_BASE}/default.aspx"))["rows"]]


def parse_result_page(html):
    """列表頁 → {'total', 'page_count', 'rows'}；total/page_count 在頁面沒有分頁資訊時為 None。"""
    m = _TOTAL_RE.search(html)
    matches = list(_ROW_RE.finditer(html))
    rows = []
    for i, row in enumerate(matches):
        jid = urllib.parse.unquote(row.group(1))
        title = re.sub(r'\s+', '', _text(row.group(2)))
        tail = html[row.end():matches[i + 1].start() if i + 1 < len(matches) else len(html)]
        snippet = _SNIPPET_RE.search(tail)
        parts = jid.split(',')
        rows.append({
            'jid': jid,
            'citation': title,
            'doc_type': '判決' if title.endswith('判決') else '裁定' if title.endswith('裁定') else None,
            'size_kb': int(row.group(3)) if row.group(3) else None,
            'doc_date': parts[4] if len(parts) > 4 else None,
            'case_cause': _text(row.group(5)),
            'snippet': re.sub(r'\s+', ' ', _text(snippet.group(1))) if snippet else None,
            'url': document_url(jid),
        })
    return {'total': int(m.group(1).replace(',', '')) if m else None,
            'page_count': int(m.group(2)) if m else None, 'rows': rows}


def _roc_date_fields(prefix_year, prefix_month, prefix_day, iso_date):
    year, month, day = (int(x) for x in iso_date.split('-'))
    return {prefix_year: str(year - 1911), prefix_month: str(month), prefix_day: str(day)}


def advanced_search(keywords=(), case_cause=None, date_from=None, date_to=None, pages=2, citation=None,
                    min_size_kb=None, court=SUPREME_COURT, category=CIVIL, timeout=DEFAULT_TIMEOUT, session=None):
    """進階搜尋 → {'total', 'page_count', 'pages_read', 'rows'}。

    date_from/date_to 為 YYYY-MM-DD(西元)；citation 為 (年度, 字別, 號次)，如 ('111', '台上', '1069')；
    min_size_kb 為裁判內容大小下限(列表上的「（11K）」)。
    """
    session = session or Session(timeout)
    fields = {"judtype": "JUDBOOK", "whosub": "1", "jud_court": court, "jud_sys": category,
              "jud_kw": "&".join(k.strip() for k in keywords if k and k.strip()),
              "jud_title": case_cause or "", "ctl00$cp_content$btnQry": "送出查詢"}
    if citation:
        fields.update(zip(("jud_year", "jud_case", "jud_no"), citation))
    if min_size_kb:
        fields["KbStart"] = str(min_size_kb)
    if date_from:
        fields.update(_roc_date_fields("dy1", "dm1", "dd1", date_from))
    if date_to:
        fields.update(_roc_date_fields("dy2", "dm2", "dd2", date_to))
    token = _submit(session, "Default_AD.aspx", fields)
    if token is None:
        return {'total': 0, 'page_count': 0, 'pages_read': 0, 'rows': []}
    first = parse_result_page(session.get(_list_url(token, 1), referer=f"{FJUD_BASE}/Default_AD.aspx"))
    rows, pages_read = list(first['rows']), 1
    for page in range(2, min(pages, first['page_count'] or 1) + 1):
        rows += parse_result_page(session.get(_list_url(token, page), referer=_list_url(token, page - 1)))['rows']
        pages_read += 1
    return {'total': first['total'] if first['total'] is not None else len(rows),
            'page_count': first['page_count'] or 1, 'pages_read': pages_read, 'rows': rows}


def document_url(jid):
    return f"{FJUD_BASE}/data.aspx?ty=JD&id={urllib.parse.quote(jid)}&ot=in"


def _div_block(html, start):
    depth = 0
    for m in re.finditer(r'<div\b|</div>', html[start:], re.I):
        depth += 1 if m.group(0).lower().startswith('<div') else -1
        if depth == 0:
            return html[start:start + m.end()]
    return html[start:]


def extract_full_text(html):
    """全文頁 → 裁判全文(保留原文換行)；頁面改版而無法辨認時回空字串，不把導覽文字當全文。"""
    starts = [m.start() for m in re.finditer(r'<div[^>]+class=["\'][^"\']*htmlcontent[^"\']*["\'][^>]*>', html, re.I)]
    starts += [m.start() for m in re.finditer(r'<div[^>]+class=["\'][^"\']*text-pre[^"\']*["\'][^>]*>', html, re.I)]
    for start in starts:
        block = re.sub(r'<!--.*?-->', '', _div_block(html, start), flags=re.S)
        text = _text(re.sub(r'<br\s*/?>|</div>|</p>|</pre>', '\n', block, flags=re.I))
        text = '\n'.join(line.rstrip() for line in text.splitlines()).strip()
        if text:
            return text
    return ''


def extract_case_cause(html):
    m = re.search(r'裁判案由[：:]\s*</[^>]+>\s*<[^>]+>(.*?)</', html, re.S)
    return _text(m.group(1)) or None if m else None


def fetch_document(jid, timeout=DEFAULT_TIMEOUT, session=None):
    """→ {'jid', 'url', 'full_text', 'case_cause'}；連線錯誤照常拋出，由呼叫端區分網路錯誤與查無。"""
    url = document_url(jid)
    html = (session or Session(timeout)).get(url)
    return {'jid': jid, 'url': url, 'full_text': extract_full_text(html), 'case_cause': extract_case_cause(html)}
