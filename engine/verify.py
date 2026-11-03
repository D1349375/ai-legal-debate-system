"""法規/判例引用查證(對應實作規劃 1.3，比照 Startup Guide 的 draft→fact_checked→published)。

權威來源固定：法規查 law.moj.gov.tw(全國法規資料庫)；判例查司法院裁判書查詢系統 FJUD
(judgment.judicial.gov.tw)。2026-11-01 起兩者都經 engine/retrieval_cache.py 取得：
- 判決：本次實跑快照 → 長期快取 → corpus/judgments(唯讀預先內容) → 上網，抓到的寫回快取；
  查證與角色讀同一份全文。字號查詢用 FJUD 進階搜尋的字號欄位(engine/fjud.py)，同字號多份文件須指定日期。
- 條文：7 天內的快取可放行(verified_via 註明來源與抓取時間)；過期或沒有就上網，重試一次仍失敗回
  network_error。不退回 corpus/statutes/*.txt 的舊版法典：用過時條文放行比查不到更危險。
- 法規名稱：法務部開放資料建的名稱索引(corpus/statutes/law_index.json)裡的法規都能查；已廢止法規
  歸為 version_unverified，索引查無的名稱為 unsupported_law。
- 連上官網但頁面無法辨認條文或裁判全文時回 full_text_unavailable，與連線失敗的 network_error 分開；
  不讓它落到 doc_type_mismatch、quote_not_found 而讓人以為引用寫錯。兩者都不放行。
"""
import functools
import json
import os
import re

from engine import fjud, retrieval_cache
from engine.law_lookup import (  # noqa: F401 - 舊呼叫端仍由此匯入
    DEFAULT_TIMEOUT, STATUTES_DIR, _fetch_article_page, _network_call, _parse_article_html,
    known_law_names, resolve_law,
)

FJUD_BASE = fjud.FJUD_BASE
_FJUD_HEADERS = fjud.HEADERS

CORPUS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'corpus')
JUDGMENTS_DIR = os.path.join(CORPUS_DIR, 'judgments')
# 本次實跑快照(engine/retrieval_cache.py)；CLI 的 --snapshot 或 UI 實跑以環境變數指定，查證與角色讀同一版本。
SNAPSHOT_ENV = 'LEGAL_DEBATE_RUN_SNAPSHOT'

# 2026-11-01 前查證引擎只認這 11 部(含簡稱)；之後改用法規名稱索引(corpus/statutes/law_index.json，11,804 部)，
# 此表只留給既有測試核對索引與 pcode 一致。
STATUTE_PCODES = {
    "民法": "B0000001",
    "公司法": "J0080001",
    "勞動基準法": "N0030001",
    "勞基法": "N0030001",
    "消費者保護法": "J0170001",
    "刑法": "C0000001",
    "民事訴訟法": "B0010001",
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
# 判決書多用國字條號(「民法第一百二十七條」)。判例摘句要從全文逐字複製,國字條號就會進到書狀正文;
# 2026-11-03 實跑四份書狀因此被標 unparseable、不能匯出。國字條號換成阿拉伯數字再查(flno 用阿拉伯數字)。
# 判決書的「零」也常寫成圓圈「○」(第一○一條),和國字〇是不同字元,兩個都要認得。
_CN_NUM = '零〇○一二兩三四五六七八九十百千'
_ARTICLE_REF_RE = re.compile(rf'第\s*([0-9]+(?:-[0-9]+)?|[{_CN_NUM}]+)\s*條(?:\s*之\s*([0-9]+|[{_CN_NUM}]+))?')
_NAME_WINDOW = 40


def _arabic(number):
    """國字數字(一百二十七、二百零五、十二)→ '127'、'205'、'12';已是阿拉伯數字的原樣回傳。
    沒有十百千的逐位寫法(一○一、二二七)照位數讀:'101'、'227'。"""
    if not number or number[0].isdigit():
        return number
    digits = {'零': 0, '〇': 0, '○': 0, '一': 1, '二': 2, '兩': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
    units = {'十': 10, '百': 100, '千': 1000}
    if not any(ch in units for ch in number):
        return str(int(''.join(str(digits[ch]) for ch in number)))
    total, current = 0, 0
    for ch in number:
        if ch in digits:
            current = digits[ch]
        else:
            total += (current or 1) * units[ch]
            current = 0
    return str(total + current)
UNSUPPORTED_STATUTE_RE = re.compile(
    r'([㐀-鿿]+?(?:法|條例|規則|辦法|通則))\s*第\s*([0-9]+(?:-[0-9]+)?)\s*條(?:\s*之\s*([0-9]+))?'
)
# 字別(台上/台簡抗/台抗等)原為列舉白名單，2026-08-09 端到端測試發現本地語料庫實際涵蓋
# 台上/台再/台抗/台簡上/台簡抗/台簡聲/台聲共7種字別，列舉版只認得3種，其餘4種(尤其常見的
# 「台簡上」)一律 unparseable，等同於機械查證閘門會擋下所有引用該字別判例的合法引用——
# 跟先前「之N子條文」是同一類「白名單漏掉真實存在的變體」錯誤，故改為結構化比對(以「台」
# 開頭、後接1-3個非數字非空白字元)，不再逐一列舉，避免未來出現新字別時重蹈覆轍。
JUDGMENT_CITATION_RE = re.compile(r'(最高法院)?\s*([0-9]{2,3})年度(台[^\s字0-9]{1,3})字第\s*([0-9]+)\s*號')


@functools.lru_cache(maxsize=1)
def _law_names():
    return frozenset(known_law_names())


class _StatuteMatch:
    def __init__(self, text, start, end, law_name, article_no):
        self._text, self._span, self.law_name, self.article_no = text, (start, end), law_name, article_no

    def group(self, index=0):
        if index:
            raise IndexError('法條引用比對只提供 group(0)，名稱與條號請用 law_name、article_no')
        return self._text

    def start(self):
        return self._span[0]

    def end(self):
        return self._span[1]

    def span(self):
        return self._span


class _StatuteCitationFinder:
    """在文字中找「法規名稱第N條(之M)」；介面同正規式的 search／finditer。

    法規名稱取「第N條」前方文字中、名稱索引裡最長的那一段(避免把「依土地法第34條」切成「依土地法」，
    也讓「民法債編施行法」不會被切成「民法」)；索引外的名稱不在此列，由 UNSUPPORTED_STATUTE_RE 另行辨認。
    """

    def finditer(self, text):
        names = _law_names()
        for m in _ARTICLE_REF_RE.finditer(text):
            before = text[max(0, m.start() - _NAME_WINDOW):m.start()]
            stripped = before.rstrip()
            name = next((stripped[i:] for i in range(len(stripped)) if stripped[i:] in names), None)
            if name is None:
                continue
            start = m.start() - (len(before) - len(stripped)) - len(name)
            article_no = _arabic(m.group(1)) + (f"-{_arabic(m.group(2))}" if m.group(2) else '')
            yield _StatuteMatch(text[start:m.end()], start, m.end(), name, article_no)

    def search(self, text):
        return next(self.finditer(text), None)


STATUTE_CITATION_RE = _StatuteCitationFinder()


def parse_citation(citation_text):
    m = STATUTE_CITATION_RE.search(citation_text)
    if m:
        return {"type": "statute", "law_name": m.law_name, "article_no": m.article_no}
    m = JUDGMENT_CITATION_RE.search(citation_text)
    if m:
        return {"type": "judgment", "jyear": m.group(2), "jcase": m.group(3), "jno": m.group(4)}
    m = UNSUPPORTED_STATUTE_RE.search(citation_text)
    if m:
        article_no = m.group(2) + (f"-{m.group(3)}" if m.group(3) else "")
        return {"type": "statute", "law_name": m.group(1), "article_no": article_no}
    return {"type": "unknown"}


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
    """落地前的純本機分類；不以現行條文替歷史版本或已廢止法規背書。"""
    parsed = parse_citation(citation_text)
    if parsed['type'] != 'statute':
        return None
    common = {**parsed, 'citation_text': citation_text, 'source_type': 'statute'}
    if _historical_version(citation_text, version_hint):
        return {**common, 'status': 'version_unverified', 'note': '歷史條文版本尚未查證，律師待核；不得作為書狀引用'}
    law = resolve_law(parsed['law_name'])
    if law is None:
        return {**common, 'status': 'unsupported_law',
                'note': '法規名稱索引查無此法規，查證引擎尚未支援，律師待核；不表示法規不存在'}
    if law.get('abandoned'):
        return {**common, 'status': 'version_unverified',
                'note': f"{law['law_name']}已廢止，官網條文不是現行法；律師待核，不得作為書狀引用"}
    return None


def _snapshot(snapshot):
    return snapshot or os.environ.get(SNAPSHOT_ENV) or None


# 查證結果的 verified_via：本次實際從哪裡取得比對內容
_VIA = {'run_snapshot': 'run_snapshot', 'retrieval_cache': 'retrieval_cache', 'corpus': 'local_corpus'}


def verify_statute_citation(law_name, article_no, timeout=DEFAULT_TIMEOUT, *, citation_text=None, version_hint=None,
                            snapshot=None):
    """條文在快取有效期(7 天)內以快取放行並註明抓取時間；過期或沒有就上網(重試一次)，仍失敗回 network_error，
    不用過期版本或本地舊版法典放行。"""
    warning = citation_warning(citation_text or f'{law_name}第{article_no}條', version_hint)
    if warning:
        return warning
    law = resolve_law(law_name)
    if law is None:
        return {"status": "unsupported_law", "law_name": law_name, "article_no": article_no}
    common = {'law_name': law_name, 'article_no': article_no, 'official_name': law['law_name'], 'pcode': law['pcode']}
    try:
        r = retrieval_cache.get_article(law, article_no, snapshot=_snapshot(snapshot), timeout=timeout)
    except retrieval_cache.RetrievalUnavailable as error:
        return {**common, 'status': 'network_error', 'reason': str(error), 'note': '官網無法連線且無有效快取，非查無此條'}
    if r['status'] == 'not_found':
        return {**common, 'status': 'not_found', 'primary_source_url': r['url'], 'attempts': r['attempts'],
                'note': '官網查無此條（已重查確認），可能條號有誤或該條已刪除'}
    if r['status'] != 'found':
        return {**common, 'status': 'full_text_unavailable', 'reason': r.get('reason'), 'primary_source_url': r.get('url'),
                'note': '全國法規資料庫頁面無法辨認條文，不代表引用寫錯或查無此條'}
    return {**common, 'status': 'published', 'primary_source_url': r['url'], 'matched_text': r['text'],
            'verified_via': _VIA.get(r['served_from'], 'law_moj_live'), 'fetched_at': r['fetched_at'],
            'modified_date': r.get('modified_date'), 'attempts': r['attempts']}


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


def _document(entry, served):
    """快取記錄 → 查證結果的文件欄位。預先內容沿用原本的來源檔與 PDF 網址。"""
    document = {'jid': entry['jid'], 'doc_date': entry['doc_date'], 'doc_type': _document_type(entry['text']),
                'jtitle': entry.get('case_cause'), 'full_text': entry['text'], 'matched_text': entry['text'][:200],
                'primary_source_url': entry.get('source_pdf_url') or entry.get('source_url'),
                'verified_via': _VIA.get(served, 'fjud_live'), 'fetched_at': entry.get('fetched_at')}
    if entry.get('source_file'):
        document['source_file'] = entry['source_file']
    return document


def _cached_document(jid, snapshot):
    """不連網取全文；有的話記進快照，查證與角色比對同一份。"""
    try:
        entry = retrieval_cache.get_judgment(jid, snapshot=snapshot, corpus_dir=JUDGMENTS_DIR, allow_live=False)
    except retrieval_cache.LiveFetchNotAllowed:
        return None
    return _document(entry, entry['served_from'])


def verify_judgment_citation(jyear, jcase, jno, timeout=DEFAULT_TIMEOUT, *, doc_date=None, snapshot=None):
    """字號 → 文件身分。字號對照與全文都先查快照、預先內容與長期快取，沒有才上網(重試一次)；
    同字號多份文件時須以 doc_date 唯一識別。"""
    common = {'jyear': jyear, 'jcase': jcase, 'jno': jno}
    if doc_date is not None:
        doc_date = re.sub(r'[-/]', '', str(doc_date))
        if not re.fullmatch(r'\d{8}', doc_date):
            return {**common, 'status': 'invalid_document_date', 'reason': 'doc_date 必須是 YYYYMMDD'}
    snapshot = _snapshot(snapshot)
    citation_query = f"{jyear}年度{jcase}字第{jno}號"
    try:
        found = retrieval_cache.judgment_candidates(
            jyear, jcase, jno, snapshot=snapshot, corpus_dir=JUDGMENTS_DIR,
            search=lambda: _fjud_search(jyear, jcase, jno, timeout=timeout), timeout=timeout)
    except retrieval_cache.RetrievalUnavailable as error:
        return {"status": "network_error", **common, "reason": str(error), "note": "FJUD 即時查證連線失敗，非查無此判決"}
    if not found['jids']:
        return {"status": "not_found", **common, "fjud_query": citation_query, "fjud_raw_hits": found.get('raw_hits', []),
                "note": "FJUD 即時查證查無此裁判字號，可能字號有誤，或非最高法院裁判(本查證僅涵蓋TPSV前綴/最高法院)"}
    documents = []
    for jid in found['jids']:
        entry, served = retrieval_cache.peek_judgment(jid, snapshot, JUDGMENTS_DIR)
        documents.append(_document(entry, served) if entry else {'jid': jid, 'doc_date': retrieval_cache.doc_date_of(jid)})
    public_candidates = [{k: v for k, v in d.items() if k not in ('full_text', 'matched_text')} for d in documents]
    selected = [d for d in documents if doc_date is None or d['doc_date'] == doc_date]
    if not selected:
        return {**common, 'status': 'not_found', 'candidates': public_candidates, 'reason': '該字號沒有指定日期的裁判文件'}
    if len(selected) > 1:
        return {**common, 'status': 'ambiguous', 'candidates': public_candidates,
                'reason': '同一字號有多份文件，須指定可唯一識別的 doc_date'}
    jid = selected[0]['jid']
    document = _cached_document(jid, snapshot)
    if document is not None:
        return {**common, **document, 'status': 'published', 'candidates': public_candidates}
    return {"status": "published", **common, "primary_source_url": fjud.document_url(jid), "jid": jid,
            "doc_date": selected[0]['doc_date'], 'candidates': public_candidates,
            "verified_via": "fjud_live" if found['served_from'] == 'live' else _VIA[found['served_from']],
            "note": "僅確認裁判字號存在且可由律師自行點開原文核對，未涵蓋裁判全文之實質內容比對"}


def verify_precedent_note(note, timeout=DEFAULT_TIMEOUT, *, snapshot=None):
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
    snapshot = _snapshot(snapshot)
    result = verify_judgment_citation(parsed['jyear'], parsed['jcase'], parsed['jno'], timeout=timeout,
                                      doc_date=note['doc_date'], snapshot=snapshot)
    result.update(citation_text=note['citation'], source_type='judgment', precedent_note=dict(note), support_review_required=True)
    if result['status'] != 'published':
        return result
    if not result.get('full_text') and result.get('jid'):
        # 與角色讀的是同一份：快照 → 長期快取 → 預先內容 → 上網，抓到的寫回快取與快照。
        try:
            entry = retrieval_cache.get_judgment(result['jid'], snapshot=snapshot, corpus_dir=JUDGMENTS_DIR, timeout=timeout)
        except retrieval_cache.FullTextUnavailable as error:
            return {**result, 'status': 'full_text_unavailable', 'reason': str(error),
                    'note': '官網頁面無法辨認裁判全文，未能比對文種與摘句；不代表引用寫錯'}
        except retrieval_cache.RetrievalUnavailable as error:
            return {**result, 'status': 'network_error', 'reason': str(error)}
        result.update({k: v for k, v in _document(entry, entry['served_from']).items() if k != 'source_file'})
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


PASSING = ('published', 'needs_explanation')
SIDE_LABELS = {'plaintiff': '原告', 'defendant': '被告'}


def _read_by_snapshot(snapshot, read_by):
    snapshot = _snapshot(snapshot)
    if read_by and not snapshot:
        raise ValueError('read_by 須搭配案件快照根目錄(--snapshot 或環境變數 LEGAL_DEBATE_RUN_SNAPSHOT)')
    return snapshot


def _require_read(result, snapshot, read_by):
    """read_by(plaintiff／defendant)：該方角色在本案沒有用 judgment 讀過全文的判決不放行。
    字號與摘句比對過了也一樣：摘句可能取自 search-judgments 的命中句，沒讀前後文就引用。"""
    if not read_by or result.get('status') not in PASSING or not result.get('jid'):
        return result
    if retrieval_cache.read_by_side(snapshot, read_by, result['jid']):
        return result
    return {**result, 'status': 'not_read_by_side', 'read_by': read_by,
            'reason': f"{SIDE_LABELS.get(read_by, read_by)}在本案沒有用 judgment 讀過這份判決全文",
            'note': '字號存在，但引用方沒讀過全文，不放行；用 judgment 讀過全文(帶本方的 --snapshot)再引用'}


def validate_precedent_notes(notes, *, snapshot=None, read_by=None):
    if not isinstance(notes, list):
        raise ValueError('precedent_notes 必須是陣列')
    snapshot = _read_by_snapshot(snapshot, read_by)
    results = [_require_read(verify_precedent_note(note, snapshot=snapshot), snapshot, read_by) for note in notes]
    errors = [r for r in results if r['status'] not in PASSING]
    if errors:
        raise ValueError('判例查證拒絕落地：' + '; '.join(f"{r.get('citation_text', '')}: {r['status']} {r.get('reason', '')}" for r in errors))
    return results


def verify_citations(citation_texts, timeout=DEFAULT_TIMEOUT, *, precedent_notes=None, version_hints=None, snapshot=None,
                     read_by=None):
    """read_by：查某一方書狀的引用時給 plaintiff 或 defendant，該方沒用 judgment 讀過全文的判決回 not_read_by_side。"""
    if read_by:
        snapshot = _read_by_snapshot(snapshot, read_by)
    notes ={note['citation']: note for note in (precedent_notes or []) if isinstance(note, dict) and 'citation' in note}
    hints = version_hints or {}
    results = []
    for citation_text in citation_texts:
        parsed = parse_citation(citation_text)
        if parsed["type"] == "statute":
            result = verify_statute_citation(parsed["law_name"], parsed["article_no"], timeout=timeout,
                                            citation_text=citation_text, version_hint=hints.get(citation_text),
                                            snapshot=snapshot)
        elif parsed["type"] == "judgment":
            note = notes.get(citation_text)
            if note is None:
                note = next((n for n in notes.values() if parse_citation(n['citation']) == parsed), None)
            result = (verify_precedent_note(note, timeout=timeout, snapshot=snapshot) if note else
                      verify_judgment_citation(parsed["jyear"], parsed["jcase"], parsed["jno"], timeout=timeout,
                                               snapshot=snapshot))
            result = _require_read(result, snapshot, read_by)
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
