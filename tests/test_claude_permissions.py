"""即時執行的 Bash 權限邊界：用真的 claude.exe 與 server/live_run.py 相同的旗標，搭配本機假的 Messages API。

假 API 依序要求 Bash 執行幾個帶輸出導向的 `python main.py` 指令，再看 Claude Code 的權限判定。
不連 Anthropic、不用帳號額度:ANTHROPIC_BASE_URL 指向本機，金鑰是假值，設定目錄是暫存資料夾。
需要本機裝有 Claude Code,且要等 CLI 啟動，預設略過；設 LEGALDEBATE_PROBE_CLAUDE=1 才跑。
2026-10-29 以 Claude Code 2.1.312 實測：寫到 database/live_runs/ 之下放行，其餘導向一律拒絕(結果見 ui/README.md)。
"""
import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from server import live_run

pytestmark = pytest.mark.skipif(os.environ.get("LEGALDEBATE_PROBE_CLAUDE") != "1",
                                reason="需要本機 Claude Code;設 LEGALDEBATE_PROBE_CLAUDE=1 才跑")


def _events(blocks, stop):
    evs = [{"type": "message_start", "message": {"id": "msg_probe", "type": "message", "role": "assistant",
            "model": "claude-sonnet-5-5", "content": [], "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1}}}]
    for i, b in enumerate(blocks):
        if b["type"] == "tool_use":
            evs += [{"type": "content_block_start", "index": i, "content_block": {**b, "input": {}}},
                    {"type": "content_block_delta", "index": i,
                     "delta": {"type": "input_json_delta", "partial_json": json.dumps(b["input"])}}]
        else:
            evs += [{"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}},
                    {"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": b["text"]}}]
        evs.append({"type": "content_block_stop", "index": i})
    return evs + [{"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None}, "usage": {"output_tokens": 5}},
                  {"type": "message_stop"}]


def fake_api(commands):
    """每次請求帶著該工具就送出下一個工具呼叫，送完回 end_turn。
    commands 每筆為 (名稱, Bash 指令) 或 (名稱, 工具名稱, 工具輸入)。"""
    queue = [c if len(c) == 3 else (c[0], "Bash", {"command": c[1], "description": c[0]}) for c in commands]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
            if not self.path.startswith("/v1/messages") or "count_tokens" in self.path:
                payload, ctype = b'{"input_tokens": 1}', "application/json"
            else:
                tools = {t.get("name") for t in body.get("tools") or []}
                if queue and queue[0][1] in tools:
                    name, tool, tool_input = queue.pop(0)
                    evs = _events([{"type": "tool_use", "id": f"toolu_{name}", "name": tool,
                                    "input": tool_input}], "tool_use")
                else:
                    evs = _events([{"type": "text", "text": "done"}], "end_turn")
                if body.get("stream"):
                    payload = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in evs).encode()
                    ctype = "text/event-stream"
                else:
                    msg = {**evs[0]["message"], "content": [{"type": "text", "text": "done"}], "stop_reason": "end_turn"}
                    payload, ctype = json.dumps(msg).encode(), "application/json"
            self.send_response(200)
            self.send_header("content-type", ctype)
            self.end_headers()
            self.wfile.write(payload)

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(live_run.__file__)))


def run_probe(tmp_path, cases):
    """用與 live_run 相同的旗標跑真的 Claude Code，回傳被權限拒絕的工具呼叫名稱集合。

    Claude Code 2.1.x 對 Read 的路徑拒絕不列在 result 的 permission_denials，而是工具結果回錯誤
    「File is in a directory that is denied by your permission settings」(2026-11-01 實測)，兩種都算拒絕。"""
    prefix, missing = live_run.resolve_claude_command()
    if prefix is None:
        pytest.skip(missing)
    server = fake_api(cases)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ANTHROPIC_", "CLAUDE_CODE_OAUTH"))}
    env.update(ANTHROPIC_BASE_URL=f"http://127.0.0.1:{server.server_address[1]}",
               ANTHROPIC_API_KEY="sk-ant-api03-localprobe-not-a-real-key", CLAUDE_CONFIG_DIR=str(tmp_path / "cfg"),
               CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1", DISABLE_TELEMETRY="1", DISABLE_AUTOUPDATER="1",
               DISABLE_ERROR_REPORTING="1")
    try:
        p = subprocess.run(live_run.build_args(prefix, "probe", model="claude-sonnet-5-5", budget_usd=1),
                           cwd=ROOT, env=env, capture_output=True, timeout=180, stdin=subprocess.DEVNULL)
        events = [json.loads(line) for line in p.stdout.decode("utf-8", "replace").splitlines() if line.startswith("{")]
        result = [e for e in events if e.get("type") == "result"][-1]
        denied = {d["tool_use_id"] for d in result.get("permission_denials") or []}
        for event in events:
            content = (event.get("message") or {}).get("content") if event.get("type") == "user" else None
            for block in content if isinstance(content, list) else []:
                if block.get("type") == "tool_result" and block.get("is_error") and "denied by your permission settings" in str(block.get("content")):
                    denied.add(block["tool_use_id"])
        return {tool_id.replace("toolu_", "") for tool_id in denied}
    finally:
        server.shutdown()


def test_retrieval_cache_snapshots_and_logs_cannot_be_read_directly(tmp_path):
    """快取、案件快照與檢索紀錄禁止 Read／Glob／Grep；同一個執行資料夾的其他檔案照常可讀。"""
    case_dir = os.path.join(ROOT, "database", "live_runs", "case-probe-read")
    snapshot = os.path.join(case_dir, "retrieval_cache", "plaintiff", "judgments")
    logs = os.path.join(case_dir, "search_logs")
    cache = os.path.join(ROOT, "database", "retrieval_cache", "judgments")
    run_dir = os.path.join(ROOT, "database", "live_runs", "run-probe-read")
    created = [d for d in (case_dir, run_dir, os.path.join(ROOT, "database", "retrieval_cache")) if not os.path.exists(d)]
    for folder in (snapshot, logs, cache, run_dir):
        os.makedirs(folder, exist_ok=True)
    files = {"snapshot": os.path.join(snapshot, "probe.json"), "log": os.path.join(logs, "plaintiff_p1.jsonl"),
             "cache": os.path.join(cache, "probe-read.json"), "run": os.path.join(run_dir, "role.json")}
    for path in files.values():
        with open(path, "w", encoding="utf-8") as f:
            f.write("{}")
    cases = [(f"read_{name}", "Read", {"file_path": path}) for name, path in files.items()]
    cases += [("glob_snapshot", "Glob", {"pattern": "**/*.json", "path": os.path.join(case_dir, "retrieval_cache")}),
              ("grep_logs", "Grep", {"pattern": "query", "path": logs})]
    try:
        denied = run_probe(tmp_path, cases)
        assert denied == {"read_snapshot", "read_log", "read_cache", "glob_snapshot", "grep_logs"}
    finally:
        os.remove(files["cache"])
        for folder in created:
            shutil.rmtree(folder, ignore_errors=True)


def test_bash_redirect_outside_runs_dir_is_denied(tmp_path):
    prefix, missing = live_run.resolve_claude_command()
    if prefix is None:
        pytest.skip(missing)
    root = ROOT
    inside_dir = os.path.join(root, "database", "live_runs", "probe-redirect")
    outside = (tmp_path / "outside.txt").as_posix()
    cases = [
        ("inside_runs_dir", "python main.py --help > database/live_runs/probe-redirect/inside.txt"),
        ("outside_abs", f"python main.py --help > {outside}"),
        ("outside_parent", "python main.py --help > ../probe_outside_rel.txt"),
        ("project_root", "python main.py --help > probe_root.txt"),
        ("append_outside", f"python main.py --help >> {outside}"),
        ("stderr_outside", f"python main.py --help 2> {outside}"),
        ("tee_outside", f"python main.py --help | tee {outside}"),
        ("plain", "python main.py --help"),
    ]
    os.makedirs(inside_dir, exist_ok=True)
    server = fake_api(cases)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ANTHROPIC_", "CLAUDE_CODE_OAUTH"))}
    env.update(ANTHROPIC_BASE_URL=f"http://127.0.0.1:{server.server_address[1]}",
               ANTHROPIC_API_KEY="sk-ant-api03-localprobe-not-a-real-key", CLAUDE_CONFIG_DIR=str(tmp_path / "cfg"),
               CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1", DISABLE_TELEMETRY="1", DISABLE_AUTOUPDATER="1",
               DISABLE_ERROR_REPORTING="1")
    try:
        p = subprocess.run(live_run.build_args(prefix, "probe", model="claude-sonnet-5-5", budget_usd=1),
                           cwd=root, env=env, capture_output=True, timeout=180, stdin=subprocess.DEVNULL)
        result = [json.loads(line) for line in p.stdout.decode("utf-8", "replace").splitlines()
                  if line.startswith("{") and '"type":"result"' in line][-1]
        denied = {d["tool_use_id"].replace("toolu_", "") for d in result.get("permission_denials") or []}
        assert os.path.exists(os.path.join(inside_dir, "inside.txt"))
        assert denied == {"outside_abs", "outside_parent", "project_root", "append_outside", "stderr_outside", "tee_outside"}
        assert not os.path.exists(outside) and not os.path.exists(os.path.join(root, "probe_root.txt"))
        assert not os.path.exists(os.path.join(os.path.dirname(root), "probe_outside_rel.txt"))
    finally:
        server.shutdown()
        shutil.rmtree(inside_dir, ignore_errors=True)
