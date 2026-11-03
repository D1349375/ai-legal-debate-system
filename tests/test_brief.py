"""W6 P4、P5 依爭點組織:每輪的爭點段落檢查(T6.1)、第 255 條與推測字樣警告(T6.3)、main.py brief 組成書狀(T6.2)、
finalize 不受影響(T6.4)。不連網。"""
import json
import os
import subprocess
import sys

import pytest

from database.db import (DB_URL_ENV, finalize_case, get_session, record_argument, record_case, record_issue_sheet,
                         record_pleading, upsert_citation)
from database.schema import DebateArgument, PleadingDraft
from engine import pleading_render
from engine.brief import render_brief, round_problems, round_warnings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CF1 = "原告於112年3月1日匯款100萬元至被告帳戶。"
CF2 = "兩造約定三個月內返還。"


def sheet():
    return {
        "undisputed": [{"id": "U1", "text": "原告於112年3月1日匯款100萬元", "source": ["CF1"], "evidence": ["甲證1"]}],
        "issues": [
            {"id": "I1", "kind": "fact", "text": "系爭匯款是否基於消費借貸合意", "from": ["CF2"], "plaintiff_claim": "約定返還",
             "plaintiff_evidence": [], "defendant_defense": "僅證明交付", "defendant_evidence": [],
             "legal_basis": ["民法第478條"], "burden": "plaintiff", "hypothetical": False},
            {"id": "I2", "kind": "defense", "text": "若被告主張已清償,是否可採", "from": [], "plaintiff_claim": "",
             "plaintiff_evidence": [], "defendant_defense": "若被告能提出清償紀錄", "defendant_evidence": [],
             "legal_basis": ["民法第309條"], "burden": "defendant", "hypothetical": True},
        ],
        "clarifications": [], "questions": [],
    }


GOOD = "【爭點 I1】兩造於LINE約定三個月內返還,足證借貸合意。\n【爭點 I2】若被告能提出清償紀錄,原告亦否認其效力。"


class TestRoundProblems:  # T6.1
    def test_every_issue_that_is_not_a_guess_needs_a_paragraph(self):
        assert round_problems(GOOD, sheet()) == []
        assert round_problems("【爭點 I1】借貸合意成立。", sheet()) == []  # 推測爭點 I2 不強制
        out = round_problems("【爭點 I2】若被告能提出清償紀錄,否認之。", sheet())
        assert len(out) == 1 and "I1" in out[0]

    def test_unknown_issue_marks_are_refused(self):
        out = round_problems(GOOD + "\n【爭點 I9】其他。", sheet())
        assert len(out) == 1 and "I9" in out[0]


class TestRoundWarnings:  # T6.3
    def test_new_plaintiff_basis_warns_about_article_255(self):
        out = round_warnings(GOOD, sheet(), side="plaintiff", basis=["民法第478條", "民法第179條"],
                             complaint_basis=["民法第478條"])
        assert len(out) == 1 and "民法第179條" in out[0] and "第255條" in out[0]
        assert round_warnings(GOOD, sheet(), side="defendant", basis=["民法第179條"], complaint_basis=["民法第478條"]) == []

    def test_guessed_issue_paragraph_keeps_the_guess_wording(self):
        text = "【爭點 I1】借貸合意成立。\n【爭點 I2】被告已清償。"
        out = round_warnings(text, sheet(), side="defendant", basis=[], complaint_basis=[])
        assert len(out) == 1 and "I2" in out[0] and "推測" in out[0]


@pytest.fixture
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path / 'brief.db'}"
    s = get_session(url)
    case = record_case(s, case_id="v2", case_type="返還借款", facts_summary="事實", claims="返還借款",
                       parties={"plaintiff": {"name": "甲"}, "defendant": {"name": "乙"}}, protocol="v2",
                       represented_side="plaintiff", evidence=[{"id": "甲證1", "type": "書證", "description": "匯款單"}])
    record_argument(s, case_id="v2", side="plaintiff", stage=1, position="返還借款", reasoning="依民法第478條請求。")
    complaint = {
        "cause": "返還借款", "prayers": ["被告應給付原告新臺幣100萬元。"],
        "claim_basis": [{"seq": 1, "role": "primary", "basis": ["民法第478條"], "prayer": "訴之聲明第一項"}],
        "fact_points": [{"id": "CF1", "text": CF1, "evidence_ids": ["甲證1"], "statement_quote": None},
                        {"id": "CF2", "text": CF2, "evidence_ids": [], "statement_quote": None}],
        "legal_argument": "依民法第478條請求返還。", "procedural_statements": [], "basis": ["民法第478條"],
        "citations": [], "precedent_notes": [], "fact_gaps": [], "lawyer_notes": [],
    }
    view_case = {"parties": json.loads(case.parties_json), "claim_amount": None, "evidence": json.loads(case.evidence_json)}
    text = pleading_render.render_complaint(complaint, case=view_case, party_checks={}, procedural=[])
    row = record_pleading(s, case_id="v2", draft_text=text, citations_used=[], pleading_type="complaint", round=1,
                          structured=pleading_render.stored_complaint(complaint))
    record_argument(s, case_id="v2", side="defendant", stage=1, position="否認借貸", reasoning="匯款不等於借貸。")
    responses = [{"fact_id": "CF1", "stance": "admit", "ground": None, "reason": None, "hypothetical": False},
                 {"fact_id": "CF2", "stance": "deny", "ground": "insufficient_proof", "reason": "僅證明交付", "hypothetical": False}]
    answer = {"responses": responses, "legal_argument": "原告未證明借貸合意。", "citations": [], "to_confirm": [], "defenses": []}
    answer_text = pleading_render.render_answer(answer, case=view_case, party_checks={}, procedural=None, complaint_text=text)
    answer_row = record_pleading(s, case_id="v2", draft_text=answer_text, citations_used=[], side="defendant",
                                 pleading_type="answer", round=1, is_simulated=1,
                                 structured=pleading_render.stored_answer(answer, row.id))
    record_issue_sheet(s, case_id="v2", sheet=sheet(), complaint_id=row.id, answer_id=answer_row.id)
    for statute in ("民法第478條", "民法第179條"):
        upsert_citation(s, citation_text=statute, source_type="statute", status="published",
                        primary_source_url="https://law.moj.gov.tw/x")
    s.close()
    return url


def stage_payload(side="plaintiff", stage=2, argument=GOOD, **over):
    return {"case_id": "v2", "side": side, "stage": stage, "position": f"{side} 第 {stage} 輪立場",
            "argument": argument + "\n【內部檢討】哨兵內部檢討【內部檢討結束】", "cited_statutes": ["民法第478條"],
            "cited_precedents": [], "falsifier": "哨兵讓步條件", "basis": ["民法第478條"], **over}


def run(db_url, tmp_path, *args, payload=None):
    env = {**os.environ, DB_URL_ENV: db_url, "PYTHONIOENCODING": "utf-8"}
    if payload is not None:
        path = tmp_path / "arg.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        args = ("record", "--json", str(path))
    return subprocess.run([sys.executable, "main.py", *args], cwd=ROOT, env=env, capture_output=True,
                          encoding="utf-8", timeout=60)


class TestRecordRound:
    def test_missing_issue_paragraph_goes_back_before_landing(self, db_url, tmp_path):  # T6.1
        r = run(db_url, tmp_path, payload=stage_payload(argument="【爭點 I2】若被告能提出清償紀錄,否認之。"))
        assert r.returncode == 1 and "I1" in r.stderr and "subagent" in r.stderr
        s = get_session(db_url)
        assert s.query(DebateArgument).filter_by(case_id="v2", stage=2).count() == 0

    def test_lands_with_basis_and_warns_on_new_basis(self, db_url, tmp_path):  # T6.3
        r = run(db_url, tmp_path, payload=stage_payload(basis=["民法第478條", "民法第179條"]))
        assert r.returncode == 0, r.stderr
        assert "第255條" in r.stderr and "民法第179條" in r.stderr
        row = get_session(db_url).query(DebateArgument).filter_by(case_id="v2", side="plaintiff", stage=2).one()
        assert json.loads(row.basis_json) == ["民法第478條", "民法第179條"]

    def test_basis_must_be_statutes(self, db_url, tmp_path):
        r = run(db_url, tmp_path, payload=stage_payload(basis=["不當得利"]))
        assert r.returncode == 1 and "basis" in r.stderr

    def test_v2_cases_without_an_issue_sheet_are_refused(self, tmp_path):
        # 第 4 批(審查第 4 節 W6 列):原本「沒有爭點整理表就不檢查」只到 W6 接線為止,之後 v2 沒有整理表就拒絕落地
        url = f"sqlite:///{tmp_path / 'old.db'}"
        s = get_session(url)
        record_case(s, case_id="v2", case_type="x", facts_summary="x", claims="x", protocol="v2", represented_side="plaintiff")
        s.close()
        r = run(url, tmp_path, payload=stage_payload(argument="沒有爭點段落的過渡寫法。"))
        assert r.returncode == 1 and "爭點整理表" in r.stderr


def land_rounds(db_url, tmp_path):
    for side in ("plaintiff", "defendant"):
        for stage in (2, 3):
            r = run(db_url, tmp_path, payload=stage_payload(side=side, stage=stage, basis=[] if side == "defendant" else ["民法第478條"]))
            assert r.returncode == 0, r.stderr


class TestBrief:
    def test_same_input_gives_the_same_text_without_internal_parts(self, db_url, tmp_path):  # T6.2
        land_rounds(db_url, tmp_path)
        first = run(db_url, tmp_path, "brief", "--case-id", "v2", "--side", "plaintiff", "--round", "2", "--check")
        second = run(db_url, tmp_path, "brief", "--case-id", "v2", "--side", "plaintiff", "--round", "2", "--check")
        assert first.returncode == 0, first.stderr
        assert first.stdout == second.stdout
        assert "哨兵內部檢討" not in first.stdout and "哨兵讓步條件" not in first.stdout
        assert "民事準備書狀" in first.stdout and "【爭點 I1】系爭匯款是否基於消費借貸合意" in first.stdout
        assert "若被告主張已清償,是否可採(推測)" in first.stdout

    def test_lands_brief_and_closing_once(self, db_url, tmp_path):
        land_rounds(db_url, tmp_path)
        for side, rnd, kind in (("plaintiff", "2", "brief"), ("defendant", "3", "closing")):
            r = run(db_url, tmp_path, "brief", "--case-id", "v2", "--side", side, "--round", rnd)
            assert r.returncode == 0, r.stderr
            row = get_session(db_url).query(PleadingDraft).filter_by(case_id="v2", pleading_type=kind).one()
            assert (row.side, row.round, row.is_simulated) == (side, int(rnd), 1)
        title = get_session(db_url).query(PleadingDraft).filter_by(pleading_type="closing").one().draft_text.splitlines()[0]
        assert title.startswith("民事言詞辯論意旨狀")
        again = run(db_url, tmp_path, "brief", "--case-id", "v2", "--side", "plaintiff", "--round", "2")
        assert again.returncode == 1 and "不可覆寫" in again.stderr

    def test_needs_the_round_to_be_landed(self, db_url, tmp_path):
        r = run(db_url, tmp_path, "brief", "--case-id", "v2", "--side", "plaintiff", "--round", "3", "--check")
        assert r.returncode == 1 and "stage 3" in r.stderr

    def test_new_basis_is_noted_for_the_lawyer(self, db_url, tmp_path):
        r = run(db_url, tmp_path, payload=stage_payload(basis=["民法第478條", "民法第179條"]))
        assert r.returncode == 0, r.stderr
        out = run(db_url, tmp_path, "brief", "--case-id", "v2", "--side", "plaintiff", "--round", "2", "--check").stdout
        body, note = out.split("【本稿產出說明】")
        assert "民法第179條" in note and "第255條" in note


def test_finalize_still_works_with_issue_paragraphs(db_url, tmp_path):  # T6.4
    land_rounds(db_url, tmp_path)
    anchor = finalize_case(get_session(db_url), case_id="v2")
    assert set(anchor) >= {"weak_points", "position_drift", "procedural_issues"}
    assert set(anchor["position_drift"]) == {"plaintiff", "defendant"}


def test_render_brief_is_pure():
    case = {"parties": {"plaintiff": {"name": "甲"}, "defendant": {"name": "乙"}}}
    kwargs = dict(side="defendant", round=3, sheet=sheet(), case=case, party_checks={}, procedural=None,
                  complaint_text="為請求返還借款提起訴訟事:", citations=["民法第478條"], new_basis=[])
    text = render_brief(GOOD, **kwargs)
    assert text == render_brief(GOOD, **kwargs)
    assert text.splitlines()[0].startswith("民事言詞辯論意旨狀") and "為返還借款事件" in text
    assert "民法第478條" in text and "(模擬被告未附證物)" in text
