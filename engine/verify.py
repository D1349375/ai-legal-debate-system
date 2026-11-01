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
FJUD 的連線與頁面解析自 2026-11-01 起集中在 engine/fjud.py，與判決上網檢索共用。
"""
import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

from engine import fjud

FJUD_BASE = fjud.FJUD_BASE
_FJUD_HEADERS = fjud.HEADERS

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
    "銀行法": "G0380001",
    "民法債編施行法": "B0000003",
    "民事訴訟法施行法": "B0010002",
}

# 條號後可接「之N」子條文寫法(如「民法第191條之2」「第227條之1」)——2026-08-08 依端到端測試
# 發現此前版本只抓「第191條」丟掉「之2」，導致查證引擎誤把「191條之2」驗證成「191條」本身
# (兩者是完全不同的條文，前者為汽車駕駛人責任，後者為工作物所有人責任)，卻回傳 published，
# 是比查不到更危險的靜默誤判。法規全文資料庫(law.moj.gov.tw)的 flno 參數對子條文採「N-M」格式
# (如 flno=191-2)，故子條文號需轉換後才能查對正確條文。
STATUTE_CITATION_RE = re.compile(
    '(' + '|'.join(sorted(map(re.escape, STATUTE_PCODES), key=len, reverse=True))
    + r')\s*第\s*([0-9]+(?:-[0-9]+)?)\s*條(?:\s*之\s*([0-9]+))?'
)
UNSUPPORTED_STATUTE_RE = re.compile(
    r'([\u3400-\u9fff]+?(?:法|條例|規則|辦法|通則))\s*第\s*([0-9]+(?:-[0-9]+)?)\s*條(?:\s*之\s*([0-9]+))?'
)
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
        article_no = m.group(2) + (f"-{m.group(3)}" if m.group(3) else "")
        return {"type": "statute", "law_name": m.group(1), "article_no": article_no}
    return {"type": "unknown"}


DEFAULT_TIMEOUT = 20


def _historical_version(citation_text, version_hint=None):
    if isinstance(version_hint, dict):
        version_fields = ('version_hint', 'version', 'applicable_version', 'historical_version',
                          'version_note', 'law_version', 'statute_version')
        if any(version_hint.get(key) and str(version_hint[key]).strip().lower() not in
               ('current', '現行', '現行法', '現行版本') for key in version_fields):
            return True
    hint = json.dumps(version_hint, ensure_ascii=False) if isinstance(version_hint, (dict, list)) else str(version_hint or "")
    text = f"{citation_text} {hint}"
    return bool(re.search(r'修正前|舊法|舊版|歷史版本|(?:民國)?\d{2,4}\s*年(?:度)?(?:版)?[^第]{0,25}(?:法|條例)|\d{2,4}\s*年(?:度)?版', text)
                or version_hint is True)


def citation_warning(citation_text, version_hint=None):
    """落地前的純本機分類；不以現行條文替歷史版本背書。"""
    parsed = parse_citation(citation_text)
    if parsed['type'] != 'statute':
        return None
    common = {**parsed, 'citation_text': citation_text, 'source_type': 'statute'}
    if _historical_version(citation_text, version_hint):
        return {**common, 'status': 'version_unverified', 'note': '歷史條文版本尚未查證，律師待核；不得作為書狀引用'}
    if parsed['law_name'] not in STATUTE_PCODES:
        return {**common, 'status': 'unsupported_law', 'note': '查證引擎尚未支援此法規，律師待核；不表示法規不存在'}
    return None


def _network_call(call):
    """區分連線失敗與查無；自動重試依本輪範圍決定留待後續。"""
    try:
        return call(), 1, None
    except (urllib.error.URLError, TimeoutError, ssl.SSLError, ConnectionError, OSError) as error:
        return None, 1, str(error)


def _fetch_article_page(pcode, article_no, timeout=DEFAULT_TIMEOUT):
    url = f"https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode={pcode}&flno={article_no}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8"), url


def _fetch_single_article(pcode, article_no, timeout=DEFAULT_TIMEOUT):
    html, url = _fetch_article_page(pcode, article_no, timeout=timeout)
    if "查無資料" in html:
        return None, url
    return _parse_article_html(html, article_no), url


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


def verify_statute_citation(law_name, article_no, timeout=DEFAULT_TIMEOUT, *, citation_text=None, version_hint=None):
    warning = citation_warning(citation_text or f'{law_name}第{article_no}條', version_hint)
    if warning:
        return warning
    pcode = STATUTE_PCODES.get(law_name)
    if pcode is None:
        return {"status": "unsupported_law", "law_name": law_name, "article_no": article_no}
    fetched, attempts, error = _network_call(lambda: _fetch_single_article(pcode, article_no, timeout=timeout))
    if error:
        return {"status": "network_error", "reason": error, "law_name": law_name,
                "article_no": article_no, "attempts": attempts}
    live_text, url = fetched
    if live_text is None:
        return {"status": "not_found", "law_name": law_name, "article_no": article_no,
                "primary_source_url": url,
                "note": "官網查無此條，可能條號有誤或該條已刪除", "attempts": attempts}
    return {"status": "published", "law_name": law_name, "article_no": article_no,
            "primary_source_url": url, "matched_text": live_text, "attempts": attempts}


def _fjud_search(jyear, jcase, jno, timeout=DEFAULT_TIMEOUT):
    """以 FJUD 進階搜尋的字號欄位找最高法院民事裁判，回傳 JID 清單(可能為空、一筆、或多筆)。

    2026-11-01 前用簡易搜尋輸入完整字號，那是全文搜尋，會先命中內文引用該字號的其他法院裁判，
    不在本地語料又被他案引用過的最高法院裁判因此一律誤報 not_found。"""
    return [row['jid'] for row in fjud.advanced_search(citation=(jyear, jcase, jno), pages=1, timeout=timeout)['rows']]


def _jid_matches(jid, jyear, jcase, jno):
    parts = jid.split(",")
    return len(parts) >= 4 and parts[0] == "TPSV" and parts[1] == jyear and parts[2] == jcase and parts[3] == jno


def _document_type(text):
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), '')
    match = re.search(r'(判決|裁定)', first_line)
    return match.group(1) if match else None


def _local_judgment(path):
    with open(path, encoding='utf-8') as f:
        content = f.read()
    metadata_path = os.path.splitext(path)[0] + '_source.json'
    metadata = {}
    if os.path.isfile(metadata_path):
        with open(metadata_path, encoding='utf-8') as f:
            metadata = json.load(f)
    jid = metadata.get('jid') or os.path.splitext(os.path.basename(path))[0]
    parts = jid.split(',')
    return {'jid': jid, 'doc_date': metadata.get('jdate') or (parts[4] if len(parts) > 4 else None),
            'doc_type': _document_type(content), 'jtitle': metadata.get('jtitle'),
            'source_file': path, 'full_text': content, 'matched_text': content[:200],
            'primary_source_url': metadata.get('source_pdf_url'), 'verified_via': 'local_corpus'}


def _fetch_judgment_text(jid, timeout=DEFAULT_TIMEOUT):
    # 頁面改版而無法辨認全文容器時 full_text 為空，不能把導覽文字當裁判全文。
    document = fjud.fetch_document(jid, timeout=timeout)
    text = document['full_text']
    if not text:
        return {'full_text': '', 'primary_source_url': document['url'], 'jtitle': None, 'doc_type': None}
    return {'full_text': text, 'matched_text': text[:200], 'primary_source_url': document['url'],
            'jtitle': document['case_cause'], 'doc_type': _document_type(text)}


def verify_judgment_citation(jyear, jcase, jno, timeout=DEFAULT_TIMEOUT, *, doc_date=None):
    common = {'jyear': jyear, 'jcase': jcase, 'jno': jno}
    if doc_date is not None:
        doc_date = re.sub(r'[-/]', '', str(doc_date))
        if not re.fullmatch(r'\d{8}', doc_date):
            return {**common, 'status': 'invalid_document_date', 'reason': 'doc_date 必須是 YYYYMMDD'}
    prefix = f"TPSV,{jyear},{jcase},{jno},"
    if not os.path.isdir(JUDGMENTS_DIR):
        candidates = []
    else:
        candidates = sorted(f for f in os.listdir(JUDGMENTS_DIR) if f.startswith(prefix) and f.endswith('.txt'))
    if candidates:
        documents = [_local_judgment(os.path.join(JUDGMENTS_DIR, name)) for name in candidates]
        public_candidates = [{k: v for k, v in d.items() if k not in ('full_text', 'matched_text')} for d in documents]
        selected = [d for d in documents if doc_date is None or d['doc_date'] == doc_date]
        if not selected:
            return {**common, 'status': 'not_found', 'candidates': public_candidates,
                    'reason': '該字號沒有指定日期的裁判文件'}
        if len(selected) > 1:
            return {**common, 'status': 'ambiguous', 'candidates': public_candidates,
                    'reason': '同一字號有多份文件，須指定可唯一識別的 doc_date'}
        return {**common, **selected[0], 'status': 'published', 'candidates': public_candidates}

    # 本地語料庫未命中，退而求其次即時查證 FJUD(不再直接回報 not_in_phase1_seed_corpus 了事)。
    citation_query = f"{jyear}年度{jcase}字第{jno}號"
    jids, attempts, error = _network_call(lambda: _fjud_search(jyear, jcase, jno, timeout=timeout))
    if error:
        return {"status": "network_error", **common, 'attempts': attempts,
                "reason": error, "note": "FJUD 即時查證連線失敗，非查無此判決"}

    matched = [j for j in jids if _jid_matches(j, jyear, jcase, jno)]
    if not matched:
        return {"status": "not_found", "jyear": jyear, "jcase": jcase, "jno": jno,
                "fjud_query": citation_query, "fjud_raw_hits": jids,
                "note": "FJUD 即時查證查無此裁判字號，可能字號有誤，或非最高法院裁判(本查證僅涵蓋TPSV前綴/最高法院)"}
    documents = [{'jid': jid, 'doc_date': jid.split(',')[4] if len(jid.split(',')) > 4 else None} for jid in sorted(set(matched))]
    selected = [d for d in documents if doc_date is None or d['doc_date'] == doc_date]
    if not selected:
        return {**common, 'status': 'not_found', 'candidates': documents, 'reason': '指定日期查無文件'}
    if len(selected) > 1:
        return {**common, 'status': 'ambiguous', 'candidates': documents, 'reason': '同字號多份文件，請指定日期'}
    jid = selected[0]['jid']
    url = f"{FJUD_BASE}/data.aspx?ty=JD&id={urllib.parse.quote(jid)}&ot=in"
    return {"status": "published", "jyear": jyear, "jcase": jcase, "jno": jno,
            "primary_source_url": url, "jid": jid, "doc_date": selected[0]['doc_date'], 'candidates': documents,
            "verified_via": "fjud_live", 'attempts': attempts,
            "note": "僅確認裁判字號存在且可由律師自行點開原文核對，未涵蓋裁判全文之實質內容比對"}


def verify_precedent_note(note, timeout=DEFAULT_TIMEOUT):
    """第一、二層：文件身分、案由與原文摘句；不代替獨立支持性查證。"""
    if not isinstance(note, dict):
        return {'status': 'invalid_precedent_note', 'reason': 'precedent_note 必須是物件'}
    required = ('citation', 'doc_date', 'doc_type', 'case_cause', 'quote', 'proposition')
    missing = [key for key in required if not isinstance(note.get(key), str) or not note[key].strip()]
    if missing:
        return {'status': 'invalid_precedent_note', 'citation_text': note.get('citation'),
                'reason': '缺少判例資料：' + ', '.join(missing)}
    parsed = parse_citation(note['citation'])
    if parsed['type'] != 'judgment':
        return {'status': 'unparseable', 'citation_text': note['citation'], 'reason': '不是可解析的裁判字號'}
    result = verify_judgment_citation(parsed['jyear'], parsed['jcase'], parsed['jno'], timeout=timeout, doc_date=note['doc_date'])
    result.update(citation_text=note['citation'], source_type='judgment', precedent_note=dict(note), support_review_required=True)
    if result['status'] != 'published':
        return result
    if not result.get('full_text') and result.get('jid'):
        fetched, attempts, error = _network_call(lambda: _fetch_judgment_text(result['jid'], timeout=timeout))
        if error:
            return {**result, 'status': 'network_error', 'reason': error, 'attempts': attempts}
        result.update(fetched)
    if result.get('doc_type') != note['doc_type']:
        return {**result, 'status': 'doc_type_mismatch', 'reason': f"引用文種 {note['doc_type']} 與原文 {result.get('doc_type')} 不符"}
    # 只忽略網頁與文字檔的換行空白，不容許改寫摘句。
    normalize = lambda text: re.sub(r'\s+', '', text or '')
    if normalize(note['quote']) not in normalize(result.get('full_text')):
        return {**result, 'status': 'quote_not_found', 'reason': '原文摘句不是裁判全文的子字串'}
    if not result.get('jtitle'):
        return {**result, 'status': 'document_identity_unverified', 'reason': '未取得官方裁判案由，不能核對文件身分'}
    normalize_cause = lambda cause: re.sub(r'^請求|等$', '', normalize(cause))
    if normalize_cause(note['case_cause']) != normalize_cause(result['jtitle']):
        if not isinstance(note.get('analogy_reason'), str) or not note['analogy_reason'].strip():
            return {**result, 'status': 'analogy_required', 'reason': '案由不同，須提供 analogy_reason 交獨立查證'}
        return {**result, 'status': 'needs_explanation', 'note': '需說明：案由不同；類推理由交獨立查證角色判斷'}
    return result


def validate_precedent_notes(notes):
    if not isinstance(notes, list):
        raise ValueError('precedent_notes 必須是陣列')
    results = [verify_precedent_note(note) for note in notes]
    errors = [r for r in results if r['status'] not in ('published', 'needs_explanation')]
    if errors:
        raise ValueError('判例查證拒絕落地：' + '; '.join(f"{r.get('citation_text', '')}: {r['status']} {r.get('reason', '')}" for r in errors))
    return results


def verify_citations(citation_texts, timeout=DEFAULT_TIMEOUT, *, precedent_notes=None, version_hints=None):
    notes = {note['citation']: note for note in (precedent_notes or []) if isinstance(note, dict) and 'citation' in note}
    hints = version_hints or {}
    results = []
    for citation_text in citation_texts:
        parsed = parse_citation(citation_text)
        if parsed["type"] == "statute":
            result = verify_statute_citation(parsed["law_name"], parsed["article_no"], timeout=timeout,
                                            citation_text=citation_text, version_hint=hints.get(citation_text))
        elif parsed["type"] == "judgment":
            note = notes.get(citation_text)
            if note is None:
                note = next((n for n in notes.values() if parse_citation(n['citation']) == parsed), None)
            result = (verify_precedent_note(note, timeout=timeout) if note else
                      verify_judgment_citation(parsed["jyear"], parsed["jcase"], parsed["jno"], timeout=timeout))
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
