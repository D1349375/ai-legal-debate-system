"""書狀屬於哪一方(side):原告起訴狀 / 被告答辯狀。舊資料庫遷移、落地閘門、CLI 與撰狀素材。"""
import json
import os
import sqlite3
import subprocess
import sys

import pytest

from database.db import (
    DB_URL_ENV, get_session, pleading_materials, pleading_side, record_argument, record_case, record_pleading,
    record_pleading_edit, upsert_citation,
)
from database.schema import PleadingDraft

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ANSWER = "民事答辯狀\n答辯聲明\n一、原告之訴及假執行之聲請均駁回。\n事實及理由\n依民法第125條為時效抗辯。"


def run_main(*args, db_url):
    env = {**os.environ, DB_URL_ENV: db_url, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, "main.py", *args], cwd=ROOT, env=env, capture_output=True,
                          encoding="utf-8", timeout=60)


@pytest.fixture
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path / 'side.db'}"
    s = get_session(url)
    record_case(s, case_id="c1", case_type="消費借貸", facts_summary="借款未還", claims="被告應給付原告50萬元")
    upsert_citation(s, citation_text="民法第474條", source_type="statute", status="published")
    upsert_citation(s, citation_text="民法第125條", source_type="statute", status="published")
    s.close()
    return url


def land_stage3(url, *, defendant=True):
    s = get_session(url)
    record_argument(s, case_id="c1", side="plaintiff", stage=3, position="被告應返還借款", reasoning="原告論證",
                    cited_statutes=["民法第474條"], falsifier="若無交付借款")
    if defendant:
        record_argument(s, case_id="c1", side="defendant", stage=3, position="請求權已罹於時效", reasoning="被告論證",
                        cited_statutes=["民法第125條", "民法第144條"], falsifier="若有中斷時效事由")
    s.close()


class TestMigration:
    def test_old_database_gains_side_column_and_reads_as_plaintiff(self, tmp_path):
        path = tmp_path / "old.db"
        conn = sqlite3.connect(path)
        # side 欄位新增前的 pleading_drafts(含律師編輯版欄位)
        conn.execute("CREATE TABLE pleading_drafts (id INTEGER PRIMARY KEY, case_id VARCHAR NOT NULL, "
                     "draft_text TEXT NOT NULL, citation_verification_status VARCHAR NOT NULL, "
                     "generated_at VARCHAR NOT NULL, source VARCHAR, parent_id INTEGER, citation_check_json TEXT)")
        conn.execute("INSERT INTO pleading_drafts (case_id, draft_text, citation_verification_status, generated_at) "
                     "VALUES ('old', '民事起訴狀', 'published', '2026-08-09T00:00:00Z')")
        conn.commit()
        conn.close()
        s = get_session(f"sqlite:///{path}")
        row = s.query(PleadingDraft).one()
        assert row.side is None and pleading_side(row) == "plaintiff"
        assert row.draft_text == "民事起訴狀"  # 既有資料不動
        s.close()


class TestRecord:
    def test_default_side_is_plaintiff(self, db_url):
        s = get_session(db_url)
        row = record_pleading(s, case_id="c1", draft_text="民事起訴狀", citations_used=["民法第474條"])
        assert row.side == "plaintiff"

    def test_defendant_answer_goes_through_same_gate(self, db_url):
        s = get_session(db_url)
        row = record_pleading(s, case_id="c1", draft_text=ANSWER, citations_used=["民法第125條"], side="defendant")
        assert row.side == "defendant"
        with pytest.raises(ValueError, match="尚未查證為 published"):
            record_pleading(s, case_id="c1", draft_text=ANSWER, citations_used=["民法第144條"], side="defendant")
        with pytest.raises(ValueError, match="非法 side"):
            record_pleading(s, case_id="c1", draft_text=ANSWER, citations_used=[], side="judge")

    def test_lawyer_edit_keeps_parent_side(self, db_url):
        s = get_session(db_url)
        answer = record_pleading(s, case_id="c1", draft_text=ANSWER, citations_used=[], side="defendant")
        edit = record_pleading_edit(s, case_id="c1", parent_id=answer.id, draft_text=ANSWER + "\n補充",
                                    citation_check=[])
        assert edit.side == "defendant"
        old = PleadingDraft(case_id="c1", draft_text="民事起訴狀", citation_verification_status="published",
                            generated_at="2026-08-09T00:00:00Z")  # 舊紀錄 side=NULL
        s.add(old)
        s.commit()
        assert record_pleading_edit(s, case_id="c1", parent_id=old.id, draft_text="民事起訴狀\n改",
                                    citation_check=[]).side == "plaintiff"


class TestMaterials:
    def test_requires_own_stage3(self, db_url):
        land_stage3(db_url, defendant=False)
        s = get_session(db_url)
        with pytest.raises(ValueError, match="尚未完成 stage3"):
            pleading_materials(s, case_id="c1", side="defendant")
        with pytest.raises(ValueError, match="找不到案件"):
            pleading_materials(s, case_id="nope", side="defendant")

    def test_defendant_materials(self, db_url):
        land_stage3(db_url)
        s = get_session(db_url)
        m = pleading_materials(s, case_id="c1", side="defendant")
        assert m["own_stage3"]["argument"] == "被告論證" and m["own_stage3"]["position"] == "請求權已罹於時效"
        assert m["own_stage3"]["citations"] == [{"citation_text": "民法第125條", "status": "published"},
                                                {"citation_text": "民法第144條", "status": "no_record"}]
        # 對造只給結構化摘要，不給完整論證原文
        assert m["opponent_stage3_summary"] == {"side": "plaintiff", "position": "被告應返還借款",
                                                "citations": ["民法第474條"]}
        assert "原告論證" not in json.dumps(m, ensure_ascii=False)
        assert m["case"]["claims"] == "被告應給付原告50萬元" and m["existing_system_drafts"] == 0
        assert set(m["party_checks"]) == {"plaintiff", "defendant"} and "issues" in m["procedural_issues"]


class TestCli:
    def test_pleading_side_flag(self, db_url, tmp_path):
        draft = tmp_path / "answer.txt"
        draft.write_text(ANSWER, encoding="utf-8")
        ok = tmp_path / "ok.json"
        ok.write_text(json.dumps(["民法第125條"], ensure_ascii=False), encoding="utf-8")
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps(["民法第144條"], ensure_ascii=False), encoding="utf-8")
        r = run_main("pleading", "--case-id", "c1", "--draft-file", str(draft), "--citations", str(ok),
                     "--side", "defendant", db_url=db_url)
        assert r.returncode == 0 and "已落地答辯狀草稿" in r.stdout, r.stderr
        r = run_main("pleading", "--case-id", "c1", "--draft-file", str(draft), "--citations", str(bad),
                     "--side", "defendant", db_url=db_url)
        assert r.returncode == 1 and "拒絕落地" in r.stderr
        r = run_main("pleading", "--case-id", "c1", "--draft-file", str(draft), "--citations", str(ok), db_url=db_url)
        assert r.returncode == 0 and "已落地起訴狀草稿" in r.stdout  # 未指定 --side:向下相容，視為原告
        s = get_session(db_url)
        assert [x.side for x in s.query(PleadingDraft).order_by(PleadingDraft.id)] == ["defendant", "plaintiff"]
        s.close()

    def test_pleading_source(self, db_url):
        r = run_main("pleading-source", "--case-id", "c1", "--side", "defendant", db_url=db_url)
        assert r.returncode == 1 and "尚未完成 stage3" in r.stderr
        land_stage3(db_url)
        r = run_main("pleading-source", "--case-id", "c1", "--side", "defendant", db_url=db_url)
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        assert out["side"] == "defendant" and out["own_stage3"]["citations"][0]["status"] == "published"
        assert "reasoning" not in out["own_stage3"]  # 輸出欄位名避開 reasoning_extraction 分類器


class TestApi:
    @pytest.fixture
    def client(self, db_url, tmp_path):
        from fastapi.testclient import TestClient
        from server.app import create_app
        app = create_app(db_url=db_url, cases_dir=str(tmp_path / "none"), live_checks_path=str(tmp_path / "none.json"),
                         seed_on_empty=False, local_clients=("testclient",))
        return TestClient(app, base_url="http://127.0.0.1:8000")

    def test_missing_answer_is_reported_not_substituted(self, client, db_url):
        s = get_session(db_url)
        s.add(PleadingDraft(case_id="c1", draft_text="民事起訴狀\n依民法第474條", citation_verification_status="published",
                            generated_at="2026-08-09T00:00:00Z"))  # 舊紀錄 side=NULL
        s.commit()
        s.close()
        d = client.get("/api/cases/c1").json()
        assert d["pleadings"]["plaintiff"]["id"] == 1 and d["pleadings"]["defendant"] is None
        assert d["pleading"]["id"] == 1  # 舊欄位仍是原告起訴狀
        assert [v["side"] for v in d["pleading_versions"]] == ["plaintiff"]
        steps = {p["key"]: p for p in d["progress"]}
        assert steps["pleading"]["state"] == "done" and steps["answer"]["state"] == "pending"
        [item] = [c for c in client.get("/api/cases").json()["cases"] if c["case_id"] == "c1"]
        assert item["has_pleading"] is True and item["has_answer"] is False

    def test_answer_listed_exported_and_edited_separately(self, client, db_url, monkeypatch):
        s = get_session(db_url)
        record_pleading(s, case_id="c1", draft_text="民事起訴狀\n依民法第474條", citations_used=["民法第474條"])
        record_pleading(s, case_id="c1", draft_text=ANSWER, citations_used=["民法第125條"], side="defendant")
        s.close()
        d = client.get("/api/cases/c1").json()
        assert d["pleadings"]["defendant"]["id"] == 2 and d["pleadings"]["plaintiff"]["id"] == 1
        assert {p["key"]: p["state"] for p in d["progress"]}["answer"] == "done"
        r = client.get("/api/cases/c1/pleadings/2/export")
        assert r.status_code == 200 and "c1_answer_v2_system.txt" in r.headers["content-disposition"]
        assert "書狀:民事答辯狀(被告)" in r.content.decode("utf-8")
        assert "c1_complaint_v1_system.txt" in client.get("/api/cases/c1/pleadings/1/export").headers["content-disposition"]
        r = client.post("/api/cases/c1/pleadings", json={"parent_id": 2, "draft_text": ANSWER + "\n補充", "mode": "offline"})
        assert r.status_code == 201, r.text
        assert r.json()["side"] == "defendant" and r.json()["document"] == "民事答辯狀(被告)"
        d = client.get("/api/cases/c1").json()
        assert d["pleadings"]["defendant"]["id"] == 2  # 預設仍顯示系統產生版
        assert [v["side"] for v in d["pleading_versions"]] == ["plaintiff", "defendant", "defendant"]
