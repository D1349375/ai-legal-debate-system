"""測試用的假 Claude Code:不呼叫任何模型，只模擬 `claude -p --output-format stream-json` 的輸出格式，
並依 FAKE_CLAUDE_MODE 把固定內容寫進 LEGALDEBATE_DB_URL 指向的資料庫(驗證後端有把同一顆 DB 交給子程序)。

模式：full(跑完整流程) / partial(只落地 Stage 1 就回報完成) / budget(花費上限中止) / api_error(API 錯誤)
      / crash(無 result 直接崩潰) / hang(卡住等取消)。
FAKE_CLAUDE_AUTH=0 模擬未登入；FAKE_CLAUDE_DELAY(秒)讓每次落地之間停頓，方便在瀏覽器看進度。
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
    for side in ("plaintiff", "defendant"):
        tool("Agent", {"description": f"{side} Stage 1"})
        record_argument(s, case_id=case_id, side=side, stage=1, position=f"{side} 立場", reasoning="推理",
                        cited_statutes=[], cited_precedents=[], model_id=model)
        landed(f"已落地論證 {case_id} {side} stage1", parent="agent-1")
    if mode == "partial":
        emit({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 1.5, "result": "完成(其實沒有)"})
        return 0
    record_question(s, case_id=case_id, question_text="請說明", target_side="defendant", based_on="被告 Stage1 立場")
    for stage in (2, 3):
        for side in ("plaintiff", "defendant"):
            record_argument(s, case_id=case_id, side=side, stage=stage, position=f"{side} s{stage}", reasoning="推理",
                            cited_statutes=[], cited_precedents=[], falsifier="若對方補證則讓步", model_id=model)
            landed(f"已落地論證 {case_id} {side} stage{stage}")
    anchor = finalize_case(s, case_id=case_id)
    record_verdict(s, case_id=case_id, verdict_main_text="評估", verdict_reasoning="理由",
                   risk_map={"對原告不利之處": [], "對被告不利之處": [], "建議補強證據": []},
                   mechanical_anchor_json=anchor, protocol_version="test", citations_used=[])
    record_pleading(s, case_id=case_id, draft_text="民事起訴狀\n訴之聲明\n一、被告應給付原告。", citations_used=[])
    landed(f"已落地訴狀草稿 {case_id}")
    emit({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 3.21, "result": "全部完成"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
