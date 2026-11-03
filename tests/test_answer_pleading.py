"""W4 後半:模擬答辯狀的結構檢查、程式組成正文(T4.6)與 main.py answer 落地。不連網。"""
import json
import os
import subprocess
import sys

import pytest

from database.db import (DB_URL_ENV, get_session, record_argument, record_case, record_gate, record_pleading,
                         record_pleading_edit, upsert_citation)
from database.schema import PleadingDraft
from engine import pleading_render
from engine.pleading_render import answer_problems, render_answer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPLAINT_TEXT = ("民事起訴狀\n訴之聲明\n一、被告應給付原告新臺幣100萬元。\n二、訴訟費用由被告負擔。\n\n事實及理由\n一、事實\n"
                  "(一)原告於112年3月1日匯款100萬元至被告帳戶。〔CF1〕\n(二)兩造約定三個月內返還。〔CF2〕\n")
FACT_EVIDENCE = {"CF1": ["甲證1"], "CF2": []}
EVIDENCE = [{"id": "甲證1", "type": "書證", "date": None, "description": "匯款單"}]


def answer(**over):
    payload = {
        "responses": [
            {"fact_id": "CF1", "stance": "admit", "ground": None, "reason": None, "hypothetical": False},
            {"fact_id": "CF2", "stance": "deny", "ground": "insufficient_proof",
             "reason": "匯款僅證明交付,不足以證明借貸合意", "hypothetical": False},
        ],
        "defenses": [{"type": "payment", "statement": "若被告能提出清償紀錄,主張已清償",
                      "legal_basis": ["民法第309條"], "hypothetical": True}],
        "legal_argument": "原告未證明兩造有借貸合意,請求無理由。",
        "citations": ["民法第309條"],
        "to_confirm": ["是否另有代墊款紀錄"],
    }
    payload.update(over)
    return payload


def problems(payload, text=COMPLAINT_TEXT):
    return answer_problems(payload, complaint_text=text, fact_evidence=FACT_EVIDENCE)


class TestAnswerProblems:
    def test_valid_answer_passes(self):
        assert problems(answer()) == []

    def test_stances_are_checked_against_the_complaint(self):  # T4.1 經由 answer_problems
        out = problems(answer(responses=answer()["responses"][:1]))
        assert out == ["CF2 沒有表態"]

    def test_defenses_need_a_statement_statute_basis_and_flag(self):
        bad = [{"type": "", "statement": " ", "legal_basis": ["清償"], "hypothetical": "yes"}]
        out = problems(answer(defenses=bad))
        assert any("type" in m for m in out) and any("statement" in m for m in out)
        assert any("legal_basis" in m and "清償" in m for m in out) and any("hypothetical" in m for m in out)
        assert problems(answer(defenses=[])) == []

    def test_text_fields_and_lists(self):
        out = problems(answer(legal_argument=" ", citations="民法第309條", to_confirm=[1]))
        assert any("legal_argument" in m for m in out) and any("citations" in m for m in out)
        assert any("to_confirm" in m for m in out)
        assert problems([]) == ["答辯狀輸出必須是 JSON 物件"]

    def test_judgments_need_precedent_notes(self):
        out = problems(answer(citations=["民法第309條", "最高法院110年度台上字第839號民事判決"]))
        assert any("precedent_notes" in m and "839" in m for m in out)


class TestRenderAnswer:
    def render(self, payload=None, text=COMPLAINT_TEXT):
        case = {"parties": {"plaintiff": {"name": "甲"}, "defendant": {"name": "乙"}}, "claim_amount": 1000000}
        return render_answer(payload or answer(), case=case, party_checks={}, procedural=None, complaint_text=text)

    def test_title_marks_it_simulated(self):  # T4.6
        assert self.render().splitlines()[0] == "民事答辯狀(模擬答辯,非針對實際起訴狀)"

    def test_prayers_follow_whether_the_complaint_asks_for_provisional_execution(self):
        lines = self.render().splitlines()
        start = lines.index("答辯聲明")
        assert lines[start + 1:start + 4] == ["一、駁回原告之訴。", "二、訴訟費用由原告負擔。",
                                              "三、如受不利之判決,願供擔保請准宣告免為假執行。"]
        with_execution = COMPLAINT_TEXT.replace("二、訴訟費用由被告負擔。", "二、願供擔保,請准宣告假執行。")
        assert "一、駁回原告之訴及其假執行之聲請。" in self.render(text=with_execution)

    def test_each_fact_point_gets_its_stance(self):
        text = self.render()
        assert "原告主張「原告於112年3月1日匯款100萬元至被告帳戶。」〔CF1〕:不爭執。" in text
        assert "原告主張「兩造約定三個月內返還。」〔CF2〕:否認。原告舉證不足:匯款僅證明交付,不足以證明借貸合意" in text
        assert "若被告能提出清償紀錄,主張已清償(推測;依據:民法第309條)" in text

    def test_alternative_explanation_is_marked_as_a_guess(self):
        responses = answer()["responses"]
        responses[1] = {**responses[1], "ground": "alternative_explanation", "hypothetical": True,
                        "reason": "該款可能是贈與"}
        assert "另一可能解釋(推測):該款可能是贈與" in self.render(answer(responses=responses))

    def test_open_questions_go_to_the_note_not_the_body(self):
        body, note = self.render().split("【本稿產出說明】")
        assert "代墊款" not in body and "待被告本人確認:是否另有代墊款紀錄" in note
        assert "第三項" in note and "律師" in note
        assert "被證" not in body and "模擬答辯未附證物" in body


@pytest.fixture
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path / 'answer.db'}"
    s = get_session(url)
    case = record_case(s, case_id="v2", case_type="返還借款", facts_summary="兩造約定三個月內返還。", claims="返還借款",
                       parties={"plaintiff": {"name": "甲"}, "defendant": {"name": "乙"}}, protocol="v2",
                       represented_side="plaintiff",
                       evidence=[{"id": "甲證1", "type": "書證", "description": "匯款單"},
                                 {"id": "甲證2", "type": "照片", "description": "交付現場照片"}])
    record_argument(s, case_id="v2", side="plaintiff", stage=1, position="返還借款", reasoning="依民法第478條請求。")
    complaint = {
        "cause": "返還借款", "prayers": ["被告應給付原告新臺幣100萬元。", "訴訟費用由被告負擔。"],
        "claim_basis": [{"seq": 1, "role": "primary", "basis": ["民法第478條"], "prayer": "訴之聲明第一項"}],
        "fact_points": [
            {"id": "CF1", "text": "原告於112年3月1日匯款100萬元至被告帳戶。", "evidence_ids": ["甲證1"], "statement_quote": None},
            {"id": "CF2", "text": "兩造約定三個月內返還。", "evidence_ids": [], "statement_quote": "三個月內返還"},
            {"id": "CF3", "text": "原告交付現金時有拍照。", "evidence_ids": ["甲證2"], "statement_quote": None},
        ],
        "legal_argument": "依民法第478條請求返還。", "procedural_statements": [], "basis": ["民法第478條"],
        "citations": [], "precedent_notes": [], "fact_gaps": [], "lawyer_notes": [],
    }
    view_case = {"parties": json.loads(case.parties_json), "claim_amount": None, "evidence": json.loads(case.evidence_json)}
    text = pleading_render.render_complaint(complaint, case=view_case, party_checks={}, procedural=[])
    record_pleading(s, case_id="v2", draft_text=text, citations_used=[], pleading_type="complaint", round=1,
                    structured=pleading_render.stored_complaint(complaint))
    record_argument(s, case_id="v2", side="defendant", stage=1, position="否認借貸", reasoning="匯款不等於借貸。")
    upsert_citation(s, citation_text="民法第309條", source_type="statute", status="published",
                    primary_source_url="https://law.moj.gov.tw/x")
    s.close()
    return url


def full_answer(**over):
    responses = answer()["responses"] + [{"fact_id": "CF3", "stance": "to_confirm", "ground": None,
                                          "reason": "需被告本人說明", "hypothetical": False}]
    return answer(responses=responses, **over)


def run(db_url, tmp_path, payload, *extra):
    path = tmp_path / "answer.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    env = {**os.environ, DB_URL_ENV: db_url, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, "main.py", "answer", "--case-id", "v2", "--json", str(path), *extra],
                          cwd=ROOT, env=env, capture_output=True, encoding="utf-8", timeout=60)


def answers(db_url):
    s = get_session(db_url)
    rows = s.query(PleadingDraft).filter_by(case_id="v2", pleading_type="answer").all()
    s.close()
    return rows


class TestAnswerCommand:
    def test_check_prints_the_text_and_lands_nothing(self, db_url, tmp_path):
        r = run(db_url, tmp_path, full_answer(), "--check")
        assert r.returncode == 0, r.stderr
        assert "民事答辯狀(模擬答辯" in r.stdout and "民法第309條" in r.stdout
        assert answers(db_url) == []

    def test_lands_once_as_a_simulated_answer(self, db_url, tmp_path):
        r = run(db_url, tmp_path, full_answer())
        assert r.returncode == 0, r.stderr
        [row] = answers(db_url)
        assert (row.side, row.round, row.is_simulated) == ("defendant", 1, 1)
        stored = json.loads(row.structured_json)
        assert [x["fact_id"] for x in stored["responses"]] == ["CF1", "CF2", "CF3"]
        assert stored["complaint_id"] > 0
        again = run(db_url, tmp_path, full_answer())
        assert again.returncode == 1 and "不可覆寫" in again.stderr

    def test_missing_stance_is_sent_back(self, db_url, tmp_path):
        r = run(db_url, tmp_path, answer(), "--check")
        assert r.returncode == 1 and "CF3 沒有表態" in r.stderr and "撰狀 subagent" in r.stderr

    def test_needs_the_defense_analysis_first(self, db_url, tmp_path):
        s = get_session(db_url)
        from database.schema import DebateArgument
        s.query(DebateArgument).filter_by(case_id="v2", side="defendant").delete()
        s.commit()
        s.close()
        r = run(db_url, tmp_path, full_answer(), "--check")
        assert r.returncode == 1 and "防禦分析" in r.stderr

    def test_unpublished_citation_is_refused(self, db_url, tmp_path):
        r = run(db_url, tmp_path, full_answer(citations=["民法第309條", "民法第334條"],
                                              legal_argument="依民法第334條主張抵銷。"))
        assert r.returncode == 1 and "民法第334條" in r.stderr
        assert answers(db_url) == []

    def test_judgment_in_a_stance_reason_must_be_listed(self, db_url, tmp_path):  # 表態理由是被告的話,判決也要查證
        payload = full_answer()
        payload["responses"][1]["reason"] = "依最高法院112年度台上字第100號判決,匯款不足以證明借貸合意"
        r = run(db_url, tmp_path, payload, "--check")
        assert r.returncode == 1 and "最高法院112年度台上字第100號" in r.stderr and "citations" in r.stderr

    def test_answers_the_version_the_lawyer_confirmed(self, db_url, tmp_path):  # T4.2 接上關卡 1
        s = get_session(db_url)
        system = s.query(PleadingDraft).filter_by(case_id="v2", pleading_type="complaint").one()
        edited = system.draft_text.replace("(三)原告交付現金時有拍照。〔CF3〕", "(三)被告曾以LINE承認借款。〔CF4〕")
        row = record_pleading_edit(s, case_id="v2", parent_id=system.id, draft_text=edited, citation_check=[])
        record_gate(s, case_id="v2", gate="complaint", version_id=row.id, action="continue", by="ui")
        edited_id = row.id
        s.close()
        assert "CF4 沒有表態" in run(db_url, tmp_path, full_answer(), "--check").stderr
        responses = answer()["responses"] + [{"fact_id": "CF4", "stance": "to_confirm", "ground": None,
                                              "reason": "需被告本人確認 LINE 對話", "hypothetical": False}]
        r = run(db_url, tmp_path, answer(responses=responses))
        assert r.returncode == 0, r.stderr
        assert json.loads(answers(db_url)[0].structured_json)["complaint_id"] == edited_id

    def test_authenticity_on_a_photo_only_warns(self, db_url, tmp_path):
        responses = answer()["responses"] + [{"fact_id": "CF3", "stance": "authenticity", "ground": None,
                                              "reason": "照片拍攝者與時間不明", "hypothetical": False}]
        r = run(db_url, tmp_path, answer(responses=responses), "--check")
        assert r.returncode == 0, r.stderr
        assert "警告" in r.stdout and "CF3" in r.stdout and "照片" in r.stdout
