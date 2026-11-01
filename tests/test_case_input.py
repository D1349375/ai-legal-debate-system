"""案件輸入 v2:新欄位的檢查、CLI、API、匯出匯入與角色檔。"""
import json
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from database.db import DB_URL_ENV, case_payload, get_session, record_case
from database.schema import Case
from engine.case_input import clean_claim_amount, clean_evidence, clean_known_gaps, clean_opponent_responses
from server import seed
from server.app import create_app

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL = "http://127.0.0.1:8000"
EVIDENCE = [{"id": "甲證1", "type": "bank_record", "date": "2023-03-01", "description": "匯款單", "proves": "金錢交付"}]
RESPONSES = [{"source": "存證信函回函", "date": "2024-05-10", "text": "該款項為投資款"}]
CASE = {"case_type": "返還借款", "facts_summary": "原告於112年3月1日匯款100萬元予被告，約定三個月內返還。",
        "claims": "被告應給付原告新臺幣100萬元。", "plaintiff": {"name": "甲公司"}, "defendant": {"name": "乙"}}


def run_main(*args, db_url):
    env = {**os.environ, DB_URL_ENV: db_url, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, "main.py", *args], cwd=ROOT, env=env, capture_output=True,
                          text=True, encoding="utf-8")


@pytest.fixture
def db_url(tmp_path):
    return f"sqlite:///{tmp_path / 'input.db'}"


@pytest.fixture
def client(db_url, tmp_path):
    app = create_app(db_url=db_url, cases_dir=str(tmp_path / "none"), seed_on_empty=False, local_clients=("testclient",))
    return TestClient(app, base_url=LOCAL)


class TestCleaning:
    def test_evidence_keeps_known_fields(self):
        assert clean_evidence(EVIDENCE) == EVIDENCE
        assert clean_evidence(None) == []

    @pytest.mark.parametrize("bad", [
        [{"id": "原證1", "description": "匯款單"}],
        [{"id": "甲證1", "description": "  "}],
        [{"id": "甲證1", "description": "甲"}, {"id": "甲證1", "description": "乙"}],
        [{"id": "甲證1", "description": "匯款單", "date": "去年"}],
        "不是清單",
    ])
    def test_bad_evidence_is_refused(self, bad):
        with pytest.raises(ValueError):
            clean_evidence(bad)

    def test_sub_numbered_evidence_is_accepted(self):
        assert clean_evidence([{"id": "甲證3-1", "description": "收據"}])[0]["id"] == "甲證3-1"

    def test_amount(self):
        assert clean_claim_amount(None) is None and clean_claim_amount(100) == 100
        for bad in (-1, 1.5, "100", True):
            with pytest.raises(ValueError):
                clean_claim_amount(bad)

    def test_responses_and_gaps(self):
        assert clean_opponent_responses(RESPONSES) == RESPONSES
        with pytest.raises(ValueError):
            clean_opponent_responses([{"source": "回函", "text": " "}])
        assert clean_known_gaps([" 無書面借據 ", ""]) == ["無書面借據"]


class TestRecordCase:
    def test_old_case_stays_v1(self, db_url):
        s = get_session(db_url)
        row = record_case(s, case_id="old", case_type="錄製", facts_summary="事實", claims="請求")
        assert row.protocol is None
        payload = case_payload(row)
        assert payload["protocol"] is None and payload["evidence"] == [] and payload["claim_amount"] is None
        s.close()

    def test_bad_input_writes_nothing(self, db_url):
        s = get_session(db_url)
        with pytest.raises(ValueError):
            record_case(s, case_id="bad", case_type="借款", facts_summary="事實", claims="請求", protocol="v2",
                        represented_side="plaintiff", evidence=[{"id": "原證1", "description": "匯款單"}])
        assert s.query(Case).count() == 0
        s.close()

    def test_defendant_mode_is_not_available_yet(self, db_url):
        s = get_session(db_url)
        with pytest.raises(ValueError, match="原告"):
            record_case(s, case_id="d", case_type="借款", facts_summary="事實", claims="請求", protocol="v2",
                        represented_side="defendant")
        s.close()


class TestCli:
    def test_old_json_lands_as_v1(self, tmp_path, db_url):
        path = tmp_path / "old.json"
        path.write_text(json.dumps({"case_id": "old1", "case_type": "借款", "facts_summary": "事實", "claims": "請求"},
                                   ensure_ascii=False), encoding="utf-8")
        assert run_main("case", "--json", str(path), db_url=db_url).returncode == 0
        s = get_session(db_url)
        assert s.query(Case).filter_by(case_id="old1").one().protocol is None
        s.close()

    def _land_v2(self, tmp_path, db_url):
        path = tmp_path / "new.json"
        path.write_text(json.dumps({
            "protocol": "v2", "case_id": "new1", "case_type": "返還借款", "represented_side": "plaintiff",
            "facts_summary": CASE["facts_summary"], "claims": CASE["claims"], "claim_amount": 1000000,
            "parties": {"plaintiff": {"name": "甲"}, "defendant": {"name": "乙"}},
            "evidence": EVIDENCE, "opponent_known_responses": RESPONSES, "known_gaps": ["無書面借據"],
        }, ensure_ascii=False), encoding="utf-8")
        assert run_main("case", "--json", str(path), db_url=db_url).returncode == 0

    def test_v2_json_and_precheck_and_role_view(self, tmp_path, db_url):
        self._land_v2(tmp_path, db_url)
        r = run_main("precheck", "--case-id", "new1", db_url=db_url)
        assert r.returncode == 0
        assert json.loads(r.stdout)["procedure"]["type"] == "依金額屬通常程序範圍"
        r = run_main("role-view", "--case-id", "new1", "--role", "plaintiff", db_url=db_url)
        assert r.returncode == 0
        view = json.loads(r.stdout)
        assert view["role"] == "plaintiff" and view["case"]["evidence"] == EVIDENCE
        assert view["case"]["opponent_known_responses"] == RESPONSES and view["case"]["known_gaps"] == ["無書面借據"]
        assert "precheck" in view and "procedural_issues" in view

    def test_bad_v2_json_is_refused_without_traceback(self, tmp_path, db_url):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"protocol": "v2", "case_id": "b", "case_type": "借款", "facts_summary": "事實",
                                    "claims": "請求", "evidence": [{"id": "原證1", "description": "單"}]},
                                   ensure_ascii=False), encoding="utf-8")
        r = run_main("case", "--json", str(path), db_url=db_url)
        assert r.returncode == 1 and "拒絕" in r.stderr and "Traceback" not in r.stderr

    def test_missing_case_reports_cleanly(self, db_url):
        for args in (("precheck", "--case-id", "none"), ("role-view", "--case-id", "none", "--role", "plaintiff")):
            r = run_main(*args, db_url=db_url)
            assert r.returncode == 1 and "找不到案件" in r.stderr and "Traceback" not in r.stderr


class TestApi:
    def test_round_trip(self, client):
        r = client.post("/api/cases", json={**CASE, "claim_amount": 1000000, "evidence": EVIDENCE,
                                            "opponent_known_responses": RESPONSES, "known_gaps": ["無書面借據"]})
        assert r.status_code == 201, r.text
        d = client.get(f"/api/cases/{r.json()['case_id']}").json()
        assert d["case"]["protocol"] == "v2" and d["case"]["represented_side"] == "plaintiff"
        assert d["case"]["claim_amount"] == 1000000 and d["case"]["evidence"] == EVIDENCE
        assert d["case"]["opponent_known_responses"] == RESPONSES and d["case"]["known_gaps"] == ["無書面借據"]
        assert d["precheck"]["procedure"]["type"] == "依金額屬通常程序範圍"

    def test_amount_is_optional_and_warned(self, client):
        case_id = client.post("/api/cases", json=CASE).json()["case_id"]
        d = client.get(f"/api/cases/{case_id}").json()
        assert d["case"]["claim_amount"] is None and d["precheck"]["procedure"]["type"] == "待確認"

    @pytest.mark.parametrize("over", [
        {"claim_amount": -1}, {"claim_amount": "很多"},
        {"evidence": [{"id": "原證1", "description": "匯款單"}]},
        {"evidence": [{"id": "甲證1", "description": "甲"}, {"id": "甲證1", "description": "乙"}]},
        {"represented_side": "defendant"},
    ])
    def test_bad_input_is_422(self, client, over):
        assert client.post("/api/cases", json={**CASE, **over}).status_code == 422

    def test_old_case_has_no_precheck(self, client, db_url):
        s = get_session(db_url)
        record_case(s, case_id="rec", case_type="錄製", facts_summary="錄製案件事實", claims="請求")
        s.close()
        d = client.get("/api/cases/rec").json()
        assert d["case"]["protocol"] is None and d["precheck"] is None


def test_new_fields_survive_export_and_import(tmp_path, db_url):
    s = get_session(db_url)
    record_case(s, case_id="v2", case_type="借款", facts_summary="事實", claims="請求", protocol="v2",
                represented_side="plaintiff", claim_amount=5, evidence=EVIDENCE,
                opponent_responses=RESPONSES, known_gaps=["缺口"])
    path = tmp_path / "fixture.json"
    seed.write_fixture(s, str(path))
    s.close()
    other = get_session(f"sqlite:///{tmp_path / 'other.db'}")
    seed.seed_if_empty(other, str(path))
    payload = case_payload(other.query(Case).filter_by(case_id="v2").one())
    other.close()
    assert payload["protocol"] == "v2" and payload["claim_amount"] == 5 and payload["evidence"] == EVIDENCE
    assert payload["opponent_known_responses"] == RESPONSES and payload["known_gaps"] == ["缺口"]
