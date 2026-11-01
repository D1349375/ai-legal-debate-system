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
