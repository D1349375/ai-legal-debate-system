"""書狀字樣檢查：模擬流程用語只警告、不阻擋，也不檢查系統補充說明。"""
import json
import os
import subprocess
import sys

from database.db import DB_URL_ENV, get_session, record_case
from database.schema import PleadingDraft
from server.pleading_export import lint_pleading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_plaintiff_flags_opponent_and_flow_words():
    assert lint_pleading("民事起訴狀\n被告主張已清償。本段取自 Stage 3,stage3 亦同。對造未回應。") == [
        {"word": "被告主張", "count": 1}, {"word": "Stage", "count": 2}, {"word": "對造", "count": 1}]


def test_defendant_may_write_plaintiff_contention_but_not_flow_words():
    assert lint_pleading("民事答辯狀\n原告主張要旨:給付價金。被告主張時效。", "defendant") == []
    assert lint_pleading("(被告 Stage 3 未表示意見,待律師補充)", "defendant") == [{"word": "Stage", "count": 1}]


def test_note_section_is_not_checked():
    assert lint_pleading("民事起訴狀\n訴之聲明\n【骨架版聲明】本稿取自 Stage 3") == []


def test_clean_draft_has_no_warning():
    assert lint_pleading("民事起訴狀\n訴之聲明\n一、被告應給付原告50萬元。") == []


def test_cli_warns_but_still_lands(tmp_path):
    url = f"sqlite:///{tmp_path / 'p.db'}"
    session = get_session(url)
    record_case(session, case_id="c1", case_type="消費借貸", facts_summary="借款未還", claims="返還借款")
    draft = tmp_path / "d.txt"
    draft.write_text("民事起訴狀\n被告主張已清償,見存證信函。", encoding="utf-8")
    citations = tmp_path / "c.json"
    citations.write_text(json.dumps([]), encoding="utf-8")
    env = {**os.environ, DB_URL_ENV: url, "PYTHONIOENCODING": "utf-8"}
    done = subprocess.run([sys.executable, "main.py", "pleading", "--case-id", "c1", "--draft-file", str(draft),
                           "--citations", str(citations)], cwd=ROOT, env=env, capture_output=True,
                          text=True, encoding="utf-8")
    assert done.returncode == 0 and "被告主張×1" in done.stderr
    session.expire_all()
    assert session.query(PleadingDraft).filter_by(case_id="c1").count() == 1
