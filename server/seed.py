"""錄製紀錄的匯出/匯入，讓 demo 不依賴那顆被 .gitignore 排除的 database/legal_debate.db。

fixture 只是把資料庫裡「已落地」的資料原樣搬出(保留 created_at 等原始時間戳)，
不新增、不改寫任何論證內容；匯入只發生在資料庫完全沒有案件時。
"""
import datetime
import json
import os

from database.schema import (
    Case, CitationVerification, CourtQuestion, DebateArgument, PleadingDraft, Verdict,
)
from engine.verify import verify_citations
from database.db import _citation_key

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO_DIR = os.path.join(ROOT, "demo")
FIXTURE_PATH = os.path.join(DEMO_DIR, "recorded_cases.json")
LIVE_CHECKS_PATH = os.path.join(DEMO_DIR, "recorded_live_checks.json")

# 匯出/匯入順序即資料表順序；court_questions 依原始 id 排序以保留訊問先後
_TABLES = (
    ("cases", Case), ("debate_arguments", DebateArgument), ("court_questions", CourtQuestion),
    ("verdicts", Verdict), ("citation_verifications", CitationVerification),
    ("pleading_drafts", PleadingDraft),
)


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_dict(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns if c.name != "id"}


def export_fixture(session):
    data = {
        "_meta": {"format": "legaldebate-recorded-cases/1", "exported_at": _now_iso(),
                  "note": "資料庫已落地紀錄的原樣匯出(含原始 created_at)，非即時生成；內容由 Claude Code subagent 產生後經 record CLI 落地。"},
    }
    for name, model in _TABLES:
        data[name] = [_row_to_dict(r) for r in session.query(model).order_by(model.id).all()]
    return data


def write_fixture(session, path=FIXTURE_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = export_fixture(session)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return {name: len(data[name]) for name, _ in _TABLES}


def seed_if_empty(session, path=FIXTURE_PATH):
    """DB 內沒有任何案件、且 fixture 存在時才匯入。回傳匯入筆數(dict)或 None(未匯入)。"""
    if session.query(Case).count() > 0 or not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    counts = {}
    for name, model in _TABLES:
        rows = data.get(name, [])
        session.add_all(model(**row) for row in rows)
        counts[name] = len(rows)
    session.commit()
    return counts


def collect_live_checks(session):
    """對「DB 內沒有 published 紀錄」的已引用引用，實際執行一次查證並記下結果(含時間戳)。

    用途：現場離線時，UI 能把「先前錄製的實際查證結果」與「本次查證失敗」分開顯示，
    兩者不得混為一談。此函式必須連網執行，結果原樣記錄，不改寫。
    """
    published = {_citation_key(r.citation_text) for r in
                 session.query(CitationVerification).filter_by(status="published").all()}
    cited = set()
    for a in session.query(DebateArgument).all():
        for raw in (a.cited_statutes, a.cited_precedents):
            cited.update(json.loads(raw or "[]"))
    pending = sorted(c for c in cited if _citation_key(c) not in published)
    checks = []
    for text in pending:
        r = verify_citations([text], timeout=20)[0]
        entry = {"citation_text": text, "status": r.get("status"), "checked_at": _now_iso(),
                 "source_type": r.get("source_type"), "note": r.get("note")}
        if r.get("status") == "verification_failed":
            continue  # 查不到就不記錄，避免把「連線失敗」誤當成有意義的先前結果
        if r.get("status") == "not_found":
            entry["verified_via"] = "fjud_live"
            entry["fjud_query"] = r.get("fjud_query")
            entry["fjud_hit_count"] = len(r.get("fjud_raw_hits", []))
        checks.append(entry)
    return checks


def write_live_checks(session, path=LIVE_CHECKS_PATH):
    checks = collect_live_checks(session)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"_meta": {"format": "legaldebate-recorded-live-checks/1", "recorded_at": _now_iso(),
                             "note": "對 DB 中無 published 紀錄之引用，於 recorded_at 實際連線查證的原始結果。"},
                   "checks": checks}, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return checks


def load_recorded_checks(path=LIVE_CHECKS_PATH):
    """→ {citation_key: entry}，供 verify/case detail 以正規化 key 比對。"""
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {_citation_key(c["citation_text"]): {**c, "recorded_at": data["_meta"]["recorded_at"],
                                                  "source": "demo/recorded_live_checks.json"}
            for c in data.get("checks", [])}
