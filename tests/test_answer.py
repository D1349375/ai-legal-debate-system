"""W4 被告角色檔與逐點表態檢查(T4.1–T4.5)。T4.2 只驗「以傳入的正文為準」,關卡 1 確認版的對接待 W3。不連網。"""
import json
import os
import subprocess
import sys

import pytest

from database.db import DB_URL_ENV, defendant_view, get_session, record_argument, record_case, record_pleading, \
    record_pleading_edit
from engine import pleading_render
from engine.fact_points import response_problems

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXT = "一、事實\n(一)原告於112年3月1日匯款100萬元至被告帳戶。〔CF1〕\n(二)兩造約定三個月內返還。〔CF2〕\n"
FACT_EVIDENCE = {"CF1": ["甲證1"], "CF2": []}
# 哨兵字串:只放在被告不該看到的地方
SENTINELS = ("哨兵事實經過", "哨兵已知缺口", "哨兵內部檢討", "哨兵未列證據", "哨兵證明目的", "哨兵事實缺口", "哨兵律師附註")


def resp(cf, stance="deny", **over):
    return {"fact_id": cf, "stance": stance, "ground": None, "reason": "匯款僅證明交付", "hypothetical": False, **over}


def problems(responses, text=TEXT, fact_evidence=FACT_EVIDENCE):
    return response_problems(responses, complaint_text=text, fact_evidence=fact_evidence)


class TestResponses:
    def test_every_cf_once_passes(self):
        assert problems([resp("CF1", "admit", reason=None), resp("CF2")]) == []

    def test_missing_or_duplicate_cf_is_refused(self):  # T4.1
        out = problems([resp("CF1")])
        assert len(out) == 1 and "CF2" in out[0]
        out = problems([resp("CF1"), resp("CF2"), resp("CF2", "to_confirm")])
        assert len(out) == 1 and "CF2" in out[0] and "重複" in out[0]

    def test_cf_list_follows_the_text_passed_in(self):  # T4.2(以傳入的正文為準)
        edited = "(一)原告於112年3月1日匯款100萬元至被告帳戶。〔CF1〕\n(二)被告曾承認借款。〔CF3〕\n"
        out = problems([resp("CF1"), resp("CF2")], text=edited, fact_evidence={"CF1": ["甲證1"], "CF3": []})
        assert any("CF3" in m for m in out) and any("CF2" in m and "正文" in m for m in out)

    def test_admit_needs_evidence(self):  # T4.3
        out = problems([resp("CF1"), resp("CF2", "admit", reason=None)])
        assert len(out) == 1 and "CF2" in out[0] and "admit" in out[0]

    def test_alternative_explanation_must_be_hypothetical(self):  # T4.4
        out = problems([resp("CF1"), resp("CF2", ground="alternative_explanation")])
        assert len(out) == 1 and "CF2" in out[0] and "hypothetical" in out[0]
        assert problems([resp("CF1"), resp("CF2", ground="alternative_explanation", hypothetical=True)]) == []

    def test_reason_required_and_values_checked(self):
        for stance in ("deny", "authenticity", "to_confirm"):
            out = problems([resp("CF1"), resp("CF2", stance, reason=" ")])
            assert len(out) == 1 and "CF2" in out[0] and "reason" in out[0]
        assert any("stance" in m for m in problems([resp("CF1"), resp("CF2", "partial")]))
        assert any("ground" in m for m in problems([resp("CF1"), resp("CF2", ground="guess")]))
        assert problems("x") == ["responses 必須是陣列"]


def complaint_payload():
    return {
        "cause": "返還借款", "prayers": ["被告應給付原告新臺幣100萬元。", "訴訟費用由被告負擔。"],
        "claim_basis": [{"seq": 1, "role": "primary", "basis": ["民法第478條"], "prayer": "訴之聲明第一項"}],
        "fact_points": [
            {"id": "CF1", "text": "原告於112年3月1日匯款100萬元至被告帳戶。", "evidence_ids": ["甲證1"], "statement_quote": None},
            {"id": "CF2", "text": "兩造約定三個月內返還。", "evidence_ids": [], "statement_quote": "三個月內返還"},
        ],
        "legal_argument": "兩造成立消費借貸,依民法第478條請求返還。", "procedural_statements": [],
        "basis": ["民法第478條"], "citations": [], "precedent_notes": [],
        "fact_gaps": ["哨兵事實缺口"], "lawyer_notes": ["哨兵律師附註"],
    }


@pytest.fixture
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path / 'answer.db'}"
    s = get_session(url)
    case = record_case(s, case_id="v2", case_type="返還借款", facts_summary="兩造約定三個月內返還。哨兵事實經過",
                       claims="返還借款", parties={"plaintiff": {"name": "甲"}, "defendant": {"name": "乙"}},
                       protocol="v2", represented_side="plaintiff", known_gaps=["哨兵已知缺口"],
                       evidence=[{"id": "甲證1", "type": "書證", "description": "匯款單", "proves": "哨兵證明目的"},
                                 {"id": "甲證2", "type": "書證", "description": "哨兵未列證據"}],
                       opponent_responses=[{"source": "LINE", "text": "那是贈與"}])
    record_argument(s, case_id="v2", side="plaintiff", stage=1, position="返還借款",
                    reasoning="依民法第478條請求。\n【內部檢討】哨兵內部檢討")
    payload = complaint_payload()
    view_case = {"parties": json.loads(case.parties_json), "claim_amount": None,
                 "evidence": json.loads(case.evidence_json)}
    text = pleading_render.render_complaint(payload, case=view_case, party_checks={}, procedural=[])
    record_pleading(s, case_id="v2", draft_text=text, citations_used=[], pleading_type="complaint", round=1,
                    structured=pleading_render.stored_complaint(payload))
    s.close()
    return url


class TestDefendantView:
    def test_view_holds_only_the_complaint_side(self, db_url):  # T4.5
        view = defendant_view(get_session(db_url), "v2")
        dumped = json.dumps(view, ensure_ascii=False)
        assert [s for s in SENTINELS if s in dumped] == []
        assert "〔CF1〕" in view["complaint"]["text"] and "本稿產出說明" not in view["complaint"]["text"]
        assert view["fact_evidence"] == FACT_EVIDENCE
        assert [e["id"] for e in view["evidence"]] == ["甲證1"] and view["evidence"][0]["description"] == "匯款單"
        assert view["opponent_known_responses"][0]["text"] == "那是贈與"
        assert {"party_checks", "procedural_issues"} <= set(view)

    def test_lawyer_version_decides_the_cfs(self, db_url):  # T4.2(以傳入的版本為準)
        s = get_session(db_url)
        system = defendant_view(s, "v2")["complaint"]
        edited = system["text"].replace("〔CF1〕", "").replace("(二)兩造約定", "(二)被告曾承認借款。〔CF3〕\n(三)兩造約定")
        row = record_pleading_edit(s, case_id="v2", parent_id=system["id"], draft_text=edited, citation_check=[])
        view = defendant_view(s, "v2", complaint_id=row.id)
        assert view["complaint"]["id"] == row.id and "被告曾承認借款" in view["complaint"]["text"]
        assert view["fact_evidence"] == {"CF3": [], "CF2": []} and view["evidence"] == []

    def test_cli_writes_the_defendant_view(self, db_url, tmp_path):
        out = tmp_path / "defendant_view.json"
        env = {**os.environ, DB_URL_ENV: db_url, "PYTHONIOENCODING": "utf-8"}
        r = subprocess.run([sys.executable, "main.py", "role-view", "--case-id", "v2", "--role", "defendant",
                            "--out", str(out)], cwd=ROOT, env=env, capture_output=True, encoding="utf-8", timeout=60)
        assert r.returncode == 0, r.stderr
        assert json.loads(out.read_text(encoding="utf-8"))["role"] == "defendant"

    def test_no_complaint_yet_is_an_error(self, tmp_path):
        s = get_session(f"sqlite:///{tmp_path / 'empty.db'}")
        record_case(s, case_id="v2", case_type="返還借款", facts_summary="x", claims="x", protocol="v2",
                    represented_side="plaintiff")
        with pytest.raises(ValueError, match="起訴狀"):
            defendant_view(s, "v2")
