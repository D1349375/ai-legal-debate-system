"""訴狀版本：律師編輯另存、引用重新查證、未放行不得匯出。即時查證一律以 monkeypatch 取代，不連網。"""
import pytest
from fastapi.testclient import TestClient

from database.db import get_session, record_case, record_pleading, upsert_citation
from database.schema import PleadingDraft
from engine import verify as engine_verify
from server import services
from server.app import create_app

LOCAL = "http://127.0.0.1:8000"
DRAFT = "民事起訴狀\n訴之聲明\n一、被告應給付原告50萬元。\n事實及理由\n依民法第474條請求返還借款。\n【本稿產出說明】骨架版"
FABRICATED = "最高法院105年度台簡上字第33號"


@pytest.fixture
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path / 'p.db'}"
    s = get_session(url)
    record_case(s, case_id="c1", case_type="消費借貸", facts_summary="借款未還", claims="返還借款")
    record_case(s, case_id="c2", case_type="其他", facts_summary="其他事實", claims="請求")
    upsert_citation(s, citation_text="民法第474條", source_type="statute", status="published",
                    primary_source_url="https://law.moj.gov.tw/x")
    record_pleading(s, case_id="c1", draft_text=DRAFT, citations_used=["民法第474條"])
    s.close()
    return url


@pytest.fixture
def calls(monkeypatch):
    """即時查證樁：民法第184條通過、其餘條文查無；判決一律查無。記錄每次被查的引用。"""
    seen = []

    def statute(law, art, timeout):
        seen.append(f"{law}第{art}條")
        if art == "184":
            return {"status": "published", "primary_source_url": "https://law.moj.gov.tw/184"}
        return {"status": "not_found", "note": "查無此條"}

    def judgment(y, c, n, timeout):
        seen.append(f"{y}{c}{n}")
        return {"status": "not_found", "note": "FJUD 查無", "fjud_query": "x", "fjud_hit_count": 0}

    monkeypatch.setattr(engine_verify, "verify_statute_citation", statute)
    monkeypatch.setattr(engine_verify, "verify_judgment_citation", judgment)
    return seen


@pytest.fixture
def client(db_url, tmp_path):
    app = create_app(db_url=db_url, cases_dir=str(tmp_path / "none"), live_checks_path=str(tmp_path / "none.json"),
                     seed_on_empty=False, local_clients=("testclient",))
    return TestClient(app, base_url=LOCAL)


def versions(client, case_id="c1"):
    return client.get(f"/api/cases/{case_id}").json()["pleading_versions"]


def save(client, text, parent_id=1, **extra):
    return client.post("/api/cases/c1/pleadings", json={"parent_id": parent_id, "draft_text": text, **extra})


class TestExtract:
    def test_recognized_and_unrecognized_citations(self):
        found = services.extract_citations(
            "依民法第184條第1項及土地法第34條之1，參最高法院108年度台上字第1號、臺灣高等法院110年度上字第5號，"
            "並依民法第184條。民事訴訟法第277條")
        assert [(c["citation_text"], c["recognized"]) for c in found] == [
            ("民法第184條", True), ("土地法第34條之1", False), ("最高法院108年度台上字第1號", True),
            ("110年度上字第5號", False), ("民事訴訟法第277條", True)]


class TestVersions:
    def test_system_version_is_listed_and_exportable(self, client):
        d = client.get("/api/cases/c1").json()
        assert d["pleading"]["id"] == 1 and d["pleading"]["draft_count"] == 1
        [v] = d["pleading_versions"]
        assert v["source"] == "system" and v["label"] == "系統產生版 #1" and v["exportable"] is True
        assert v["origin"] == {"kind": "recorded"}
        r = client.get("/api/cases/c1/pleadings/1/export")
        assert r.status_code == 200 and "c1_complaint_v1_system.txt" in r.headers["content-disposition"]
        text = r.content.decode("utf-8")
        assert text.startswith("﻿民事起訴狀") and "錄製紀錄" in text and "民法第474條:已查證通過" in text
        assert "須經執業律師審核" in text

    def test_lawyer_edit_keeps_original_and_verifies_new_citation(self, client, calls):
        edited = DRAFT.replace("依民法第474條請求返還借款。", "依民法第474條請求返還借款，並依民法第184條請求賠償。")
        r = save(client, edited)
        assert r.status_code == 201, r.text
        v = r.json()
        assert v["source"] == "lawyer_edit" and v["parent_id"] == 1 and v["exportable"] is True
        by = {c["citation_text"]: c for c in v["citation_check"]}
        assert by["民法第474條"]["change"] == "unchanged" and by["民法第474條"]["verified_now"] is False
        assert by["民法第184條"]["change"] == "added" and by["民法第184條"]["verified_now"] is True
        assert calls == ["民法第184條"]  # 沿用且已通過的引用不重查
        listed = versions(client)
        assert [x["source"] for x in listed] == ["system", "lawyer_edit"]
        assert listed[0]["draft_text"] == DRAFT  # 原稿不動
        assert client.get("/api/cases/c1").json()["pleading"]["id"] == 1  # 預設仍是系統產生版
        exported = client.get(f"/api/cases/c1/pleadings/{v['id']}/export").content.decode("utf-8")
        assert "律師在 UI 編輯後另存(基於 #1)" in exported and "民法第184條:已查證通過" in exported

    def test_failed_citation_blocks_export(self, client, calls):
        v = save(client, DRAFT + f"\n參{FABRICATED}。").json()
        assert v["status"] == "blocked" and v["exportable"] is False and v["blocked_count"] == 1
        bad = [c for c in v["citation_check"] if c["gate"] != "pass"][0]
        assert bad["citation_text"] == FABRICATED and bad["status"] == "not_found"
        r = client.get(f"/api/cases/c1/pleadings/{v['id']}/export")
        assert r.status_code == 409 and "未放行" in r.json()["detail"]

    def test_unrecognized_and_offline_citations_are_not_passed(self, client, calls, monkeypatch):
        monkeypatch.setattr(engine_verify, "verify_statute_citation",
                            lambda law, art, timeout: {"status": "verification_failed", "reason": "timed out"})
        v = save(client, DRAFT + "\n另依民法第184條及土地法第34條之1。").json()
        by = {c["citation_text"]: c for c in v["citation_check"]}
        assert by["民法第184條"]["status"] == "local_cache_only" and by["民法第184條"]["gate"] == "blocked"
        assert by["土地法第34條之1"]["status"] == "unparseable" and "無法辨識" in by["土地法第34條之1"]["note"]
        assert v["blocked_count"] == 2 and not v["exportable"]
        # 網路恢復後重新查證：只重查未通過者；認不得的寫法仍不放行
        monkeypatch.setattr(engine_verify, "verify_statute_citation",
                            lambda law, art, timeout: {"status": "published", "primary_source_url": "https://law.moj.gov.tw/184"})
        r = client.post(f"/api/cases/c1/pleadings/{v['id']}/reverify", json={})
        again = {c["citation_text"]: c for c in r.json()["citation_check"]}
        assert again["民法第184條"]["gate"] == "pass" and again["民法第184條"]["change"] == "added"
        assert again["土地法第34條之1"]["gate"] == "blocked" and r.json()["exportable"] is False

    def test_system_version_without_record_can_be_reverified(self, client, db_url, calls):
        s = get_session(db_url)
        s.add(PleadingDraft(case_id="c2", draft_text="民事起訴狀\n依民法第184條請求。", citation_verification_status="published",
                            generated_at="2026-10-01T00:00:00Z"))
        s.commit()
        [v] = versions(client, "c2")
        assert v["status"] == "blocked" and v["citation_check"][0]["status"] == "no_record"
        assert client.get(f"/api/cases/c2/pleadings/{v['id']}/export").status_code == 409
        r = client.post(f"/api/cases/c2/pleadings/{v['id']}/reverify", json={}).json()
        assert r["exportable"] is True and r["draft_text"] == "民事起訴狀\n依民法第184條請求。"

    def test_guards(self, client, db_url, tmp_path, calls):
        assert save(client, "   ").status_code == 422
        assert save(client, DRAFT, parent_id=999).status_code == 404
        assert client.post("/api/cases/c2/pleadings", json={"parent_id": 1, "draft_text": DRAFT}).status_code == 404
        assert client.get("/api/cases/c1/pleadings/999/export").status_code == 404
        remote = TestClient(create_app(db_url=db_url, cases_dir=str(tmp_path / "none"), seed_on_empty=False), base_url=LOCAL)
        assert remote.post("/api/cases/c1/pleadings", json={"parent_id": 1, "draft_text": DRAFT}).status_code == 403
        assert remote.post("/api/cases/c1/pleadings/1/reverify", json={}).status_code == 403
        assert remote.get("/api/cases/c1/pleadings/1/export").status_code == 200  # 匯出是唯讀
