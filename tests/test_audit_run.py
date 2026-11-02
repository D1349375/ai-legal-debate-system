"""scripts/audit_run.py:從 stream.jsonl 列出每個 agent 碰過哪些檔，檢查被告隔離與來源裁判。"""
import importlib.util
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "audit_run.py")
_spec = importlib.util.spec_from_file_location("audit_run", SCRIPT)
audit_run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audit_run)

CWD = "C:\\work\\LegalDebate"


def _tool(name, tool_input, tool_id, parent=None):
    return {"type": "assistant", "parent_tool_use_id": parent,
            "message": {"content": [{"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}]}}


def _events():
    return [
        {"type": "system", "subtype": "init", "cwd": CWD, "session_id": "s1"},
        _tool("Read", {"file_path": CWD + "\\.claude\\skills\\legal-debate\\SKILL.md"}, "m1"),
        _tool("Agent", {"description": "原告分析", "subagent_type": "general-purpose",
                        "prompt": "讀 database/live_runs/run-9/plaintiff_view.json"}, "A1"),
        _tool("Read", {"file_path": CWD + "\\database\\live_runs\\run-9\\case.json"}, "p1", parent="A1"),
        _tool("Agent", {"description": "被告防禦分析", "prompt": "讀 database/live_runs/run-9/defendant_view.json"}, "A2"),
        _tool("Read", {"file_path": CWD + "\\database\\live_runs\\run-9\\defendant_view.json"}, "d1", parent="A2"),
        _tool("Grep", {"pattern": "借款", "path": CWD + "\\database\\live_runs\\run-9"}, "d2", parent="A2"),
        _tool("Bash", {"command": "python main.py judgment 114 台上 1987"}, "d3", parent="A2"),
        _tool("PowerShell", {"command": "Get-Content case.json"}, "d4", parent="A2"),
        {"type": "system", "subtype": "permission_denied", "tool_name": "PowerShell", "tool_use_id": "d4"},
        _tool("Write", {"file_path": CWD + "\\database\\live_runs\\run-9\\answer.json", "content": "{}"}, "m2"),
        # 續跑:同一個檔裡的第二個 session
        {"type": "system", "subtype": "init", "cwd": CWD, "session_id": "s2"},
        _tool("Agent", {"description": "被告答辯狀撰狀", "prompt": "案件事實:原告於112年3月1日匯款100萬元"}, "A3"),
        _tool("Read", {"file_path": "database/live_runs/run-9/answer_prompt.txt"}, "w1", parent="A3"),
    ]


def _agent(report, name):
    return next(a for a in report["agents"] if a["name"] == name)


def test_lists_each_agent_with_relative_paths():
    report = audit_run.audit(_events())
    assert [a["name"] for a in report["agents"]] == ["主 agent", "原告分析", "被告防禦分析", "被告答辯狀撰狀"]
    main = _agent(report, "主 agent")
    assert main["reads"] == [".claude/skills/legal-debate/SKILL.md"]
    assert main["writes"] == ["database/live_runs/run-9/answer.json"]
    defendant = _agent(report, "被告防禦分析")
    assert defendant["reads"] == ["database/live_runs/run-9/defendant_view.json"]
    assert defendant["searches"] == ["Grep 借款 @ database/live_runs/run-9"]
    assert defendant["commands"] == ["python main.py judgment 114 台上 1987", "PowerShell: Get-Content case.json"]
    assert defendant["tool_counts"] == {"Read": 1, "Grep": 1, "Bash": 1, "PowerShell": 1}
    assert defendant["denied"] == 1
    assert _agent(report, "被告答辯狀撰狀")["reads"] == ["database/live_runs/run-9/answer_prompt.txt"]
    assert CWD not in json.dumps(report, ensure_ascii=False)


def test_the_working_folder_itself_is_not_printed():
    events = [{"type": "system", "subtype": "init", "cwd": CWD},
              _tool("Glob", {"pattern": "corpus/*", "path": CWD}, "g1"),
              _tool("Bash", {"command": f'cd "{CWD}" && python main.py verify 民法第184條'}, "b1"),
              _tool("Agent", {"description": "查證", "prompt": "第一行\n第二行 case.json 第三行"}, "A9")]
    report = audit_run.audit(events, forbid=["case.json"])
    main = _agent(report, "主 agent")
    assert main["searches"] == ["Glob corpus/* @ ."]
    assert main["commands"] == ['cd "." && python main.py verify 民法第184條']
    assert "\n" not in report["violations"][0]["input"]
    assert "work" not in json.dumps(report, ensure_ascii=False)


def test_home_folders_outside_the_working_folder_are_masked():
    # Claude Code 把過長的工具結果存到使用者家目錄，subagent 會回頭 Grep 那個檔
    events = [{"type": "system", "subtype": "init", "cwd": CWD},
              _tool("Grep", {"pattern": "status", "path": "C:\\Users\\someone\\.claude\\projects\\C--Users-someone-repo\\s1\\tool-results\\a.txt"}, "g1"),
              _tool("Read", {"file_path": "/home/someone/notes.txt"}, "r1")]
    main = _agent(audit_run.audit(events), "主 agent")
    assert main["searches"] == ["Grep status @ ~/.claude/projects/<專案>/s1/tool-results/a.txt"]
    assert main["reads"] == ["~/notes.txt"]


def test_forbid_only_checks_the_named_agents():
    report = audit_run.audit(_events(), forbid=["case.json"], agent_filter="被告")
    # 原告分析讀 case.json 不算;被告的 PowerShell 指令提到 case.json 算(雖然被拒，仍是嘗試)
    assert report["violations"] == [{"agent": "被告防禦分析", "tool": "PowerShell",
                                     "input": "Get-Content case.json"}]


def test_forbid_also_checks_the_dispatch_prompt():
    report = audit_run.audit(_events(), forbid=["100萬元", "1987"], agent_filter="被告")
    assert {(v["agent"], v["tool"]) for v in report["violations"]} == {
        ("被告防禦分析", "Bash"), ("被告答辯狀撰狀", "派工 prompt")}


def test_without_forbid_there_are_no_violations():
    assert audit_run.audit(_events())["violations"] == []


def _run(*args):
    return subprocess.run([sys.executable, SCRIPT, *args], cwd=ROOT, capture_output=True, encoding="utf-8",
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=60)


def test_cli_reads_a_run_folder_and_sets_the_exit_code(tmp_path):
    (tmp_path / "stream.jsonl").write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in _events()) + "\n",
                                          encoding="utf-8")
    clean = _run(str(tmp_path), "--agent", "被告", "--forbid", "plaintiff_view")
    assert clean.returncode == 0, clean.stderr
    assert "被告防禦分析" in clean.stdout and "defendant_view.json" in clean.stdout
    hit = _run(str(tmp_path / "stream.jsonl"), "--json", "--agent", "被告", "--forbid", "case.json")
    assert hit.returncode == 1
    assert json.loads(hit.stdout)["violations"][0]["agent"] == "被告防禦分析"


def test_cli_rejects_a_missing_stream(tmp_path):
    r = _run(str(tmp_path))
    assert r.returncode == 2 and "stream.jsonl" in r.stderr


def test_real_run_four_shows_the_old_flow_reading_case_json():
    # 舊流程 run-4:原告 Stage 1 subagent 讀了 case.json(當時允許)。拿來確認真實格式解析得出來
    report = audit_run.audit(audit_run.load_events(os.path.join(ROOT, "docs", "live-run-records", "run-4")),
                             forbid=["case.json"])
    agents = {a["name"] for a in report["agents"]}
    assert "主 agent" in agents and len(agents) > 5
    assert any("Stage 1" in v["agent"] for v in report["violations"])
    assert "Users" not in json.dumps([a["reads"] for a in report["agents"]], ensure_ascii=False)
