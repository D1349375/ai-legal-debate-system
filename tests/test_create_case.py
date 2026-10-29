"""UI 建立案件(POST /api/cases)與本機寫入保護的測試。"""
import pytest
from fastapi.testclient import TestClient

from database.db import get_session, record_case
from server.app import create_app

LOCAL = "http://127.0.0.1:8000"
CASE = {"case_type": "買賣價金", "facts_summary": "原告於115年1月出賣貨物予被告，被告迄未給付價金。",
        "claims": "被告應給付原告新臺幣50萬元。",
        "plaintiff": {"name": "甲公司", "ban": "22099131"}, "defendant": {"name": "乙"}}


@pytest.fixture
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path / 'create.db'}"
    s = get_session(url)
    record_case(s, case_id="rec1", case_type="錄製", facts_summary="錄製案件事實", claims="請求")
    s.close()
    return url


@pytest.fixture
def client(db_url, tmp_path):
    app = create_app(db_url=db_url, cases_dir=str(tmp_path / "none"), seed_on_empty=False, local_clients=("testclient",))
    return TestClient(app, base_url=LOCAL)


def create(client, **over):
    r = client.post("/api/cases", json={**CASE, **over})
    assert r.status_code == 201, r.text
    return r.json()["case_id"]


def test_creates_case_with_parties_and_safe_id(client):
    case_id = create(client)
    assert case_id.startswith("ui-") and case_id.endswith("-001")
    d = client.get(f"/api/cases/{case_id}").json()
    assert d["case"]["created_via"] == "ui"
    assert d["case"]["parties"] == {"plaintiff": {"name": "甲公司", "ban": "22099131"},
                                    "defendant": {"name": "乙", "ban": None}}
    assert d["provenance"]["kind"] == "case_only" and d["arguments"] == []
    assert create(client).endswith("-002")
    listed = {c["case_id"]: c for c in client.get("/api/cases").json()["cases"]}
    assert listed[case_id]["created_via"] == "ui" and listed["rec1"]["created_via"] is None


def test_rejects_bad_input(client):
    assert client.post("/api/cases", json={**CASE, "plaintiff": {"name": "甲", "ban": "123"}}).status_code == 422
    assert client.post("/api/cases", json={**CASE, "facts_summary": "太短"}).status_code == 422
    assert client.post("/api/cases", json={**CASE, "case_id": "../etc"}).status_code == 409
    assert client.post("/api/cases", json={**CASE, "case_id": "rec1"}).status_code == 409


def test_writes_only_from_local_browser(client, db_url):
    assert client.post("/api/cases", json=CASE, headers={"Host": "evil.example:8000"}).status_code == 403
    assert client.post("/api/cases", json=CASE, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/cases", json=CASE, headers={"Origin": LOCAL}).status_code == 201
    remote = TestClient(create_app(db_url=db_url, seed_on_empty=False), base_url=LOCAL)  # 預設只認 127.0.0.1/::1
    r = remote.post("/api/cases", json=CASE)
    assert r.status_code == 403 and "本機" in r.json()["detail"]
    assert remote.get("/api/cases").status_code == 200  # 讀取不受限
