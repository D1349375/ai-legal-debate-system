"""測試用的假 Claude Code:不呼叫任何模型，只模擬 `claude -p --output-format stream-json` 的輸出格式，
並依 FAKE_CLAUDE_MODE 把固定內容寫進 LEGALDEBATE_DB_URL 指向的資料庫(驗證後端有把同一顆 DB 交給子程序)。

模式：full(跑完整流程) / partial(只落地 Stage 1 就回報完成；只產答辯狀時什麼都不落地就回報完成) / budget(花費上限中止)
      / api_error(API 錯誤) / tree(開孫程序後卡住) / crash(無 result 直接崩潰) / hang(卡住等取消)。
FAKE_CLAUDE_AUTH=0 模擬未登入；FAKE_CLAUDE_DELAY(秒)讓每次落地之間停頓，方便在瀏覽器看進度。
FAKE_CLAUDE_SAFETY=1 在被告 Stage 1 插入一則「回覆被安全分類器中止」的通知(格式照 2026-10-29 執行 #4 的 stream-json);
FAKE_CLAUDE_QUOTA=1 在開始與結束各送一則 rate_limit_event(訂閱額度);FAKE_CLAUDE_STOP_AFTER_S1=budget 在 Stage 1 落地後以花費上限中止。
書狀只落地 prompt「本次要產生的書狀」列出的那幾份；prompt 是「只跑 Step 9C」時只補產這幾份書狀，不跑攻防。
prompt 是續跑時，照 prompt 的指示跳過資料庫已有的紀錄，並確認 landed.json 存在；
FAKE_CLAUDE_FORCE_RELAND=1 則故意重新落地已有的紀錄，驗證資料庫層會拒絕覆寫。
case.json 的 protocol 是 v2(書狀交換流程)時改走 run_v2(見該函數)。
"""
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from database.db import (  # noqa: E402
    finalize_case, get_session, plaintiff_view, pleading_side, record_argument, record_pleading, record_question,
    record_verdict,
)
from database.schema import CourtQuestion, DebateArgument, PleadingDraft, Verdict  # noqa: E402

DRAFTS = {"plaintiff": "民事起訴狀\n訴之聲明\n一、被告應給付原告。",
          "defendant": "民事答辯狀\n答辯聲明\n一、原告之訴及假執行之聲請均駁回。"}
COMPLAINT = ("民事起訴狀\n訴之聲明\n一、被告甲、乙間就系爭房地所為之贈與行為應予撤銷。\n事實及理由\n"
             "一、原告公司於民國104年4月間解散。〔CF1〕\n")


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
    expected_db_url = os.environ.get("FAKE_CLAUDE_EXPECT_DB_URL")
    if not expected_db_url or os.environ.get("LEGALDEBATE_DB_URL") != expected_db_url:
        print("假 Claude 收到的資料庫位址與測試預期不同", file=sys.stderr)
        return 4
    prompt = argv[argv.index("-p") + 1]
    case_id = re.match(r"/legal-debate (\S+)", prompt).group(1)
    run_dir = re.search(r"案件輸入檔是 (\S+)/case\.json", prompt).group(1)
    mode = os.environ.get("FAKE_CLAUDE_MODE", "full")
    emit({"type": "system", "subtype": "init", "model": argv[argv.index("--model") + 1], "session_id": "fake"})
    with open(os.path.join(ROOT, run_dir, "case.json"), encoding="utf-8") as f:
        case = json.load(f)
    assert case["case_id"] == case_id
    # 記下後端給的案件快照根目錄，供測試確認續跑沿用同一份快照
    with open(os.path.join(ROOT, run_dir, "snapshot_env.txt"), "w", encoding="utf-8") as f:
        f.write(os.environ.get("LEGAL_DEBATE_RUN_SNAPSHOT", ""))
    tool("Read", {"file_path": os.path.join(ROOT, run_dir, "case.json")})
    with_quota = os.environ.get("FAKE_CLAUDE_QUOTA") == "1"
    if with_quota:
        quota(0, 0.93)

    if mode == "hang":
        time.sleep(120)
        return 0
    if mode == "tree":  # 像 Claude Code 跑 Bash 一樣再開一層子程序(孫程序),驗證取消時整個程序樹都會終止
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        with open(os.path.join(ROOT, run_dir, "tree_pids.json"), "w", encoding="utf-8") as f:
            json.dump({"fake_claude": os.getpid(), "grandchild": child.pid}, f)
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
    if case.get("protocol") == "v2":
        return run_v2(s, case_id, run_dir, prompt, mode, model)
    m = re.search(r"本次要產生的書狀：([^。\n]*)", prompt)
    wanted = [side for side, label in (("plaintiff", "原告起訴狀"), ("defendant", "被告答辯狀")) if m and label in m.group(1)]

    def land_pleading(side):
        record_pleading(s, case_id=case_id, side=side, citations_used=[], draft_text=DRAFTS[side])
        landed(f"已落地{'起訴狀' if side == 'plaintiff' else '答辯狀'}草稿 {case_id}")

    if "的 Step 9C(只替既有案件補產書狀骨架" in prompt:
        for side in wanted:
            tool("Bash", {"command": f"python main.py pleading-source --case-id {case_id} --side {side}"})
            if mode != "partial":
                land_pleading(side)
        emit({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.4, "result": "完成"})
        return 0
    resume = "本次是續跑" in prompt
    if resume:
        with open(os.path.join(ROOT, run_dir, "landed.json"), encoding="utf-8") as f:
            json.load(f)
        tool("Read", {"file_path": os.path.join(ROOT, run_dir, "landed.json")})
    force = os.environ.get("FAKE_CLAUDE_FORCE_RELAND") == "1"

    def has(model_cls, **kw):
        return resume and not force and s.query(model_cls).filter_by(case_id=case_id, **kw).count() > 0

    def has_pleading(side):
        return resume and not force and any(pleading_side(r) == side for r in
                                            s.query(PleadingDraft).filter_by(case_id=case_id).all())

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
    if not has(Verdict):
        verdict_file = os.path.join(ROOT, run_dir, "verdict.json")
        with open(verdict_file, "w", encoding="utf-8") as f:
            json.dump({"verdict_main_text": "評估", "verdict_analysis": "理由",
                       "risk_map": {"對原告不利之處": [], "對被告不利之處": [], "建議補強證據": []},
                       "citations_used": []}, f, ensure_ascii=False)
        result = subprocess.run([sys.executable, "main.py", "verdict", "--case-id", case_id,
                                 "--json", verdict_file], cwd=ROOT, env=os.environ.copy(),
                                capture_output=True, text=True, encoding="utf-8", timeout=60)
        if result.returncode:
            print(result.stderr, file=sys.stderr)
            return result.returncode
    for side in wanted:
        if not has_pleading(side):
            land_pleading(side)
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


V2_STOPS = (("本次只跑到起訴狀", "complaint"), ("本次只跑到模擬答辯狀", "answer"), ("本次只跑到爭點整理表", "issue_sheet"))
ANSWER = {"responses": [{"fact_id": "CF1", "stance": "deny", "ground": "insufficient_proof",
                         "reason": "原告未提出解散登記資料", "hypothetical": False}],
          "legal_argument": "原告未證明詐害債權要件。", "citations": [], "to_confirm": [],
          "defenses": [{"type": "denial", "statement": "被告否認贈與時已無資力", "legal_basis": [], "hypothetical": False}]}
SHEET = {"undisputed": [],
         "issues": [{"id": "I1", "kind": "fact", "text": "原告公司是否於104年4月間解散", "from": ["CF1"],
                     "plaintiff_claim": "原告公司於104年4月間解散", "plaintiff_evidence": [],
                     "defendant_defense": "原告未提出解散登記資料", "defendant_evidence": [],
                     "legal_basis": ["民法第244條"], "burden": "plaintiff", "hypothetical": False}],
         "clarifications": [], "questions": [{"question_text": "原告就解散事實有何證據?", "target_side": "plaintiff",
                                               "based_on": "I1:解散"}]}
RISK_MAP = {"對原告不利之處": ["解散時點只有原告主張"], "對被告不利之處": [], "建議補強證據": ["公司登記資料"],
            "issue_assessment": [{"issue_id": "I1", "strength": "中", "reason": "缺登記資料"}],
            "evidence_todo": [{"issue_id": "I1", "missing": "公司解散登記", "why": "證明解散時點"}],
            "complaint_revisions": [{"fact_id": "CF1", "kind": "revise", "suggestion": "補上解散登記日期"}],
            "fact_gaps": ["解散登記日期"], "opponent_hypotheticals": []}


def run_v2(s, case_id, run_dir, prompt, mode, model):
    """書狀交換流程(protocol v2)P0–P6,步驟照 server/live_run.py RUN_STEPS_V2。prompt 的停止點(只跑到起訴狀、
    模擬答辯狀、爭點整理表)到了就停;續跑時跳過資料庫已有的紀錄。內容是固定的假資料，直接寫資料庫(不經過 main.py 的檢查),
    只為了讓 UI 與步驟表能跑完全程。
    partial:只落地原告分析就回報完成;FAKE_CLAUDE_STOP_AFTER_P1=1:沒有停止點，但起訴狀落地後就回報完成。
    關卡之後會把讀到的起訴狀版本寫進 complaint_read.txt;收到的排除清單環境變數寫進 exclude_env.txt。"""
    from database.db import case_payload, issue_sheet, latest_answer, record_complaint_revision, record_issue_sheet
    from database.schema import Case, IssueSheet
    from engine import pleading_render
    with open(os.path.join(ROOT, run_dir, "exclude_env.txt"), "w", encoding="utf-8") as f:
        f.write(os.environ.get("LEGALDEBATE_EXCLUDE", ""))
    resume = "本次是續跑" in prompt
    if resume:
        with open(os.path.join(ROOT, run_dir, "landed.json"), encoding="utf-8") as f:
            json.load(f)
        tool("Read", {"file_path": os.path.join(ROOT, run_dir, "landed.json")})
    stop = next((key for mark, key in V2_STOPS if mark in prompt), None)

    def has(model_cls, **kw):
        return s.query(model_cls).filter_by(case_id=case_id, **kw).count() > 0

    def has_pleading(side, kind):
        return any(pleading_side(r) == side and r.pleading_type == kind and r.source in (None, "system")
                   for r in s.query(PleadingDraft).filter_by(case_id=case_id).all())

    def done(text):
        emit({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 1.15, "result": text})
        return 0

    def argue(side, stage, description, position):
        if has(DebateArgument, side=side, stage=stage):
            return
        tool("Agent", {"description": description})
        reasoning = f"【爭點 I1】{position}\n【內部檢討】假資料【內部檢討結束】" if stage > 1 else position
        record_argument(s, case_id=case_id, side=side, stage=stage, position=position, reasoning=reasoning,
                        cited_statutes=[], cited_precedents=[], falsifier="若對方補證則讓步" if stage > 1 else None,
                        model_id=model)
        landed(f"已落地論證 {case_id} {side} stage{stage}", parent="agent")

    tool("Bash", {"command": f"python main.py role-view --case-id {case_id} --role plaintiff"})
    argue("plaintiff", 1, "原告請求權基礎檢驗", "撤銷詐害行為")
    if mode == "partial":
        return done("完成(其實沒有)")
    if not has(PleadingDraft, pleading_type="complaint"):
        tool("Bash", {"command": f"python main.py complaint --case-id {case_id} --json {run_dir}/complaint.json"})
        record_pleading(s, case_id=case_id, draft_text=COMPLAINT, citations_used=[], pleading_type="complaint", round=1,
                        is_simulated=0, structured={"fact_points": [{"id": "CF1", "text": "原告公司於104年4月間解散。"}]})
        landed(f"已落地起訴狀 v1 {case_id}")
    if stop == "complaint" or os.environ.get("FAKE_CLAUDE_STOP_AFTER_P1") == "1":
        return done("起訴狀 v1 已落地")
    complaint = plaintiff_view(s, case_id)["complaint"]
    with open(os.path.join(ROOT, run_dir, "complaint_read.txt"), "w", encoding="utf-8") as f:
        f.write(str(complaint["version_id"]))
    case = case_payload(s.query(Case).filter_by(case_id=case_id).one())
    tool("Bash", {"command": f"python main.py role-view --case-id {case_id} --role defendant"})
    argue("defendant", 1, "被告防禦分析", "否認詐害")
    if not has_pleading("defendant", "answer"):
        text = pleading_render.render_answer(ANSWER, case=case, party_checks={}, procedural=None,
                                             complaint_text=complaint["draft_text"])
        row = record_pleading(s, case_id=case_id, draft_text=text, citations_used=[], side="defendant",
                              pleading_type="answer", round=1, is_simulated=1,
                              structured=pleading_render.stored_answer(ANSWER, complaint["version_id"]))
        landed(f"已落地答辯狀 {case_id} #{row.id}")
    if stop == "answer":
        return done("答辯狀已落地")
    if not has(IssueSheet):
        tool("Agent", {"description": "法官爭點整理"})
        record_issue_sheet(s, case_id=case_id, sheet=SHEET, complaint_id=complaint["version_id"],
                           answer_id=latest_answer(s, case_id).id)
        landed(f"已落地爭點整理表 {case_id}")
    if stop == "issue_sheet":
        return done("爭點整理表已落地")
    for stage, kind, label in ((2, "brief", "準備書狀"), (3, "closing", "言詞辯論意旨狀")):
        for side in ("plaintiff", "defendant"):
            argue(side, stage, f"{'原告' if side == 'plaintiff' else '被告'}第 {stage} 輪", f"{side} 第 {stage} 輪立場")
        for side in ("plaintiff", "defendant"):
            if not has_pleading(side, kind):
                record_pleading(s, case_id=case_id, side=side, citations_used=[], pleading_type=kind, round=stage,
                                is_simulated=1, draft_text=f"民事{label}(模擬)\n【爭點 I1】{side} 第 {stage} 輪立場",
                                structured={"issue_sheet_id": issue_sheet(s, case_id)["id"]})
                landed(f"已落地{kind} {case_id} {side}(第 {stage} 輪)")
    anchor = finalize_case(s, case_id=case_id)
    if not has(Verdict):
        record_verdict(s, case_id=case_id, verdict_main_text="解散時點的證據不足,建議補強。",
                       verdict_reasoning="爭點 I1 中等。", risk_map=RISK_MAP, mechanical_anchor_json=anchor,
                       protocol_version="v2-pleading-exchange", citations_used=[])
        landed(f"已落地判決 {case_id}")
    if not any(r.source == "system_revision" for r in s.query(PleadingDraft).filter_by(case_id=case_id).all()):
        row = record_complaint_revision(s, case_id=case_id, parent_id=complaint["version_id"],
                                        draft_text=COMPLAINT.replace("解散。", "解散(登記日期待補)。"), citations_used=[],
                                        structured={"fact_points": [{"id": "CF1", "text": "原告公司於104年4月間解散。"}],
                                                    "parent_id": complaint["version_id"]})
        landed(f"已落地起訴狀 v2 {case_id}(#{row.id})")
    return done("全部完成")


if __name__ == "__main__":
    sys.exit(main())
