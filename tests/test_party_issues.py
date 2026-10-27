"""官方事實層 → 法官職權調查事項(engine/party_issues.py)與其在 finalize、案件 API 的串接。不連網。"""
import pytest
from fastapi.testclient import TestClient

from database.db import (
    finalize_case, get_session, record_argument, record_case, record_party_check, record_question,
    record_verdict,
)
from database.schema import PartyCheck
from engine import party_issues, party_rules
from engine.verify import STATUTE_PCODES, parse_citation
from server.app import create_app


def _resp(rows):
    return {"ok": True, "rows": rows, "url": "https://data.gcis.nat.gov.tw/od/data/api/test",
            "fetched_at": "2026-10-03T00:00:00Z", "error": None}


def check(status="核准設立", name="甲有限公司", rep="王小明", *, kind="company", via="gcis_live",
          query_status="ok", ban="12345678", **extra):
    data = {"company": _resp([{"Company_Name": name, "Company_Status_Desc": status, "Responsible_Name": rep,
                               "Company_Location": "新竹市東區某路1號", **extra}]),
            "directors": _resp([{"Person_Position_Name": "董事長", "Person_Name": rep}]), "branches": _resp([])}
    result = party_rules.summarize(ban, kind, data if kind == "company" else {})
    result.update(query_status=query_status, via=via, fetched_at="2026-10-03T00:00:00Z", errors=[])
    return result


def ids(view):
    return [i["id"] for i in view["issues"]]


def test_dissolved_defendant_becomes_one_ex_officio_question_to_plaintiff():
    view = party_issues.procedural_issues({"plaintiff": check(), "defendant": check("解散", rep="")})
    # 解散已說明法定代理人應列清算人，同一當事人的「未提供負責人」不再重複成另一則訊問
    assert ids(view) == ["defendant:dissolved"]
    issue = view["issues"][0]
    assert issue["level"] == "bad" and issue["kind"] == "法定代理" and issue["ex_officio"] is True
    assert issue["target_side"] == "plaintiff"
    assert "被告「甲有限公司」（統編 12345678）商工登記狀態為「解散」" in issue["question_text"]
    assert "清算人" in issue["question_text"] and "命其補正" in issue["procedure"]
    assert {"民事訴訟法第244條", "民事訴訟法第49條", "民事訴訟法第52條", "民事訴訟法第249條"} <= set(issue["legal_basis"])
    assert "公司法第113條" in issue["legal_basis"]  # 保留原警示的依據
    assert view["notes"] == []


def test_normal_parties_have_no_issues_but_are_reported_as_checked():
    view = party_issues.procedural_issues({"plaintiff": check(), "defendant": check()})
    assert view["issues"] == [] and view["notes"] == []
    assert view["parties"]["defendant"]["status_text"] == "核准設立"


def test_unchecked_or_failed_party_is_a_note_never_a_clean_bill():
    failed = {"ban": "12345678", "entity_type": "unresolved", "query_status": "failed", "warnings": [],
              "errors": [{"dataset": "公司登記基本資料", "error": "timed out"}]}
    view = party_issues.procedural_issues({"plaintiff": None, "defendant": failed})
    assert view["issues"] == []
    assert any("原告尚未查核" in n and "不得據此推定" in n for n in view["notes"])
    assert any("被告商工查核未完成" in n and "公司登記基本資料" in n for n in view["notes"])
    assert party_issues.procedural_issues(None)["parties"] == {"plaintiff": None, "defendant": None}


def test_recorded_lookup_is_labelled_in_the_question():
    view = party_issues.procedural_issues({"defendant": check("解散", rep="", via="recorded")})
    assert "錄製的查詢結果，查詢時間 2026-10-03T00:00:00Z" in view["issues"][0]["question_text"]


def test_suspension_is_strategy_not_ex_officio():
    view = party_issues.procedural_issues({"defendant": check(Sus_Beg_Date="1150101", Sus_End_Date="")})
    issue = view["issues"][0]
    assert issue["id"] == "defendant:suspended" and issue["ex_officio"] is False and issue["procedure"] is None


@pytest.mark.parametrize("status,code,kind", [
    ("合併解散", "merged", "當事人能力"), ("破產", "bankrupt", "當事人適格"),
    ("解散已清算完結", "liquidated", "法定代理"), ("重整", "reorganization", "法定代理"),
])
def test_status_rules_map_to_procedural_kind(status, code, kind):
    view = party_issues.procedural_issues({"defendant": check(status, rep="")})
    assert ids(view) == [f"defendant:{code}"] and view["issues"][0]["kind"] == kind


def test_bad_issues_sort_first_and_plaintiff_wording_names_plaintiff():
    view = party_issues.procedural_issues({
        "plaintiff": check("解散", rep=""), "defendant": check(Sus_Beg_Date="1150101", Sus_End_Date="")})
    assert ids(view) == ["plaintiff:dissolved", "defendant:suspended"]
    assert view["issues"][0]["question_text"].startswith("原告「甲有限公司」")
    assert "原告列載自身之法定代理人" in view["issues"][0]["question_text"]
    assert view["issues"][0]["warning"].startswith("此公司已解散")


def test_every_rule_with_a_level_is_mapped_and_all_bases_are_verifiable():
    leveled = {rule["code"] for rule in party_rules.RULES if rule["level"]}
    assert leveled <= set(party_issues.ASKS)
    for _, _, basis in [*party_issues.KINDS.values(), (None, None, party_issues.DEFENDANT_SPECIAL_AGENT[1])]:
        for text in basis:
            parsed = parse_citation(text)
            assert parsed["type"] in ("statute", "judgment"), text
            if parsed["type"] == "statute":
                assert parsed["law_name"] in STATUTE_PCODES, text


def test_representation_procedure_cites_the_supreme_court_ruling_on_registration():
    view = party_issues.procedural_issues({"defendant": check("解散", rep="")})
    issue = view["issues"][0]
    assert "最高法院115年度台抗字第105號" in issue["legal_basis"] and "公司法第12條" in issue["legal_basis"]
    assert "對抗第三人" in issue["procedure"] and "逾期未補正" in issue["procedure"]
    assert view["stage"].startswith("起訴審查")


def test_special_agent_route_only_for_defendant_representation():
    defendant = party_issues.procedural_issues({"defendant": check("解散", rep="")})["issues"][0]
    assert "選任特別代理人" in defendant["procedure"] and "不得為捨棄、認諾、撤回或和解" in defendant["procedure"]
    assert {"民事訴訟法第51條", "民事訴訟法第52條"} <= set(defendant["legal_basis"])
    # 原告自身欠缺代表權時是原告應補正，不是原告聲請特別代理人
    plaintiff = party_issues.procedural_issues({"plaintiff": check("解散", rep="")})["issues"][0]
    assert "特別代理人" not in plaintiff["procedure"] and "民事訴訟法第51條" not in plaintiff["legal_basis"]
    merged = party_issues.procedural_issues({"defendant": check("合併解散", rep="")})["issues"][0]
    assert "特別代理人" not in merged["procedure"]


def test_cure_marker_accepts_full_and_half_width_brackets_only_for_the_same_id():
    assert party_issues.cured_in("…程序補正（defendant:dissolved）：暫列清算人(待查明)", "defendant:dissolved")
    assert party_issues.cured_in("程序補正(defendant:dissolved):…", "defendant:dissolved")
    assert not party_issues.cured_in("程序補正(plaintiff:dissolved):…", "defendant:dissolved")
    assert not party_issues.cured_in("被告已解散，應列清算人", "defendant:dissolved")


# ───────── 串接：finalize 錨點與案件 API ─────────

def _case(url, *, check_before_debate, cured, follow_up=False):
    s = get_session(url)
    record_case(s, case_id="c1", case_type="買賣價金", facts_summary="事實", claims="請求")
    dissolved = {**check("解散", rep=""), "ban": "00000001"}

    def party():
        record_party_check(s, case_id="c1", role="defendant", query_ban="00000001", result=dissolved, raw={},
                           fetched_at="2026-10-03T00:00:00Z")
    if check_before_debate:
        party()
    for stage in (1, 2, 3):
        for side in ("plaintiff", "defendant"):
            reasoning = "r"
            if cured and side == "plaintiff" and stage == 1:
                reasoning = "實體分析…\n程序補正（defendant:dissolved）：法定代理人暫列清算人(待查明)，將調閱變更登記表。"
            record_argument(s, case_id="c1", side=side, stage=stage, position="p", reasoning=reasoning,
                            falsifier=None if stage == 1 else "f")
        if stage == 1:
            record_question(s, case_id="c1", question_text="補正僅列待查明，應提出何資料？", target_side="plaintiff",
                            based_on="官方事實層(defendant:dissolved)：原告補正不足" if follow_up else "原告Stage1主張")
    if not check_before_debate:
        party()
        # 落地時間只到秒，測試內同一秒完成；明確把查核時間放到攻防之後
        s.query(PartyCheck).update({PartyCheck.created_at: "2099-01-01T00:00:00Z"})
        s.commit()
    return s


def test_finalize_anchor_carries_procedural_issues(tmp_path):
    s = _case(f"sqlite:///{tmp_path / 'a.db'}", check_before_debate=True, cured=True)
    anchor = finalize_case(s, case_id="c1")
    assert [i["id"] for i in anchor["procedural_issues"]["issues"]] == ["defendant:dissolved"]
    assert {"weak_points", "position_drift"} <= set(anchor)


@pytest.mark.parametrize("before,cured,follow_up,expected", [
    (True, True, True, "answered"), (True, True, False, "answered"),
    (True, False, False, "not_answered"), (False, False, False, "predates_check"),
])
def test_case_detail_reports_stage1_cure_and_judge_follow_up(tmp_path, before, cured, follow_up, expected):
    url = f"sqlite:///{tmp_path / 'b.db'}"
    s = _case(url, check_before_debate=before, cured=cured, follow_up=follow_up)
    anchor = finalize_case(s, case_id="c1")
    if not before:  # 錄製於串接之前的評估：錨點沒有程序事項
        anchor.pop("procedural_issues")
    record_verdict(s, case_id="c1", verdict_main_text="m", verdict_reasoning="r",
                   risk_map={"對原告不利之處": [], "對被告不利之處": [], "建議補強證據": []},
                   mechanical_anchor_json=anchor, protocol_version="v1", citations_used=[])
    s.close()
    client = TestClient(create_app(db_url=url, cases_dir=str(tmp_path), seed_on_empty=False))
    pi = client.get("/api/cases/c1").json()["procedural_issues"]
    assert pi["coverage"]["debate"] == expected
    assert pi["issues"][0]["cured_in_stage1"] is cured
    assert pi["issues"][0]["followed_up_in"] == ([1] if follow_up else [])
    assert pi["coverage"]["verdict"] == ("included" if before else "not_included")


def test_cli_issues_prints_json(monkeypatch, capsys, tmp_path):
    import json

    import main
    url = f"sqlite:///{tmp_path / 'c.db'}"
    _case(url, check_before_debate=True, cured=False).close()
    monkeypatch.setattr(main, "get_session", lambda: get_session(url))
    assert main.cmd_issues(type("A", (), {"case_id": "c1"})()) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["case_id"] == "c1" and out["issues"][0]["id"] == "defendant:dissolved"
