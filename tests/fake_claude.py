"""測試用的假 Claude Code:不呼叫任何模型，只模擬 `claude -p --output-format stream-json` 的輸出格式，
並依 FAKE_CLAUDE_MODE 把固定內容寫進 LEGALDEBATE_DB_URL 指向的資料庫(驗證後端有把同一顆 DB 交給子程序)。

模式：full(跑完整流程) / partial(只落地 Stage 1 就回報完成) / budget(花費上限中止) / api_error(API 錯誤)
      / crash(無 result 直接崩潰) / hang(卡住等取消)。
FAKE_CLAUDE_AUTH=0 模擬未登入；FAKE_CLAUDE_DELAY(秒)讓每次落地之間停頓，方便在瀏覽器看進度。
FAKE_CLAUDE_SAFETY=1 在被告 Stage 1 插入一則「回覆被安全分類器中止」的通知(格式照 2026-10-29 執行 #4 的 stream-json);
FAKE_CLAUDE_QUOTA=1 在開始與結束各送一則 rate_limit_event(訂閱額度);FAKE_CLAUDE_STOP_AFTER_S1=budget 在 Stage 1 落地後以花費上限中止。
prompt 是續跑(第 8 點)時，照 prompt 的指示跳過資料庫已有的紀錄，並確認 landed.json 存在；
FAKE_CLAUDE_FORCE_RELAND=1 則故意重新落地已有的紀錄，驗證資料庫層會拒絕覆寫。
"""
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from database.db import (  # noqa: E402
    finalize_case, get_session, record_argument, record_pleading, record_question, record_verdict,
)
from database.schema import CourtQuestion, DebateArgument, PleadingDraft, Verdict  # noqa: E402


def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def tool(name, inp, parent=None):
    emit({"type": "assistant", "parent_tool_use_id": parent,
          "message": {"content": [{"type": "tool_use", "id": "t", "name": name, "input": inp}]}})


def landed(text, parent=None):
    time.sleep(float(os.environ.get("FAKE_CLAUDE_DELAY", "0")))
    emit({"type": "user", "parent_tool_use_id": parent,
          "message": {"content": [{"type": "tool_result", "tool_use_id": "t", "content": text}]}})


def safety_stop(task):
    emit({"type": "user", "parent_tool_use_id": "toolu_agent", "task_description": task, "isSynthetic": True,
          "message": {"role": "user", "content": [{"type": "text", "text": (
              "Your response above was stopped by a safety classifier — this is not a tool or API error. "
              "The rest of it was withheld, and tool calls in it that had not finished did not run.")}]}})


def quota(five_hour, seven_day):
    emit({"type": "rate_limit_event", "rate_limit_info": {"status": "allowed_warning", "unifiedWindows": {
        "five_hour": {"utilization": five_hour, "resetsAt": 1793269800, "status": "allowed"},
        "seven_day": {"utilization": seven_day, "resetsAt": 1793548800, "status": "allowed_warning"}}}})


def main():
    argv = sys.argv[1:]
    if argv[:2] == ["auth", "status"]:
        logged_in = os.environ.get("FAKE_CLAUDE_AUTH", "1") == "1"
        print(json.dumps({"loggedIn": logged_in, "authMethod": "claude.ai" if logged_in else "none"}))
        return 0 if logged_in else 1
    prompt = argv[argv.index("-p") + 1]
    case_id = re.match(r"/legal-debate (\S+)", prompt).group(1)
    run_dir = re.search(r"案件輸入檔是 (\S+)/case\.json", prompt).group(1)
    mode = os.environ.get("FAKE_CLAUDE_MODE", "full")
    emit({"type": "system", "subtype": "init", "model": argv[argv.index("--model") + 1], "session_id": "fake"})
    with open(os.path.join(ROOT, run_dir, "case.json"), encoding="utf-8") as f:
        case = json.load(f)
    assert case["case_id"] == case_id
    tool("Read", {"file_path": os.path.join(ROOT, run_dir, "case.json")})
    with_quota = os.environ.get("FAKE_CLAUDE_QUOTA") == "1"
    if with_quota:
        quota(0, 0.93)

    if mode == "hang":
        time.sleep(120)
        return 0
    if mode == "crash":
        sys.stderr.write("fake crash: something broke\n")
        return 3
    if mode == "budget":
        emit({"type": "result", "subtype": "error_max_budget_usd", "is_error": True, "total_cost_usd": 15.02})
        return 1
    if mode == "api_error":  # 實測:認證失敗時 subtype 仍為 success,只有 is_error 為真
        emit({"type": "result", "subtype": "success", "is_error": True, "total_cost_usd": 0,
              "terminal_reason": "api_error", "result": "Failed to authenticate: OAuth session expired"})
        return 1

    s = get_session()
    model = os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL")
    resume = "本次是續跑" in prompt
    if resume:
        with open(os.path.join(ROOT, run_dir, "landed.json"), encoding="utf-8") as f:
            json.load(f)
        tool("Read", {"file_path": os.path.join(ROOT, run_dir, "landed.json")})
    force = os.environ.get("FAKE_CLAUDE_FORCE_RELAND") == "1"

    def has(model_cls, **kw):
        return resume and not force and s.query(model_cls).filter_by(case_id=case_id, **kw).count() > 0

    for side in ("plaintiff", "defendant"):
        if has(DebateArgument, side=side, stage=1):
            continue
        tool("Agent", {"description": f"{side} Stage 1"})
        if side == "defendant" and os.environ.get("FAKE_CLAUDE_SAFETY") == "1":
            safety_stop("被告 Stage 1")
            tool("Agent", {"description": "被告 Stage 1(重派)"})
        try:
            record_argument(s, case_id=case_id, side=side, stage=1, position=f"{side} 立場", reasoning="推理",
                            cited_statutes=[], cited_precedents=[], model_id=model)
        except ValueError as e:  # 已落地不可覆寫：照 SKILL.md 回報，不刪除或改寫
            s.rollback()
            landed(f"錯誤:{e}")
            emit({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.4,
                  "result": f"遇到已落地不可覆寫:{e}"})
            return 0
        landed(f"已落地論證 {case_id} {side} stage1", parent="agent-1")
    if with_quota:
        quota(0.27, 0.95)
    if os.environ.get("FAKE_CLAUDE_STOP_AFTER_S1") == "budget":  # Stage 1 之後才撞到花費上限
        emit({"type": "result", "subtype": "error_max_budget_usd", "is_error": True, "total_cost_usd": 15.01})
        return 1
    if mode == "partial":
        emit({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 1.5, "result": "完成(其實沒有)"})
        return 0
    if not has(CourtQuestion):
        record_question(s, case_id=case_id, question_text="請說明", target_side="defendant", based_on="被告 Stage1 立場")
    for stage in (2, 3):
        for side in ("plaintiff", "defendant"):
            if has(DebateArgument, side=side, stage=stage):
                continue
            record_argument(s, case_id=case_id, side=side, stage=stage, position=f"{side} s{stage}", reasoning="推理",
                            cited_statutes=[], cited_precedents=[], falsifier="若對方補證則讓步", model_id=model)
            landed(f"已落地論證 {case_id} {side} stage{stage}")
    anchor = finalize_case(s, case_id=case_id)
    if not has(Verdict):
        record_verdict(s, case_id=case_id, verdict_main_text="評估", verdict_reasoning="理由",
                       risk_map={"對原告不利之處": [], "對被告不利之處": [], "建議補強證據": []},
                       mechanical_anchor_json=anchor, protocol_version="test", citations_used=[])
    if not has(PleadingDraft):
        record_pleading(s, case_id=case_id, draft_text="民事起訴狀\n訴之聲明\n一、被告應給付原告。", citations_used=[])
    landed(f"已落地訴狀草稿 {case_id}")
    # 實測(2026-10-28):主 agent 會讀 main.py 原始碼(含「已落地」字樣,前有行號);
    # subagent 在背景執行時，stream 結尾連續出現多筆 result,花費為累計值、權限拒絕只記在當輪
    tool("Read", {"file_path": os.path.join(ROOT, "main.py")})
    landed('    60\t    print(f"已落地論證 {row.case_id} {row.side} stage{row.stage}")')
    emit({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 3.21, "result": "Stage 1 已派出，等待完成",
          "permission_denials": [{"tool_name": "Bash", "tool_input": {"command": "for i in 1 2; do python main.py record; done"}}]})
    # 實測 modelUsage 是整次累計值(含 subagent);usage 只是主 agent 最後一輪
    emit({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 3.21, "result": "全部完成",
          "permission_denials": [], "usage": {"input_tokens": 9, "output_tokens": 99},
          "modelUsage": {"claude-sonnet-5-5": {"inputTokens": 188, "outputTokens": 138510, "cacheReadInputTokens": 6185052,
                                               "cacheCreationInputTokens": 389538, "costUSD": 3.21}}})
    return 0


if __name__ == "__main__":
    sys.exit(main())
