"""內部檢討段落:法官、對手摘要、書狀素材與自承檢查都不能讀到。"""
import json
import os
import subprocess
import sys

from database.db import (
    DB_URL_ENV, admission_sources, get_session, pleading_materials, public_arguments, record_argument, record_case,
)
from engine.admission_check import admission_problems
from engine.internal_review import END, START, review_warnings, strip_internal_review

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECRET = "這是本案最大弱點哨兵"
ARGUMENT = f"公開主張甲。{START}{SECRET}。{END}公開主張乙。"


def run_main(*args, db_url):
    env = {**os.environ, DB_URL_ENV: db_url, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, "main.py", *args], cwd=ROOT, env=env, capture_output=True,
                          encoding="utf-8", timeout=60)


class TestStrip:
    def test_removes_every_section(self):
        assert strip_internal_review(f"甲{START}x{END}乙{START}y{END}丙") == "甲乙丙"

    def test_unclosed_section_hides_the_rest(self):
        assert strip_internal_review(f"甲{START}x 還有後面") == "甲"

    def test_no_section_is_unchanged_and_none_is_empty(self):
        assert strip_internal_review("甲") == "甲"
        assert strip_internal_review(None) == ""


class TestWarnings:
    def test_clean_argument_has_no_warning(self):
        assert review_warnings(ARGUMENT) == []

    def test_unclosed_section_warns(self):
        assert "沒有成對" in review_warnings(f"甲{START}x")[0]

    def test_self_review_outside_the_section_warns(self):
        assert "弱點" in review_warnings("公開論證:這是我方弱點。")[0]

    def test_w0_public_self_review_warns(self):
        defendant = "被告承認,若原告於言詞辯論終結前補正出確定的數額與原因,A1 的力道會減弱,此為內部風險,不是承認。"
        plaintiff = "民法第184條第1項前段須故意過失,第2項須違反保護他人之法律且推定過失,逃漏稅捐相關規定是否為保護公司之法律,原告承認有疑義,故此一路徑列為最弱備位。"
        plaintiff_stage3 = "原告承認第184條第2項所指保護他人之法律是否包含稅捐稽徵規定本有疑義,且第197條第1項之二年期間自知有損害及賠償義務人時起算,起算時點、是否由原告公司知悉,以及被告是否確實援用,均待確認。"
        assert any("公開論證疑似含自我檢討" in w for w in review_warnings(defendant))
        assert any("公開論證疑似含自我檢討" in w for w in review_warnings(plaintiff))
        assert any("公開論證疑似含自我檢討" in w for w in review_warnings(plaintiff_stage3))

    def test_strategy_terms_alone_do_not_warn(self):
        assert review_warnings("故此一路徑列為備位。") == []
        assert review_warnings("原告將此一路徑列為最弱備位,並保留先位請求。") == []
        assert review_warnings("法律適用本有疑義，仍請法院審酌。") == []

    def test_new_terms_inside_review_section_do_not_warn(self):
        text = f"公開主張。{START}此為內部風險,A1 的力道會減弱,原告承認有疑義。{END}公開結論。"
        assert review_warnings(text) == []


def _landed_case(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'r.db'}"
    s = get_session(db_url)
    record_case(s, case_id="c1", case_type="買賣價金", facts_summary="事實", claims="請求")
    for side in ("plaintiff", "defendant"):
        for stage in (1, 2, 3):
            record_argument(s, case_id="c1", side=side, stage=stage, position=f"{side}{stage}", reasoning=ARGUMENT,
                            falsifier=None if stage == 1 else "讓步條件哨兵", cited_statutes=["民法第184條"])
    return db_url, s


class TestFlow:
    def test_case_api_marks_live_argument_with_review_warning_count(self, tmp_path):
        from fastapi.testclient import TestClient
        from database.schema import DebateArgument, LiveRun
        from server.app import create_app

        db_url, s = _landed_case(tmp_path)
        target = s.query(DebateArgument).filter_by(case_id="c1", side="defendant", stage=3).one()
        target.reasoning = "A1 的力道會減弱,此為內部風險,不是承認。"
        s.add(LiveRun(case_id="c1", status="succeeded", started_at="2000-01-01T00:00:00Z",
                      ended_at="2100-01-01T00:00:00Z"))
        s.commit()
        s.close()

        app = create_app(db_url=db_url, cases_dir=str(tmp_path / "none"), seed_on_empty=False)
        detail = TestClient(app).get("/api/cases/c1").json()
        marked = [a for a in detail["arguments"] if a["review_warning_count"]]
        assert len(marked) == 1
        assert marked[0]["review_warning_count"] == 1
        assert marked[0]["origin"]["kind"] == "live"

    def test_public_arguments_hide_review_and_falsifier(self, tmp_path):
        _, s = _landed_case(tmp_path)
        rows = public_arguments(s, case_id="c1")
        assert len(rows) == 6
        text = json.dumps(rows, ensure_ascii=False)
        assert SECRET not in text and START not in text and "讓步條件哨兵" not in text
        assert rows[0]["argument"] == "公開主張甲。公開主張乙。" and rows[0]["cited_statutes"] == ["民法第184條"]
        s.close()

    def test_through_stage_limits_what_is_returned(self, tmp_path):
        _, s = _landed_case(tmp_path)
        assert {r["stage"] for r in public_arguments(s, case_id="c1", through_stage=1)} == {1}
        assert {r["stage"] for r in public_arguments(s, case_id="c1", through_stage=2)} == {1, 2}
        s.close()

    def test_cli_prints_public_arguments(self, tmp_path):
        db_url, s = _landed_case(tmp_path)
        s.close()
        r = run_main("public-args", "--case-id", "c1", "--through-stage", "1", db_url=db_url)
        assert r.returncode == 0, r.stderr
        assert SECRET not in r.stdout and len(json.loads(r.stdout)["arguments"]) == 2

    def test_public_args_can_give_one_side_one_stage(self, tmp_path):  # P5 對手摘要只取對造 stage 2
        db_url, s = _landed_case(tmp_path)
        s.close()
        r = run_main("public-args", "--case-id", "c1", "--stage", "2", "--side", "defendant", db_url=db_url)
        assert r.returncode == 0, r.stderr
        assert [(a["side"], a["stage"]) for a in json.loads(r.stdout)["arguments"]] == [("defendant", 2)]
        r = run_main("public-args", "--case-id", "c1", "--through-stage", "2", "--side", "plaintiff", db_url=db_url)
        assert [(a["side"], a["stage"]) for a in json.loads(r.stdout)["arguments"]] == [("plaintiff", 1), ("plaintiff", 2)]

    def test_pleading_materials_hide_review(self, tmp_path):
        _, s = _landed_case(tmp_path)
        assert SECRET not in json.dumps(pleading_materials(s, case_id="c1", side="plaintiff"), ensure_ascii=False)
        s.close()

    def test_review_cannot_be_quoted_as_an_admission(self, tmp_path):
        _, s = _landed_case(tmp_path)
        sources = admission_sources(s, "c1")
        assert "不在該方論證" in admission_problems(f"被告自承「{SECRET}」。", sources)[0]
        assert admission_problems("被告自承「公開主張甲」。", sources) == []
        s.close()

    def test_full_text_stays_in_the_database_for_the_lawyer(self, tmp_path):
        from database.schema import DebateArgument
        _, s = _landed_case(tmp_path)
        assert SECRET in s.query(DebateArgument).filter_by(case_id="c1", side="plaintiff", stage=1).one().reasoning
        s.close()

    def test_landing_warns_when_self_review_is_outside_the_section(self, tmp_path):
        db_url = f"sqlite:///{tmp_path / 'w.db'}"
        s = get_session(db_url)
        record_case(s, case_id="c1", case_type="買賣價金", facts_summary="事實", claims="請求")
        s.close()
        arg = tmp_path / "a.json"
        arg.write_text(json.dumps({"case_id": "c1", "side": "defendant", "stage": 1, "position": "p",
                                   "argument": "這是我方弱點。"}, ensure_ascii=False), encoding="utf-8")
        r = run_main("record", "--json", str(arg), db_url=db_url)
        assert r.returncode == 0 and "法官會讀到" in r.stderr


class TestPleadingExchangeSources:
    """書狀交換流程(v2)的事實經過是原告律師寫的:只算原告的話。被告的話只有律師記下的對方已知反應。"""

    def _sources(self, tmp_path):
        s = get_session(f"sqlite:///{tmp_path / 'v2.db'}")
        record_case(s, case_id="v2", case_type="返還借款", facts_summary="原告於112年3月1日匯款100萬元予被告。",
                    claims="返還借款", protocol="v2", represented_side="plaintiff",
                    opponent_responses=[{"source": "LINE", "text": "被告回覆那筆錢是你送我的生日禮物"}])
        sources = admission_sources(s, "v2")
        s.close()
        return sources

    def test_facts_summary_is_not_the_defendants_word(self, tmp_path):
        problems = admission_problems("被告自承「原告於112年3月1日匯款100萬元予被告」。", self._sources(tmp_path))
        assert len(problems) == 1 and "不在該方論證" in problems[0]

    def test_known_response_is_the_defendants_word(self, tmp_path):
        assert admission_problems("被告自承「那筆錢是你送我的生日禮物」。", self._sources(tmp_path)) == []

    def test_facts_summary_is_the_plaintiffs_word(self, tmp_path):
        assert admission_problems("原告自陳「原告於112年3月1日匯款100萬元予被告」。", self._sources(tmp_path)) == []
