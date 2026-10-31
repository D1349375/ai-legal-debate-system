"""新版建案與使用者回報的 HTTP 契約。"""
import pytest
from fastapi.testclient import TestClient

from server.app import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(db_url=f"sqlite:///{tmp_path / 'role-ui.db'}", cases_dir=str(tmp_path / 'cases'),
                     seed_on_empty=False, local_clients=("testclient",))
    return TestClient(app, base_url="http://127.0.0.1:8000")


def payload(**updates):
    return {"case_type": "買賣價金", "represented_side": "plaintiff",
            "uncontested_facts": "〔書證：買賣契約〕雙方於今年訂立買賣契約。",
            "plaintiff_facts": "原告表示已將約定貨物交付被告。", "defendant_facts": "被告來信表示數量待清點。",
            "claims": "被告應給付價金。", "plaintiff": {"name": "甲"}, "defendant": {"name": "乙"}, **updates}


def test_new_case_requires_represented_side(client):
    data = payload()
    del data["represented_side"]
    assert client.post("/api/cases", json=data).status_code == 422


@pytest.mark.parametrize("side", ["plaintiff", "defendant"])
def test_new_fields_and_deterministic_overview(client, side):
    response = client.post("/api/cases", json=payload(represented_side=side, claim_amount=100000))
    assert response.status_code == 201, response.text
    body = response.json()
    detail = client.get(f"/api/cases/{body['case_id']}").json()
    assert detail["case"]["represented_side"] == side
    assert detail["case"]["claim_amount"] == 100000
    assert "買賣契約" in detail["case"]["uncontested_facts"]
    report = client.get(f"/api/cases/{body['case_id']}/report")
    assert report.status_code == 200, report.text
    assert detail["report"] == report.json()
    assert set(detail["report"]["pending"]) == {"own_client", "opponent", "third_party"}


@pytest.mark.parametrize("amount,expected", [(None, "待確認"), (100000, "小額"), (100001, "簡易"),
                                          (500000, "簡易"), (500001, "通常")])
def test_procedure_preview_is_non_blocking(client, amount, expected):
    r = client.post("/api/cases/procedure-preview", json={"claim_amount": amount, "claims": "原起訴聲明"})
    assert r.status_code == 200, r.text
    text = str(r.json())
    assert expected in text
    assert "起訴前" in text
    created = client.post("/api/cases", json=payload(claim_amount=amount))
    assert created.status_code == 201, created.text


def test_unknown_case_report_is_404(client):
    assert client.get("/api/cases/missing/report").status_code == 404


def test_ui_verifier_never_uses_current_law_for_historical_205(monkeypatch):
    from database.db import get_session
    from server.services import verify_one
    monkeypatch.setattr("server.services.engine_verify.verify_statute_citation",
                        lambda *a, **k: pytest.fail("歷史版本不應查現行條文"))
    with get_session("sqlite:///:memory:") as session:
        result = verify_one(session, "108年民法第205條")
    assert result["status"] == "version_unverified"
    assert result["gate"] == "blocked" and not result["persisted"]


def test_ui_verifier_refuses_ambiguous_document_without_network():
    from database.db import get_session
    from server.services import verify_one
    with get_session("sqlite:///:memory:") as session:
        result = verify_one(session, "最高法院114年度台上字第1945號", mode="offline")
    assert result["status"] == "ambiguous"
    assert result["gate"] == "blocked" and len(result["candidates"]) > 1
