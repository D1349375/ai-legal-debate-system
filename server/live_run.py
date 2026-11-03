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

from sqlalchemy import or_

from database.db import (
    DB_URL_ENV, case_gates, case_payload, current_complaint, default_db_path, is_main_pleading, pleading_side, record_gate,
    system_complaints,
)
from database.schema import Case, CourtQuestion, DebateArgument, IssueSheet, LiveRun, PleadingDraft, Verdict
from engine.aggregate import VALID_SIDES
from engine.judgment_search import EXCLUDE_ENV, exclusion_keys
from engine.verify import SNAPSHOT_ENV

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
# 檢索快取、案件快照(依角色分子資料夾)與檢索紀錄不給任何 agent 用 Read／Grep／Glob 直接讀：讀過哪些判決、搜過哪些詞
# 會透露該方研究方向，而同一個 Claude Code 程序裡的角色共用權限，無法只禁對造。檢索指令以 Python 讀檔，不受影響。
# PowerShell:Windows 上的 CLI 有這個工具，dontAsk 下一律被拒，但模型看得到會先試(W0 F7),直接移出工具清單。
DISALLOWED_TOOLS = ("WebFetch", "WebSearch", "PowerShell", "Read(/database/retrieval_cache/**)",
                    f"Read(/{RUNS_DIR_REL}/*/retrieval_cache/**)", f"Read(/{RUNS_DIR_REL}/*/search_logs/**)")
# 案件層級的資料夾：律師確認關卡與續跑會把一個案件分成多次執行，快照與檢索紀錄要跨執行沿用。
CASE_DIR_PREFIX = "case-"

RESULT_ERRORS = {
    "error_max_budget_usd": "已達花費上限，Claude Code 自行停止",
    "error_max_turns": "已達回合上限，Claude Code 自行停止",
    "error_during_execution": "Claude Code 執行途中發生錯誤",
}
FINAL_STATES = ("succeeded", "incomplete", "failed", "cancelled", "interrupted")
# full:完整流程(Step 1–10,新案件或續跑);pleadings:只替已跑完攻防的案件補產書狀(SKILL.md Step 9C)
RUN_KINDS = ("full", "pleadings")
# 要產生哪幾份書狀由使用者選(花費由使用者控制):plaintiff=原告起訴狀(9A)、defendant=被告答辯狀(9B)
DOC_LABEL = {"plaintiff": "原告起訴狀", "defendant": "被告答辯狀"}
DOC_STEP = {"plaintiff": "9A", "defendant": "9B"}
# 舊流程(protocol 為 NULL)的步驟在 W2 從 SKILL.md 搬到這裡;SKILL.md 的 Step 編號現在是書狀交換流程的
LEGACY_DOC = "references/legacy-v1.md"
# 書狀交換流程(protocol v2)的停止點:complaint=只跑到起訴狀 v1,停在關卡 1 等律師確認;answer、issue_sheet=
# 跑到模擬答辯狀或爭點整理表就停(分段驗證 P2、P3 用,關卡 1 一樣自動通過)。不指定時跑完全程，關卡 1 自動通過。
STOP_AFTER = ("complaint", "answer", "issue_sheet")
STOP_LABEL = {"complaint": "起訴狀 v1", "answer": "模擬答辯狀", "issue_sheet": "爭點整理表"}
AUTO_GATE_NOTE = "無人值守執行未指定停止點，關卡 1 自動通過，未經律師確認"


def normalize_documents(documents, kind):
    """回傳依原告、被告排序且不重複的書狀清單。完整流程未指定時兩份都產；補產一定要指定。"""
    if documents is None:
        if kind == "pleadings":
            raise ValueError("補產書狀須指定要產生哪一份(起訴狀或答辯狀)")
        return list(VALID_SIDES)
    chosen = [side for side in VALID_SIDES if side in documents]
    if not chosen or len(chosen) != len(set(documents)):
        raise ValueError(f"書狀選擇不合法:{documents}(只能是 plaintiff、defendant,至少一份)")
    return chosen


def documents_text(documents):
    return "、".join(DOC_LABEL[side] for side in documents)


def stored_documents(row):
    """LiveRun.documents 欄位新增前的執行為 NULL(當時固定產書狀，不記錄選擇)。"""
    return [d for d in (row.documents or "").split(",") if d] or None


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


def documents_instructions(documents, number):
    skipped = [side for side in VALID_SIDES if side not in documents]
    text = (f"{number}. 本次要產生的書狀：{documents_text(documents)}。使用者為控制花費，只選了"
            f"{'、'.join(f'{DOC_LABEL[s]}({LEGACY_DOC} Step 9 的 {DOC_STEP[s]})' for s in documents)}。")
    if skipped:
        text += (f"不要產生{documents_text(skipped)},Step 8 也不必為只會用在{documents_text(skipped)}的引用另做查證；"
                 f"之後需要時，使用者會另外要求補產。")
    return text + "\n"


def build_prompt(case_id, run_dir, resume=None, documents=VALID_SIDES, *, protocol=None, stop_after=None):
    if protocol == "v2":
        return build_prompt_v2(case_id, run_dir, resume, stop_after)
    return f"""/legal-debate {case_id}

本次由 LegalDebate UI 以無人值守方式(claude -p)觸發，過程中沒有人能回答問題。請依 .claude/skills/legal-debate/SKILL.md 跑完 Step 1–10;需要使用者決定的地方，依 SKILL.md 最保守的做法處理，並在最後的回覆說明，不要停下來等待。

本次執行的固定條件：
1. 案件已由 UI 落地資料庫(案件 ID {case_id}),案件輸入檔是 {run_dir}/case.json(含使用者填寫的雙方當事人與統編)。不要再執行 `python main.py case`。SKILL.md 的 {{CASE_FACTS_PATH}} 填這個檔案。
2. 商工查核已由 UI 依使用者提供的統編完成(沒給統編的一方不查)。不要重新查核，也不要用名稱搜尋自行選定統編。直接執行 `python main.py issues --case-id {case_id}` 取得程序事項。
3. 所有暫存檔(檢索詞摘要、程序事項、各階段 JSON、訊問、評估、訴狀草稿、引用清單)一律寫在 {run_dir}/ 之下，不要寫到其他位置。
4. 指令一律用 Bash 工具執行 `python main.py ...`(在目前目錄執行),一次一個指令，不要用迴圈或複合指令；其他 shell 指令會被拒絕。派 subagent 時把這一句寫進它的指示。
5. 落地論證時 model_id 填實際產生該論證的模型 ID。
6. 查證閘門報錯時照 SKILL.md 處理，不得繞過、不得自行改寫引用；若因此無法完成某一步，停止並在最後回覆寫明卡在哪一步、原因為何。
7. subagent 的回覆被安全分類器中止時，依 SKILL.md「subagent 的回覆被安全分類器中止時」一節處理(另開新 subagent 以同一份範本重派，最多 2 次)。
""" + documents_instructions(documents, 8) + (resume_instructions(resume, run_dir) if resume else "")


def resume_instructions(plan, run_dir):
    side_note = ""
    if plan["missing_sides"]:
        missing = "、".join(SIDE_LABEL[x] for x in plan["missing_sides"])
        present = "、".join(SIDE_LABEL[x] for x in VALID_SIDES if x not in plan["missing_sides"])
        side_note = f"\n   {plan['from_label']}只有{present}已落地：只派{missing}的 subagent、只落地{missing}。"
    no_uncontested = ("\n   法官訊問的 uncontested_points 當初沒有落地資料庫，本次無法取得；Step 7 與最後回覆用到時照實寫明無法取得，不要自行推測補寫。"
                      if "questions" in plan["landed_keys"] else "")
    return f"""9. 本次是續跑。資料庫已落地：{"、".join(plan["landed"])}。這些紀錄一律不得覆寫、刪除或重新落地(SKILL.md「落地紀律」)。
   從 {plan.get("from_doc") or LEGACY_DOC} {plan["from_step"]}({plan["from_label"]})開始(舊流程)。之前的步驟只做該檔 Step 1 的檢索詞整理與 Step 1.5 的 `python main.py issues`,不要再派 subagent 重做已落地的階段。
   已落地的論證、法官訊問與評估已由 UI 從資料庫匯出到 {run_dir}/landed.json(唯讀);後續步驟需要前階段的輸出時，以這個檔案為準；但它含雙方內部檢討，給法官與摘對手摘要仍要用 `python main.py public-args`。{side_note}{no_uncontested}
"""


def build_prompt_v2(case_id, run_dir, resume=None, stop_after=None):
    """書狀交換流程(protocol v2)。停止點寫明跑到哪裡停；關卡 1 由 UI 記錄(律師確認，或結束時自動通過),不交給 Claude。
    案件輸入檔只給主 agent:各角色只讀自己的角色檔(審查 A3),被告讀到事實經過就失去「只讀起訴狀」的意義。"""
    if stop_after == "complaint":
        scope = ("本次只跑到起訴狀：只跑 SKILL.md 書狀交換流程 Step 1–3,起訴狀 v1 落地後就停，直接到最後的回報。"
                 "不要往下跑；關卡 1(律師確認起訴狀)由使用者在 UI 進行，確認後會另開續跑。")
    else:
        if resume and resume.get("gate"):
            scope = "關卡 1 已記錄(見第 9 點)。"
        else:
            scope = ("關卡 1(律師確認起訴狀)自動通過，UI 會在執行結束時記錄為「未經律師確認」，你不用處理，也不要自己記錄。")
        if stop_after in STOP_STEP:
            scope = (f"本次只跑到{STOP_LABEL[stop_after]}:跑到 SKILL.md {STOP_STEP[stop_after]}({STOP_LABEL[stop_after]}落地)就停，"
                     f"直接到最後的回報，不要往下跑。" + scope)
        else:
            scope = "本次跑完全程(到起訴狀 v2),沒有停止點。" + scope
    return f"""/legal-debate {case_id}

本次由 LegalDebate UI 以無人值守方式(claude -p)觸發，過程中沒有人能回答問題。這個案件是書狀交換流程(protocol v2),請依 .claude/skills/legal-debate/SKILL.md 的書狀交換流程執行；需要使用者決定的地方，依 SKILL.md 最保守的做法處理，並在最後的回覆說明，不要停下來等待。

本次執行的固定條件：
1. 案件已由 UI 落地資料庫(案件 ID {case_id}),案件輸入檔是 {run_dir}/case.json(含使用者填寫的雙方當事人與統編)。不要再執行 `python main.py case`。這個檔案只給你(主 agent)判斷流程版本；不得把這個檔案或它的路徑交給任何 subagent。各角色只讀自己的角色檔：原告 `python main.py role-view --case-id {case_id} --role plaintiff`、被告 `python main.py role-view --case-id {case_id} --role defendant`、法官 `python main.py role-view --case-id {case_id} --role judge`(都加 `--out <檔>`);SKILL.md 或範本要填案件事實的地方，一律填該角色的角色檔。
2. 商工查核已由 UI 依使用者提供的統編完成(沒給統編的一方不查)。不要重新查核，也不要用名稱搜尋自行選定統編。
3. 所有暫存檔(角色檔、各階段 JSON、起訴狀 JSON、查證結果、訊問、評估、書狀草稿、引用清單)一律寫在 {run_dir}/ 之下，不要寫到其他位置。
4. 指令一律用 Bash 工具執行 `python main.py ...`(在目前目錄執行),一次一個指令，不要用迴圈或複合指令；其他 shell 指令會被拒絕。派 subagent 時把這一句寫進它的指示。
5. 落地論證時 model_id 填實際產生該論證的模型 ID。
6. 查證閘門或 `main.py` 的檢查指令報錯時照 SKILL.md 處理，不得繞過、不得自行改寫引用或事實；若因此無法完成某一步，停止並在最後回覆寫明卡在哪一步、原因為何。
7. subagent 的回覆被安全分類器中止時，依 SKILL.md「subagent 的回覆被安全分類器中止時」一節處理(另開新 subagent 以同一份範本重派，最多 2 次)。
8. {scope}
""" + (resume_instructions_v2(resume, run_dir, case_id) if resume else "")


def complaint_label(complaint):
    """續跑提示用：哪一版起訴狀、怎麼確認的。"""
    gate = complaint.get("gate") or {}
    kind = "律師編輯版" if complaint["source"] == "lawyer_edit" else "系統原稿"
    how = ("無人值守自動通過，未經律師確認" if gate.get("by") == "auto" else "使用者在 UI 確認") if gate else "尚未確認"
    return f"{kind} #{complaint['version_id']}({how})"


def resume_instructions_v2(plan, run_dir, case_id):
    head = f"""9. 本次是續跑。資料庫已落地：{"、".join(plan["landed"])}。這些紀錄一律不得覆寫、刪除或重新落地(SKILL.md「落地紀律」)。
   從 SKILL.md {plan["from_step"]}({plan["from_label"]})開始往下跑，不要再派 subagent 重做已落地的步驟。
   {run_dir}/landed.json 只給你(主 agent)看進度(哪些步驟落地了、起訴狀與爭點整理表是哪一版),不含論證全文；不要交給任何 subagent。各角色要讀前面步驟的內容時，照 SKILL.md 用角色檔與 `public-args`:被告只讀 `python main.py role-view --case-id {case_id} --role defendant`,法官讀 `--role judge`。
"""
    if plan["from_key"] in ("analysis", "complaint"):
        return head + "   Step 1 只做取得原告角色檔那一點。\n"
    side_note = ""
    if plan["missing_sides"]:
        missing = "、".join(SIDE_LABEL[x] for x in plan["missing_sides"])
        present = "、".join(SIDE_LABEL[x] for x in VALID_SIDES if x not in plan["missing_sides"])
        side_note = f"\n   {plan['from_label']}只有{present}已落地：只派{missing}的 subagent、只落地{missing}。"
    return head + f"""   關卡 1 已記錄：起訴狀以{complaint_label(plan["complaint"])}為準。之後各步驟需要起訴狀時一律讀這一版(角色檔的 complaint 就是這一版);不要改用資料庫裡的其他版本，也不要重新產生或落地起訴狀 v1。{side_note}
"""


def build_pleading_prompt(case_id, run_dir, documents):
    docs = documents_text(documents)
    sides = " / ".join(f"--side {side}" for side in documents)
    return f"""/legal-debate {case_id}

本次由 LegalDebate UI 以無人值守方式(claude -p)觸發，過程中沒有人能回答問題。只跑 .claude/skills/legal-debate/references/legacy-v1.md 的 Step 9C(只替既有案件補產書狀骨架;舊流程已從 SKILL.md 搬到該檔),不跑其他步驟；需要使用者決定的地方，依該檔最保守的做法處理，並在最後的回覆說明，不要停下來等待。

本次執行的固定條件：
1. 案件 {case_id} 的攻防、評估與查證結果已在資料庫，案件輸入檔是 {run_dir}/case.json。不要執行 `python main.py case`、`record`、`finalize`、`verdict`、`party`;既有紀錄一律不動。
2. 本次要產生的書狀：{docs}。使用者只選了這些，不要產生其他書狀。
3. 撰狀素材用 `python main.py pleading-source --case-id {case_id} --side <一方>` 取得({sides})。
4. 落地用 `python main.py pleading --case-id {case_id} --draft-file <檔案> --citations <檔案> --side <一方>`,一份書狀落地一次。
5. 所有暫存檔(書狀草稿、引用清單、查證用的清單)一律寫在 {run_dir}/ 之下，不要寫到其他位置。
6. 指令一律用 Bash 工具執行 `python main.py ...`(在目前目錄執行),一次一個指令，不要用迴圈或複合指令；其他 shell 指令會被拒絕。派 subagent 時把這一句寫進它的指示。
7. 查證閘門報錯時照 legacy-v1.md 處理，不得繞過、不得自行改寫引用；未通過查證的引用不寫進書狀，並在最後回覆列出。
8. subagent 的回覆被安全分類器中止時，依 SKILL.md「subagent 的回覆被安全分類器中止時」一節處理(另開新 subagent 以同一份範本重派，最多 2 次)。
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


USAGE_FIELDS = (("inputTokens", "input_tokens"), ("outputTokens", "output_tokens"),
                ("cacheReadInputTokens", "cache_read_input_tokens"),
                ("cacheCreationInputTokens", "cache_creation_input_tokens"))


def token_usage(result):
    """整次執行(含 subagent)的 token 數。實測(CLI 2.1.312)result 事件的 modelUsage 與 total_cost_usd 一樣是累計值，
    usage 欄只是主 agent 最後一輪，所以取 modelUsage 依模型加總。沒有 modelUsage 時回傳 None,不拿 usage 充數。"""
    by_model = {}
    for model, u in ((result or {}).get("modelUsage") or {}).items():
        if isinstance(u, dict):
            by_model[model] = {key: int(u.get(src) or 0) for src, key in USAGE_FIELDS}
    if not by_model:
        return None
    total = {key: sum(m[key] for m in by_model.values()) for _, key in USAGE_FIELDS}
    return {**total, "by_model": by_model}


def usage_from_log(path):
    """從已存的 stream-json 取最後一筆 result 的 token 數(舊執行補登用)。"""
    last = None
    try:
        with open(path, "rb") as f:
            for raw in f:
                try:
                    obj = json.loads(raw.decode("utf-8", "replace"))
                except ValueError:
                    continue
                if obj.get("type") == "result":
                    last = obj
    except OSError:
        return None
    return token_usage(last)


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
                "已落地的階段保留，額度重置後可從尚未落地的階段續跑")
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


def _system_pleadings(session, case_id, side):
    """該方流程產生的主要書狀(起訴狀或答辯狀);律師編輯版與之後的模擬準備書狀不算。"""
    return [r for r in session.query(PleadingDraft).filter_by(case_id=case_id).all()
            if r.source in (None, "system") and is_main_pleading(r, side)]


def pleading_blocker(session, case_id, documents):
    """補產書狀(Step 9C)的前提：每份要產的書狀，該方都已有 Stage 3、且還沒有該份書狀。可以執行時回傳 None,否則回傳原因。"""
    if session.query(Case).filter_by(case_id=case_id).one_or_none() is None:
        return f"找不到案件 {case_id}(必須先落地資料庫)"
    for side in documents:
        if not session.query(DebateArgument).filter_by(case_id=case_id, side=side, stage=3).count():
            return f"此案件還沒有{SIDE_LABEL[side]} Stage 3,不能只產{DOC_LABEL[side]};須先跑完攻防"
        if _system_pleadings(session, case_id, side):
            return f"此案件已有{DOC_LABEL[side]}骨架，不重複產生"
    return None


def pipeline_missing(session, case_id, kind="full", since=None, documents=VALID_SIDES, stop_after=None):
    """依資料庫實況列出流程還缺哪些落地紀錄(不看 Claude 怎麼說，只看資料庫)。書狀只檢查使用者選的那幾份；
    kind=pleadings 只看本次執行開始(since)之後有沒有落地選定的書狀。書狀交換流程依停止點檢查(見 _pipeline_missing_v2)。"""
    case = session.query(Case).filter_by(case_id=case_id).one_or_none()
    if kind == "full" and case is not None and case.protocol == "v2":
        return _pipeline_missing_v2(session, case_id, stop_after)
    if kind == "pleadings":
        return [DOC_LABEL[side] + "骨架" for side in documents
                if not [r for r in _system_pleadings(session, case_id, side) if since is None or r.generated_at >= since]]
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
    for side in documents:
        if not _system_pleadings(session, case_id, side):
            missing.append(DOC_LABEL[side] + "骨架")
    return missing


def _v2_done(session, case_id):
    """書狀交換流程各步驟落地了沒有，只看資料庫(審查 A1)。回傳 ({步驟: 是否完成}, {分方步驟: 已落地的方})。"""
    sides = {stage: set() for stage in (1, 2, 3)}
    for a in session.query(DebateArgument).filter_by(case_id=case_id).all():
        sides.setdefault(a.stage, set()).add(a.side)
    rows = [r for r in session.query(PleadingDraft).filter_by(case_id=case_id).all() if r.source in (None, "system")]
    kind_sides = {kind: {pleading_side(r) for r in rows if r.pleading_type == kind} for kind in ("brief", "closing")}
    case = session.query(Case).filter_by(case_id=case_id).one_or_none()
    per_side = {"stage2": sides[2], "brief": kind_sides["brief"], "stage3": sides[3], "closing": kind_sides["closing"]}
    done = {"analysis": "plaintiff" in sides[1], "complaint": bool(system_complaints(session, case_id)),
            "gate1": case is not None and case_gates(case).get("complaint") is not None,
            "defense": "defendant" in sides[1],
            "answer": bool(_system_pleadings(session, case_id, "defendant")),
            "issue_sheet": session.query(IssueSheet).filter_by(case_id=case_id).count() > 0,
            **{key: value >= set(VALID_SIDES) for key, value in per_side.items()},
            "verdict": session.query(Verdict).filter_by(case_id=case_id).count() > 0,
            "revision": any(r.pleading_type == "complaint" and r.source == "system_revision"
                            for r in session.query(PleadingDraft).filter_by(case_id=case_id).all())}
    return done, per_side


def _pipeline_missing_v2(session, case_id, stop_after):
    """書狀交換流程：依停止點檢查到那一步為止;不指定停止點時看到起訴狀 v2。關卡 1 不是落地紀錄，不列。"""
    done, per_side = _v2_done(session, case_id)
    last = STOP_KEY.get(stop_after, "revision")
    missing = []
    for key, label, _, _ in RUN_STEPS_V2:
        if key == "gate1" or done[key]:
            pass
        elif key in per_side:
            missing += [f"{SIDE_LABEL[side]}{label}" for side in VALID_SIDES if side not in per_side[key]]
        else:
            missing.append(label)
        if key == last:
            break
    return missing


SIDE_LABEL = {"plaintiff": "原告", "defendant": "被告"}
# 續跑的步驟順序(key, 名稱, SKILL.md 起點)。Step 6–8(finalize、查證)不落地，以評估落地為準。
RESUME_STEPS = (("stage1", "Stage 1 爭點整理", "Step 2"), ("questions", "法官訊問", "Step 3"),
                ("stage2", "Stage 2 訊問攻防", "Step 4"), ("stage3", "Stage 3 辯論終結", "Step 5"),
                ("verdict", "爭點強弱評估", "Step 6"), ("pleading", "書狀骨架", "Step 9"))


# 書狀交換流程的步驟(key, 名稱, 文件, SKILL.md 起點),照規格第 4 節的順序(審查 A1)。gate1 不是落地紀錄，是 Case.gates_json 的關卡 1。
# stage2、brief、stage3、closing 兩方各一份，名稱前面加「原告」「被告」。Step 編號照計畫第 3 節 W4–W7(Step 4–5、7–8、9–12),
# 回報是 Step 13。CLI:defense=record、answer=answer、issue_sheet=issue-sheet、stage2/stage3=record、brief=brief --round 2、
# closing=brief --round 3、verdict=verdict、revision=revision。
RUN_STEPS_V2 = (("analysis", "原告請求權基礎檢驗", "SKILL.md", "Step 2"), ("complaint", "起訴狀 v1", "SKILL.md", "Step 3"),
                ("gate1", "關卡 1", None, None),
                ("defense", "被告防禦分析", "SKILL.md", "Step 4"), ("answer", "被告答辯狀", "SKILL.md", "Step 5"),
                ("issue_sheet", "爭點整理表", "SKILL.md", "Step 6"),
                ("stage2", "第 2 輪論證", "SKILL.md", "Step 7"), ("brief", "準備書狀", "SKILL.md", "Step 7"),
                ("stage3", "第 3 輪論證", "SKILL.md", "Step 8"), ("closing", "言詞辯論意旨狀", "SKILL.md", "Step 8"),
                ("verdict", "診斷評估", "SKILL.md", "Step 9"), ("revision", "起訴狀 v2", "SKILL.md", "Step 12"))
# 停止點對應的最後一步與 SKILL.md 的 Step
STOP_KEY = {"complaint": "complaint", "answer": "answer", "issue_sheet": "issue_sheet"}
STOP_STEP = {"answer": "Step 5", "issue_sheet": "Step 6"}


def _gate_landed(gate):
    if gate["action"] == "finish":
        return f"關卡 1(到此結束，起訴狀 #{gate['version_id']})"
    if gate["by"] == "auto":
        return f"關卡 1(自動通過，未經律師確認，起訴狀 #{gate['version_id']})"
    return f"關卡 1(確認起訴狀 #{gate['version_id']})"


def _empty_plan(landed, landed_keys, **extra):
    return {"possible": False, "reason": None, "landed": landed, "landed_keys": landed_keys,
            "from_key": None, "from_label": None, "from_step": None, "from_doc": None, "missing_sides": [],
            "stop_after_allowed": False, "gate_pending": False, **extra}


def _resume_plan_v2(session, case):
    case_id = case.case_id
    gate = case_gates(case).get("complaint")
    done, per_side = _v2_done(session, case_id)
    touched = {key: done[key] or bool(per_side.get(key)) for key in done}
    landed = []
    for key, label, _, _ in RUN_STEPS_V2:
        if key == "gate1" and gate:
            landed.append(_gate_landed(gate))
        elif done[key]:
            landed.append(label)
        elif touched[key]:
            landed.append(label + "(僅" + "、".join(SIDE_LABEL[x] for x in VALID_SIDES if x in per_side[key]) + ")")
    complaint = current_complaint(session, case_id)
    plan = _empty_plan(landed, [k for k in done if done[k]], protocol="v2", gate=gate, stop_after_options=[],
                       complaint={k: v for k, v in complaint.items() if k != "draft_text"} if complaint else None)
    if not any(touched.values()):
        plan["reason"] = "此案件沒有落地紀錄，直接開始執行即可"
        return plan
    if gate and gate["action"] == "finish":
        plan["reason"] = f"已在關卡 1 選擇到此結束(起訴狀 #{gate['version_id']}),此案件不再往下跑"
        return plan
    first = next((i for i, (key, *_) in enumerate(RUN_STEPS_V2) if not done[key]), None)
    if first is None:
        plan["reason"] = "各階段皆已落地，沒有需要續跑的步驟"
        return plan
    later = [label for key, label, _, _ in RUN_STEPS_V2[first + 1:] if touched[key]]
    if later:
        plan["reason"] = (f"資料庫的落地紀錄不連續({RUN_STEPS_V2[first][1]}未落地，但{'、'.join(later)}已落地)，"
                          "無法判斷該從哪裡續跑；請建立新案件")
        return plan
    key, label, doc, step = RUN_STEPS_V2[first]
    if key == "gate1":
        plan.update(gate_pending=True,
                    reason="起訴狀 v1 已落地，等待關卡 1:請在「訴狀骨架」分頁選定要用的版本，確認並繼續，或到此結束")
        return plan
    keys = [k for k, *_ in RUN_STEPS_V2]
    # 停止點要在續跑起點之後(含起點那一步);只跑到起訴狀的停止點過了關卡 1 就不能再選
    options = [stop for stop in STOP_AFTER if keys.index(STOP_KEY[stop]) >= first
               and (stop == "complaint") == (first < keys.index("gate1"))]
    plan.update(possible=True, from_key=key, from_label=label, from_step=step, from_doc=doc,
                missing_sides=[x for x in VALID_SIDES if x not in per_side[key]] if key in per_side else [],
                stop_after_allowed="complaint" in options, stop_after_options=options)
    return plan


def resume_plan(session, case_id):
    """依資料庫實況找出第一個尚未落地的步驟，從那裡續跑；已落地的紀錄不重做、不覆寫。
    落地不連續(前面缺、後面有)或沒有需要續跑的步驟時，possible 為 False 並說明原因。
    書狀交換流程(protocol v2)見 _resume_plan_v2:起訴狀落地後要先過關卡 1。"""
    case = session.query(Case).filter_by(case_id=case_id).one_or_none()
    if case is not None and case.protocol == "v2":
        return _resume_plan_v2(session, case)
    sides = {stage: set() for stage in (1, 2, 3)}
    for a in session.query(DebateArgument).filter_by(case_id=case_id).all():
        sides.setdefault(a.stage, set()).add(a.side)
    done = {"stage1": sides[1] >= set(VALID_SIDES),
            "questions": session.query(CourtQuestion).filter_by(case_id=case_id).count() > 0,
            "stage2": sides[2] >= set(VALID_SIDES), "stage3": sides[3] >= set(VALID_SIDES),
            "verdict": session.query(Verdict).filter_by(case_id=case_id).count() > 0,
            # 任一份書狀已落地即算做過 Step 9;使用者當時沒選的另一份用「補產書狀」(Step 9C)
            "pleading": any(_system_pleadings(session, case_id, side) for side in VALID_SIDES)}
    stage_sides = {f"stage{n}": sides[n] for n in (1, 2, 3)}
    touched = {key: done[key] or bool(stage_sides.get(key)) for key in done}
    landed = []
    for key, label, _ in RESUME_STEPS:
        if done[key]:
            landed.append(label)
        elif touched[key]:
            landed.append(label + "(僅" + "、".join(SIDE_LABEL[x] for x in VALID_SIDES if x in stage_sides[key]) + ")")
    plan = _empty_plan(landed, [k for k in done if done[k]])
    if not any(touched.values()):
        plan["reason"] = "此案件沒有落地紀錄，直接開始執行即可"
        return plan
    first = next((i for i, (key, _, _) in enumerate(RESUME_STEPS) if not done[key]), None)
    if first is None:
        plan["reason"] = "各階段皆已落地，沒有需要續跑的步驟"
        return plan
    later = [label for key, label, _ in RESUME_STEPS[first + 1:] if touched[key]]
    if later:
        plan["reason"] = (f"資料庫的落地紀錄不連續({RESUME_STEPS[first][1]}未落地，但{'、'.join(later)}已落地)，"
                          "無法判斷該從哪裡續跑；請建立新案件")
        return plan
    key, label, step = RESUME_STEPS[first]
    plan.update(possible=True, from_key=key, from_label=label, from_step=step, from_doc=LEGACY_DOC,
                missing_sides=[x for x in VALID_SIDES if x not in stage_sides[key]] if key in stage_sides else [])
    return plan


def export_landed(session, case_id):
    """續跑時交給 Claude Code 的已落地紀錄(唯讀副本，資料庫才是正本)。"""
    def loads(text):
        try:
            return json.loads(text) if text else []
        except ValueError:
            return text
    verdict = session.query(Verdict).filter_by(case_id=case_id).one_or_none()
    case = session.query(Case).filter_by(case_id=case_id).one_or_none()
    if case is not None and case.protocol == "v2":
        return _export_landed_v2(session, case_id, verdict)
    return {
        "case_id": case_id,
        "note": "由 LegalDebate UI 從資料庫匯出的已落地紀錄，僅供續跑時讀取；這些紀錄不得覆寫、刪除或重新落地。",
        "arguments": [{"side": a.side, "stage": a.stage, "position": a.position, "argument": a.reasoning,
                       "cited_statutes": loads(a.cited_statutes), "cited_precedents": loads(a.cited_precedents),
                       "falsifier": a.falsifier, "model_id": a.model_id, "created_at": a.created_at}
                      for a in session.query(DebateArgument).filter_by(case_id=case_id)
                      .order_by(DebateArgument.stage, DebateArgument.side).all()],
        "court_questions": [{"question_text": q.question_text, "target_side": q.target_side, "based_on": q.based_on}
                            for q in session.query(CourtQuestion).filter_by(case_id=case_id).order_by(CourtQuestion.id).all()],
        "verdict": None if verdict is None else {
            "verdict_main_text": verdict.verdict_main_text, "verdict_analysis": verdict.verdict_reasoning,
            "risk_map": loads(verdict.risk_map), "mechanical_anchor_json": loads(verdict.mechanical_anchor_json)},
    }


def _export_landed_v2(session, case_id, verdict):
    """書狀交換流程的 landed.json 只給主 agent 看進度(審查 A4):論證只列哪一方哪一輪落地了，不含全文
    (stage 1 是各方分析，有內部檢討;被告與法官讀到原告分析就破壞隔離)。各角色要讀的內容照 SKILL.md 用角色檔與 public-args。"""
    from database.db import issue_sheet
    complaint = current_complaint(session, case_id)
    rows = session.query(PleadingDraft).filter_by(case_id=case_id).order_by(PleadingDraft.id).all()
    return {
        "case_id": case_id,
        "note": ("由 LegalDebate UI 從資料庫匯出的進度，只給主 agent 判斷從哪裡續跑，不要交給任何 subagent。"
                 "論證全文不在這裡；這些紀錄不得覆寫、刪除或重新落地。"),
        "arguments": [{"side": a.side, "stage": a.stage, "created_at": a.created_at}
                      for a in session.query(DebateArgument).filter_by(case_id=case_id)
                      .order_by(DebateArgument.stage, DebateArgument.side).all()],
        # 關卡 1 確認的那一版(可能是律師編輯版);還沒確認時是 None,不拿未確認的原稿充數
        "confirmed_complaint": complaint if complaint and complaint["confirmed"] else None,
        "pleadings": [{"id": r.id, "side": pleading_side(r), "pleading_type": r.pleading_type, "round": r.round,
                       "source": r.source or "system"} for r in rows if r.pleading_type],
        "issue_sheet": issue_sheet(session, case_id),
        "verdict": None if verdict is None else {"id": verdict.id, "protocol_version": verdict.protocol_version},
    }


def _notes(row):
    try:
        notes = json.loads(row.notes_json) if row.notes_json else {}
    except ValueError:
        return {}
    return notes if isinstance(notes, dict) else {}


def _usage(row):
    try:
        usage = json.loads(row.usage_json) if row.usage_json else None
    except ValueError:
        return None
    return usage if isinstance(usage, dict) else None


def run_to_dict(row):
    notes = _notes(row)
    return {"id": row.id, "case_id": row.case_id, "kind": row.kind or "full", "documents": stored_documents(row),
            "status": row.status, "started_at": row.started_at,
            "ended_at": row.ended_at, "model": row.model,
            "budget_usd": float(row.budget_usd) if row.budget_usd else None,
            "cost_usd": float(row.cost_usd) if row.cost_usd else None,
            "exit_code": row.exit_code, "error": row.error, "log_path": row.log_path,
            "safety_stops": notes.get("safety_stops") or [], "quota": notes.get("quota"),
            "resume_from": notes.get("resume_from"), "tokens": _usage(row), "stop_after": row.stop_after}


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
    def __init__(self, run_id, case_id, proc, events_path=None, kind="full", started_at=None, resume_from=None,
                 documents=VALID_SIDES, protocol=None, stop_after=None):
        self.run_id, self.case_id, self.proc = run_id, case_id, proc
        self.kind, self.started_at, self.documents = kind, started_at, documents
        self.protocol, self.stop_after = protocol, stop_after
        self.resume_from = resume_from
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
                 model=DEFAULT_MODEL, budget_usd=DEFAULT_BUDGET_USD, max_minutes=DEFAULT_MAX_MINUTES, runs_dir=None,
                 exclude=()):
        # 排除清單在啟動時就要能解析(字號或 JID),錯了直接不啟動，不要到實跑才發現沒排除到
        exclusion_keys(exclude)
        self.exclude = list(dict.fromkeys(v.strip() for v in exclude if v.strip()))
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

    def case_dir(self, case_id):
        """案件層級資料夾(絕對路徑)：快照 retrieval_cache/ 與檢索紀錄 search_logs/ 跨多次執行沿用。"""
        return os.path.join(self.runs_dir, f"{CASE_DIR_PREFIX}{case_id}")

    def _run_dir(self, run_id):
        """給 Claude 與存進 DB 的路徑：在專案內用相對路徑(正斜線),否則用絕對路徑。"""
        abs_dir = os.path.join(self.runs_dir, f"run-{run_id}")
        try:
            rel = os.path.relpath(abs_dir, self.root)
        except ValueError:  # Windows 不同磁碟機
            rel = ".."
        return rel.replace("\\", "/") if not rel.startswith("..") else abs_dir.replace("\\", "/")

    # ── 啟動 ──
    def resume_plan(self, case_id):
        with self.factory() as s:
            plan = resume_plan(s, case_id)
            if plan["possible"] and not s.query(LiveRun).filter_by(case_id=case_id).count():
                plan.update(possible=False, reason="此案件的紀錄不是 UI 即時執行產生的(錄製紀錄),不提供續跑")
        return plan

    def _protocol(self, case_id):
        with self.factory() as s:
            case = s.query(Case).filter_by(case_id=case_id).one_or_none()
            return case.protocol if case is not None else None

    def start(self, case_id, kind="full", resume=False, documents=None, stop_after=None):
        """回傳 run dict;不能執行時 raise PermissionError(未啟用)或 ValueError(案件狀態不允許)。
        kind=full 跑完整流程:新案件從頭跑;resume=True 時從第一個尚未落地的步驟續跑(見 resume_plan),已落地的紀錄不覆寫。
        kind=pleadings 只補產書狀(見 pleading_blocker)。documents 是使用者選的書狀(plaintiff/defendant),
        完整流程未指定時兩份都產。
        書狀交換流程(protocol v2)不選書狀，改由 stop_after 決定:complaint=只跑到起訴狀 v1,停在關卡 1;
        不指定時跑完全程，關卡 1 在結束時記為自動通過(見 _auto_gate)。"""
        if kind not in RUN_KINDS:
            raise ValueError(f"非法的執行種類:{kind}")
        if resume and kind != "full":
            raise ValueError("補產書狀的執行沒有續跑")
        if stop_after not in (None, *STOP_AFTER):
            raise ValueError(f"非法的停止點:{stop_after}(只能是 {'、'.join(STOP_AFTER)})")
        protocol = self._protocol(case_id)
        if protocol == "v2":
            if kind != "full":
                raise ValueError("書狀交換流程的案件沒有補產書狀(Step 9C 是舊流程):起訴狀在 P1 產生，答辯狀在關卡 1 之後的續跑產生")
            if documents is not None:
                raise ValueError("書狀交換流程依停止點決定產出，不選書狀(只產起訴狀，或跑完全程)")
        elif stop_after is not None:
            raise ValueError("只有書狀交換流程(protocol v2)的案件可以指定停止點")
        else:
            documents = normalize_documents(documents, kind)
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
                plan = None
                if kind == "pleadings":
                    blocker = pleading_blocker(s, case_id, documents)
                    if blocker:
                        raise ValueError(blocker)
                elif resume:
                    plan = self.resume_plan(case_id)
                    if not plan["possible"]:
                        raise ValueError(f"無法續跑：{plan['reason']}")
                    if stop_after and stop_after not in plan.get("stop_after_options", []):
                        raise ValueError(f"續跑起點「{plan['from_label']}」已過了停止點「{STOP_LABEL[stop_after]}」" +
                                         ("(或已在關卡 1 之後，不能再只跑到起訴狀)" if stop_after == "complaint" else ""))
                else:
                    existing = sum(s.query(m).filter_by(case_id=case_id).count()
                                   for m in (DebateArgument, CourtQuestion, Verdict, PleadingDraft))
                    if existing:
                        raise ValueError("此案件已有攻防或書狀紀錄。落地紀錄不可覆寫，不能整件重跑；"
                                         "可從尚未落地的階段續跑，或建立新案件")
                landed_export = export_landed(s, case_id) if plan else None
                # 關卡 1 還沒記錄、又沒有停止點：這次執行會越過關卡(結束時記為自動通過)
                auto_gate = protocol == "v2" and stop_after != "complaint" and not case_gates(case).get("complaint")
                row = LiveRun(case_id=case_id, status="running", started_at=_now_iso(), model=self.model,
                              budget_usd=str(self.budget_usd), kind=kind, stop_after=stop_after,
                              documents=",".join(documents) if documents else None,
                              # 續跑起點先存，執行中畫面就看得到；結束時與觀察結果一起覆寫
                              notes_json=json.dumps({"resume_from": plan["from_label"]}, ensure_ascii=False) if plan else None)
                s.add(row)
                s.commit()
                run_id, started_at = row.id, row.started_at
                run_dir = self._run_dir(run_id)
                row.log_path = f"{run_dir}/stream.jsonl"
                s.commit()
                input_payload = case_payload(case)
            abs_dir = self._log_abs(run_dir)
            os.makedirs(abs_dir, exist_ok=True)
            with open(os.path.join(abs_dir, "case.json"), "w", encoding="utf-8") as f:
                json.dump(input_payload, f, ensure_ascii=False, indent=2)
            if landed_export:
                with open(os.path.join(abs_dir, "landed.json"), "w", encoding="utf-8") as f:
                    json.dump(landed_export, f, ensure_ascii=False, indent=2)
            prompt = (build_pleading_prompt(case_id, run_dir, documents) if kind == "pleadings"
                      else build_prompt(case_id, run_dir, plan, documents, protocol=protocol, stop_after=stop_after))
            # 交給 Claude Code 的指示另存一份，事後可核對這次執行被要求做什麼(例如續跑讀哪一版起訴狀)
            with open(os.path.join(abs_dir, "prompt.txt"), "w", encoding="utf-8") as f:
                f.write(prompt)
            args = build_args(self.command, prompt, model=self.model, budget_usd=self.budget_usd)
            env = dict(os.environ)
            env[DB_URL_ENV] = self.db_url or env.get(DB_URL_ENV) or f"sqlite:///{default_db_path()}"
            env["CLAUDE_CODE_SUBAGENT_MODEL"] = self.model  # CLI 2.1.251 前此變數優先於 Agent 的 model 參數
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"
            # 案件快照根目錄：查證與判例落地以此比對雙方讀過的同一版本(engine/retrieval_cache.py)。
            # 各角色的檢索指令另以 --snapshot 指定 <根目錄>/plaintiff 或 defendant，不讀這個環境變數。
            env[SNAPSHOT_ENV] = os.path.join(self.case_dir(case_id), "retrieval_cache")
            # 伺服器設定的排除清單(示範案的來源裁判,審查 A5):檢索指令自己套用，不寫進 prompt
            if self.exclude:
                env[EXCLUDE_ENV] = ";".join(self.exclude)
            else:
                env.pop(EXCLUDE_ENV, None)
            popen_kw =({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "CREATE_NO_WINDOW", 0)}
                        if os.name == "nt" else {"start_new_session": True})
            stderr_file = open(os.path.join(abs_dir, "stderr.log"), "wb")
            try:
                proc = subprocess.Popen(args, cwd=self.root, env=env, stdin=subprocess.DEVNULL,
                                        stdout=subprocess.PIPE, stderr=stderr_file, **popen_kw)
            except OSError as e:
                stderr_file.close()
                self._finish(run_id, "failed", error=f"無法啟動 Claude Code:{e}")
                raise ValueError(f"無法啟動 Claude Code:{e}")
            active = _Active(run_id, case_id, proc, events_path=os.path.join(abs_dir, EVENTS_FILE),
                             kind=kind, started_at=started_at, resume_from=plan["from_label"] if plan else None,
                             documents=documents, protocol=protocol, stop_after=stop_after)
            self._active = active
            scope = ""
            if protocol == "v2":
                scope = ("。只產起訴狀：起訴狀 v1 落地後停在關卡 1,等律師確認" if stop_after == "complaint"
                         else (f"。跑到{STOP_LABEL[stop_after]}就停" if stop_after else "。跑完全程" if auto_gate else "。跑完剩下的流程")
                         + ("：關卡 1 自動通過(未經律師確認)" if auto_gate else ""))
            elif kind == "full":
                scope = f"。產生書狀：{documents_text(documents)}"
            self._append(active, "info", f"已啟動執行 #{run_id}" +
                         (f"(只補產{documents_text(documents)},Step 9C)" if kind == "pleadings" else "") +
                         f"(模型 {self.model},花費上限 {self.budget_usd:g} 美元)" + scope +
                         (f"。續跑：從{plan['from_label']}開始，已落地的{'、'.join(plan['landed'])}不重做、不覆寫" if plan else ""))
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
            gate = self._auto_gate(s, active)
            missing = pipeline_missing(s, active.case_id, kind=active.kind, since=active.started_at, documents=active.documents,
                                       stop_after=active.stop_after)
        if gate:
            self._append(active, "info", f"關卡 1 自動通過：本次執行未指定停止點，流程以系統原稿 #{gate['version_id']} 繼續往下跑；"
                                         "未經律師確認，已記錄在案件的關卡紀錄")
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
        if active.resume_from:
            notes["resume_from"] = active.resume_from
        stops = notes["safety_stops"]
        who = "、".join(s["who"] for s in stops)
        if stops and status == "incomplete":
            # Claude Code 自己回報完成但資料庫缺階段：沒有其他明確原因，分類器中止是最可能的解釋，但仍只是推斷
            error += (f"。執行期間有 {len(stops)} 次回覆被 Anthropic 安全分類器中止({who}),"
                      "很可能就是流程沒跑完的原因;請以執行紀錄與 Claude Code 最後回覆核對。這不是程式錯誤，可從尚未落地的階段續跑")
        elif stops and status == "failed":  # 已有明確失敗原因(花費上限、429、逾時…),只附註不歸因
            error += f"。另外，執行期間有 {len(stops)} 次回覆被 Anthropic 安全分類器中止({who})"
        self._append(active, "error" if status != "succeeded" else "result",
                     {"succeeded": (f"執行完成，{documents_text(active.documents)}骨架已落地資料庫" if active.kind == "pleadings"
                                    else "執行完成，起訴狀 v1 已落地資料庫，等待律師在關卡 1 確認" if active.stop_after == "complaint"
                                    else f"執行完成，已跑到{STOP_LABEL[active.stop_after]}並落地資料庫，可從下一步續跑" if active.stop_after
                                    else "執行完成，各階段皆已落地資料庫"),
                      "incomplete": "執行結束但流程不完整",
                      "cancelled": "已取消", "failed": "執行失敗"}[status] + (f":{error}" if error else ""))
        if stops and status == "succeeded":
            self._append(active, "warn", f"執行期間有 {len(stops)} 次回覆被安全分類器中止({who})。"
                                         "依 SKILL.md 被中止的輸出不得落地、應另開 subagent 重派;請以執行紀錄與最後回覆核對")
        self._finish(active.run_id, status, error=error, cost=cost, exit_code=code, notes=notes,
                     usage=token_usage(active.result))
        with self._lock:
            if self._active is active:
                self._active = None

    @staticmethod
    def _auto_gate(session, active):
        """書狀交換流程的執行沒有停止點(或停止點在關卡 1 之後)、而且流程確實越過了關卡 1(起訴狀之後的階段有落地)時，記錄關卡 1 自動通過，
        標「未經律師確認」。起訴狀落地後就停下來的執行(例如中途失敗或取消)不記，律師之後仍可確認。回傳記錄的內容或 None。"""
        if active.protocol != "v2" or active.kind != "full" or active.stop_after == "complaint":
            return None
        case = session.query(Case).filter_by(case_id=active.case_id).one_or_none()
        complaints = system_complaints(session, active.case_id)
        if case is None or case_gates(case).get("complaint") or not complaints:
            return None
        beyond = (session.query(DebateArgument).filter_by(case_id=active.case_id)
                  .filter(or_(DebateArgument.side == "defendant", DebateArgument.stage > 1)).count()
                  or session.query(CourtQuestion).filter_by(case_id=active.case_id).count()
                  or session.query(Verdict).filter_by(case_id=active.case_id).count()
                  or _system_pleadings(session, active.case_id, "defendant"))
        if not beyond:
            return None
        try:
            return record_gate(session, case_id=active.case_id, gate="complaint", version_id=complaints[-1].id,
                               action="continue", by="auto", run_id=active.run_id, note=AUTO_GATE_NOTE)
        except (LookupError, ValueError):
            session.rollback()
            return None

    @staticmethod
    def _stderr_tail(abs_dir, n=600):
        try:
            with open(os.path.join(abs_dir, "stderr.log"), "rb") as f:
                return _short(f.read()[-4000:].decode("utf-8", "replace"), n)
        except OSError:
            return ""

    def _finish(self, run_id, status, *, error=None, cost=None, exit_code=None, notes=None, usage=None):
        with self.factory() as s:
            row = s.get(LiveRun, run_id)
            row.status, row.ended_at, row.error, row.exit_code = status, _now_iso(), error, exit_code
            row.cost_usd = str(cost) if isinstance(cost, (int, float)) else None
            if notes is not None:
                row.notes_json = json.dumps(notes, ensure_ascii=False)
            if usage is not None:
                row.usage_json = json.dumps(usage, ensure_ascii=False)
            s.commit()

    def _backfill_notes(self):
        """notes_json 欄位加入前結束的執行，從存檔的 stream-json 補登(例如 2026-10-29 執行 #4 的那次中止)。"""
        with self.factory() as s:
            # 續跑在啟動時就先存了 resume_from,執行途中後端重啟的話 notes_json 不是 NULL 但還沒有觀察結果，一併補登
            for row in s.query(LiveRun).filter(or_(LiveRun.notes_json.is_(None), LiveRun.notes_json.notlike('%"safety_stops"%')),
                                               LiveRun.status != "running").all():
                notes = observe_log(self._log_abs(row.log_path)) if row.log_path else None
                if notes is not None:
                    row.notes_json = json.dumps({**_notes(row), **notes}, ensure_ascii=False)
            # token 數欄位加入前結束的執行(2026-10-28 #1 起)同樣從 stream-json 補登
            for row in s.query(LiveRun).filter(LiveRun.usage_json.is_(None), LiveRun.status != "running").all():
                usage = usage_from_log(self._log_abs(row.log_path)) if row.log_path else None
                if usage is not None:
                    row.usage_json = json.dumps(usage, ensure_ascii=False)
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


def options_for_host(host, *, model=None, budget_usd=None, exclude=()):
    """main.py serve 依綁定位址決定是否啟用即時執行。

    即時執行會以本機使用者的 Claude 帳號跑有工具權限的 Claude Code,本服務又沒有登入驗證；
    綁 0.0.0.0 等於讓區網內任何連得到的人在這台電腦上執行程式並花用帳號額度，所以整個停用，不做半套保護。"""
    if is_loopback_host(host):
        opts = {"enabled": True, "model": model or DEFAULT_MODEL,
                "budget_usd": budget_usd if budget_usd is not None else DEFAULT_BUDGET_USD}
        return {**opts, "exclude": list(exclude)} if exclude else opts
    return {"enabled": False,
            "reason": f"以 --host {host} 啟動，非僅限本機；即時執行只在綁定 127.0.0.1 時開放"}
