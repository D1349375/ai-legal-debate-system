"""由 UI 觸發 Claude Code 即時跑完整攻防流程(headless:`claude -p`)。

論證、訊問、評估與訴狀仍由 legal-debate skill 的 subagent 產生，經 `main.py record/verdict/pleading`
落地到既有資料表，查證閘門照舊；這裡只負責：
- 以最小必要權限啟動 Claude Code 子程序(只允許 `python main.py ...`、讀檔、派 subagent、寫暫存檔到本次執行資料夾)；
- 把 stream-json 輸出原樣存檔，並摘要成 UI 看得懂的步驟紀錄；
- 取消時終止整個程序樹；結束時依 result 事件與資料庫實況判定結果，失敗原因照實寫入 live_runs。

安全：此功能在本機以使用者的 Claude 帳號執行有工具權限的程式，本服務又沒有登入驗證，
所以只在綁 127.0.0.1 時啟用(main.py serve 決定)，端點另外限制本機連線(server/app.py local_only)。
"""
import datetime
import json
import os
import re
import shutil
import signal
import subprocess
import threading

from database.db import DB_URL_ENV, default_db_path
from database.schema import Case, CourtQuestion, DebateArgument, LiveRun, PleadingDraft, Verdict
from engine.aggregate import VALID_SIDES

DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_BUDGET_USD = 15.0
DEFAULT_MAX_MINUTES = 120
RUNS_DIR_REL = "database/live_runs"
EVENTS_FILE = "events.jsonl"
LANDED_LINE = re.compile(r"(?m)^\s*已落地")
MEMORY_EVENTS = 400
# 實測(CLI 2.1.312,2026-10-29 執行 #4):回覆被安全分類器中止時，CLI 會補一則合成的 user 訊息給該 agent,
# 背景 subagent 的這則訊息也會出現在 stream-json(帶 parent_tool_use_id 與 task_description)。
# 分類器的 stop_reason/category 只寫在 subagent 逐字稿，stream-json 沒有，所以只能認這句話。
SAFETY_STOP_MARK = "stopped by a safety classifier"
QUOTA_WARN_AT = 0.9

# --allowedTools:Bash 規則會把 && ; | 等複合指令拆開逐段比對，任何一段不是 `python main.py` 即被拒。
# 寫檔由 Edit 規則管轄(Write(...) 規則不會比對)，限定在本次執行資料夾的上層 database/live_runs/。
ALLOWED_TOOLS = ("Bash(python main.py *)", "Skill(legal-debate *)", "Read", "Grep", "Glob", "Agent",
                 f"Edit(/{RUNS_DIR_REL}/**)")
DISALLOWED_TOOLS = ("WebFetch", "WebSearch")

RESULT_ERRORS = {
    "error_max_budget_usd": "已達花費上限，Claude Code 自行停止",
    "error_max_turns": "已達回合上限，Claude Code 自行停止",
    "error_during_execution": "Claude Code 執行途中發生錯誤",
}
FINAL_STATES = ("succeeded", "incomplete", "failed", "cancelled", "interrupted")


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_claude_command():
    """回傳 (指令前綴, 說明)。Windows 上 npm 安裝的是 claude.cmd 包裝，直接呼叫會經過 cmd.exe，
    含括號、星號、中文的參數有轉義風險，所以改找它包裝的 claude.exe；找不到 exe 就不啟用。"""
    override = os.environ.get("LEGALDEBATE_CLAUDE_BIN")
    if override:
        return ([override], None) if os.path.isfile(override) else (None, f"LEGALDEBATE_CLAUDE_BIN 指向的檔案不存在:{override}")
    found = shutil.which("claude")
    if not found:
        return None, "找不到 Claude Code CLI(claude);請先安裝並登入"
    if found.lower().endswith((".cmd", ".bat")):
        exe = os.path.join(os.path.dirname(found), "node_modules", "@anthropic-ai", "claude-code", "bin", "claude.exe")
        if os.path.isfile(exe):
            return [exe], None
        return None, f"只找到 {os.path.basename(found)} 包裝檔，找不到其對應的 claude.exe,為避免 cmd.exe 參數轉義問題不直接呼叫"
    return [found], None


def build_prompt(case_id, run_dir):
    return f"""/legal-debate {case_id}

本次由 LegalDebate UI 以無人值守方式(claude -p)觸發，過程中沒有人能回答問題。請依 .claude/skills/legal-debate/SKILL.md 跑完 Step 1–10;需要使用者決定的地方，依 SKILL.md 最保守的做法處理，並在最後的回覆說明，不要停下來等待。

本次執行的固定條件：
1. 案件已由 UI 落地資料庫(案件 ID {case_id}),案件輸入檔是 {run_dir}/case.json(含使用者填寫的雙方當事人與統編)。不要再執行 `python main.py case`。SKILL.md 的 {{CASE_FACTS_PATH}} 填這個檔案。
2. 商工查核已由 UI 依使用者提供的統編完成(沒給統編的一方不查)。不要重新查核，也不要用名稱搜尋自行選定統編。直接執行 `python main.py issues --case-id {case_id}` 取得程序事項。
3. 所有暫存檔(檢索詞摘要、程序事項、各階段 JSON、訊問、評估、訴狀草稿、引用清單)一律寫在 {run_dir}/ 之下，不要寫到其他位置。
4. 指令只能用 `python main.py ...`(在目前目錄執行);其他 shell 指令會被拒絕。
5. 落地論證時 model_id 填實際產生該論證的模型 ID。
6. 查證閘門報錯時照 SKILL.md 處理，不得繞過、不得自行改寫引用；若因此無法完成某一步，停止並在最後回覆寫明卡在哪一步、原因為何。
7. subagent 的回覆被安全分類器中止時，依 SKILL.md「subagent 的回覆被安全分類器中止時」一節處理(另開新 subagent 以同一份範本重派，最多 2 次)。
"""


def build_args(prefix, prompt, *, model, budget_usd):
    return [*prefix, "-p", prompt, "--output-format", "stream-json", "--verbose",
            "--permission-mode", "dontAsk", "--model", model, "--max-budget-usd", str(budget_usd),
            "--setting-sources", "project", "--strict-mcp-config",
            "--allowedTools", *ALLOWED_TOOLS, "--disallowedTools", *DISALLOWED_TOOLS]


# ───────────────────────── stream-json 摘要 ─────────────────────────

def _short(text, n=300):
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n] + "…"


def _rel(path, root):
    path = str(path or "")
    norm_root = os.path.normcase(os.path.abspath(root))
    if path and os.path.normcase(os.path.abspath(path)).startswith(norm_root):
        return os.path.relpath(path, root).replace("\\", "/")
    return path


def _describe_tool(name, inp, root):
    inp = inp or {}
    if name == "Bash":
        return f"執行指令:{_short(inp.get('command'), 240)}"
    if name in ("Agent", "Task"):
        model = f"(模型 {inp['model']})" if inp.get("model") else ""
        return f"派出 subagent:{_short(inp.get('description') or inp.get('subagent_type'), 120)}{model}"
    if name == "Read":
        return f"讀取 {_rel(inp.get('file_path'), root)}"
    if name in ("Grep", "Glob"):
        return f"搜尋 {_short(inp.get('pattern'), 80)}" + (f"(於 {_rel(inp.get('path'), root)})" if inp.get("path") else "")
    if name in ("Write", "Edit"):
        return f"寫入 {_rel(inp.get('file_path'), root)}"
    if name == "Skill":
        return f"載入 skill:{inp.get('skill') or inp.get('command') or ''}"
    return f"使用工具 {name}"


def _tool_result_text(block):
    content = block.get("content")
    if isinstance(content, list):
        return " ".join(c.get("text", "") for c in content if isinstance(c, dict))
    return str(content or "")


def summarize_event(obj, root="."):
    """把一行 stream-json 轉成 0 到多則 {kind, text, subagent} 摘要。看不懂的事件不臆測，直接略過(原文仍在紀錄檔)。"""
    kind = obj.get("type")
    sub = bool(obj.get("parent_tool_use_id"))
    out = []
    if kind == "system":
        st = obj.get("subtype")
        if st == "init":
            out.append(("info", f"Claude Code 已啟動(主模型 {obj.get('model') or '未回報'})"))
        elif st == "api_retry":
            out.append(("warn", f"API 暫時失敗，重試中(第 {obj.get('attempt', '?')} 次)"))
        elif st == "permission_denied":
            out.append(("warn", f"權限拒絕:{_short(json.dumps(obj, ensure_ascii=False), 200)}"))
    elif kind == "assistant":
        for block in (obj.get("message") or {}).get("content") or []:
            if block.get("type") == "text" and block.get("text", "").strip():
                out.append(("text", _short(block["text"], 400)))
            elif block.get("type") == "tool_use":
                out.append(("tool", _describe_tool(block.get("name"), block.get("input"), root)))
    elif kind == "user":
        who = safety_stop_task(obj)
        if who:
            out.append(("warn", f"{who} 的回覆被 Anthropic 安全分類器中止(不是程式或 API 錯誤)" +
                        (";依 SKILL.md 應另開 subagent 以同一份範本重派" if who != "主 agent" else "")))
        for block in (obj.get("message") or {}).get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            text = _tool_result_text(block)
            # main.py 拒絕落地時 exit 1,工具結果必為 is_error;只看字樣會把讀到 main.py 原始碼誤判成錯誤
            if block.get("is_error") and "拒絕落地" in text:
                out.append(("error", _short(text, 300)))
            elif block.get("is_error"):
                out.append(("warn", f"工具回報錯誤:{_short(text, 240)}"))
            elif LANDED_LINE.search(text):  # main.py 的輸出以「已落地」開頭；讀到原始碼時前面有行號，不算
                out.append(("landed", _short(text, 200)))
    elif kind == "result":
        cost = obj.get("total_cost_usd")
        cost_text = f",估算花費 {cost:.2f} 美元" if isinstance(cost, (int, float)) else ""
        if obj.get("subtype") == "success" and not obj.get("is_error"):
            out.append(("result", f"Claude Code 回報完成{cost_text}"))
        else:
            out.append(("error", f"Claude Code 結束:{result_error(obj)}{cost_text}"))
        if obj.get("result") and not obj.get("is_error"):
            out.append(("text", _short(obj["result"], 1200)))
        denials = obj.get("permission_denials") or []
        if denials:
            out.append(("warn", f"本次共有 {len(denials)} 次工具呼叫因權限不足被拒"))
    return [{"kind": k, "text": t, "subagent": sub} for k, t in out]


def safety_stop_task(obj):
    """這行 stream-json 若是「回覆被安全分類器中止」的通知，回傳被中止的是誰；否則回傳 None。"""
    if obj.get("type") != "user":
        return None
    for block in (obj.get("message") or {}).get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text" and SAFETY_STOP_MARK in (block.get("text") or ""):
            if not obj.get("parent_tool_use_id"):
                return "主 agent"
            return f"subagent「{obj['task_description']}」" if obj.get("task_description") else "subagent"
    return None


def _epoch_iso(value):
    try:
        return datetime.datetime.fromtimestamp(float(value), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


class StreamObserver:
    """從 stream-json 累計 UI 需要、但 result 事件沒有的觀察：安全分類器中止次數，以及訂閱額度
    (rate_limit_event 的 5 小時/7 天視窗用量)在這次執行開始與結束時的值。API 金鑰登入時沒有額度事件。"""

    def __init__(self):
        self.safety_stops = []
        self.quota_start = None
        self.quota_end = None

    def feed(self, obj, at=None):
        who = safety_stop_task(obj)
        if who:
            self.safety_stops.append({"who": who, "at": obj.get("timestamp") or at})
        if obj.get("type") == "rate_limit_event":
            windows = (obj.get("rate_limit_info") or {}).get("unifiedWindows") or {}
            snap = {name: {"utilization": w.get("utilization"), "resets_at": _epoch_iso(w.get("resetsAt"))}
                    for name, w in windows.items() if isinstance(w, dict) and isinstance(w.get("utilization"), (int, float))}
            # 逐個視窗更新：開始值取該視窗第一次出現的值，結束值取最後一次；某則事件少了某個視窗時保留舊值
            for name, w in snap.items():
                self.quota_start = self.quota_start or {}
                self.quota_start.setdefault(name, w)
                self.quota_end = {**(self.quota_end or {}), name: w}

    def to_dict(self):
        quota = None
        if self.quota_end:
            quota = {name: {"start": self.quota_start[name]["utilization"],
                            "end": w["utilization"], "resets_at": w["resets_at"]}
                     for name, w in self.quota_end.items()}
        return {"safety_stops": self.safety_stops, "quota": quota}


def observe_log(path):
    """從已存的 stream-json 重建觀察(舊執行補登用)。讀不到檔案回傳 None。"""
    obs = StreamObserver()
    try:
        with open(path, "rb") as f:
            for raw in f:
                try:
                    obs.feed(json.loads(raw.decode("utf-8", "replace")))
                except ValueError:
                    continue
    except OSError:
        return None
    return obs.to_dict()


def summarize_results(results):
    """整次執行的 result 事件摘要。subagent 在背景執行時(實測 CLI 2.1.312),主 agent 每等一批就結束一輪，
    stream 結尾會連續出現多筆 result:花費與 modelUsage 是累計值，權限拒絕只記在當輪。所以只摘要最後一筆，
    權限拒絕次數全部加總。"""
    if not results:
        return []
    merged = dict(results[-1])
    merged["permission_denials"] = [d for r in results for d in (r.get("permission_denials") or [])]
    events = summarize_event(merged)
    if len(results) > 1:
        events.insert(1, {"kind": "info", "subagent": False,
                          "text": f"主 agent 共 {len(results)} 輪(subagent 在背景執行，每批完成後再開一輪);以下為最後一輪的回覆"})
    return events


def result_error(obj):
    """result 事件的失敗原因。實測 API 認證失敗時 subtype 仍是 success、只有 is_error 為真，所以不能只看 subtype。"""
    if obj.get("subtype") in RESULT_ERRORS:
        return RESULT_ERRORS[obj["subtype"]]
    detail = _short(obj.get("result"), 300) or obj.get("terminal_reason") or obj.get("subtype") or "未說明"
    if obj.get("api_error_status") == 429:
        # 實測訂閱帳號用完 session 額度時:is_error + api_error_status 429,result 為 "You've hit your session limit · resets …"
        return (f"Claude 帳號已達用量上限或速率限制(HTTP 429):{detail}。此額度與同一帳號的其他 Claude Code 使用共用;"
                "已落地的階段保留，額度重置後請以「以此案件內容建立新案件」重跑")
    return f"Claude Code 回報錯誤:{detail}"


def check_auth(prefix, timeout=30):
    """執行前先查 Claude Code 是否已登入(`claude auth status`,不呼叫模型、不花費)。回傳 (是否可用, 說明)。"""
    try:
        p = subprocess.run([*prefix, "auth", "status"], capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
        info = json.loads(p.stdout.decode("utf-8", "replace") or "{}")
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:
        return False, f"無法確認 Claude Code 登入狀態({type(e).__name__}: {e})"
    if info.get("loggedIn"):
        return True, info.get("authMethod")
    return False, "Claude Code 尚未登入(claude auth status 顯示 loggedIn=false);請先在終端機執行 claude 登入後再試"


def pipeline_missing(session, case_id):
    """依資料庫實況列出流程還缺哪些落地紀錄(不看 Claude 怎麼說，只看資料庫)。"""
    missing = []
    landed = {(a.side, a.stage) for a in session.query(DebateArgument).filter_by(case_id=case_id).all()}
    for stage in (1, 2, 3):
        for side in VALID_SIDES:
            if (side, stage) not in landed:
                missing.append(f"{'原告' if side == 'plaintiff' else '被告'} Stage {stage}")
    if not session.query(CourtQuestion).filter_by(case_id=case_id).count():
        missing.append("法官訊問")
    if not session.query(Verdict).filter_by(case_id=case_id).count():
        missing.append("爭點強弱評估")
    if not session.query(PleadingDraft).filter_by(case_id=case_id).count():
        missing.append("訴狀骨架")
    return missing


def _notes(row):
    try:
        notes = json.loads(row.notes_json) if row.notes_json else {}
    except ValueError:
        return {}
    return notes if isinstance(notes, dict) else {}


def run_to_dict(row):
    notes = _notes(row)
    return {"id": row.id, "case_id": row.case_id, "status": row.status, "started_at": row.started_at,
            "ended_at": row.ended_at, "model": row.model,
            "budget_usd": float(row.budget_usd) if row.budget_usd else None,
            "cost_usd": float(row.cost_usd) if row.cost_usd else None,
            "exit_code": row.exit_code, "error": row.error, "log_path": row.log_path,
            "safety_stops": notes.get("safety_stops") or [], "quota": notes.get("quota")}


def _kill_tree(proc):
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


class _Active:
    def __init__(self, run_id, case_id, proc, events_path=None):
        self.run_id, self.case_id, self.proc = run_id, case_id, proc
        self.events_path = events_path
        self.events = []
        self.seq = 0
        self.cancel_requested = False
        self.timed_out = False
        self.result = None  # 最後一筆 result 事件
        self.results = []
        self.observer = StreamObserver()
        self.lock = threading.Lock()
        self.thread = None


class LiveRunManager:
    def __init__(self, factory, *, root, db_url=None, enabled=False, reason=None, command=None,
                 model=DEFAULT_MODEL, budget_usd=DEFAULT_BUDGET_USD, max_minutes=DEFAULT_MAX_MINUTES, runs_dir=None):
        self.factory, self.root, self.db_url = factory, root, db_url
        # 預設在專案內(--allowedTools 的 Edit 規則只開放這裡);測試改用暫存資料夾
        self.runs_dir = os.path.abspath(runs_dir or os.path.join(root, *RUNS_DIR_REL.split("/")))
        self.model, self.budget_usd, self.max_minutes = model, budget_usd, max_minutes
        self.command, self.reason = command, reason
        if enabled and self.command is None:
            self.command, missing = resolve_claude_command()
            if self.command is None:
                self.reason = missing
        self.enabled = bool(enabled and self.command)
        if not enabled and not self.reason:
            self.reason = "即時執行未啟用"
        self._active = None
        self._lock = threading.Lock()
        self._mark_stale_runs()
        self._backfill_notes()
        # 登入狀態在背景查一次供 UI 提前提示(不拖慢啟動);真正的把關在 start() 每次重查
        self.auth = {"checked": False, "logged_in": None, "detail": None}
        self._auth_seq = 0
        if self.enabled:
            threading.Thread(target=self.refresh_auth, daemon=True).start()

    def refresh_auth(self):
        with self._lock:
            self._auth_seq += 1
            seq = self._auth_seq
        logged_in, detail = check_auth(self.command)
        with self._lock:
            if seq == self._auth_seq:  # 只保留最新一次查詢，避免較早的背景查詢蓋掉結果
                self.auth = {"checked": True, "logged_in": logged_in, "detail": detail}
        return logged_in, detail

    # ── 狀態 ──
    def availability(self):
        active = self._active
        return {"enabled": self.enabled, "reason": None if self.enabled else self.reason,
                "model": self.model, "budget_usd": self.budget_usd, "max_minutes": self.max_minutes,
                "auth": self.auth, "active_run": {"id": active.run_id, "case_id": active.case_id} if active else None,
                "quota": self.latest_quota(), "quota_warn_at": QUOTA_WARN_AT}

    def _mark_stale_runs(self):
        with self.factory() as s:
            for row in s.query(LiveRun).filter_by(status="running").all():
                row.status, row.ended_at = "interrupted", _now_iso()
                row.error = ("後端在執行途中停止或重新啟動，無法得知 Claude Code 子程序的結果。"
                             "已落地的階段保留在資料庫，未落地的部分不會補上。")
            s.commit()

    def _log_abs(self, path):
        return path if os.path.isabs(path) else os.path.join(self.root, *path.split("/"))

    def _run_dir(self, run_id):
        """給 Claude 與存進 DB 的路徑：在專案內用相對路徑(正斜線),否則用絕對路徑。"""
        abs_dir = os.path.join(self.runs_dir, f"run-{run_id}")
        try:
            rel = os.path.relpath(abs_dir, self.root)
        except ValueError:  # Windows 不同磁碟機
            rel = ".."
        return rel.replace("\\", "/") if not rel.startswith("..") else abs_dir.replace("\\", "/")

    # ── 啟動 ──
    def start(self, case_id):
        """回傳 run dict;不能執行時 raise PermissionError(未啟用)或 ValueError(案件狀態不允許)。"""
        if not self.enabled:
            raise PermissionError(self.reason)
        if self._active is None:
            logged_in, detail = self.refresh_auth()
            if not logged_in:
                raise PermissionError(detail)
        with self._lock:
            if self._active is not None:
                raise ValueError(f"已有一個即時執行進行中(案件 {self._active.case_id},執行 #{self._active.run_id}),同一時間只能跑一件")
            with self.factory() as s:
                case = s.query(Case).filter_by(case_id=case_id).one_or_none()
                if case is None:
                    raise ValueError(f"找不到案件 {case_id}(必須先落地資料庫)")
                existing = sum(s.query(m).filter_by(case_id=case_id).count()
                               for m in (DebateArgument, CourtQuestion, Verdict, PleadingDraft))
                if existing:
                    raise ValueError("此案件已有攻防或書狀紀錄。落地紀錄不可覆寫，不能重跑；請建立新案件")
                row = LiveRun(case_id=case_id, status="running", started_at=_now_iso(), model=self.model,
                              budget_usd=str(self.budget_usd))
                s.add(row)
                s.commit()
                run_id = row.id
                run_dir = self._run_dir(run_id)
                row.log_path = f"{run_dir}/stream.jsonl"
                s.commit()
                case_payload = {"case_id": case.case_id, "case_type": case.case_type,
                                "facts_summary": case.facts_summary, "claims": case.claims,
                                "parties": json.loads(case.parties_json) if case.parties_json else None}
            abs_dir = self._log_abs(run_dir)
            os.makedirs(abs_dir, exist_ok=True)
            with open(os.path.join(abs_dir, "case.json"), "w", encoding="utf-8") as f:
                json.dump(case_payload, f, ensure_ascii=False, indent=2)
            args = build_args(self.command, build_prompt(case_id, run_dir), model=self.model, budget_usd=self.budget_usd)
            env = dict(os.environ)
            env[DB_URL_ENV] = self.db_url or f"sqlite:///{default_db_path()}"
            env["CLAUDE_CODE_SUBAGENT_MODEL"] = self.model  # CLI 2.1.251 前此變數優先於 Agent 的 model 參數
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"
            popen_kw = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "CREATE_NO_WINDOW", 0)}
                        if os.name == "nt" else {"start_new_session": True})
            stderr_file = open(os.path.join(abs_dir, "stderr.log"), "wb")
            try:
                proc = subprocess.Popen(args, cwd=self.root, env=env, stdin=subprocess.DEVNULL,
                                        stdout=subprocess.PIPE, stderr=stderr_file, **popen_kw)
            except OSError as e:
                stderr_file.close()
                self._finish(run_id, "failed", error=f"無法啟動 Claude Code:{e}")
                raise ValueError(f"無法啟動 Claude Code:{e}")
            active = _Active(run_id, case_id, proc, events_path=os.path.join(abs_dir, EVENTS_FILE))
            self._active = active
            self._append(active, "info", f"已啟動執行 #{run_id}(模型 {self.model},花費上限 {self.budget_usd:g} 美元)")
            active.thread = threading.Thread(target=self._pump, args=(active, stderr_file, abs_dir), daemon=True)
            active.thread.start()
            return self.get(run_id)

    def _append(self, active, kind, text, subagent=False):
        with active.lock:
            active.seq += 1
            ev = {"seq": active.seq, "at": _now_iso(), "kind": kind, "text": text, "subagent": subagent}
            active.events.append(ev)
            del active.events[:-MEMORY_EVENTS]
            if active.events_path:
                # 另存摘要：結束後(含重啟後)照原序號與時間重播，並保留啟動與結論兩則 stream-json 沒有的事件
                try:
                    with open(active.events_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
                except OSError:
                    pass

    def _pump(self, active, stderr_file, abs_dir):
        watchdog = threading.Timer(self.max_minutes * 60, self._timeout, args=(active,))
        watchdog.daemon = True
        watchdog.start()
        try:
            with open(os.path.join(abs_dir, "stream.jsonl"), "wb") as log:
                for raw in active.proc.stdout:
                    log.write(raw)
                    log.flush()
                    try:
                        obj = json.loads(raw.decode("utf-8", "replace"))
                    except ValueError:
                        continue
                    active.observer.feed(obj, _now_iso())
                    if obj.get("type") == "result":  # 可能有多筆，結束後一起摘要(見 summarize_results)
                        active.results.append(obj)
                        active.result = obj
                        continue
                    for ev in summarize_event(obj, self.root):
                        self._append(active, ev["kind"], ev["text"], ev["subagent"])
            for ev in summarize_results(active.results):
                self._append(active, ev["kind"], ev["text"], ev["subagent"])
            code = active.proc.wait()
        finally:
            watchdog.cancel()
            stderr_file.close()
        self._conclude(active, code, abs_dir)

    def _timeout(self, active):
        active.timed_out = True
        _kill_tree(active.proc)

    def _conclude(self, active, code, abs_dir):
        result = active.result or {}
        cost = result.get("total_cost_usd")
        with self.factory() as s:
            missing = pipeline_missing(s, active.case_id)
        if active.cancel_requested:
            status, error = "cancelled", "使用者取消；已終止 Claude Code 程序樹。已落地的階段保留在資料庫。"
        elif active.timed_out:
            status, error = "failed", f"超過 {self.max_minutes} 分鐘仍未結束，已強制終止。"
        elif result.get("subtype") == "success" and not result.get("is_error") and code == 0:
            status = "succeeded" if not missing else "incomplete"
            error = None if not missing else "Claude Code 回報完成，但資料庫仍缺:" + "、".join(missing)
        else:
            reason = result_error(result) if result else None
            if not reason:
                reason = f"Claude Code 結束碼 {code},沒有回報完成"
                tail = self._stderr_tail(abs_dir)
                if tail:
                    reason += f"。錯誤輸出:{tail}"
            status, error = "failed", reason
        if status != "succeeded" and missing and status != "incomplete":
            error += "(資料庫尚缺:" + "、".join(missing) + ")"
        notes = active.observer.to_dict()
        stops = notes["safety_stops"]
        who = "、".join(s["who"] for s in stops)
        if stops and status == "incomplete":
            # Claude Code 自己回報完成但資料庫缺階段：沒有其他明確原因，分類器中止是最可能的解釋，但仍只是推斷
            error += (f"。執行期間有 {len(stops)} 次回覆被 Anthropic 安全分類器中止({who}),"
                      "很可能就是流程沒跑完的原因;請以執行紀錄與 Claude Code 最後回覆核對。這不是程式錯誤，可另建案件重跑")
        elif stops and status == "failed":  # 已有明確失敗原因(花費上限、429、逾時…),只附註不歸因
            error += f"。另外，執行期間有 {len(stops)} 次回覆被 Anthropic 安全分類器中止({who})"
        self._append(active, "error" if status != "succeeded" else "result",
                     {"succeeded": "執行完成，各階段皆已落地資料庫", "incomplete": "執行結束但流程不完整",
                      "cancelled": "已取消", "failed": "執行失敗"}[status] + (f":{error}" if error else ""))
        if stops and status == "succeeded":
            self._append(active, "warn", f"執行期間有 {len(stops)} 次回覆被安全分類器中止({who})。"
                                         "依 SKILL.md 被中止的輸出不得落地、應另開 subagent 重派;請以執行紀錄與最後回覆核對")
        self._finish(active.run_id, status, error=error, cost=cost, exit_code=code, notes=notes)
        with self._lock:
            if self._active is active:
                self._active = None

    @staticmethod
    def _stderr_tail(abs_dir, n=600):
        try:
            with open(os.path.join(abs_dir, "stderr.log"), "rb") as f:
                return _short(f.read()[-4000:].decode("utf-8", "replace"), n)
        except OSError:
            return ""

    def _finish(self, run_id, status, *, error=None, cost=None, exit_code=None, notes=None):
        with self.factory() as s:
            row = s.get(LiveRun, run_id)
            row.status, row.ended_at, row.error, row.exit_code = status, _now_iso(), error, exit_code
            row.cost_usd = str(cost) if isinstance(cost, (int, float)) else None
            if notes is not None:
                row.notes_json = json.dumps(notes, ensure_ascii=False)
            s.commit()

    def _backfill_notes(self):
        """notes_json 欄位加入前結束的執行，從存檔的 stream-json 補登(例如 2026-10-29 執行 #4 的那次中止)。"""
        with self.factory() as s:
            for row in s.query(LiveRun).filter(LiveRun.notes_json.is_(None), LiveRun.status != "running").all():
                notes = observe_log(self._log_abs(row.log_path)) if row.log_path else None
                if notes is not None:
                    row.notes_json = json.dumps(notes, ensure_ascii=False)
            s.commit()

    def latest_quota(self):
        """最近一次有額度資料的執行結束時的訂閱額度(開始前提醒用;不是即時值)。"""
        with self.factory() as s:
            for row in s.query(LiveRun).filter(LiveRun.notes_json.isnot(None)).order_by(LiveRun.id.desc()).all():
                quota = _notes(row).get("quota")
                if quota:
                    return {"run_id": row.id, "as_of": row.ended_at, "windows": quota}
        return None

    # ── 取消 / 查詢 ──
    def cancel(self, run_id):
        active = self._active
        if active is None or active.run_id != run_id:
            raise ValueError(f"執行 #{run_id} 不在進行中")
        active.cancel_requested = True
        self._append(active, "warn", "收到取消要求，正在終止 Claude Code 程序樹…")
        _kill_tree(active.proc)
        active.thread.join(timeout=30)
        return self.get(run_id)

    def wait(self, run_id, timeout=None):
        active = self._active
        if active is not None and active.run_id == run_id:
            active.thread.join(timeout)

    def get(self, run_id, since=0):
        with self.factory() as s:
            row = s.get(LiveRun, run_id)
            if row is None:
                return None
            run = run_to_dict(row)
        active = self._active
        if active is not None and active.run_id == run_id:
            with active.lock:
                events = [e for e in active.events if e["seq"] > since]
                total = active.seq
        else:
            events, total = self._events_from_log(run["log_path"], since)
        return {"run": run, "events": events, "event_count": total, "active": run["status"] == "running"}

    def _events_from_log(self, log_rel, since):
        """已結束的執行：讀執行期間另存的事件摘要(重啟後仍看得到失敗原因與過程);
        沒有該檔的舊執行才從 stream-json 重建(沒有時間，也沒有啟動與結論兩則)。"""
        events = []
        if not log_rel:
            return events, 0
        events_path = os.path.join(os.path.dirname(self._log_abs(log_rel)), EVENTS_FILE)
        if os.path.exists(events_path):
            try:
                with open(events_path, encoding="utf-8") as f:
                    events = [json.loads(line) for line in f if line.strip()]
            except (OSError, ValueError):
                events = []
            if events:
                total = events[-1]["seq"]
                return [e for e in events if e["seq"] > since][-MEMORY_EVENTS:], total
        results = []
        try:
            with open(self._log_abs(log_rel), "rb") as f:
                for raw in f:
                    try:
                        obj = json.loads(raw.decode("utf-8", "replace"))
                    except ValueError:
                        continue
                    if obj.get("type") == "result":
                        results.append(obj)
                        continue
                    for ev in summarize_event(obj, self.root):
                        events.append({"seq": len(events) + 1, "at": None, **ev})
        except OSError:
            return events, 0
        for ev in summarize_results(results):
            events.append({"seq": len(events) + 1, "at": None, **ev})
        total = len(events)
        return [e for e in events if e["seq"] > since][-MEMORY_EVENTS:], total

    def runs_for_case(self, case_id):
        with self.factory() as s:
            return [run_to_dict(r) for r in s.query(LiveRun).filter_by(case_id=case_id).order_by(LiveRun.id).all()]

    def shutdown(self):
        active = self._active
        if active is not None:
            active.cancel_requested = True
            _kill_tree(active.proc)
            active.thread.join(timeout=30)


def is_loopback_host(host):
    return host in ("127.0.0.1", "localhost", "::1")


def options_for_host(host, *, model=None, budget_usd=None):
    """main.py serve 依綁定位址決定是否啟用即時執行。

    即時執行會以本機使用者的 Claude 帳號跑有工具權限的 Claude Code,本服務又沒有登入驗證；
    綁 0.0.0.0 等於讓區網內任何連得到的人在這台電腦上執行程式並花用帳號額度，所以整個停用，不做半套保護。"""
    if is_loopback_host(host):
        return {"enabled": True, "model": model or DEFAULT_MODEL,
                "budget_usd": budget_usd if budget_usd is not None else DEFAULT_BUDGET_USD}
    return {"enabled": False,
            "reason": f"以 --host {host} 啟動，非僅限本機；即時執行只在綁定 127.0.0.1 時開放"}
