"""斷網重播:案件的商工查核要跟著案件 fixture 匯出、匯入(C1 的 V39、審查 W8-5)。

原本 fixture 只有 _TABLES 的六張表,商工查核另存在 recorded_party_checks.json(只有統編,
沒有案件與角色),重播時要先按一次查核,起訴審查卡片才會出現。
"""
import json

from fastapi.testclient import TestClient

from database.db import get_session, latest_party_checks, record_case, record_party_check
from database.schema import PartyCheck
from engine import party_rules
from server import seed
from server.app import create_app


def _company_calls():
    rows = [{"Business_Accounting_NO": "22099131", "Company_Name": "測試股份有限公司",
             "Company_Status_Desc": "解散", "Responsible_Name": "王小明",
             "Company_Location": "臺北市", "Company_Setup_Date": "0900101"}]
    ok = lambda r: {"ok": True, "rows": r, "url": "https://data.gcis.nat.gov.tw/x", "error": None,
                    "fetched_at": "2026-10-03T00:00:00Z"}
    return {"entity_type": ok([{"TYPE": "公司", "exist": "Y"}]), "company": ok(rows),
            "directors": ok([]), "branches": ok([])}


def _record(session, case_id, role, ban, status):
    calls = _company_calls()
    result = party_rules.summarize(ban, "company", calls)
    result.update(query_status=status, via="gcis_live", fetched_at="2026-10-03T00:00:00Z")
    raw = {k: {"rows": v["rows"], "url": v["url"], "ok": v["ok"], "error": v["error"]} for k, v in calls.items()}
    return record_party_check(session, case_id=case_id, role=role, query_ban=ban, result=result, raw=raw,
                              fetched_at=result["fetched_at"])


def _source_db(tmp_path):
    session = get_session(f"sqlite:///{tmp_path / 'src.db'}")
    record_case(session, case_id="c1", case_type="清償債務", facts_summary="事實", claims="請求")
    _record(session, "c1", "defendant", "22099131", "ok")
    _record(session, "c1", "defendant", "22099131", "failed")  # 後查的那筆才是畫面上的「最新」
    _record(session, "voided", "defendant", "22099132", "ok")
    _record(session, None, None, "22099133", "ok")
    return session


def test_case_party_checks_go_into_the_case_fixture(tmp_path):
    src = _source_db(tmp_path)
    path = tmp_path / "fixture.json"
    counts = seed.write_fixture(src, str(path))
    assert counts["party_checks"] == 3  # 作廢案件那筆不匯出;沒指定案件的單獨查詢照舊匯出
    data = json.loads(path.read_text(encoding="utf-8"))
    assert [(r["case_id"], r["role"]) for r in data["party_checks"]] == [
        ("c1", "defendant"), ("c1", "defendant"), (None, None)]
    assert seed.orphan_rows(src) == {"party_checks": {"voided": 1}}


def test_seeded_database_restores_the_latest_check_per_role(tmp_path):
    src = _source_db(tmp_path)
    path = tmp_path / "fixture.json"
    seed.write_fixture(src, str(path))
    dst = get_session(f"sqlite:///{tmp_path / 'fresh.db'}")
    assert seed.seed_if_empty(dst, str(path))["party_checks"] == 3
    restored = latest_party_checks(dst, "c1")["defendant"]
    original = latest_party_checks(src, "c1")["defendant"]
    assert restored == original and restored["query_status"] == "failed"
    assert {r.created_at for r in dst.query(PartyCheck).all()} <= {r.created_at for r in src.query(PartyCheck).all()}


def test_old_fixture_without_party_checks_still_seeds(tmp_path):
    src = _source_db(tmp_path)
    path = tmp_path / "fixture.json"
    seed.write_fixture(src, str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["party_checks"]
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    dst = get_session(f"sqlite:///{tmp_path / 'fresh.db'}")
    counts = seed.seed_if_empty(dst, str(path))
    assert counts["cases"] == 1 and counts["party_checks"] == 0


def test_replayed_case_shows_the_procedural_card_without_a_new_check(tmp_path):
    src = _source_db(tmp_path)
    path = tmp_path / "fixture.json"
    seed.write_fixture(src, str(path))
    app = create_app(db_url=f"sqlite:///{tmp_path / 'replay.db'}", cases_dir=str(tmp_path), fixture_path=str(path),
                     live_checks_path=str(tmp_path / "none.json"), party_checks_path=str(tmp_path / "none.json"))
    detail = TestClient(app).get("/api/cases/c1").json()
    assert detail["party_checks"]["defendant"]["ban"] == "22099131"
