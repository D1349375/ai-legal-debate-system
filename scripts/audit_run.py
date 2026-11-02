"""
實跑稽核：從即時執行的 stream.jsonl 列出主 agent 與每個 subagent 碰過哪些檔(W4、W8 的 X8)。

被告隔離靠提示與調度，程式擋不住 subagent 去讀 case.json;只能事後看紀錄。這支程式只讀紀錄，
不判斷內容：列出讀過、搜尋過、寫過的檔與執行過的指令，並可檢查指定的 agent 有沒有碰到某段字串。

用法:

    python scripts/audit_run.py <執行資料夾或 stream.jsonl> [--json] [--agent <名稱片段>] [--forbid <字串>] ...

- subagent 的名稱取主 agent 派工時 Agent 工具的 description;主 agent 叫「主 agent」。
- --forbid 可重複，比對工具輸入(路徑、搜尋樣式、指令)與派工 prompt 是否含這段字串;
  --agent 只檢查名稱含這段字的 agent。有命中時結束碼 1,沒有命中 0,讀不到紀錄 2。
- 在該次 cwd 底下的路徑一律轉成相對路徑，結果可以貼進公開 repo 的紀錄。

看不到的事：稽核只看工具呼叫的輸入。模型讀到什麼內容、主 agent 有沒有把檔案內容抄進派工 prompt,
只有派工 prompt 這一處查得到(--forbid 會一併比對);工具結果的內容不檢查。
"""
import argparse
import json
import os
import re
import sys

MAIN = "主 agent"
_HOME_RE = re.compile(r"(?:[A-Za-z]:)?/(?:Users|home)/[^/\s\"']+/", re.IGNORECASE)
_PROJECT_DIR_RE = re.compile(r"~/\.claude/projects/[^/\s\"']+/")
_AGENT_TOOLS = ("Agent", "Task")
_READ_TOOLS = ("Read",)
_WRITE_TOOLS = ("Write", "Edit", "NotebookEdit")
_SEARCH_TOOLS = ("Grep", "Glob")
_SHELL_TOOLS = ("Bash", "PowerShell")


def load_events(path):
    """→ 事件 list。path 可以是執行資料夾(讀其中的 stream.jsonl)或檔案本身;無法解析的行略過。"""
    if os.path.isdir(path):
        path = os.path.join(path, "stream.jsonl")
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # 中止的執行最後一行可能不完整
    return events


def _relative(text, cwd):
    """把 cwd 底下的絕對路徑改成相對路徑(cwd 本身寫成 .),其他家目錄寫成 ~/,斜線統一成 /。"""
    text = text.replace("\\", "/")
    if cwd:
        root = cwd.replace("\\", "/").rstrip("/")
        for target, replacement in ((root + "/", ""), (root, ".")):
            while target.lower() in text.lower():
                i = text.lower().index(target.lower())
                text = text[:i] + replacement + text[i + len(target):]
    # cwd 以外(例如 Claude Code 存過長工具結果的地方)遮掉使用者名稱;專案資料夾名稱也含完整路徑
    return _PROJECT_DIR_RE.sub("~/.claude/projects/<專案>/", _HOME_RE.sub("~/", text))


def _new_agent(name, tool_use_id=None, subagent_type=None, prompt=""):
    return {"name": name, "tool_use_id": tool_use_id, "subagent_type": subagent_type, "reads": [], "searches": [],
            "writes": [], "commands": [], "tool_counts": {}, "denied": 0, "_prompt": prompt}


def _add(items, value):
    if value not in items:
        items.append(value)


def _record(agent, name, tool_input, cwd):
    """把一次工具呼叫記進 agent,回傳拿來比對 --forbid 的字串(沒有可比對的輸入時為 None)。"""
    agent["tool_counts"][name] = agent["tool_counts"].get(name, 0) + 1
    if name in _READ_TOOLS:
        shown = _relative(tool_input.get("file_path", ""), cwd)
        _add(agent["reads"], shown)
        return shown
    if name in _WRITE_TOOLS:
        shown = _relative(tool_input.get("file_path") or tool_input.get("notebook_path", ""), cwd)
        _add(agent["writes"], shown)
        return shown
    if name in _SEARCH_TOOLS:
        where = _relative(tool_input.get("path", ""), cwd)
        shown = f"{name} {tool_input.get('pattern', '')}" + (f" @ {where}" if where else "")
        _add(agent["searches"], shown)
        return shown
    if name in _SHELL_TOOLS:
        command = _relative(tool_input.get("command", ""), cwd)
        _add(agent["commands"], command if name == "Bash" else f"{name}: {command}")
        return command
    return None


def audit(events, *, forbid=(), agent_filter=None):
    """→ {"agents": [...], "violations": [...]}。agent 依出現順序，主 agent 在最前面。"""
    agents = {None: _new_agent(MAIN)}
    owner_of_call = {}  # tool_use_id → 發出這次呼叫的 agent(權限被拒事件只帶 tool_use_id)
    checked = []  # (agent, 工具, 比對字串)
    cwd = None
    names = {MAIN}
    for event in events:
        if event.get("type") == "system" and event.get("subtype") == "init":
            cwd = event.get("cwd") or cwd
            continue
        if event.get("type") == "system" and event.get("subtype") == "permission_denied":
            agent = owner_of_call.get(event.get("tool_use_id"))
            if agent is not None:
                agent["denied"] += 1
            continue
        if event.get("type") != "assistant":
            continue
        agent = agents.get(event.get("parent_tool_use_id"), agents[None])
        for block in (event.get("message") or {}).get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name, tool_input = block.get("name"), block.get("input") or {}
            owner_of_call[block.get("id")] = agent
            if name in _AGENT_TOOLS:
                agent["tool_counts"][name] = agent["tool_counts"].get(name, 0) + 1
                label = tool_input.get("description") or "未命名 subagent"
                unique, n = label, 2
                while unique in names:
                    unique, n = f"{label} ({n})", n + 1
                names.add(unique)
                prompt = _relative(tool_input.get("prompt", ""), cwd)
                agents[block.get("id")] = _new_agent(unique, block.get("id"), tool_input.get("subagent_type"), prompt)
                checked.append((agents[block.get("id")], "派工 prompt", prompt))
                continue
            shown = _record(agent, name, tool_input, cwd)
            if shown is not None:
                checked.append((agent, name, shown))
    violations = []
    for agent, tool, text in checked:
        if agent_filter and agent_filter not in agent["name"]:
            continue
        for needle in forbid:
            if needle.replace("\\", "/") in text:
                violations.append({"agent": agent["name"], "tool": tool,
                                   "input": text if tool != "派工 prompt" else _excerpt(text, needle)})
                break
    report = [{k: v for k, v in a.items() if not k.startswith("_")} for a in agents.values()]
    return {"agents": report, "violations": violations}


def _excerpt(text, needle, width=40):
    i = text.index(needle.replace("\\", "/"))
    shown = ("…" if i > width else "") + text[max(0, i - width):i + len(needle) + width] + \
        ("…" if i + len(needle) + width < len(text) else "")
    return " ".join(shown.split())


def _print_text(report, forbid, agent_filter):
    for a in report["agents"]:
        total = sum(a["tool_counts"].values())
        print(f"{a['name']}(工具 {total} 次，權限被拒 {a['denied']} 次)")
        if a["tool_counts"]:
            print("  次數:" + "、".join(f"{k} {v}" for k, v in a["tool_counts"].items()))
        for label, key in (("讀", "reads"), ("搜尋", "searches"), ("寫", "writes"), ("指令", "commands")):
            for item in a[key]:
                print(f"  {label}:{' '.join(item.split())}")  # 多行指令印成一行
        print()
    if not forbid:
        return
    scope = f"名稱含「{agent_filter}」的 agent" if agent_filter else "全部 agent"
    if not report["violations"]:
        print(f"檢查 {scope} 是否碰到 {'、'.join(forbid)}:沒有命中")
        return
    print(f"檢查 {scope} 是否碰到 {'、'.join(forbid)}:命中 {len(report['violations'])} 筆")
    for v in report["violations"]:
        print(f"  {v['agent']} / {v['tool']}:{v['input']}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="列出即時執行裡每個 agent 碰過哪些檔")
    parser.add_argument("path", help="執行資料夾(含 stream.jsonl)或 stream.jsonl")
    parser.add_argument("--json", action="store_true", help="輸出 JSON")
    parser.add_argument("--agent", help="只對名稱含這段字的 agent 做 --forbid 檢查")
    parser.add_argument("--forbid", action="append", default=[], help="不該碰到的字串(路徑、字號等)，可重複")
    args = parser.parse_args(argv)
    try:
        events = load_events(args.path)
    except OSError as e:
        print(f"讀不到 stream.jsonl:{e}", file=sys.stderr)
        return 2
    report = audit(events, forbid=args.forbid, agent_filter=args.agent)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_text(report, args.forbid, args.agent)
    return 1 if report["violations"] else 0


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
