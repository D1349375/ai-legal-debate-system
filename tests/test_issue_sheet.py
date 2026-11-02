"""W5 爭點整理表:結構檢查(T5.1、T5.2、T5.5)、法官角色檔、自承來源加入書狀、main.py issue-sheet 落地、匯出(T5.4)。不連網。"""
import copy
import json
import os
import subprocess
import sys

import pytest

from database.db import (DB_URL_ENV, admission_sources, get_session, issue_sheet, judge_role_view, record_argument,
                         record_case, record_issue_sheet, record_pleading)
from engine import pleading_render
from engine.admission_check import admission_problems
from engine.issue_sheet import issue_sheet_problems, issue_sheet_warnings, render_issue_sheet

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SENTINELS = ("哨兵事實經過", "哨兵已知缺口", "哨兵內部檢討", "哨兵未列證據", "哨兵證明目的", "哨兵已知反應", "哨兵原告分析")
CF1 = "原告於112年3月1日匯款100萬元至被告帳戶。"
CF2 = "兩造約定三個月內返還。"
CF3 = "被告曾於LINE表示會還錢。"


def sheet():
    return {
        "undisputed": [{"id": "U1", "text": "原告於112年3月1日匯款100萬元至被告帳戶", "source": ["CF1"], "evidence": ["甲證1"]}],
        "issues": [
            {"id": "I1", "kind": "fact", "text": "系爭匯款是否基於消費借貸合意", "from": ["CF2"],
             "plaintiff_claim": "兩造約定三個月內返還", "plaintiff_evidence": ["甲證2"],
             "defendant_defense": "匯款僅證明交付", "defendant_evidence": [],
             "legal_basis": ["民法第478條"], "burden": "plaintiff", "hypothetical": False},
            {"id": "I2", "kind": "defense", "text": "若被告主張已清償,是否可採", "from": [],
             "plaintiff_claim": "", "plaintiff_evidence": [], "defendant_defense": "若被告能提出清償紀錄",
             "defendant_evidence": [], "legal_basis": ["民法第309條"], "burden": "defendant", "hypothetical": True},
        ],
        "clarifications": [{"target_side": "plaintiff", "question": "如不構成消費借貸,是否另依不當得利請求?",
                            "basis": "民事訴訟法第199條之1", "based_on": "I1"}],
        "questions": [{"question_text": "原告就借貸合意有無其他證據?", "target_side": "plaintiff", "based_on": "I1:借貸合意"}],
    }


COMPLAINT_TEXT = f"訴之聲明\n一、被告應給付原告新臺幣100萬元。\n\n事實及理由\n一、事實\n(一){CF1}〔CF1〕\n(二){CF2}〔CF2〕\n(三){CF3}〔CF3〕\n"
RESPONSES = [
    {"fact_id": "CF1", "stance": "admit", "ground": None, "reason": None, "hypothetical": False},
    {"fact_id": "CF2", "stance": "deny", "ground": "insufficient_proof", "reason": "匯款僅證明交付", "hypothetical": False},
    {"fact_id": "CF3", "stance": "to_confirm", "ground": None, "reason": "需被告本人說明", "hypothetical": False},
]
EVIDENCE_IDS = ["甲證1", "甲證2"]


def problems(value):
    return issue_sheet_problems(value, complaint_text=COMPLAINT_TEXT, responses=RESPONSES, evidence_ids=EVIDENCE_IDS)


class TestStructure:
    def test_valid_sheet_passes(self):
        assert problems(sheet()) == []

    def test_undisputed_must_come_from_admit(self):  # T5.1
        for cf, stance in (("CF2", "deny"), ("CF3", "to_confirm")):
            value = sheet()
            value["undisputed"][0]["source"] = [cf]
            out = problems(value)
            assert len(out) == 1 and cf in out[0] and stance in out[0]
        value = sheet()
        value["undisputed"][0]["source"] = []
        assert any("U1" in m and "source" in m for m in problems(value))

    def test_references_must_exist(self):  # T5.2
        value = sheet()
        value["issues"][0]["from"] = ["CF9"]
        value["clarifications"][0]["based_on"] = "I9"
        value["questions"][0]["based_on"] = "I8:不存在"
        out = problems(value)
        assert any("CF9" in m for m in out) and any("I9" in m for m in out) and any("I8" in m for m in out)

    def test_official_layer_questions_keep_their_format(self):  # T5.3 的結構部分
        value = sheet()
        value["questions"].append({"question_text": "原告就清算人為何人有何資料?", "target_side": "plaintiff",
                                   "based_on": "官方事實層(plaintiff:dissolved):公司已解散"})
        assert problems(value) == []

    def test_values_and_ids_are_checked(self):
        value = sheet()
        value["issues"][0].update(kind="guess", burden="court", hypothetical="no", plaintiff_evidence=["甲證9"])
        value["issues"][1]["id"] = "I1"
        value["issues"][1]["legal_basis"] = ["清償"]
        out = problems(value)
        for word in ("kind", "burden", "hypothetical", "甲證9", "重複", "清償"):
            assert any(word in m for m in out), word
        assert problems([]) == ["爭點整理表必須是 JSON 物件"]
        assert any("issues" in m for m in problems({**sheet(), "issues": "x"}))


class TestHypothetical:  # T5.5
    def test_the_table_marks_guesses(self):
        text = render_issue_sheet(sheet(), complaint_text=COMPLAINT_TEXT,
                                  evidence=[{"id": "甲證1", "type": "書證", "date": None, "description": "匯款單"}])
        assert "若被告主張已清償,是否可採(推測)" in text and "系爭匯款是否基於消費借貸合意(推測)" not in text
        for title in ("聲明與請求權基礎", "預期不爭執事項", "爭點整理表", "證據清單"):
            assert title in text
        assert "被告應給付原告新臺幣100萬元" in text and "甲證1" in text

    def test_issue_from_a_guessed_stance_should_be_marked(self):
        responses = copy.deepcopy(RESPONSES)
        responses[1].update(ground="alternative_explanation", hypothetical=True)
        out = issue_sheet_warnings(sheet(), responses=responses)
        assert any("I1" in w and "CF2" in w and "hypothetical" in w for w in out)
        assert issue_sheet_warnings(sheet(), responses=RESPONSES) == []

    def test_factual_question_to_the_defendant_warns(self):
        value = sheet()
        value["questions"].append({"question_text": "被告手上是否持有清償收據?", "target_side": "defendant",
                                   "based_on": "I2:清償"})
        assert any("被告" in w and "事實" in w for w in issue_sheet_warnings(value, responses=RESPONSES))


@pytest.fixture
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path / 'sheet.db'}"
    s = get_session(url)
    case = record_case(s, case_id="v2", case_type="返還借款", facts_summary="哨兵事實經過", claims="返還借款",
                       parties={"plaintiff": {"name": "甲"}, "defendant": {"name": "乙"}}, protocol="v2",
                       represented_side="plaintiff", known_gaps=["哨兵已知缺口"],
                       evidence=[{"id": "甲證1", "type": "書證", "description": "匯款單", "proves": "哨兵證明目的"},
                                 {"id": "甲證2", "type": "書證", "description": "LINE 對話截圖"},
                                 {"id": "甲證3", "type": "書證", "description": "哨兵未列證據"}],
                       opponent_responses=[{"source": "LINE", "text": "哨兵已知反應"}])
    record_argument(s, case_id="v2", side="plaintiff", stage=1, position="哨兵原告分析",
                    reasoning="依民法第478條請求。\n【內部檢討】哨兵內部檢討")
    complaint = {
        "cause": "返還借款", "prayers": ["被告應給付原告新臺幣100萬元。"],
        "claim_basis": [{"seq": 1, "role": "primary", "basis": ["民法第478條"], "prayer": "訴之聲明第一項"}],
        "fact_points": [{"id": "CF1", "text": CF1, "evidence_ids": ["甲證1"], "statement_quote": None},
                        {"id": "CF2", "text": CF2, "evidence_ids": ["甲證2"], "statement_quote": None},
                        {"id": "CF3", "text": CF3, "evidence_ids": [], "statement_quote": None}],
        "legal_argument": "依民法第478條請求返還。", "procedural_statements": [], "basis": ["民法第478條"],
        "citations": [], "precedent_notes": [], "fact_gaps": [], "lawyer_notes": [],
    }
    view_case = {"parties": json.loads(case.parties_json), "claim_amount": None, "evidence": json.loads(case.evidence_json)}
    text = pleading_render.render_complaint(complaint, case=view_case, party_checks={}, procedural=[])
    row = record_pleading(s, case_id="v2", draft_text=text, citations_used=[], pleading_type="complaint", round=1,
                          structured=pleading_render.stored_complaint(complaint))
    record_argument(s, case_id="v2", side="defendant", stage=1, position="否認借貸", reasoning="匯款不等於借貸。")
    answer = {"responses": RESPONSES, "legal_argument": "原告未證明借貸合意。", "citations": [], "to_confirm": [],
              "defenses": [{"type": "payment", "statement": "若被告能提出清償紀錄,主張已清償",
                            "legal_basis": [], "hypothetical": True}]}
    answer_text = pleading_render.render_answer(answer, case=view_case, party_checks={}, procedural=None,
                                                complaint_text=text)
    record_pleading(s, case_id="v2", draft_text=answer_text, citations_used=[], side="defendant",
                    pleading_type="answer", round=1, is_simulated=1,
                    structured=pleading_render.stored_answer(answer, row.id))
    s.close()
    return url


class TestJudgeView:
    def test_judge_reads_only_the_pleadings(self, db_url):
        view = judge_role_view(get_session(db_url), "v2")
        dumped = json.dumps(view, ensure_ascii=False)
        assert [s for s in SENTINELS if s in dumped] == []
        assert "〔CF1〕" in view["complaint"]["text"] and "民事答辯狀" in view["answer"]["text"]
        assert "本稿產出說明" not in view["complaint"]["text"] + view["answer"]["text"]
        assert [r["fact_id"] for r in view["answer"]["responses"]] == ["CF1", "CF2", "CF3"]
        assert [e["id"] for e in view["evidence"]] == ["甲證1", "甲證2"]
        assert {"procedural_issues", "party_checks"} <= set(view)

    def test_no_answer_yet_is_an_error(self, tmp_path):
        s = get_session(f"sqlite:///{tmp_path / 'none.db'}")
        record_case(s, case_id="v2", case_type="x", facts_summary="x", claims="x", protocol="v2", represented_side="plaintiff")
        with pytest.raises(ValueError):
            judge_role_view(s, "v2")


class TestAdmissionSources:  # 舊設計殘留第 1 項
    def check(self, db_url, text):
        return admission_problems(text, admission_sources(get_session(db_url), "v2"))

    def test_quoting_the_complaint_and_admitted_points_passes(self, db_url):
        assert self.check(db_url, "原告起訴狀自陳「原告於112年3月1日匯款100萬元至被告帳戶」。") == []
        assert self.check(db_url, "被告自認「原告於112年3月1日匯款100萬元至被告帳戶」。") == []
        assert self.check(db_url, "被告自承「匯款僅證明交付」。") == []

    def test_points_the_defendant_did_not_admit_are_not_its_words(self, db_url):
        assert self.check(db_url, "被告自認「兩造約定三個月內返還」。")
        assert self.check(db_url, "被告自認「被告曾於LINE表示會還錢」。")


def run(db_url, tmp_path, value, *extra):
    path = tmp_path / "sheet.json"
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    env = {**os.environ, DB_URL_ENV: db_url, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, "main.py", "issue-sheet", "--case-id", "v2", "--json", str(path), *extra],
                          cwd=ROOT, env=env, capture_output=True, encoding="utf-8", timeout=60)


class TestIssueSheetCommand:
    def test_check_prints_the_tables_and_lands_nothing(self, db_url, tmp_path):
        r = run(db_url, tmp_path, sheet(), "--check")
        assert r.returncode == 0, r.stderr
        assert "爭點整理表" in r.stdout and "(推測)" in r.stdout
        assert issue_sheet(get_session(db_url), "v2") is None

    def test_lands_once(self, db_url, tmp_path):
        r = run(db_url, tmp_path, sheet())
        assert r.returncode == 0, r.stderr
        stored = issue_sheet(get_session(db_url), "v2")
        assert stored["sheet"]["issues"][0]["id"] == "I1" and stored["complaint_id"] and stored["answer_id"]
        again = run(db_url, tmp_path, sheet())
        assert again.returncode == 1 and "不可覆寫" in again.stderr

    def test_structure_problems_go_back_to_the_judge(self, db_url, tmp_path):
        value = sheet()
        value["undisputed"][0]["source"] = ["CF2"]
        r = run(db_url, tmp_path, value)
        assert r.returncode == 1 and "CF2" in r.stderr and "法官 subagent" in r.stderr

    def test_admission_wording_is_checked(self, db_url, tmp_path):
        value = sheet()
        value["issues"][0]["defendant_defense"] = "被告自認「兩造約定三個月內返還」"
        r = run(db_url, tmp_path, value)
        assert r.returncode == 1 and "自認" in r.stderr

    def test_record_refuses_a_second_sheet(self, db_url):
        s = get_session(db_url)
        record_issue_sheet(s, case_id="v2", sheet=sheet(), complaint_id=1, answer_id=2)
        with pytest.raises(ValueError, match="不可覆寫"):
            record_issue_sheet(s, case_id="v2", sheet=sheet(), complaint_id=1, answer_id=2)


def test_export_and_import_keep_the_sheet(db_url, tmp_path):  # T5.4
    from server import seed
    s = get_session(db_url)
    record_issue_sheet(s, case_id="v2", sheet=sheet(), complaint_id=1, answer_id=2)
    path = tmp_path / "fixture.json"
    assert seed.write_fixture(s, str(path))["issue_sheets"] == 1
    fresh = get_session(f"sqlite:///{tmp_path / 'fresh.db'}")
    assert seed.seed_if_empty(fresh, str(path))["issue_sheets"] == 1
    assert issue_sheet(fresh, "v2")["sheet"] == sheet()
