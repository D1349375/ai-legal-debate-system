"""T7 合併 main-finals-fixes 後不會出現衝突標記、但要一起改的地方(審查 T7-1、T7-4/A6)。"""
import os

from server import live_run

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEGACY = os.path.join(ROOT, ".claude", "skills", "legal-debate", "references", "legacy-v1.md")
SKILL = os.path.join(ROOT, ".claude", "skills", "legal-debate", "SKILL.md")
BASH_RULE = "指令一律用 Bash 工具執行 `python main.py ...`"


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_v2_prompt_also_says_to_use_the_bash_tool():  # T7-4、A6:T5 原本只改了 v1 的 prompt
    for stop_after in (None, "complaint"):
        p = live_run.build_prompt("c1", "database/live_runs/run-9", protocol="v2", stop_after=stop_after)
        assert BASH_RULE in p and "不要用迴圈或複合指令" in p and "派 subagent 時" in p
        assert "指令只能用 `python main.py ...`" not in p


def test_legacy_runbook_carries_the_t2_t5_t10_changes():  # T7-1:舊流程段落已搬到 legacy-v1.md
    text = read(LEGACY)
    assert "只供核對，不用抄進 verdict JSON" in text
    assert "`mechanical_anchor_json`/`citations_used`)" not in text  # 不再叫主 agent 把機械彙整抄進 verdict JSON
    assert "不需 `mechanical_anchor_json`" in text
    assert "用 Bash 工具執行,一個 `verify` 指令列出全部引用" in text
    assert "轉述待核對警告" in text and "`check-judge` 的轉述警告不退回法官" in text


def test_v2_runbook_verify_and_report_lines():
    text = read(SKILL)
    assert "用 Bash 工具執行,一個 `verify` 指令列出全部引用" in text
    assert "`issue-sheet` 印出的「轉述警告」" in text
