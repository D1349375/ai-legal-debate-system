"""W7 P6 診斷與起訴狀 v2(T7.1–T7.5):被告推測不得寫進 v2、新事實對應檢查、v2 落地與版本鏈、
P6 評估新鍵的結構檢查、勝訴機率類字樣警告、舊案評估不變、v1 與 v2 差異。不連網。"""
import copy
import json
import os
import subprocess
import sys

import pytest

from database.db import (DB_URL_ENV, current_complaint, get_session, record_argument, record_case,
                         record_complaint_revision, record_gate, record_issue_sheet, record_pleading,
                         record_pleading_edit, record_verdict, system_complaints, upsert_citation)
from database.schema import PleadingDraft, Verdict
from engine import pleading_render
from engine.diagnosis import verdict_v2_problems, win_probability_warnings
from engine.pleading_diff import complaint_diff
from engine.revision import hypothetical_problems, hypothetical_warnings, opponent_hypotheticals, stored_revision

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CF1 = "原告於112年3月1日匯款100萬元至被告帳戶。"
CF2 = "兩造約定三個月內返還。"
CF3 = "被告曾於LINE表示會還錢。"
FACTS = CF1 + CF2 + CF3 + "原告多次催討未果。"
# 被告推測的內容(答辯狀 hypothetical 抗辯、另一解釋的理由、爭點整理表的推測爭點)
DEFENSE_GUESS = "若被告能提出清償紀錄,主張已清償"
ALT_GUESS = "該筆款項係原告對被告之贈與"
SHEET_GUESS = "被告已於112年6月間以現金清償全部借款"
NOT_A_GUESS = "匯款僅證明交付"  # insufficient_proof、非推測:可以回應

RESPONSES = [
    {"fact_id": "CF1", "stance": "admit", "ground": None, "reason": None, "hypothetical": False},
    {"fact_id": "CF2", "stance": "deny", "ground": "alternative_explanation", "reason": ALT_GUESS, "hypothetical": True},
    {"fact_id": "CF3", "stance": "deny", "ground": "insufficient_proof", "reason": NOT_A_GUESS, "hypothetical": False},
]
ANSWER = {"responses": RESPONSES, "legal_argument": "原告未證明借貸合意。", "citations": [], "to_confirm": [],
          "defenses": [{"type": "payment", "statement": DEFENSE_GUESS, "legal_basis": [], "hypothetical": True},
                       {"type": "denial", "statement": "原告未舉證借貸合意", "legal_basis": [], "hypothetical": False}]}
SHEET = {
    "undisputed": [{"id": "U1", "text": "原告於112年3月1日匯款100萬元至被告帳戶", "source": ["CF1"], "evidence": ["甲證1"]}],
    "issues": [
        {"id": "I1", "kind": "fact", "text": "系爭匯款是否基於消費借貸合意", "from": ["CF2"],
         "plaintiff_claim": "兩造約定三個月內返還", "plaintiff_evidence": ["甲證2"],
         "defendant_defense": NOT_A_GUESS, "defendant_evidence": [],
         "legal_basis": ["民法第478條"], "burden": "plaintiff", "hypothetical": False},
        {"id": "I2", "kind": "defense", "text": "被告是否已清償", "from": [],
         "plaintiff_claim": "", "plaintiff_evidence": [], "defendant_defense": SHEET_GUESS,
         "defendant_evidence": [], "legal_basis": ["民法第309條"], "burden": "defendant", "hypothetical": True},
    ],
    "clarifications": [], "questions": [],
}


def complaint(**over):
    p = {
        "cause": "返還借款", "prayers": ["被告應給付原告新臺幣100萬元。", "訴訟費用由被告負擔。"],
        "claim_basis": [{"seq": 1, "role": "primary", "basis": ["民法第478條"], "prayer": "訴之聲明第一項"}],
        "fact_points": [{"id": "CF1", "text": CF1, "evidence_ids": ["甲證1"], "statement_quote": None},
                        {"id": "CF2", "text": CF2, "evidence_ids": ["甲證2"], "statement_quote": None},
                        {"id": "CF3", "text": CF3, "evidence_ids": [], "statement_quote": "被告曾於LINE表示會還錢"}],
        "legal_argument": "兩造成立消費借貸,依民法第478條請求返還。", "procedural_statements": [],
        "basis": ["民法第478條"], "citations": ["民法第478條"], "precedent_notes": [],
        "fact_gaps": ["借貸合意的書面證據待確認"], "lawyer_notes": [],
    }
    p.update(over)
    return p


def revision(**over):
    """起訴狀 v2:加列備位不當得利,理由改寫。"""
    p = complaint(
        claim_basis=[{"seq": 1, "role": "primary", "basis": ["民法第478條"], "prayer": "訴之聲明第一項"},
                     {"seq": 2, "role": "alternative", "basis": ["民法第179條"], "prayer": "訴之聲明第一項"}],
        basis=["民法第478條", "民法第179條"], citations=["民法第478條", "民法第179條"],
        legal_argument="兩造成立消費借貸,依民法第478條請求返還;縱認借貸合意不成立,被告受領款項亦無法律上原因,"
                       "備位依民法第179條請求返還。",
    )
    p.update(over)
    return p


def risk_map(**over):
    value = {
        "對原告不利之處": ["借貸合意只有LINE對話"], "對被告不利之處": ["匯款事實不爭執"], "建議補強證據": ["借據或對話紀錄"],
        "issue_assessment": [{"issue_id": "I1", "strength": "中", "reason": "有匯款與LINE對話,但無借據"},
                             {"issue_id": "I2", "strength": "弱", "reason": "被告未提出清償證據"}],
        "evidence_todo": [{"issue_id": "I1", "missing": "借貸合意的書面或證人", "why": "匯款本身不足以證明借貸合意"}],
        "complaint_revisions": [{"fact_id": "CF2", "kind": "revise", "suggestion": "寫明約定返還的時間與方式"},
                                {"fact_id": None, "kind": "add_alternative", "suggestion": "備位依民法第179條請求"}],
        "fact_gaps": ["約定返還時有無第三人在場"],
        "opponent_hypotheticals": ["被告可能主張已清償,請向當事人確認"],
    }
    value.update(over)
    return value


def verdict(rm=None, **over):
    v = {"verdict_main_text": "借貸合意爭點中等,建議補強書面證據。", "verdict_analysis": "爭點一中等;爭點二弱。",
         "risk_map": risk_map() if rm is None else rm, "mechanical_anchor_json": {}, "citations_used": []}
    v.update(over)
    return v


def build_case(url, *, sheet=True, verdict_landed=True, confirm_edit=False):
    """v2 案件:原告分析、起訴狀 v1、(可選)律師編輯版並在關卡 1 確認、模擬答辯狀、爭點整理表、P6 評估。"""
    s = get_session(url)
    case = record_case(s, case_id="v2", case_type="返還借款", facts_summary=FACTS, claims="返還借款",
                       parties={"plaintiff": {"name": "甲"}, "defendant": {"name": "乙"}}, protocol="v2",
                       represented_side="plaintiff",
                       evidence=[{"id": "甲證1", "type": "書證", "description": "匯款單"},
                                 {"id": "甲證2", "type": "書證", "description": "LINE 對話截圖"}])
    for c in ("民法第478條", "民法第179條"):
        upsert_citation(s, citation_text=c, source_type="statute", status="published")
    record_argument(s, case_id="v2", side="plaintiff", stage=1, position="返還借款",
                    reasoning="依民法第478條請求。\n【內部檢討】無")
    view_case = {"parties": json.loads(case.parties_json), "claim_amount": None, "evidence": json.loads(case.evidence_json)}
    text = pleading_render.render_complaint(complaint(), case=view_case, party_checks={}, procedural=None)
    v1 = record_pleading(s, case_id="v2", draft_text=text, citations_used=["民法第478條"], pleading_type="complaint",
                         round=1, is_simulated=0, structured=pleading_render.stored_complaint(complaint()))
    confirmed = v1
    if confirm_edit:
        edited = text.replace("兩造成立消費借貸", "兩造確已成立消費借貸")
        confirmed = record_pleading_edit(s, case_id="v2", parent_id=v1.id, draft_text=edited, citation_check=[])
        record_gate(s, case_id="v2", gate="complaint", version_id=confirmed.id, action="continue", by="ui")
    record_argument(s, case_id="v2", side="defendant", stage=1, position="否認借貸", reasoning="匯款不等於借貸。")
    answer_text = pleading_render.render_answer(ANSWER, case=view_case, party_checks={}, procedural=None,
                                                complaint_text=confirmed.draft_text)
    answer = record_pleading(s, case_id="v2", draft_text=answer_text, citations_used=[], side="defendant",
                             pleading_type="answer", round=1, is_simulated=1,
                             structured=pleading_render.stored_answer(ANSWER, confirmed.id))
    if sheet:
        record_issue_sheet(s, case_id="v2", sheet=SHEET, complaint_id=confirmed.id, answer_id=answer.id)
    if verdict_landed:
        v = verdict()
        record_verdict(s, case_id="v2", verdict_main_text=v["verdict_main_text"], verdict_reasoning=v["verdict_analysis"],
                       risk_map=v["risk_map"], mechanical_anchor_json={}, protocol_version="v2-pleading-exchange",
                       citations_used=[])
    ids = {"v1": v1.id, "confirmed": confirmed.id, "answer": answer.id}
    s.close()
    return ids


@pytest.fixture
def db_url(tmp_path):
    return f"sqlite:///{tmp_path / 'revision.db'}"


def run_main(*args, db_url):
    env = {**os.environ, DB_URL_ENV: db_url, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, "main.py", *args], cwd=ROOT, env=env, capture_output=True,
                          encoding="utf-8", timeout=60)


def write(tmp_path, obj, name="revision.json"):
    path = tmp_path / name
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return str(path)


def revisions(url):
    with get_session(url) as s:
        return [r for r in s.query(PleadingDraft).all() if r.source == "system_revision"]


# ---- T7.1 被告推測不得寫進 v2(純函數)----

class TestOpponentHypotheticals:
    def test_collects_only_guesses(self):
        found = opponent_hypotheticals(ANSWER, SHEET)
        assert set(found) == {DEFENSE_GUESS, ALT_GUESS, SHEET_GUESS}
        assert NOT_A_GUESS not in found and "原告未舉證借貸合意" not in found

    def test_alternative_explanation_counts_even_if_flag_missing(self):
        answer = copy.deepcopy(ANSWER)
        answer["responses"][1]["hypothetical"] = False  # 答辯狀檢查會擋,但這裡不依賴旗標
        assert ALT_GUESS in opponent_hypotheticals(answer, None)

    def test_missing_answer_or_sheet(self):
        assert opponent_hypotheticals(None, None) == []
        assert opponent_hypotheticals(ANSWER, None) == [DEFENSE_GUESS, ALT_GUESS]


class TestHypotheticalProblems:
    guesses = [DEFENSE_GUESS, ALT_GUESS, SHEET_GUESS]

    def test_clean_revision_passes(self):
        assert hypothetical_problems(revision(), self.guesses) == []

    def test_guess_in_fact_point_is_refused(self):
        fp = revision()["fact_points"] + [{"id": "CF4", "text": "該筆款項 係原告對被告之贈與。", "evidence_ids": ["甲證1"],
                                           "statement_quote": None}]
        out = hypothetical_problems(revision(fact_points=fp), self.guesses)
        assert len(out) == 1 and "CF4" in out[0] and ALT_GUESS in out[0]

    def test_guess_in_legal_argument_is_refused_ignoring_punctuation(self):
        p = revision(legal_argument="被告已於112年6月間，以現金清償全部借款;惟原告仍得請求。")
        out = hypothetical_problems(p, self.guesses)
        assert len(out) == 1 and "legal_argument" in out[0] and SHEET_GUESS in out[0]

    def test_text_already_in_the_confirmed_complaint_is_not_the_defendants(self):
        p = revision(legal_argument="原告曾稱該筆款項係原告對被告之贈與,嗣後改稱借款。")
        assert hypothetical_problems(p, self.guesses, confirmed_text="原告曾稱該筆款項係原告對被告之贈與") == []
        assert hypothetical_problems(p, self.guesses)

    def test_short_guesses_do_not_block(self):
        assert hypothetical_problems(revision(legal_argument="被告已清償與否待查。"), ["已清償"]) == []

    def test_partial_copy_only_warns(self):
        p = revision(legal_argument="兩造成立消費借貸。被告以現金清償全部借款之說,並無證據。")
        assert hypothetical_problems(p, self.guesses) == []
        out = hypothetical_warnings(p, self.guesses)
        assert len(out) == 1 and "以現金清償全部借款" in out[0]


def test_stored_revision_adds_parent():
    stored = stored_revision({**revision(), "extra": 1}, 7)
    assert stored["parent_id"] == 7 and "extra" not in stored and stored["basis"] == ["民法第478條", "民法第179條"]


# ---- 起訴狀 v2 落地(CLI)----

class TestRevisionCommand:
    def test_lands_as_revision_of_the_confirmed_version(self, db_url, tmp_path):  # T7.3
        ids = build_case(db_url, confirm_edit=True)
        r = run_main("revision", "--case-id", "v2", "--json", write(tmp_path, revision()), db_url=db_url)
        assert r.returncode == 0, r.stderr
        [row] = revisions(db_url)
        assert row.parent_id == ids["confirmed"] != ids["v1"]
        assert (row.side, row.pleading_type, row.round, row.is_simulated, row.citation_verification_status) == (
            "plaintiff", "complaint", 2, 0, "published")
        stored = json.loads(row.structured_json)
        assert stored["parent_id"] == ids["confirmed"] and stored["basis"] == ["民法第478條", "民法第179條"]
        assert "民事起訴狀" in row.draft_text and "〔CF1〕" in row.draft_text and "備位:民法第179條" in row.draft_text
        with get_session(db_url) as s:  # revision 不會被當成原稿或確認版
            assert [c.id for c in system_complaints(s, "v2")] == [ids["v1"]]
            assert current_complaint(s, "v2")["version_id"] == ids["confirmed"]
        again = run_main("revision", "--case-id", "v2", "--json", write(tmp_path, revision()), db_url=db_url)
        assert again.returncode == 1 and "不可覆寫" in again.stderr
        assert len(revisions(db_url)) == 1

    def test_without_gate_parent_is_the_current_system_draft(self, db_url, tmp_path):
        ids = build_case(db_url)
        r = run_main("revision", "--case-id", "v2", "--json", write(tmp_path, revision()), db_url=db_url)
        assert r.returncode == 0, r.stderr
        [row] = revisions(db_url)
        assert row.parent_id == ids["v1"]
        with get_session(db_url) as s:
            assert current_complaint(s, "v2")["version_id"] == ids["v1"]
            assert [c.id for c in system_complaints(s, "v2")] == [ids["v1"]]
        # v1 已落地、v2 也落地後,complaint 指令照舊只看 v1(round 1)
        again = run_main("complaint", "--case-id", "v2", "--json", write(tmp_path, complaint(), "c.json"), db_url=db_url)
        assert again.returncode == 1 and "v1 已落地" in again.stderr

    def test_check_only_prints_and_lands_nothing(self, db_url, tmp_path):
        build_case(db_url)
        r = run_main("revision", "--case-id", "v2", "--json", write(tmp_path, revision()), "--check", db_url=db_url)
        assert r.returncode == 0, r.stderr
        assert "民事起訴狀" in r.stdout and "檢查通過" in r.stdout and revisions(db_url) == []

    def test_opponent_guess_is_refused(self, db_url, tmp_path):  # T7.1 經 CLI
        build_case(db_url)
        fp = revision()["fact_points"] + [{"id": "CF4", "text": ALT_GUESS + "之說不實。", "evidence_ids": ["甲證1"],
                                           "statement_quote": None}]
        bad = revision(fact_points=fp, legal_argument="被告已於112年6月間以現金清償全部借款,惟仍應返還。")
        r = run_main("revision", "--case-id", "v2", "--json", write(tmp_path, bad), db_url=db_url)
        assert r.returncode == 1 and "改寫 subagent" in r.stderr
        assert "CF4" in r.stderr and ALT_GUESS in r.stderr and SHEET_GUESS in r.stderr
        assert revisions(db_url) == []

    def test_partial_guess_only_warns(self, db_url, tmp_path):
        build_case(db_url)
        p = revision(legal_argument=revision()["legal_argument"] + "被告以現金清償全部借款之說並無證據。")
        r = run_main("revision", "--case-id", "v2", "--json", write(tmp_path, p), "--check", db_url=db_url)
        assert r.returncode == 0, r.stderr
        assert "警告" in r.stdout and "以現金清償全部借款" in r.stdout

    def test_unmapped_new_fact_is_refused(self, db_url, tmp_path):  # T7.2
        build_case(db_url)
        fp = revision()["fact_points"] + [{"id": "CF4", "text": "被告曾向他人借款周轉。", "evidence_ids": [],
                                           "statement_quote": "被告曾向他人借款周轉"}]
        r = run_main("revision", "--case-id", "v2", "--json", write(tmp_path, revision(fact_points=fp)), db_url=db_url)
        assert r.returncode == 1 and "CF4" in r.stderr and "fact_gaps" in r.stderr
        fp[-1].update(statement_quote=None, evidence_ids=["甲證9"])
        r = run_main("revision", "--case-id", "v2", "--json", write(tmp_path, revision(fact_points=fp)), db_url=db_url)
        assert r.returncode == 1 and "甲證9" in r.stderr
        assert revisions(db_url) == []

    def test_mapped_new_fact_lands(self, db_url, tmp_path):
        build_case(db_url)
        fp = revision()["fact_points"] + [{"id": "CF4", "text": "原告多次催討未果。", "evidence_ids": [],
                                           "statement_quote": "原告多次催討未果"}]
        r = run_main("revision", "--case-id", "v2", "--json", write(tmp_path, revision(fact_points=fp)), db_url=db_url)
        assert r.returncode == 0, r.stderr
        assert "〔CF4〕" in revisions(db_url)[0].draft_text

    def test_unpublished_citation_is_refused(self, db_url, tmp_path):
        build_case(db_url)
        p = revision(legal_argument="依民法第478條及民法第184條請求。")
        r = run_main("revision", "--case-id", "v2", "--json", write(tmp_path, p), db_url=db_url)
        assert r.returncode == 1 and "民法第184條" in r.stderr and revisions(db_url) == []

    def test_requires_a_landed_diagnosis(self, db_url, tmp_path):
        build_case(db_url, verdict_landed=False)
        r = run_main("revision", "--case-id", "v2", "--json", write(tmp_path, revision()), "--check", db_url=db_url)
        assert r.returncode == 1 and "評估" in r.stderr

    def test_requires_v2_case_and_complaint(self, db_url, tmp_path):
        with get_session(db_url) as s:
            record_case(s, case_id="old", case_type="消費借貸", facts_summary="借款未還", claims="返還借款")
            record_case(s, case_id="empty", case_type="消費借貸", facts_summary=FACTS, claims="返還借款", protocol="v2",
                        represented_side="plaintiff")
            record_argument(s, case_id="empty", side="plaintiff", stage=1, position="p", reasoning="r")
        r = run_main("revision", "--case-id", "old", "--json", write(tmp_path, revision()), "--check", db_url=db_url)
        assert r.returncode == 1 and "v2" in r.stderr
        r = run_main("revision", "--case-id", "empty", "--json", write(tmp_path, revision()), "--check", db_url=db_url)
        assert r.returncode == 1 and "起訴狀" in r.stderr
        r = run_main("revision", "--case-id", "none", "--json", write(tmp_path, revision()), "--check", db_url=db_url)
        assert r.returncode == 1 and "找不到案件" in r.stderr


class TestRecordComplaintRevision:
    def test_parent_must_be_the_current_complaint(self, db_url):
        ids = build_case(db_url, confirm_edit=True)
        with get_session(db_url) as s:
            with pytest.raises(ValueError, match="確認版"):
                record_complaint_revision(s, case_id="v2", parent_id=ids["v1"], draft_text="x", citations_used=[],
                                          structured={})
            with pytest.raises(ValueError, match="尚未查證"):
                record_complaint_revision(s, case_id="v2", parent_id=ids["confirmed"], draft_text="x",
                                          citations_used=["民法第184條"], structured={})
            row = record_complaint_revision(s, case_id="v2", parent_id=ids["confirmed"], draft_text="x",
                                            citations_used=["民法第478條"], structured={"basis": []})
            assert (row.source, row.round, json.loads(row.structured_json)["parent_id"]) == ("system_revision", 2,
                                                                                             ids["confirmed"])
            with pytest.raises(ValueError, match="不可覆寫"):
                record_complaint_revision(s, case_id="v2", parent_id=ids["confirmed"], draft_text="y",
                                          citations_used=[], structured={})


# ---- P6 評估新鍵(純函數)----

class TestVerdictV2Problems:
    def check(self, rm):
        return verdict_v2_problems(rm, issue_ids=["I1", "I2"], fact_ids=["CF1", "CF2", "CF3"])

    def test_valid_risk_map_passes(self):
        assert self.check(risk_map()) == []

    def test_missing_keys_and_wrong_types(self):
        rm = risk_map()
        del rm["evidence_todo"]
        rm["fact_gaps"] = "一段文字"
        out = self.check(rm)
        assert any("evidence_todo" in m for m in out) and any("fact_gaps" in m for m in out)
        assert self.check([]) == ["risk_map 必須是 JSON 物件"]

    def test_issue_ids_must_exist_and_be_covered(self):
        rm = risk_map(issue_assessment=[{"issue_id": "I1", "strength": "很強", "reason": "x"},
                                        {"issue_id": "I1", "strength": "中", "reason": ""},
                                        {"issue_id": "I9", "strength": "弱", "reason": "x"}],
                      evidence_todo=[{"issue_id": "I8", "missing": "x", "why": "x"}])
        out = self.check(rm)
        for word in ("很強", "重複", "reason", "I9", "I8", "I2"):
            assert any(word in m for m in out), (word, out)

    def test_fact_ids_and_kinds(self):
        rm = risk_map(complaint_revisions=[{"fact_id": "CF9", "kind": "revise", "suggestion": "x"},
                                           {"fact_id": None, "kind": "revise", "suggestion": "x"},
                                           {"fact_id": "CF1", "kind": "rewrite", "suggestion": ""}])
        out = self.check(rm)
        for word in ("CF9", "revise", "rewrite", "suggestion"):
            assert any(word in m for m in out), (word, out)
        ok = risk_map(complaint_revisions=[{"fact_id": "CF3", "kind": "delete", "suggestion": "刪除不利陳述"},
                                           {"fact_id": None, "kind": "delete", "suggestion": "刪除理由段的推論"}])
        assert self.check(ok) == []


class TestWinProbabilityWarnings:  # T7.4(純函數)
    @pytest.mark.parametrize("text", ["原告勝訴機率約七成", "本案勝算不高", "勝訴率偏低", "原告有百分之六十的勝訴可能",
                                      "勝訴可能性約 70%", "被告敗訴機率高", "原告約有八成把握"])
    def test_hits(self, text):
        assert win_probability_warnings({"verdict_main_text": text})

    @pytest.mark.parametrize("text", ["爭點一:強", "按週年利率百分之五計算之利息", "利率 5% 計算", "原告舉證責任較重"])
    def test_ordinary_wording_passes(self, text):
        assert win_probability_warnings({"verdict_main_text": text}) == []

    def test_reports_where(self):
        out = win_probability_warnings({"verdict_main_text": "結論", "risk_map": {"issue_assessment": [
            {"issue_id": "I1", "strength": "強", "reason": "勝算高"}]}})
        assert len(out) == 1 and "勝算" in out[0] and "risk_map" in out[0]


# ---- P6 評估落地(CLI)----

def land_verdict(tmp_path, db_url, value, case_id="v2"):
    return run_main("verdict", "--case-id", case_id, "--json", write(tmp_path, value, "verdict.json"), db_url=db_url)


def stored_verdict(db_url, case_id="v2"):
    with get_session(db_url) as s:
        return s.query(Verdict).filter_by(case_id=case_id).one_or_none()


class TestVerdictCommand:
    def test_v2_with_issue_sheet_checks_new_keys(self, db_url, tmp_path):
        build_case(db_url, verdict_landed=False)
        bad = risk_map()
        del bad["issue_assessment"]
        r = land_verdict(tmp_path, db_url, verdict(bad))
        assert r.returncode == 1 and "issue_assessment" in r.stderr and "法官 subagent" in r.stderr
        assert stored_verdict(db_url) is None
        r = land_verdict(tmp_path, db_url, verdict())
        assert r.returncode == 0, r.stderr
        row = stored_verdict(db_url)
        assert row.protocol_version == "v2-pleading-exchange"
        assert json.loads(row.risk_map)["issue_assessment"][0]["issue_id"] == "I1"

    def test_v2_without_issue_sheet_is_not_blocked(self, db_url, tmp_path):
        build_case(db_url, sheet=False, verdict_landed=False)
        old_style = {"對原告不利之處": ["x"], "對被告不利之處": ["y"], "建議補強證據": ["z"]}
        r = land_verdict(tmp_path, db_url, verdict(old_style))
        assert r.returncode == 0, r.stderr
        assert stored_verdict(db_url).protocol_version == "v2-pleading-exchange"

    def test_win_probability_only_warns(self, db_url, tmp_path):  # T7.4
        build_case(db_url, verdict_landed=False)
        r = land_verdict(tmp_path, db_url, verdict(verdict_main_text="原告勝訴機率約七成。"))
        assert r.returncode == 0, r.stderr
        assert "警告" in r.stderr and "勝訴機率" in r.stderr
        assert stored_verdict(db_url) is not None

    def test_old_case_is_unchanged(self, db_url, tmp_path):  # T7.5
        import main
        with get_session(db_url) as s:
            record_case(s, case_id="old", case_type="消費借貸", facts_summary="借款未還", claims="返還借款")
        old_style = {"對原告不利之處": ["x"], "對被告不利之處": ["y"], "建議補強證據": ["z"]}
        r = land_verdict(tmp_path, db_url, verdict(old_style, verdict_main_text="原告勝訴機率約七成。"), case_id="old")
        assert r.returncode == 0 and r.stderr == ""
        assert stored_verdict(db_url, "old").protocol_version == main.PROTOCOL_VERSION


# ---- v1 與 v2 差異 ----

class TestComplaintDiff:
    OLD = "民事起訴狀\n一、事實\n(一)甲〔CF1〕\n(二)乙〔CF2〕\n此　致\n\n---\n【本稿產出說明】給律師,不是起訴狀正文\n- 事實缺口:舊\n"
    NEW = "民事起訴狀\n一、事實\n(一)甲〔CF1〕\n(二)乙改〔CF2〕\n(三)丙〔CF3〕\n此　致\n\n---\n【本稿產出說明】給律師\n- 事實缺口:新\n"

    def test_line_changes(self):
        out = complaint_diff(self.OLD, self.NEW)
        ops = [(d["op"], d["text"]) for d in out["lines"]]
        assert ("delete", "(二)乙〔CF2〕") in ops and ("insert", "(二)乙改〔CF2〕") in ops and ("insert", "(三)丙〔CF3〕") in ops
        assert ("equal", "(一)甲〔CF1〕") in ops and (out["added"], out["removed"]) == (2, 1)
        assert not any("本稿產出說明" in t or "事實缺口" in t or t == "---" for _, t in ops)

    def test_line_numbers(self):
        out = complaint_diff(self.OLD, self.NEW)
        insert = next(d for d in out["lines"] if d["text"] == "(三)丙〔CF3〕")
        delete = next(d for d in out["lines"] if d["op"] == "delete")
        assert (insert["old_no"], insert["new_no"]) == (None, 5) and (delete["old_no"], delete["new_no"]) == (4, None)

    def test_identical_and_empty(self):
        out = complaint_diff(self.OLD, self.OLD)
        assert (out["added"], out["removed"]) == (0, 0) and all(d["op"] == "equal" for d in out["lines"])
        assert complaint_diff("", "") == {"lines": [], "added": 0, "removed": 0}
