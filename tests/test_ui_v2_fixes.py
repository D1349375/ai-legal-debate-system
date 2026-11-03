"""第 4 批:main.py 檢查與畫面資料(審查 W7-4、W5-5、W6 列、W7-3、W5-6、W4-4、舊設計殘留第 2 項 B、T9)。"""
import json
import os
import shutil
import subprocess

import pytest

from database.db import finalize_case, get_session, record_argument, record_case
from server import services
from tests.test_gate import client, create_v2, db_url, run  # noqa: F401
from tests.test_revision import ANSWER, build_case, land_verdict, risk_map, run_main, verdict, write  # noqa: F401

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def v2_url(tmp_path):
    url = f"sqlite:///{tmp_path / 'v2.db'}"
    build_case(url, verdict_landed=False)
    return url


class TestCheckJudge:
    def test_v2_verdict_gate_runs_before_landing(self, v2_url, tmp_path):  # W7-4
        bad = risk_map()
        del bad["issue_assessment"]
        r = run_main("check-judge", "--case-id", "v2", "--json", write(tmp_path, verdict(bad), "v.json"), db_url=v2_url)
        assert r.returncode == 1 and "issue_assessment" in r.stderr
        r = run_main("check-judge", "--case-id", "v2", "--json", write(tmp_path, verdict(), "v.json"), db_url=v2_url)
        assert r.returncode == 0, r.stderr

    def test_win_probability_warns_in_check_judge(self, v2_url, tmp_path):
        value = verdict(verdict_main_text="原告勝訴機率約七成。")
        r = run_main("check-judge", "--case-id", "v2", "--json", write(tmp_path, value, "v.json"), db_url=v2_url)
        assert r.returncode == 0 and "勝訴機率" in r.stderr

    def test_issue_sheet_without_questions_is_not_a_crash(self, v2_url, tmp_path):  # W5-5
        sheet = {"undisputed": [], "issues": [], "clarifications": []}
        r = run_main("check-judge", "--case-id", "v2", "--json", write(tmp_path, sheet, "s.json"), db_url=v2_url)
        assert r.returncode == 2 and "issue-sheet" in r.stderr and "Traceback" not in r.stderr

    def test_unknown_payload_is_reported(self, v2_url, tmp_path):
        r = run_main("check-judge", "--case-id", "v2", "--json", write(tmp_path, {"x": 1}, "s.json"), db_url=v2_url)
        assert r.returncode == 2 and "Traceback" not in r.stderr


class TestRoundsNeedTheSheet:  # 審查第 4 節 W6 列
    def payload(self, stage, side="plaintiff"):
        return {"case_id": "v2", "side": side, "stage": stage, "position": "p", "argument": "【爭點 I1】r",
                "cited_statutes": [], "cited_precedents": [], "falsifier": "x", "basis": []}

    def test_v2_round_without_issue_sheet_is_refused(self, tmp_path):
        url = f"sqlite:///{tmp_path / 'nosheet.db'}"
        build_case(url, sheet=False, verdict_landed=False)
        for stage in (2, 3):
            r = run_main("record", "--json", write(tmp_path, self.payload(stage), "a.json"), db_url=url)
            assert r.returncode == 1 and "爭點整理表" in r.stderr, r.stderr

    def test_legacy_round_without_sheet_still_lands(self, tmp_path):
        url = f"sqlite:///{tmp_path / 'old.db'}"
        with get_session(url) as s:
            record_case(s, case_id="v2", case_type="t", facts_summary="f", claims="c")
        r = run_main("record", "--json", write(tmp_path, self.payload(2), "a.json"), db_url=url)
        assert r.returncode == 0, r.stderr


class TestStrongestPointAlias:  # T9
    def summary(self, **over):
        value = {"side": "plaintiff", "stage": 1, "position": "返還借款", "cited_statutes": [], "cited_precedents": []}
        value.update(over)
        return value

    def test_verbatim_field_is_accepted(self, v2_url, tmp_path):
        value = self.summary(strongest_point_verbatim="依民法第478條請求。")
        r = run_main("check-summary", "--case-id", "v2", "--json", write(tmp_path, value, "s.json"), db_url=v2_url)
        assert r.returncode == 0, r.stderr

    def test_both_fields_must_agree(self, v2_url, tmp_path):
        value = self.summary(strongest_point="依民法第478條請求。", strongest_point_verbatim="另一句。")
        r = run_main("check-summary", "--case-id", "v2", "--json", write(tmp_path, value, "s.json"), db_url=v2_url)
        assert r.returncode == 2 and "strongest_point" in r.stderr


class TestDriftNotApplicable:  # 舊設計殘留第 2 項,組長選 B
    def rounds(self, s, case_id):
        for stage in (1, 2, 3):
            for side in ("plaintiff", "defendant"):
                if stage == 1 and side == "plaintiff" and case_id == "v2":
                    continue
                if stage == 1 and side == "defendant" and case_id == "v2":
                    continue
                record_argument(s, case_id=case_id, side=side, stage=stage, position="p", reasoning="r",
                                cited_statutes=["民法第478條"] if stage == 3 else [], cited_precedents=[],
                                falsifier="x" if stage > 1 else None)

    def test_finalize_marks_drift_not_applicable_for_v2(self, v2_url):
        with get_session(v2_url) as s:
            self.rounds(s, "v2")
            anchor = finalize_case(s, case_id="v2")
        assert anchor["position_drift"] == {"plaintiff": None, "defendant": None}
        assert "不適用" in anchor["position_drift_note"]

    def test_legacy_drift_is_unchanged(self, tmp_path):
        with get_session(f"sqlite:///{tmp_path / 'old.db'}") as s:
            record_case(s, case_id="old", case_type="t", facts_summary="f", claims="c")
            self.rounds(s, "old")
            anchor = finalize_case(s, case_id="old")
        assert anchor["position_drift"] == {"plaintiff": 1.0, "defendant": 1.0} and "position_drift_note" not in anchor


class TestCaseDetailV2:  # 用假 Claude 跑完全程的案件看畫面資料
    @pytest.fixture
    def detail(self, client, db_url):  # noqa: F811
        case_id = create_v2(client)
        done = run(client, case_id)
        assert done["run"]["status"] == "succeeded", done["run"]["error"]
        return case_id, client.get(f"/api/cases/{case_id}").json()

    def test_issue_sheet_is_returned(self, detail):  # W5-6
        _, d = detail
        assert d["issue_sheet"]["sheet"]["issues"][0]["id"] == "I1"
        assert "爭點" in d["issue_sheet"]["text"] and d["issue_sheet"]["created_at"]

    def test_progress_follows_the_new_steps(self, detail):  # W5-6
        _, d = detail
        keys = [p["key"] for p in d["progress"]]
        assert keys[:3] == ["case", "analysis", "complaint"] and "issue_sheet" in keys and "questions" not in keys
        assert all(p["state"] == "done" for p in d["progress"] if p["key"] not in ("case", "gate1", "finalize", "verify"))
        assert next(p for p in d["progress"] if p["key"] == "gate1")["detail"].startswith("自動通過")

    def test_revision_is_its_own_source(self, client, detail):  # noqa: F811  W7-3
        case_id, d = detail
        rev = [v for v in d["pleading_versions"] if v.get("pleading_type") == "complaint" and v["source"] == "system_revision"]
        assert len(rev) == 1 and "v2" in rev[0]["label"] and rev[0]["origin"]["kind"] != "lawyer_edit"
        assert rev[0]["exportable"] is True
        assert d["pleadings"]["plaintiff"]["id"] != rev[0]["id"]  # 總覽的原告書狀仍是起訴狀 v1
        r = client.get(f"/api/cases/{case_id}/pleadings/{rev[0]['id']}/export")
        assert r.status_code == 200 and "_revision.txt" in r.headers["content-disposition"]

    def test_drift_is_not_applicable_and_not_red(self, client, detail):  # noqa: F811
        case_id, d = detail
        assert d["drift_detail"]["not_applicable"] is True
        check = d["verdict"]["anchor_check"]
        assert check["consistent"] is True and not check["differences"]
        assert any("不適用" in n for n in check["notes"])
        r = client.post(f"/api/cases/{case_id}/finalize").json()
        assert r["drift_detail"]["not_applicable"] is True


def test_ui_has_v2_wording_for_the_answer_and_drift():  # W4-4 與第 2 項 B:文字有分流(畫面另在瀏覽器看)
    source = open(os.path.join(ROOT, "ui", "app.js"), encoding="utf-8").read()
    assert "DOCUMENT_V2" in source and "新流程不適用" in source and "system_revision" in source


def test_v2_followups_come_from_the_issue_sheet(client, db_url):  # noqa: F811  W5-6
    from database.db import current_complaint, get_session, latest_answer, record_issue_sheet, record_party_check
    from engine import party_rules
    from engine.party_issues import procedural_issues
    from tests.test_gcis import company
    from tests.test_revision import SHEET
    case_id = create_v2(client)
    run(client, case_id, stop_after="answer")
    with get_session(db_url) as s:
        result = party_rules.summarize("22099131", "company", company(status="解散"))
        result.update(query_status="ok", via="gcis_live", fetched_at="2026-10-03T00:00:00Z")
        record_party_check(s, case_id=case_id, role="plaintiff", query_ban="22099131", result=result, raw={},
                           fetched_at=result["fetched_at"])
        issue_id = procedural_issues({"plaintiff": result, "defendant": None})["issues"][0]["id"]
        sheet = {**SHEET, "issues": [{**SHEET["issues"][0], "from": ["CF1"]}], "undisputed": [],
                 "questions": [{"question_text": "原告就清算人有何資料?", "target_side": "plaintiff",
                                "based_on": f"官方事實層({issue_id}):公司已解散"}]}
        record_issue_sheet(s, case_id=case_id, sheet=sheet, complaint_id=current_complaint(s, case_id)["version_id"],
                           answer_id=latest_answer(s, case_id).id)
    issues = client.get(f"/api/cases/{case_id}").json()["procedural_issues"]["issues"]
    assert next(i for i in issues if i["id"] == issue_id)["followed_up_in"] == [1]


def test_v2_cure_status_reads_the_complaint_statements(client, db_url):  # noqa: F811  舊設計殘留第 3 項
    from database.db import current_complaint, get_session, record_party_check
    from database.schema import PleadingDraft
    from engine import party_rules
    from engine.party_issues import procedural_issues
    from tests.test_gcis import company
    case_id = create_v2(client)
    run(client, case_id, stop_after="answer")
    with get_session(db_url) as s:
        result = party_rules.summarize("22099131", "company", company(status="解散"))
        result.update(query_status="ok", via="gcis_live", fetched_at="2026-10-03T00:00:00Z")
        record_party_check(s, case_id=case_id, role="plaintiff", query_ban="22099131", result=result, raw={},
                           fetched_at=result["fetched_at"])
        issue_id = procedural_issues({"plaintiff": result, "defendant": None})["issues"][0]["id"]
    view = client.get(f"/api/cases/{case_id}").json()["procedural_issues"]
    item = next(i for i in view["issues"] if i["id"] == issue_id)
    # 起訴狀是在查核之前寫的,「四、程序事項」沒有這則:看起訴狀,不看原告分析
    assert item["cured_in"] == "complaint" and item["cured_in_stage1"] is False
    assert view["coverage"]["where"] == "complaint" and view["coverage"]["debate"] == "not_answered"
    with get_session(db_url) as s:  # 起訴狀的結構化內容補上這則說明後就算已說明
        row = s.get(PleadingDraft, current_complaint(s, case_id)["version_id"])
        stored = json.loads(row.structured_json)
        stored["procedural_statements"] = [{"id": issue_id, "text": "清算人待查明後補正"}]
        row.structured_json = json.dumps(stored, ensure_ascii=False)
        s.commit()
    view = client.get(f"/api/cases/{case_id}").json()["procedural_issues"]
    assert next(i for i in view["issues"] if i["id"] == issue_id)["cured_in_stage1"] is True
    assert view["coverage"]["debate"] == "answered"
