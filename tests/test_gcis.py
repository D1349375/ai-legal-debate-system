"""商工當事人查核；CI 測試皆用官方回應欄位的本地樣本，不連網。"""
import json
import urllib.error
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from database.db import get_session, latest_party_checks
from database.schema import PartyCheck
from engine import court_map, gcis, party_rules
from engine.verify import STATUTE_PCODES, parse_citation
from server.app import create_app


def response(dataset, rows=None, ok=True):
    return {"dataset": dataset, "ok": ok, "rows": rows or [], "url": "https://data.gcis.nat.gov.tw/od/data/api/test",
            "fetched_at": "2026-10-03T00:00:00Z" if ok else None,
            "error": None if ok else "商工資料逾時：timed out"}


def company(status="核准設立", name="甲股份有限公司", rep="王小明", **extra):
    row = {"Company_Name": name, "Company_Status_Desc": status, "Responsible_Name": rep,
           "Company_Location": "新竹科學園區新竹市力行六路8號", "Company_Setup_Date": "0760221",
           "Change_Of_Approval_Data": "1150821", **extra}
    return {"entity_type": response("entity_type", [{"TYPE": "公司", "exist": "Y"}]),
            "company": response("company", [row]),
            "directors": response("directors", [{"Person_Position_Name": "董事長", "Person_Name": "王小明"}]),
            "branches": response("branches")}


def summary(status="核准設立", name="甲股份有限公司", rep="王小明", input_name=None, **extra):
    return party_rules.summarize("22099131", "company", company(status, name, rep, **extra), input_name=input_name)


def codes(result):
    return {warning["code"] for warning in result["warnings"]}


def warning(result, code):
    return next(item for item in result["warnings"] if item["code"] == code)


# 70801932：2026-10-03 從經濟部「公司登記基本資料-應用一」取得的回應。
FOREIGN_70801932_ROW = {
    "Business_Accounting_NO": "70801932",
    "Company_Status_Desc": "核准登記",
    "Company_Name": "新加坡商全球紀實有限公司",
    "Capital_Stock_Amount": 20000000,
    "Paid_In_Capital_Amount": 0,
    "Share_Val": 0,
    "Equity_Amt": 0,
    "Responsible_Name": "賈斯汀艾莫",
    "Company_Location": "臺北市中山區市民大道3段209號4樓",
    "Register_Organization_Desc": "經濟部商業司",
    "Company_Setup_Date": "0900216",
    "Change_Of_Approval_Data": "1110518",
    "Revoke_App_Date": "",
    "Case_Status": "",
    "Case_Status_Desc": "",
    "Sus_App_Date": "",
    "Sus_Beg_Date": "",
    "Sus_End_Date": "",
}


def foreign_company(row=None):
    return {
        "entity_type": response("entity_type", [{"TYPE": "公司", "exist": "Y"}]),
        "company": response("company", [row or FOREIGN_70801932_ROW]),
        "directors": response("directors"),
        "branches": response("branches"),
    }


def test_real_foreign_branch_row_is_normal_registration_with_lawyer_confirmation():
    result = party_rules.summarize("70801932", "company", foreign_company())
    assert result["company_form"] == "外國公司"
    assert result["status_text"] == "核准登記" and result["status_level"] == "warn"
    assert result["registered_responsible_name"] == "賈斯汀艾莫"
    assert result["legal_representative"] is None
    assert codes(result) == {"foreign_branch"}
    foreign = warning(result, "foreign_branch")
    assert "屬正常營業狀態" in foreign["message"] and "賈斯汀艾莫" in foreign["message"]
    assert foreign["legal_basis"] == ["公司法第4條", "公司法第372條", "民事訴訟法第2條"]


@pytest.mark.parametrize("status", ["解散", "撤銷", "廢止", "廢止登記"])
def test_foreign_abnormal_status_uses_foreign_liquidation_rule(status):
    row = {**FOREIGN_70801932_ROW, "Company_Status_Desc": status, "Responsible_Name": ""}
    result = party_rules.summarize("70801932", "company", foreign_company(row))
    assert result["company_form"] == "外國公司"
    assert result["status_level"] == "bad" and result["legal_representative"] is None
    assert codes(result) == {"foreign_dissolved"}
    foreign = warning(result, "foreign_dissolved")
    assert f"已{status}" in foreign["message"]
    assert "全體股東為清算人" not in foreign["message"]
    assert foreign["legal_basis"] == ["公司法第380條"]


def test_foreign_detection_uses_status_or_explicit_name_prefixes():
    by_status = summary("核准登記", name="未列前綴有限公司", rep="")
    assert by_status["company_form"] == "外國公司"
    assert codes(by_status) == {"foreign_branch"}
    for prefix in ("美商", "香港商", "英屬百慕達商", "挪威商"):
        result = summary("廢止", name=prefix + "某有限公司", rep="")
        assert result["company_form"] == "外國公司"
        assert codes(result) == {"foreign_dissolved"}
    domestic = summary(name="華南商業銀行股份有限公司")
    assert domestic["company_form"] == "股份有限公司"
    assert "foreign_branch" not in codes(domestic) and "foreign_dissolved" not in codes(domestic)


@pytest.mark.parametrize("value,expected", [("22099131", "22099131"), (" 2209 9131 ", "22099131"),
                                           ("2209913", None), ("2209A131", None)])
def test_validate_ban(value, expected):
    assert gcis.validate_ban(value) == expected


def test_roc_dates():
    assert gcis.roc_date("0760221") == "民國76年2月21日"
    assert gcis.roc_date_iso("0760221") == "1987-02-21"
    assert gcis.roc_date("") is None and gcis.roc_date("       ") is None


def test_empty_body_is_not_found_but_network_error_is_failure(monkeypatch):
    class Empty:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self): return b""
    monkeypatch.setattr(gcis.urllib.request, "urlopen", lambda *a, **k: Empty())
    r = gcis.company_basic("22099131")
    assert r["ok"] is True and r["rows"] == []
    assert "%20" in r["url"]
    def fail(*a, **k): raise urllib.error.URLError("timed out")
    monkeypatch.setattr(gcis.urllib.request, "urlopen", fail)
    r = gcis.company_basic("22099131")
    assert r["ok"] is False and r["rows"] == [] and "逾時" in r["error"]


def test_normal_company_and_limited_company():
    normal = summary()
    assert normal["legal_representative"] == {"name": "王小明", "title": "董事長", "basis": ["公司法第208條"]}
    assert normal["setup_date"] == "民國76年2月21日" and not normal["warnings"]
    limited = summary(name="甲有限公司")
    assert limited["legal_representative"]["title"] == "董事／董事長"
    assert limited["legal_representative"]["basis"] == ["公司法第108條"]


def test_rep_mismatch():
    data = company()
    data["directors"]["rows"][0]["Person_Name"] = "李小明"
    result = party_rules.summarize("22099131", "company", data)
    assert "rep_mismatch" in codes(result) and result["legal_representative"] is None


@pytest.mark.parametrize("status,expected", [
    ("解散", "dissolved"), ("廢止", "dissolved"), ("撤銷", "dissolved"),
    ("核准設立，但已命令解散", "ordered_dissolve"), ("合併解散", "merged"),
    ("破產", "bankrupt"), ("解散已清算完結", "liquidated"),
    ("撤回登記", "withdrawn"),
])
def test_abnormal_rules(status, expected):
    result = summary(status, rep="")
    assert expected in codes(result) and "no_rep" in codes(result)
    assert result["legal_representative"] is None
    assert result["status_level"] == ("warn" if expected in {"withdrawn", "liquidated"} else "bad")


def test_dissolved_liquidators_depend_on_company_form():
    stock = summary("解散", rep="")
    limited = summary("解散", name="甲有限公司", rep="")
    stock_warning = warning(stock, "dissolved")
    limited_warning = warning(limited, "dissolved")
    assert stock["legal_representative"] is None and limited["legal_representative"] is None
    assert "解散前全體董事" in stock_warning["message"]
    assert "股東會另選" in stock_warning["message"]
    assert "全體股東" in limited_warning["message"]
    assert "股東決議另選" in limited_warning["message"]
    assert "股東會" not in limited_warning["message"]
    for item in (stock_warning, limited_warning):
        assert "登記資料已不顯示董事與清算人" in item["message"]
        assert "清算人有數人而未推定代表者" in item["message"]
        assert "公司法第85條" in item["legal_basis"]
    # 公司與董事間訴訟由監察人代表(第213條)屬股份有限公司章；有限公司不設監察人，不得套用。
    assert "由監察人代表公司" in stock_warning["message"]
    assert "監察人" not in limited_warning["message"]
    assert stock_warning["legal_basis"] == ["公司法第24條", "公司法第25條", "公司法第8條", "公司法第322條", "公司法第85條", "公司法第213條"]
    assert limited_warning["legal_basis"] == ["公司法第24條", "公司法第25條", "公司法第8條", "公司法第113條", "公司法第79條", "公司法第85條"]
    assert "公司法第26條之1" not in limited_warning["legal_basis"]
    revoked = summary("撤銷", name="甲有限公司", rep="")
    assert "公司法第26條之1" in warning(revoked, "dissolved")["legal_basis"]
    unknown = summary("撤銷", name="甲企業", rep="")
    assert "依公司型態與章程而定" in warning(unknown, "dissolved")["message"]
    assert warning(unknown, "dissolved")["legal_basis"] == ["公司法第24條", "公司法第25條"]


def test_other_abnormal_rules_keep_required_procedure_details():
    merged = warning(summary("合併解散", rep=""), "merged")
    assert "存續或新設公司" in merged["message"] and "有訴訟代理人時不當然停止" in merged["message"]
    assert merged["legal_basis"] == ["公司法第75條", "公司法第319條", "民事訴訟法第169條", "民事訴訟法第173條"]
    bankrupt = warning(summary("破產", rep=""), "bankrupt")
    assert "破產管理人" in bankrupt["message"] and "有訴訟代理人亦同" in bankrupt["message"]
    assert "破產法第75條" in bankrupt["message"] and bankrupt["legal_basis"] == ["民事訴訟法第174條"]
    liquidated = warning(summary("解散已清算完結", rep=""), "liquidated")
    assert liquidated["level"] == "warn" and "聲報備查不等於法人格消滅" in liquidated["message"]
    assert "最高法院114年度台聲字第397號" in liquidated["message"]
    assert liquidated["legal_basis"] == ["公司法第25條", "民法第40條"]


def test_suspension_and_name_mismatch():
    r = summary(Sus_Beg_Date="1150101", Sus_End_Date="       ", input_name="乙股份有限公司")
    assert {"suspended", "name_mismatch"} <= codes(r)
    assert r["suspension"]["from"] == "民國115年1月1日"
    suspended = warning(r, "suspended")
    assert "停業不影響法人格與代表人" in suspended["message"]
    assert "須釋明請求及假扣押原因" in suspended["message"]
    assert suspended["legal_basis"] == ["民事訴訟法第522條", "民事訴訟法第523條", "民事訴訟法第526條"]
    assert "name_mismatch" not in codes(summary(name="台灣股份有限公司", input_name="臺灣股份有限公司"))


def test_branch_business_and_not_found():
    branch = party_rules.summarize("12345678", "branch", {"entity_type": response("entity_type")})
    assert "branch_entity" in codes(branch)
    branch_warning = warning(branch, "branch_entity")
    assert "業務範圍內事項涉訟有當事人能力" in branch_warning["message"]
    assert "最高法院40年台上字第39號判例" in branch_warning["message"]
    assert branch_warning["legal_basis"] == ["民事訴訟法第6條"]
    # 99053801：雲程小吃店；2026-10-03 官方 API 實測 TYPE=商業、exist=Y。
    business = party_rules.summarize("99053801", "business", {
        "entity_type": response("entity_type"), "business": response("business", [{
            "Business_Name": "雲程小吃店", "Business_Current_Status_Desc": "核准設立",
            "Business_Address": "高雄市鼓山區明誠里中華１路２９巷２２弄４５號",
            "Business_Setup_Approve_Date": "0921021"}])})
    assert "business_entity" in codes(business)
    business_warning = warning(business, "business_entity")
    assert "獨資商號無當事人能力" in business_warning["message"]
    assert "應以商號主人（負責人）為當事人" in business_warning["message"]
    assert "最高法院42年台抗字第12號、43年台上字第601號判例" in business_warning["message"]
    assert business_warning["legal_basis"] == ["民事訴訟法第40條"]
    assert business["name"] == "雲程小吃店" and business["status_text"] == "核准設立"
    assert business["setup_date"] == "民國92年10月21日"
    missing = party_rules.summarize("12345678", "not_found", {"entity_type": response("entity_type")})
    assert "not_found" in codes(missing)


def test_partial_api_failure_remains_visible():
    data = company()
    data["directors"] = response("directors", ok=False)
    result = party_rules.summarize("22099131", "company", data)
    assert result["name"] == "甲股份有限公司"
    assert result["sources"][2]["ok"] is False and "逾時" in result["sources"][2]["error"]


def test_failed_company_basic_does_not_invent_registry_warnings():
    data = company()
    data["company"] = response("company", ok=False)
    result = party_rules.summarize("22099131", "company", data)
    assert result["warnings"] == []
    assert result["legal_representative"] is None
    assert result["name"] is None and result["address"] is None
    assert result["basic_data_available"] is False
    assert result["status_level"] == "warn"


def test_all_rule_legal_bases_are_supported():
    for rule in party_rules.RULES:
        for text in rule["legal_basis"]:
            parsed = parse_citation(text)
            assert parsed["type"] == "statute", text
            assert parsed["law_name"] in STATUTE_PCODES, text


def test_court_map():
    assert court_map.resolve_address("新竹市東區某路1號")["primary"]["court"] == "臺灣新竹地方法院"
    assert court_map.resolve_address("新竹科學園區新竹市力行六路8號")["primary"]["court"] == "臺灣新竹地方法院"
    uncertain = court_map.resolve_address("新北市某路1號")
    assert uncertain["primary"] is None and len(uncertain["candidates"]) == 4
    assert "需依行政區確認" in uncertain["note"]
    assert court_map.resolve_address("新北市淡水區某路1號")["primary"]["court"] == "臺灣士林地方法院"
    assert court_map.resolve_address("地址不明")["primary"] is None


def test_api_party_check_search_and_persistence(monkeypatch, tmp_path):
    ban = "22099131"
    data = company()
    for key in data:
        if key == "entity_type":
            monkeypatch.setattr(gcis, "entity_type", lambda *a, **k: data["entity_type"])
        elif key == "company":
            monkeypatch.setattr(gcis, "company_basic", lambda *a, **k: data["company"])
        elif key == "directors":
            monkeypatch.setattr(gcis, "directors", lambda *a, **k: data["directors"])
        elif key == "branches":
            monkeypatch.setattr(gcis, "branches", lambda *a, **k: data["branches"])
    monkeypatch.setattr(gcis, "search_companies", lambda *a, **k: response("keyword", [{
        "Business_Accounting_NO": ban, "Company_Name": "甲股份有限公司", "Company_Location": "新竹市東區"}]))
    url = f"sqlite:///{tmp_path / 'party.db'}"
    client = TestClient(create_app(db_url=url, cases_dir=str(tmp_path), seed_on_empty=False))
    assert client.post("/api/party-check", json={"ban": "123"}).status_code == 422
    assert client.get("/api/party-search?q=a").status_code == 422
    found = client.get("/api/party-search?q=甲股").json()
    assert found["candidates"][0]["ban"] == ban
    checked = client.post("/api/party-check", json={"ban": ban, "case_id": "c1", "role": "defendant"}).json()
    assert checked["query_status"] == "ok" and checked["persisted"] is True
    with get_session(url) as session:
        assert session.query(PartyCheck).count() == 1
        assert latest_party_checks(session, "c1")["defendant"]["ban"] == ban
        assert json.loads(session.query(PartyCheck).one().raw_json)["company"]["rows"][0]["Company_Name"] == "甲股份有限公司"


def test_api_case_detail_contains_party_checks(monkeypatch, tmp_path):
    from database.db import record_case, record_party_check
    url = f"sqlite:///{tmp_path / 'case.db'}"
    with get_session(url) as session:
        record_case(session, case_id="c2", case_type="契約", facts_summary="甲乙爭議", claims="給付")
        record_party_check(session, case_id="c2", role="plaintiff", query_ban="22099131",
                           result={"ban": "22099131", "entity_type": "company", "status_text": "核准設立"},
                           raw={}, fetched_at="2026-10-03T00:00:00Z")
    client = TestClient(create_app(db_url=url, cases_dir=str(tmp_path), seed_on_empty=False))
    checks = client.get("/api/cases/c2").json()["party_checks"]
    assert checks["plaintiff"]["ban"] == "22099131" and checks["defendant"] is None


def test_api_type_failure_is_not_reported_as_not_found(monkeypatch, tmp_path):
    monkeypatch.setattr(gcis, "entity_type", lambda *a, **k: response("entity_type", ok=False))
    client = TestClient(create_app(db_url=f"sqlite:///{tmp_path / 'failed.db'}", cases_dir=str(tmp_path),
                                   party_checks_path=str(tmp_path / "no-recordings.json"), seed_on_empty=False))
    result = client.post("/api/party-check", json={"ban": "22099131", "persist": False}).json()
    assert result["query_status"] == "failed" and result["entity_type"] == "unresolved"
    assert result["live_attempt"]["outcome"] == "timeout"


def test_api_basic_failure_only_reports_query_error(monkeypatch, tmp_path):
    monkeypatch.setattr(gcis, "entity_type", lambda *a, **k: response("entity_type", [{"TYPE": "公司", "exist": "Y"}]))
    monkeypatch.setattr(gcis, "company_basic", lambda *a, **k: response("company", ok=False))
    monkeypatch.setattr(gcis, "directors", lambda *a, **k: response("directors", [{"Person_Position_Name": "董事長", "Person_Name": "王小明"}]))
    monkeypatch.setattr(gcis, "branches", lambda *a, **k: response("branches"))
    client = TestClient(create_app(db_url=f"sqlite:///{tmp_path / 'basic-failed.db'}", cases_dir=str(tmp_path),
                                   party_checks_path=str(tmp_path / "no-recordings.json"), seed_on_empty=False))
    result = client.post("/api/party-check", json={"ban": "22099131", "persist": False}).json()
    assert result["query_status"] == "failed"
    assert result["warnings"] == []
    assert result["basic_data_available"] is False
    assert result["errors"][0]["dataset"] == gcis.DATASETS["company"][1]
    assert result["name"] is None and result["address"] is None


def test_branch_type_does_not_claim_registration_details(monkeypatch, tmp_path):
    monkeypatch.setattr(gcis, "entity_type", lambda *a, **k: response("entity_type", [{"TYPE": "分公司", "exist": "Y"}]))
    client = TestClient(create_app(db_url=f"sqlite:///{tmp_path / 'branch.db'}", cases_dir=str(tmp_path), seed_on_empty=False))
    result = client.post("/api/party-check", json={"ban": "00005748", "persist": False}).json()
    assert result["query_status"] == "ok" and result["entity_type"] == "branch"
    assert result["name"] is None and result["address"] is None
    assert result["legal_representative"] is None
    assert "branch_entity" in codes(result)


def test_cli_labels_representative_branch_and_empty_basis(monkeypatch, capsys):
    import main
    from server import seed, services

    class Session:
        def close(self): pass

    monkeypatch.setattr(main, "get_session", lambda: Session())
    monkeypatch.setattr(seed, "load_recorded_party_checks", lambda: {})
    args = SimpleNamespace(ban="22099131", case_id=None, role=None, name=None, no_persist=True)
    normal = summary()
    normal.update(query_status="ok", via="gcis_live", errors=[], fetched_at="2026-10-03T00:00:00Z")
    monkeypatch.setattr(services, "party_check_one", lambda *a, **k: normal)
    assert main.cmd_party(args) == 0
    assert "法定代理人：董事長 王小明" in capsys.readouterr().out

    branch = party_rules.summarize("00005748", "branch", {"entity_type": response("entity_type")})
    branch.update(query_status="ok", via="gcis_live", errors=[], fetched_at="2026-10-03T00:00:00Z")
    monkeypatch.setattr(services, "party_check_one", lambda *a, **k: branch)
    args.ban = "00005748"
    assert main.cmd_party(args) == 0
    output = capsys.readouterr().out
    assert "本功能未查詢分公司登記資料" in output
    assert "法定代理人：" not in output and "官方未提供名稱" not in output

    missing = party_rules.summarize("12345678", "not_found", {"entity_type": response("entity_type")})
    missing.update(query_status="not_found", via="gcis_live", errors=[], fetched_at="2026-10-03T00:00:00Z")
    monkeypatch.setattr(services, "party_check_one", lambda *a, **k: missing)
    args.ban = "12345678"
    assert main.cmd_party(args) == 0
    output = capsys.readouterr().out
    assert "警示〔bad〕商工登記查無此統編\n" in output
    assert "（）" not in output


def test_cli_foreign_representative_is_only_a_confirmation_hint(monkeypatch, capsys):
    import main
    from server import seed, services

    class Session:
        def close(self): pass

    monkeypatch.setattr(main, "get_session", lambda: Session())
    monkeypatch.setattr(seed, "load_recorded_party_checks", lambda: {})
    args = SimpleNamespace(ban="70801932", case_id=None, role=None, name=None, no_persist=True)
    foreign = party_rules.summarize("70801932", "company", foreign_company())
    foreign.update(query_status="ok", via="gcis_live", errors=[], fetched_at="2026-10-03T00:00:00Z")
    monkeypatch.setattr(services, "party_check_one", lambda *a, **k: foreign)
    assert main.cmd_party(args) == 0
    output = capsys.readouterr().out
    assert "法定代理人：待確認(在臺負責人:賈斯汀艾莫)" in output
    assert "foreign_branch" not in output and "公司法第372條" in output

    revoked_row = {**FOREIGN_70801932_ROW, "Company_Status_Desc": "廢止"}
    revoked = party_rules.summarize("70801932", "company", foreign_company(revoked_row))
    revoked.update(query_status="ok", via="gcis_live", errors=[], fetched_at="2026-10-03T00:00:00Z")
    monkeypatch.setattr(services, "party_check_one", lambda *a, **k: revoked)
    assert main.cmd_party(args) == 0
    output = capsys.readouterr().out
    assert "法定代理人：待確認(清算人)" in output
    assert "全體股東為清算人" not in output


def test_export_demo_flag_keeps_existing_live_checks_behavior(monkeypatch):
    import main
    from server import seed

    calls = []
    monkeypatch.setattr(main, "get_session", lambda: object())
    monkeypatch.setattr(seed, "write_fixture", lambda session: calls.append("fixture") or {})
    monkeypatch.setattr(seed, "write_live_checks", lambda session: calls.append("live") or [])
    monkeypatch.setattr(seed, "write_party_checks", lambda session: calls.append("party") or [])
    assert main.cmd_export_demo(SimpleNamespace(live_checks=True, party_checks=False)) == 0
    assert calls == ["fixture", "live"]
    calls.clear()
    assert main.cmd_export_demo(SimpleNamespace(live_checks=False, party_checks=True)) == 0
    assert calls == ["party"]


def test_type_exists_but_basic_dataset_empty_is_partial(monkeypatch, tmp_path):
    monkeypatch.setattr(gcis, "entity_type", lambda *a, **k: response("entity_type", [{"TYPE": "公司", "exist": "Y"}]))
    monkeypatch.setattr(gcis, "company_basic", lambda *a, **k: response("company"))
    monkeypatch.setattr(gcis, "directors", lambda *a, **k: response("directors"))
    monkeypatch.setattr(gcis, "branches", lambda *a, **k: response("branches"))
    client = TestClient(create_app(db_url=f"sqlite:///{tmp_path / 'empty-basic.db'}", cases_dir=str(tmp_path), seed_on_empty=False))
    result = client.post("/api/party-check", json={"ban": "22099131", "persist": False}).json()
    assert result["query_status"] == "partial" and result["status_level"] == "warn"
    assert result["basic_data_available"] is False and result["warnings"] == []
    assert "基本資料集查無" in result["errors"][0]["error"]
    assert result["live_attempt"]["outcome"] == "ok"


def test_recorded_fallback_keeps_original_time_and_live_failure_separate(monkeypatch, tmp_path):
    from database.db import record_party_check
    from server import seed
    url = f"sqlite:///{tmp_path / 'replay.db'}"
    original = party_rules.summarize("22099131", "company", company())
    original.update(query_status="ok", via="gcis_live", fetched_at="2026-10-03T00:00:00Z")
    with get_session(url) as session:
        record_party_check(session, query_ban="22099131", result=original,
                           raw={key: {"rows": value["rows"], "url": value["url"], "ok": value["ok"],
                                      "error": value["error"]} for key, value in company().items()},
                           fetched_at=original["fetched_at"])
        path = tmp_path / "recorded.json"
        assert len(seed.write_party_checks(session, str(path))) == 1
    monkeypatch.setattr(gcis, "entity_type", lambda *a, **k: response("entity_type", ok=False))
    client = TestClient(create_app(db_url=url, cases_dir=str(tmp_path), party_checks_path=str(path), seed_on_empty=False))
    replay = client.post("/api/party-check", json={"ban": "22099131", "case_id": "c1", "role": "plaintiff"}).json()
    assert replay["via"] == "recorded" and replay["query_status"] == "recorded"
    assert replay["fetched_at"] == "2026-10-03T00:00:00Z"
    assert replay["live_attempt"]["outcome"] == "timeout" and replay["live_errors"]
    with get_session(url) as session:
        assert session.query(PartyCheck).count() == 2
        assert latest_party_checks(session, "c1")["plaintiff"]["via"] == "recorded"


@pytest.mark.network
def test_live_company_and_branches():
    result = gcis.company_basic("22099131")
    assert result["ok"] and "台灣積體電路製造" in result["rows"][0]["Company_Name"]
    assert result["rows"][0]["Company_Status_Desc"] == "核准設立"
    branches = gcis.branches("22555003")
    assert branches["ok"] and len(branches["rows"]) > 0


@pytest.mark.network
def test_live_keyword_needs_human_selection():
    result = gcis.search_companies("台積電")
    assert result["ok"] and any("台積電機" in row.get("Company_Name", "") or
                                "台積電梯" in row.get("Company_Name", "") for row in result["rows"])
