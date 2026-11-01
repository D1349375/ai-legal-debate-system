"""檢索快取：長期快取(跨實跑) + 每次實跑快照。法條與判決只從網路取得，抓過的進快取。

長期快取放在 database/retrieval_cache/(不進 git；測試以環境變數 LEGAL_DEBATE_RETRIEVAL_CACHE 改到暫存目錄)：
- 判決全文以 JID 為鍵，長期有效。查找順序：長期快取 → corpus/judgments/(唯讀預先內容) → 上網，上網抓到的寫回。
- 條文以 pcode＋條號為鍵，7 天有效(官方每週更新)，過期重抓；重抓失敗不用過期版本。
- 搜尋結果列表不快取(總筆數與排序會變，2026-11-01 評估相差 1～4%)。

每個案件一份快照(snapshot)，跨律師確認關卡與續跑沿用：本案用到的每份判決與條文都存一份(內容、來源、抓取時間、
雜湊)，之後的角色與查證都先讀快照，確保讀到同一版本，事後檢討與重播不需網路。字號 → JID 的對照也存在快照
(citations/)，同一案件不用重查。

快照依角色分開：<快照根目錄>/plaintiff/、<快照根目錄>/defendant/，由調度員以 {RETRIEVAL_CACHE_DIR} 傳給該角色指令的
--snapshot。判決內容是公開資料，但讀過哪些判決會透露研究方向(屬於內部分析)，所以對造不得共用。
查證與調度員以快照根目錄為 --snapshot：讀取時一併查雙方子資料夾，自己新讀的記在根目錄。

每筆記錄一個 JSON 檔、寫入時先寫暫存檔再改名：雙方角色會同時執行，不共用同一個索引檔就不會互相覆寫。
連線失敗重試一次；仍失敗且快取沒有時拋 RetrievalUnavailable，訊息寫明「不代表查無資料」，不退回本地舊版法典。
"""
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone

from engine import fjud
from engine.law_lookup import NETWORK_ERRORS, fetch_article, with_retry

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
DEFAULT_CACHE_DIR = os.path.join(ROOT, 'database', 'retrieval_cache')
CORPUS_JUDGMENTS_DIR = os.path.join(ROOT, 'corpus', 'judgments')
CACHE_ENV = 'LEGAL_DEBATE_RETRIEVAL_CACHE'
STATUTE_TTL = timedelta(days=7)
UNAVAILABLE_NOTE = '網路無法連線且無快取，不代表查無資料'
# served_from：本次從哪裡取得。snapshot_source：寫進快照時的來源(預先內容／長期快取／上網)。
SERVED_FROM = ('run_snapshot', 'retrieval_cache', 'corpus', 'live')
SNAPSHOT_SIDES = ('plaintiff', 'defendant')


def snapshot_dirs(snapshot):
    """讀取快照時要查的資料夾：本身，加上底下存在的角色子資料夾(以根目錄讀取時涵蓋雙方)。"""
    if not snapshot:
        return []
    sides = [os.path.join(snapshot, side) for side in SNAPSHOT_SIDES]
    return [snapshot] + [path for path in sides if os.path.isdir(path)]


class LiveFetchNotAllowed(Exception):
    """快取沒有、且呼叫端不允許上網(查詢預算用完或只查快取)。"""


class RetrievalUnavailable(Exception):
    def __init__(self, reason):
        super().__init__(f'retrieval_unavailable：{reason}；{UNAVAILABLE_NOTE}')
        self.reason = reason


def cache_dir():
    return os.environ.get(CACHE_ENV) or DEFAULT_CACHE_DIR


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _parse_iso(value):
    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _sha256(text):
    return hashlib.sha256((text or '').encode('utf-8')).hexdigest()


def _file_name(key):
    return re.sub(r'[\\/:*?"<>|]', '_', key) + '.json'


def _read(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write(path, entry):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix='.tmp')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(entry, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _record_snapshot(snapshot, path_fn, key, entry, source):
    if snapshot:
        _write(path_fn(snapshot, key), {**entry, 'snapshot_source': source, 'snapshot_at': now_iso()})


# ───────────────────────── 判決 ─────────────────────────

def _judgment_path(base, jid):
    return os.path.join(base, 'judgments', _file_name(jid))


def doc_date_of(jid):
    parts = jid.split(',')
    return parts[4] if len(parts) > 4 else None


def judgment_entry(jid, text, case_cause, source_url, origin, **extra):
    """預先內容(origin='corpus')來自司法院開放資料月封裝檔，沒有抓取時間；其餘記錄寫入當下時間。"""
    return {'kind': 'judgment', 'jid': jid, 'doc_date': doc_date_of(jid), 'case_cause': case_cause,
            'source_url': source_url, 'fetched_at': None if origin == 'corpus' else now_iso(), 'origin': origin,
            'sha256': _sha256(text), 'text': text, **extra}


def _corpus_judgment(jid, corpus_dir):
    path = os.path.join(corpus_dir, jid + '.txt')
    if not os.path.isfile(path):
        return None
    with open(path, encoding='utf-8') as f:
        text = f.read()
    metadata = _read(os.path.splitext(path)[0] + '_source.json') or {}
    return judgment_entry(jid, text, metadata.get('jtitle'), fjud.document_url(jid), 'corpus', source_file=path, source_pdf_url=metadata.get('source_pdf_url'),
                          doc_date=metadata.get('jdate') or doc_date_of(jid))


def peek_judgment(jid, snapshot=None, corpus_dir=None):
    """不連網：→ (entry, served_from)，都沒有時 (None, None)。"""
    for folder in snapshot_dirs(snapshot):
        entry = _read(_judgment_path(folder, jid))
        if entry:
            return entry, 'run_snapshot'
    entry = _read(_judgment_path(cache_dir(), jid))
    if entry:
        return entry, 'retrieval_cache'
    entry = _corpus_judgment(jid, corpus_dir or CORPUS_JUDGMENTS_DIR)
    return (entry, 'corpus') if entry else (None, None)


def get_judgment(jid, snapshot=None, corpus_dir=None, timeout=fjud.DEFAULT_TIMEOUT, session=None, allow_live=True):
    """→ 判決全文記錄＋served_from。查找順序：快照 → 長期快取 → 預先內容 → 上網(寫回長期快取)；
    用到的版本都記進快照。allow_live=False 時不上網(查詢預算用完)，快取沒有就拋 LiveFetchNotAllowed。"""
    entry, served = peek_judgment(jid, snapshot, corpus_dir)
    if entry is None:
        if not allow_live:
            raise LiveFetchNotAllowed(jid)
        try:
            document = with_retry(lambda: fjud.fetch_document(jid, timeout=timeout, session=session))
        except NETWORK_ERRORS as error:
            raise RetrievalUnavailable(f'司法院裁判書查詢系統連線失敗（{error}）') from error
        if not document['full_text']:
            raise RetrievalUnavailable('官網頁面無法辨認裁判全文')
        entry, served = store_judgment(jid, document['full_text'], document['case_cause'], document['url']), 'live'
    if served != 'run_snapshot':
        _record_snapshot(snapshot, _judgment_path, jid, entry, served)
    return {**entry, 'served_from': served}


def store_judgment(jid, text, case_cause, source_url, snapshot=None):
    """上網抓到的全文寫進長期快取(search-judgments --fetch 也走這裡)。"""
    entry = judgment_entry(jid, text, case_cause, source_url, 'live')
    _write(_judgment_path(cache_dir(), jid), entry)
    _record_snapshot(snapshot, _judgment_path, jid, entry, 'live')
    return entry


def _citation_path(base, prefix):
    return os.path.join(base, 'citations', _file_name(prefix.rstrip(',')))


def corpus_jids(prefix, corpus_dir):
    if not os.path.isdir(corpus_dir):
        return []
    return sorted(name[:-4] for name in os.listdir(corpus_dir) if name.startswith(prefix) and name.endswith('.txt'))


def cached_jids(prefix):
    folder = os.path.join(cache_dir(), 'judgments')
    if not os.path.isdir(folder):
        return []
    return sorted(entry['jid'] for entry in (_read(os.path.join(folder, n)) for n in os.listdir(folder)
                                              if n.startswith(prefix) and n.endswith('.json')) if entry)


def judgment_candidates(jyear, jcase, jno, snapshot=None, corpus_dir=None, doc_date=None,
                        search=None, timeout=fjud.DEFAULT_TIMEOUT):
    """裁判字號 → {'jids', 'served_from'}：同字號的全部文件(多份時由呼叫端依日期選)。

    查找順序：快照的字號對照 → 預先內容(視為完整) → 指定日期且長期快取已有該份 → 上網進階搜尋。
    沒指定日期時只靠長期快取無法確認是否還有同字號的其他文件，所以仍上網。
    search 為上網查字號的函式(預設 FJUD 進階搜尋)，回傳 JID 清單；連線失敗重試一次，仍失敗拋 RetrievalUnavailable。
    """
    prefix = f"TPSV,{jyear},{jcase},{jno},"
    for folder in snapshot_dirs(snapshot):
        recorded = _read(_citation_path(folder, prefix))
        if recorded is not None:
            return {'jids': recorded['jids'], 'served_from': 'run_snapshot'}
    jids, served = corpus_jids(prefix, corpus_dir or CORPUS_JUDGMENTS_DIR), 'corpus'
    if not jids and doc_date:
        jids, served = [j for j in cached_jids(prefix) if doc_date_of(j) == doc_date], 'retrieval_cache'
    if not jids:
        search = search or (lambda: [row['jid'] for row in fjud.advanced_search(
            citation=(jyear, jcase, jno), pages=1, timeout=timeout)['rows']])
        try:
            hits = with_retry(search)
        except NETWORK_ERRORS as error:
            raise RetrievalUnavailable(f'司法院裁判書查詢系統連線失敗（{error}）') from error
        jids, served = sorted({j for j in hits if j.startswith(prefix)}), 'live'
        if not jids:
            return {'jids': [], 'served_from': served, 'raw_hits': hits}
    if snapshot:
        _write(_citation_path(snapshot, prefix), {'citation_prefix': prefix, 'jids': jids, 'source': served,
                                                   'recorded_at': now_iso()})
    return {'jids': jids, 'served_from': served}


# ───────────────────────── 條文 ─────────────────────────

def _article_path(base, key):
    return os.path.join(base, 'statutes', _file_name(key))


def _article_key(pcode, flno):
    return f"{pcode}_{flno}"


def is_fresh(entry, now=None):
    fetched = _parse_iso((entry or {}).get('fetched_at'))
    return fetched is not None and (now or datetime.now(timezone.utc)) - fetched <= STATUTE_TTL


def peek_article(pcode, flno, snapshot=None):
    """不連網：→ (entry, served_from)，不論是否過期；都沒有時 (None, None)。呼叫端以 is_fresh 判斷能否放行。"""
    key = _article_key(pcode, flno)
    places = [(folder, 'run_snapshot') for folder in snapshot_dirs(snapshot)] + [(cache_dir(), 'retrieval_cache')]
    for base, served in places:
        entry = _read(_article_path(base, key))
        if entry and (is_fresh(entry) or served == 'retrieval_cache'):
            return entry, served
    return None, None


def get_article(law, flno, snapshot=None, timeout=fjud.DEFAULT_TIMEOUT):
    """law 為 law_lookup.resolve_law 的結果。→ {'status': found|not_found|unrecognized_page, 'text', 'url',
    'fetched_at', 'served_from', ...}；有效期內讀快取，否則上網(重試一次)，仍失敗拋 RetrievalUnavailable。"""
    key = _article_key(law['pcode'], flno)
    entry, served = peek_article(law['pcode'], flno, snapshot)
    if entry is None or not is_fresh(entry):
        try:
            fetched = fetch_article(law['pcode'], flno, timeout=timeout)
        except NETWORK_ERRORS as error:
            stale = f'；快取版本抓取於 {entry["fetched_at"]}，已超過 7 天，不使用' if entry else ''
            raise RetrievalUnavailable(f'全國法規資料庫連線失敗（{error}）{stale}') from error
        if fetched['status'] != 'found':
            return {**fetched, 'served_from': 'live'}
        entry = {'kind': 'statute', 'law_name': law['law_name'], 'pcode': law['pcode'], 'article_no': flno,
                 'modified_date': law.get('modified_date'), 'abandoned': law.get('abandoned', False),
                 'url': fetched['url'], 'fetched_at': now_iso(), 'origin': 'live',
                 'sha256': _sha256(fetched['text']), 'text': fetched['text']}
        _write(_article_path(cache_dir(), key), entry)
        served = 'live'
        attempts = fetched['attempts']
    else:
        attempts = 0
    if served != 'run_snapshot':
        _record_snapshot(snapshot, _article_path, key, entry, served)
    return {**entry, 'status': 'found', 'served_from': served, 'attempts': attempts}


# ───────────────────────── 快照與快取盤點 ─────────────────────────

def snapshot_manifest(snapshot):
    """→ 快照內每份判決與條文的來源、抓取時間、雜湊(不含全文)，供實跑紀錄與驗收比對。
    scope 為記錄所在的角色子資料夾，根目錄(查證與調度員)為 case。"""
    manifest = {'judgments': [], 'statutes': [], 'citations': []}
    for base in snapshot_dirs(snapshot):
        scope = 'case' if base == snapshot else os.path.basename(base)
        for kind in manifest:
            folder = os.path.join(base, kind)
            if not os.path.isdir(folder):
                continue
            for name in sorted(os.listdir(folder)):
                entry = _read(os.path.join(folder, name)) if name.endswith('.json') else None
                if entry:
                    manifest[kind].append({**{k: v for k, v in entry.items() if k != 'text'}, 'scope': scope})
    return manifest


def cache_counts(base=None):
    base = base or cache_dir()
    count = lambda kind: (sum(n.endswith('.json') for n in os.listdir(os.path.join(base, kind)))
                          if os.path.isdir(os.path.join(base, kind)) else 0)
    return {'judgments': count('judgments'), 'statutes': count('statutes')}
