"""LegalDebate CLI — 供 Claude Code orchestrator(legal-debate skill)呼叫的落地工具。

LLM 推理不在這裡發生:原告/被告/法官的論證由 Claude Code subagent 產生，
本 CLI 只負責案件輸入、攻防落地、機械聚合、查證與最終輸出的資料庫紀律。

用法:
  python main.py case     --json <file>                 案件輸入
  python main.py precheck --case-id X                    起訴前檢查的提示(程序類型、調解、時效)
  python main.py role-view --case-id X --role plaintiff|defendant [--out <檔>]  印出(或寫成檔)該角色可讀的案件資料
  python main.py record   --json <file>                 落地一方一階段的論證，或一則法官訊問
  python main.py finalize --case-id X [--for-judge]      機械彙整(雙方讓步條件+引用清單差異+程序事項)，印出評估錨點；--for-judge 只印給法官讀的部分
  python main.py issues   --case-id X                    依商工查核結果印出法官應依職權調查的程序事項
  python main.py public-args --case-id X [--through-stage N] [--out <檔>]  印出(或寫成檔)法官與對手摘要可讀的論證(濾掉內部檢討)
  python main.py check-judge --case-id X --json <file>    落地前檢查法官輸出(整批訊問或評估)，不寫入資料庫
  python main.py verify   <citation> [<citation> ...]     引用查證
  python main.py verdict  --case-id X --json <file>       落地法官判決書(引用未 published 即拒絕)
  python main.py pleading --case-id X --draft-file <file> --citations <file> [--side plaintiff|defendant]
                                                          落地訴狀草稿(預設原告起訴狀；defendant=被告答辯狀)
  python main.py pleading-source --case-id X --side defendant  印出該方撰狀素材(Stage 3+查證狀態),不重跑攻防補產書狀用
  python main.py complaint --case-id X --json <file> [--check] [--review-json <file>]
                                                          書狀交換流程的起訴狀 v1:檢查事實對應、由程式組成正文後落地；--check 只檢查不落地
  python main.py serve    [--port 8000] [--no-browser]     啟動 UI 後端(重播錄製案例、執行機械環節；綁本機時可由 UI 觸發即時執行)
  python main.py export-demo [--live-checks]               把 DB 的錄製紀錄匯出為 demo/ fixture(離線重現用)
  python main.py party --ban 22099131 [--case-id X --role defendant] [--name 名稱] [--no-persist]
  python main.py article 民法 33 [--json]                  依法規名稱與條號查現行條文(經快取；也接受「民法第191條之2」)
  python main.py search-judgments --kw 締約上過失 [--title X] [--from/--to YYYY-MM-DD] [--pages 2] [--fetch 3] [--save-dir D] [--json]
                                                          上網搜尋最高法院民事裁判，可抓全文整理主文與引用法條
  python main.py search-statutes --kw 知有損害 [--law 民法] [--laws 3] [--json]
                                                          依關鍵字上網搜尋法規條文
  python main.py judgment 111年度台上字第1069號 [--doc-date YYYYMMDD] [--json]
                                                          依字號或 JID 讀判決全文(經快取，印去換行版)
  python main.py retrieval-rules --phase p1 [--side plaintiff --case-dir <案件資料夾>] [--exclude <來源裁判>] [--json]
                                                          印出該階段的檢索規則(調度員填範本的 {RETRIEVAL_RULES})
  python main.py prompt stage1_prompt --out <檔> --set KEY=VALUE [--phase p1 --side plaintiff --case-dir <案件資料夾>]
                                                          把範本填好寫成檔，只印路徑(subagent 自己讀，主 agent 不經手全文)
  檢索指令共用：--snapshot <本次實跑快照資料夾>(角色與查證讀同一版本)、--log <檢索紀錄檔>(記錄每次查詢並計算本輪預算)
  search-judgments、judgment 另有 --issue <爭點id>、--exclude <字號或 JID>(不提供的裁判，如示範案的來源裁判)
"""
import argparse
import json
import os
import re
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

from database.db import (
    get_session, record_case, record_argument, record_question, case_precheck, plaintiff_view, defendant_view,
    admission_sources, public_arguments, finalize_case, record_verdict, record_pleading, upsert_citation,
)
from database.schema import Case
from engine.admission_check import admission_problems, looks_factual, strings_in
from engine.aggregate import judge_view
from engine.internal_review import review_warnings, strip_internal_review
from engine.party_issues import mixed_dismissal_citations
from engine.verify import verify_citations

PROTOCOL_VERSION = "v1.1-2026-11-02"
PLEADING_LABEL = {"plaintiff": "起訴狀", "defendant": "答辯狀"}
_ADMISSION_REFUSAL = "寫「自承、自認、自陳、坦承」要緊接引述該方原句(例如:被告自承「……」),請退回法官 subagent 改寫:"


def _pick(payload, *keys):
    """依序取第一個存在的欄位。subagent 範本的輸出欄位已改名(argument / verdict_analysis):
    JSON 欄位叫 reasoning 會觸發 Claude 安全分類器 reasoning_extraction(2026-10-28 實跑被擋)。
    資料庫欄位名不變，舊名仍接受(錄製紀錄與舊 JSON)。"""
    for key in keys:
        if key in payload:
            return payload[key]
    raise KeyError(" 或 ".join(keys))


def cmd_case(args):
    with open(args.json, 'r', encoding='utf-8') as f:
        payload = json.load(f)
    session = get_session()
    extra = {}
    if payload.get("protocol") == "v2":  # 沒有 protocol 的 JSON 維持舊流程，舊案件不受影響
        extra = {"protocol": "v2", "represented_side": payload.get("represented_side", "plaintiff"),
                 "parties": payload.get("parties"), "claim_amount": payload.get("claim_amount"),
                 "evidence": payload.get("evidence"), "opponent_responses": payload.get("opponent_known_responses"),
                 "known_gaps": payload.get("known_gaps")}
    try:
        row = record_case(session, case_id=payload["case_id"], case_type=payload["case_type"],
                          facts_summary=payload["facts_summary"], claims=payload["claims"], **extra)
    except ValueError as e:
        print(f"拒絕落地:{e}", file=sys.stderr)
        return 1
    print(f"已落地案件 {row.case_id}")
    return 0


def cmd_precheck(args):
    session = get_session()
    row = session.query(Case).filter_by(case_id=args.case_id).one_or_none()
    if row is None:
        print(f"找不到案件 {args.case_id}", file=sys.stderr)
        return 1
    print(json.dumps(case_precheck(row), ensure_ascii=False, indent=2))
    return 0


def cmd_role_view(args):
    session = get_session()
    try:
        view = (plaintiff_view if args.role == "plaintiff" else defendant_view)(session, args.case_id)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    _emit(view, args.out)
    return 0


def _emit(data, out):
    """給了 --out 就寫成檔、只印路徑：主 agent 的上下文每輪都重讀，大段 JSON 不經過它，交給 subagent 自己讀檔。"""
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if not out:
        print(text)
        return
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(text)
    print(out)


def _verdict_admission_problems(session, case_id, payload, analysis):
    return [p for text in strings_in([payload["verdict_main_text"], analysis, payload["risk_map"]])
            for p in admission_problems(text, admission_sources(session, case_id))]


def cmd_public_args(args):
    session = get_session()
    _emit({"case_id": args.case_id, "arguments": public_arguments(session, case_id=args.case_id, through_stage=args.through_stage)},
          args.out)
    return 0


def cmd_check_judge(args):
    """落地前檢查法官輸出，不寫入資料庫。訊問要整批通過才落地:部分落地後中斷，續跑會把法官訊問當成已完成。"""
    with open(args.json, 'r', encoding='utf-8') as f:
        payload = json.load(f)
    session = get_session()
    if "questions" in payload:
        sources = admission_sources(session, args.case_id)
        problems = [f"第 {i} 則:{p}" for i, q in enumerate(payload["questions"], 1)
                    for p in admission_problems(q["question_text"], sources, target_side=q["target_side"])]
    else:
        problems = _verdict_admission_problems(session, args.case_id, payload, _pick(payload, "verdict_analysis", "verdict_reasoning"))
    if problems:
        print("未通過:" + _ADMISSION_REFUSAL + ";".join(problems), file=sys.stderr)
        return 1
    print("法官輸出檢查通過")
    return 0


def cmd_record(args):
    with open(args.json, 'r', encoding='utf-8') as f:
        payload = json.load(f)
    session = get_session()
    try:
        if "question_text" in payload:
            problems = admission_problems(payload["question_text"], admission_sources(session, payload["case_id"]),
                                          target_side=payload["target_side"])
            if problems:
                raise ValueError(_ADMISSION_REFUSAL + ";".join(problems))
            row = record_question(session, case_id=payload["case_id"], question_text=payload["question_text"],
                                   target_side=payload["target_side"], based_on=payload["based_on"])
            print(f"已落地訊問 {row.case_id} -> {row.target_side}")
            if row.target_side == "defendant" and not row.based_on.startswith("官方事實層") and looks_factual(row.question_text):
                print("警告:這則訊問看起來要被告回答事實,被告沒有本人的事實,請確認是否該改成給原告的準備題", file=sys.stderr)
            return 0
        row = record_argument(
            session, case_id=payload["case_id"], side=payload["side"], stage=int(payload["stage"]),
            position=payload["position"], reasoning=_pick(payload, "argument", "reasoning"),
            cited_statutes=payload.get("cited_statutes"), cited_precedents=payload.get("cited_precedents"),
            falsifier=payload.get("falsifier"), model_id=payload.get("model_id"),
        )
    except ValueError as e:  # 如重複落地(不可覆寫):與 verdict/pleading 一致，印原因而非 traceback
        print(f"拒絕落地:{e}", file=sys.stderr)
        return 1
    print(f"已落地論證 {row.case_id} {row.side} stage{row.stage}")
    problems = admission_problems(strip_internal_review(row.reasoning), admission_sources(session, row.case_id), allow_first_person=True)
    if problems:
        print("警告:論證含未引述原句的自承類用語,請確認:" + ";".join(problems), file=sys.stderr)
    for warning in review_warnings(row.reasoning):
        print("警告:" + warning, file=sys.stderr)
    return 0


def cmd_finalize(args):
    session = get_session()
    result = finalize_case(session, case_id=args.case_id)
    if args.for_judge:
        result = judge_view(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_issues(args):
    from database.db import latest_party_checks
    from engine.party_issues import procedural_issues
    session = get_session()
    result = procedural_issues(latest_party_checks(session, args.case_id))
    print(json.dumps({"case_id": args.case_id, **result}, ensure_ascii=False, indent=2))
    return 0


def cmd_verify(args):
    session = get_session()
    notes = None
    if args.precedent_notes:
        with open(args.precedent_notes, encoding='utf-8') as f:
            notes = json.load(f)
    try:
        results = verify_citations(args.citations, precedent_notes=notes, snapshot=args.snapshot, read_by=args.read_by)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    for r in results:
        if r.get("status") == "published":
            upsert_citation(session, citation_text=r["citation_text"], source_type=r["source_type"],
                             status="published", primary_source_url=r.get("primary_source_url"))
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


def cmd_verdict(args):
    with open(args.json, 'r', encoding='utf-8') as f:
        payload = json.load(f)
    analysis = _pick(payload, "verdict_analysis", "verdict_reasoning")
    mixed = mixed_dismissal_citations("\n".join([payload["verdict_main_text"], analysis,
                                                 json.dumps(payload["risk_map"], ensure_ascii=False)]))
    if mixed:
        print("拒絕落地:第249條與最高法院115年度台抗字第105號放在同一個括號，讀起來像該裁定也支持駁回:"
              + ";".join(mixed) + "。請退回法官 subagent 分開引註:第249條接在逾期未補正以裁定駁回之後，"
              "115台抗105 只接在法院應依職權調查實際代表權之後", file=sys.stderr)
        return 1
    session = get_session()
    problems = _verdict_admission_problems(session, args.case_id, payload, analysis)
    if problems:
        print("拒絕落地:" + _ADMISSION_REFUSAL + ";".join(problems), file=sys.stderr)
        return 1
    try:
        row = record_verdict(
            session, case_id=args.case_id, verdict_main_text=payload["verdict_main_text"],
            verdict_reasoning=analysis, risk_map=payload["risk_map"],
            mechanical_anchor_json=payload["mechanical_anchor_json"],
            protocol_version=PROTOCOL_VERSION, citations_used=payload.get("citations_used", []),
        )
    except ValueError as e:
        print(f"拒絕落地:{e}", file=sys.stderr)
        return 1
    print(f"已落地判決 {row.case_id}")
    return 0


def cmd_pleading(args):
    with open(args.draft_file, 'r', encoding='utf-8') as f:
        draft_text = f.read()
    with open(args.citations, 'r', encoding='utf-8') as f:
        citations_used = json.load(f)
    session = get_session()
    try:
        row = record_pleading(session, case_id=args.case_id, draft_text=draft_text,
                               citations_used=citations_used, side=args.side)
    except ValueError as e:
        print(f"拒絕落地:{e}", file=sys.stderr)
        return 1
    print(f"已落地{PLEADING_LABEL[row.side]}草稿 {row.case_id}")
    from server.pleading_export import lint_pleading
    hits = lint_pleading(draft_text, row.side)
    if hits:
        print("警告:書狀正文含模擬流程用語,請確認:" + "、".join(f"{h['word']}×{h['count']}" for h in hits), file=sys.stderr)
    return 0


def _complaint_review_problems(review, citations):
    """P1 起訴狀正式引用的判決要先經乾淨 subagent 做實質核對(SKILL.md Step 3)。沒有核對、或核對認為不支持,都不落地。"""
    from engine.verify import parse_citation
    judgments = [c for c in citations if parse_citation(c)["type"] == "judgment"]
    if not judgments:
        return []
    if not isinstance(review, list) or not all(isinstance(r, dict) and isinstance(r.get("citation"), str) for r in review):
        return [f"正式引用的判決要先做實質核對(--review-json):{'、'.join(judgments)}"]
    by_key = {_judgment_key(r["citation"]): r for r in review}
    problems = []
    for c in judgments:
        r = by_key.get(_judgment_key(c))
        if r is None:
            problems.append(f"{c} 沒有實質核對結果")
        elif r.get("supports") is not True:
            problems.append(f"{c} 實質核對未通過:{r.get('reason') or '未說明'}")
    return problems


def _judgment_key(citation):
    from engine.verify import parse_citation
    parsed = parse_citation(citation)
    return (parsed.get("jyear"), parsed.get("jcase"), parsed.get("jno")) if parsed["type"] == "judgment" else citation


def cmd_complaint(args):
    """書狀交換流程 P1 起訴狀 v1。模型只交內容,正文由 engine/pleading_render.py 組成。結構問題硬擋(退回撰狀 subagent),
    自然語言問題(lint_pleading)只警告。--check 只檢查並印出正文,不落地。"""
    from database.db import latest_party_checks
    from database.schema import DebateArgument, PleadingDraft
    from engine.fact_points import paraphrase_warnings
    from engine.party_issues import procedural_issues
    from engine.pleading_render import complaint_problems, render_complaint, stored_complaint
    from server.pleading_export import lint_pleading
    from server.services import extract_citations
    with open(args.json, 'r', encoding='utf-8') as f:
        payload = json.load(f)
    session = get_session()
    case = session.query(Case).filter_by(case_id=args.case_id).one_or_none()
    if case is None or case.protocol != "v2":
        print(f"拒絕落地:{args.case_id} 不是書狀交換流程(v2)的案件" if case else f"拒絕落地:找不到案件 {args.case_id}",
              file=sys.stderr)
        return 1
    analysis = session.query(DebateArgument).filter_by(case_id=args.case_id, side="plaintiff", stage=1).one_or_none()
    if analysis is None:
        print("拒絕落地:原告的請求權基礎分析(stage 1)還沒落地,先完成分析再撰狀", file=sys.stderr)
        return 1
    if not args.check and any(r.pleading_type == "complaint" and r.round == 1 and r.source in (None, "system")
                              for r in session.query(PleadingDraft).filter_by(case_id=args.case_id).all()):
        print(f"拒絕落地:{args.case_id} 起訴狀 v1 已落地,不可覆寫", file=sys.stderr)
        return 1
    from database.db import case_payload
    data, checks = case_payload(case), latest_party_checks(session, args.case_id)
    procedural = procedural_issues(checks)
    problems = complaint_problems(payload, case=data, procedural=procedural,
                                  analysis_text=f"{analysis.position}\n{strip_internal_review(analysis.reasoning)}")
    if problems:
        print("未通過,請把以下原因交回撰狀 subagent 修改後重新輸出整份 JSON(同一份最多退回 2 次):\n"
              + "\n".join(f"- {p}" for p in problems), file=sys.stderr)
        return 1
    text = render_complaint(payload, case=data, party_checks=checks, procedural=procedural)
    # 正文裡看起來像引用的文字(含 legal_argument 順帶提到的)一律要 published,不只 citations 欄位
    in_body = [c["citation_text"] for c in extract_citations(text)]
    listed = {_judgment_key(c) for c in payload.get("citations", [])}
    unlisted = [c for c in in_body if _judgment_key(c) != c and _judgment_key(c) not in listed]
    if unlisted:  # 判決要附摘句與實質核對,只出現在正文、沒列進 citations 會繞過
        print("未通過,請把以下原因交回撰狀 subagent 修改後重新輸出整份 JSON(同一份最多退回 2 次):\n- 正文提到的判決要列進 "
              "citations 並附 precedent_notes,或從正文刪除:" + "、".join(unlisted), file=sys.stderr)
        return 1
    gate = list(dict.fromkeys(payload.get("citations", []) + payload["basis"] + in_body))
    warnings = [f"書狀正文含模擬流程用語,請確認:{h['word']}×{h['count']}" for h in lint_pleading(text, "plaintiff")]
    warnings += paraphrase_warnings(payload["fact_points"], data["facts_summary"])
    if args.check:
        print(text)
        print("結構檢查通過。落地前要全部 published 的引用:" + "、".join(gate))
        for warning in warnings:
            print("警告:" + warning)
        return 0
    from database.db import _assert_all_published
    review = None
    if args.review_json:
        with open(args.review_json, 'r', encoding='utf-8') as f:
            review = json.load(f)
    try:
        _assert_all_published(session, gate)
        review_problems = _complaint_review_problems(review, payload.get("citations", []))
        if review_problems:
            raise ValueError("判決實質核對:" + ";".join(review_problems))
        if payload.get("precedent_notes"):
            from engine.verify import validate_precedent_notes  # 摘句與文件身分(快照 → 快取 → 上網)
            # 起訴狀引用的判決要原告方在本案用 judgment 讀過全文(not_read_by_side 不放行);需要案件快照根目錄
            validate_precedent_notes(payload["precedent_notes"], snapshot=args.snapshot, read_by="plaintiff")
        stored = stored_complaint(payload)
        if review is not None:
            stored["citation_review"] = review
        row = record_pleading(session, case_id=args.case_id, draft_text=text, citations_used=gate, side="plaintiff",
                              pleading_type="complaint", round=1, is_simulated=0, structured=stored)
    except ValueError as e:
        print(f"拒絕落地:{e}", file=sys.stderr)
        return 1
    print(f"已落地起訴狀 v1 {row.case_id}(#{row.id},事實點 {len(payload['fact_points'])} 個)")
    for warning in warnings:
        print("警告:" + warning, file=sys.stderr)
    return 0


def cmd_pleading_source(args):
    from database.db import pleading_materials
    session = get_session()
    try:
        result = pleading_materials(session, case_id=args.case_id, side=args.side)
    except ValueError as e:
        print(f"無法取得撰狀素材:{e}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_serve(args):
    import threading
    import webbrowser

    import uvicorn
    from server.app import create_app

    from server.live_run import options_for_host
    app = create_app(live=options_for_host(args.host, model=args.model, budget_usd=args.budget_usd))
    url = f"http://{args.host}:{args.port}/"
    if app.state.seeded:
        print(f"資料庫原本沒有案件，已由 demo/recorded_cases.json 匯入錄製紀錄:{app.state.seeded}")
    print(f"LegalDebate UI:{url}(Ctrl+C 結束)")
    avail = app.state.live.availability()
    print("即時執行:" + (f"已啟用(模型 {avail['model']},每次花費上限 {avail['budget_usd']:g} 美元)" if avail["enabled"]
                        else f"停用——{avail['reason']}"))
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def cmd_export_demo(args):
    from server import seed
    session = get_session()
    # 維持既有 --live-checks 同時匯出案件 fixture 的行為；僅單獨 --party-checks 略過。
    if not args.party_checks or args.live_checks:
        counts = seed.write_fixture(session)
        print(f"已匯出 {seed.FIXTURE_PATH}:{counts}")
    if args.live_checks:
        checks = seed.write_live_checks(session)
        print(f"已記錄 {len(checks)} 筆即時查證結果到 {seed.LIVE_CHECKS_PATH}")
        for c in checks:
            print(f"  {c['citation_text']} → {c['status']}")
    if args.party_checks:
        checks = seed.write_party_checks(session)
        print(f"已匯出 {len(checks)} 筆過去實際商工查詢到 {seed.PARTY_CHECKS_PATH}")
    return 0


def cmd_party(args):
    from engine.gcis import validate_ban
    from server.services import party_check_one
    from server.seed import load_recorded_party_checks
    ban = validate_ban(args.ban)
    if ban is None:
        print("統一編號須為 8 位數字", file=sys.stderr)
        return 2
    if args.case_id and not args.role:
        print("指定案件時須同時指定 --role", file=sys.stderr)
        return 2
    session = get_session()
    try:
        r = party_check_one(session, ban, case_id=args.case_id, role=args.role,
                            input_name=args.name, persist=not args.no_persist,
                            recorded_party_checks=load_recorded_party_checks())
    finally:
        session.close()
    is_branch = r["entity_type"] == "branch"
    is_not_found = r["entity_type"] == "not_found"
    failed = r["query_status"] == "failed"
    basic_missing = r["entity_type"] in ("company", "business") and r.get("basic_data_available") is False
    name = ("分公司統編" if is_branch else "商工登記查無此統編" if is_not_found
            else r.get("name") or ("查核未完成" if failed else "基本資料未取得" if basic_missing else "未取得登記名稱"))
    status = ("未查詢分公司登記" if is_branch else "查無" if is_not_found
              else r.get("status_text") or ("查核未完成" if failed else "基本資料未取得" if basic_missing else "未提供"))
    print(f"當事人查核：{name}（統編 {ban}）")
    print(f"查詢狀態：{r['query_status']}；類型：{r['entity_type']}；登記狀態：{status}")
    if r["via"] == "recorded":
        print(f"錄製的查詢結果（查詢時間 {r['fetched_at']}），非本次即時查詢；本次失敗：{r['live_attempt']['error']}")
    if is_branch:
        print("此統編為分公司；本功能未查詢分公司登記資料，請改以總公司統編查核。")
    elif not is_not_found and not basic_missing:
        from engine.pleading_render import representative_text  # 與 UI、起訴狀當事人欄同一套規則
        print(f"法定代理人：{representative_text(r)}")
        print(f"地址：{r.get('address') or ('查核未完成' if failed else '官方未提供')}")
    for warning in r["warnings"]:
        basis = f"（{'、'.join(warning['legal_basis'])}）" if warning["legal_basis"] else ""
        print(f"警示〔{warning['level']}〕{warning['message']}{basis}")
    j = r["jurisdiction"]
    primary = j["primary"]
    print("主要管轄：" + ("未查詢分公司登記資料，無法建議" if is_branch
                         else "商工查詢未完成，無法建議" if failed
                         else "基本資料未取得，無法建議" if basic_missing or is_not_found
                         else f"{primary['court']}（{primary['basis']}）" if primary else "未能確定"))
    if not is_branch and not failed and not basic_missing and not is_not_found and j.get("primary_candidates"):
        print("候選法院：" + "、".join(j["primary_candidates"]) + "；需依行政區確認")
    for alternative in ([] if is_branch or failed or basic_missing or is_not_found else j["alternatives"]):
        print(f"分公司候選：{alternative['court']}（{alternative['basis']}；{alternative['condition']}）")
    for failure in r["errors"]:
        print(f"查詢失敗：{failure['dataset']}：{failure['error']}")
    if r["attribution"]:
        print(r["attribution"])
    print(f"查詢時間：{r.get('fetched_at') or '無成功回應'}；資料授權：https://data.gov.tw/license")
    return 1 if r["query_status"] == "failed" else 0


def _snapshot(args):
    """檢索指令只用明示的 --snapshot(該角色的快照子資料夾)。環境變數 LEGAL_DEBATE_RUN_SNAPSHOT 指向案件的快照根目錄，
    只給查證與落地用；角色漏給 --snapshot 時若退回根目錄，對造就能從根目錄看出我方讀過哪些判決。"""
    return getattr(args, 'snapshot', None) or None


def _search_log(args):
    from engine.search_log import SearchLog
    return SearchLog(args.log) if getattr(args, 'log', None) else None


SOURCE_LABEL = {'run_snapshot': '本次實跑快照', 'retrieval_cache': '長期快取', 'corpus': '預先內容（司法院開放資料）',
                'live': '上網'}


def _source_line(entry):
    fetched = f"，抓取於 {entry['fetched_at']}" if entry.get('fetched_at') else ''
    return f"來源：{SOURCE_LABEL.get(entry.get('served_from'), entry.get('served_from'))}{fetched}"


def cmd_article(args):
    from engine.law_lookup import lookup_article, split_query
    query = split_query(args.query)
    if query is None:
        print("請輸入法規名稱與條號，例如：民法 33、民法第191條之2", file=sys.stderr)
        return 2
    r = lookup_article(*query, snapshot=_snapshot(args))
    log = _search_log(args)
    if log and r["status"] not in ("invalid_article_no", "unknown_law"):
        fetched = ([{'key': f"{r['pcode']}_{r['article_no']}", 'kind': 'statute', 'served_from': r['served_from']}]
                   if r.get('served_from') else [])
        log.append('article', {'law_name': query[0], 'article_no': query[1]}, r["status"], fetched=fetched)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0 if r["status"] == "found" else 1
    if r["status"] in ("invalid_article_no", "unknown_law"):
        print(f"{r['law_name']} {r['article_no']}：{r['reason']}", file=sys.stderr)
        if r.get("suggestions"):
            print("你是不是要找：" + "、".join(r["suggestions"]), file=sys.stderr)
        return 2
    level = f"，{r['level']}" if r.get("level") else ""
    print(f"{r['law_name']} 第 {r['article_no']} 條（pcode {r['pcode']}{level}）")
    if r.get("abandoned"):
        print("警示：此法規已廢止，以下為官網保留的條文，不是現行法。")
    if r["status"] == "found":
        print(("" if r.get("abandoned") else "現行條文；") + f"官方法規異動日期 {r.get('modified_date') or '未提供'}")
        print(_source_line(r))
    if r.get("url"):
        print(r["url"])
    print()
    print(r["text"] if r["status"] == "found" else f"{r['status']}：{r['reason']}")
    return 0 if r["status"] == "found" else 1


def cmd_judgment(args):
    from engine import judgment_text, retrieval_cache
    from engine.judgment_search import exclusion_keys
    from engine.search_log import BudgetExceeded
    from engine.verify import JUDGMENT_CITATION_RE, JUDGMENTS_DIR, _document_type
    snapshot, log = _snapshot(args), _search_log(args)
    target = args.target.strip()
    doc_date = args.doc_date.replace('-', '').replace('/', '') if args.doc_date else None
    query = {'target': target, 'doc_date': doc_date}

    def fail(status, message, code=1):
        if log:
            log.append('judgment', query, status, issue=args.issue)
        print(message, file=sys.stderr)
        return code

    if doc_date and (len(doc_date) != 8 or not doc_date.isdigit()):
        return fail('invalid_document_date', '--doc-date 須為 YYYYMMDD', 2)
    try:
        excluded = exclusion_keys(getattr(args, 'exclude', None))
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    try:
        hit = bool(excluded & exclusion_keys([target]))
    except ValueError:
        hit = False  # 字號格式錯誤由下方照常回報
    if hit:
        # 依字號比對，在查任何來源之前就拒絕：排除的裁判連字號查詢都不做
        return fail('excluded', 'excluded：此裁判在本案的排除清單內，不提供全文')
    if ',' in target:
        jid = target
    else:
        m = JUDGMENT_CITATION_RE.search(target) or PRECEDENT_FORM_RE.search(target)
        if not m:
            print('請輸入裁判字號(如 111年度台上字第1069號)或 JID(如 TPSV,111,台上,1069,20250716,1)', file=sys.stderr)
            return 2
        try:
            found = retrieval_cache.judgment_candidates(m.group(2), m.group(3), m.group(4), snapshot=snapshot,
                                                        corpus_dir=JUDGMENTS_DIR)
        except retrieval_cache.RetrievalUnavailable as error:
            return fail('retrieval_unavailable', str(error))
        selected = [j for j in found['jids'] if not doc_date or retrieval_cache.doc_date_of(j) == doc_date]
        dates = '、'.join(retrieval_cache.doc_date_of(j) or '?' for j in (selected or found['jids']))
        if not selected:
            return fail('not_found', "not_found：最高法院民事查無此字號" + (f"該日期的文件（此字號文件日期：{dates}）" if dates else ''))
        if len(selected) > 1:
            return fail('ambiguous', f"ambiguous：同字號有多份文件（日期 {dates}），請加 --doc-date YYYYMMDD 指定", 2)
        jid = selected[0]
    try:
        entry = retrieval_cache.get_judgment(jid, snapshot=snapshot, corpus_dir=JUDGMENTS_DIR,
                                             allow_live=log is None or log.remaining_fetches() > 0)
    except retrieval_cache.LiveFetchNotAllowed:
        try:
            log.check_fetch()
        except BudgetExceeded as error:
            return fail('budget_exceeded', f"budget_exceeded：{error}")
        raise
    except retrieval_cache.FullTextUnavailable as error:
        code = fail('full_text_unavailable', str(error))
        if _before_text_index(jid):
            _list_citing_judgments(jid, args, log, snapshot)
        return code
    except retrieval_cache.RetrievalUnavailable as error:
        return fail('retrieval_unavailable', str(error))
    if log:
        log.append('judgment', query, 'found', hits=1, fetched=[{'jid': jid, 'served_from': entry['served_from']}],
                   issue=args.issue)
    retrieval_cache.mark_read(snapshot, jid)
    if args.json:
        print(json.dumps({**entry, 'flat_text': judgment_text.flatten(entry['text'])}, ensure_ascii=False, indent=2))
        return 0
    parts = jid.split(',')
    citation = f"{parts[1]}年度{parts[2]}字第{parts[3]}號" if len(parts) >= 4 else jid
    print(f"最高法院 {citation} {_document_type(entry['text']) or ''}｜{_iso(entry['doc_date'])}｜{entry.get('case_cause') or '案由未提供'}")
    print(f"JID {jid}；{_source_line(entry)}；內容雜湊 {entry['sha256'][:12]}")
    print(entry.get('source_url') or '')
    if not jid.startswith('TPSV,'):
        print('警示：不是最高法院民事字號（TPSV），查證引擎不支援，不可正式引用。')
    if log:
        print(log.summary())
    print()
    print(judgment_text.flatten(entry['text']))
    return 0


# 司法院裁判書查詢系統的全文自民國85年(1996)起；之前的裁判(多為舊判例)只有掃描檔，關鍵字搜不到、全文讀不到
TEXT_INDEX_FROM_YEAR = 85
CITING_SHOWN = 5
# 舊判例的寫法沒有「度」(73年台上字第1173號)；只讓 judgment 認得，查證仍只收「年度」(舊判例不能正式引用)
PRECEDENT_FORM_RE = re.compile(r'(最高法院)?\s*([0-9]{2,3})年(台[^\s字0-9]{1,3})字第\s*([0-9]+)\s*號')


def _before_text_index(jid):
    parts = jid.split(',')
    return len(parts) >= 4 and parts[1].isdigit() and int(parts[1]) < TEXT_INDEX_FROM_YEAR


def _list_citing_judgments(jid, args, log, snapshot):
    """舊裁判沒有可讀全文時，改列援引它的近年判決：這些判決常逐字重述舊判例的見解，讀全文後可改引。

    只在有 --log 的角色檢索時自動查，並計一次搜尋；法官、查證(不帶 --log)只印提示，不替它們搜尋。"""
    from engine.judgment_search import NETWORK_ERRORS, search_judgments
    from engine.search_log import BudgetExceeded
    parts = jid.split(',')
    keyword = f"{parts[1]}年{parts[2]}字第{parts[3]}號"
    hint = f"可用 search-judgments --kw {keyword} 找援引它的近年判決"
    if not log:
        print(f"民國{TEXT_INDEX_FROM_YEAR}年以前的裁判官網沒有可讀全文，不能正式引用；{hint}。")
        return
    exclude = getattr(args, 'exclude', None) or []
    query = {'keywords': [keyword], 'pages': 1, 'sort': 'date', 'exclude': exclude, 'citing': jid}
    try:
        log.check_search()
    except BudgetExceeded as error:
        log.append('search-judgments', query, 'budget_exceeded', note='citing_lookup', issue=args.issue)
        print(f"未自動查援引它的近年判決：{error}", file=sys.stderr)
        return
    try:
        r = search_judgments([keyword], pages=1, sort='date', snapshot=snapshot, exclude=exclude)
    except NETWORK_ERRORS as error:
        log.append('search-judgments', query, 'retrieval_unavailable', note='citing_lookup', issue=args.issue)
        print(f"retrieval_unavailable：查援引判決時連線失敗（已重試；{error}），不代表沒有援引；{hint}", file=sys.stderr)
        return
    log.append('search-judgments', {**r['query'], 'citing': jid}, 'found', hits=r['total'], counts_as_search=True,
               note='citing_lookup', issue=args.issue)
    # 援引它的裁判若也在民國85年以前，同樣沒有全文，不列(也排除判例本身)
    rows = [row for row in r['rows'] if row['verifiable'] and row['doc_type'] == '判決'
            and not _before_text_index(row['jid'])][:CITING_SHOWN]
    if args.json:
        print(json.dumps({'status': 'full_text_unavailable', 'jid': jid, 'citing_keyword': keyword,
                          'citing_total': r['total'], 'citing_judgments': rows}, ensure_ascii=False, indent=2))
        return
    print(f"民國{TEXT_INDEX_FROM_YEAR}年以前的裁判官網沒有可讀全文，不能正式引用。")
    if not rows:
        print(f"查無援引 {keyword} 的近年最高法院判決；不要用這個見解，或寫「待確認」。")
    else:
        print(f"援引 {keyword} 的近年最高法院判決（共 {r['total']} 筆，依日期新到舊列前 {len(rows)} 份判決）。"
              "要用這個見解：用 judgment 讀其中一份全文，引用那份判決，摘句取它重述該見解的原句；"
              f"{keyword} 只放 precedent_leads。")
        for i, row in enumerate(rows, 1):
            print(f"\n{i}. {row['citation']}｜{_iso(row['doc_date'])}｜{row['case_cause']}")
            if row.get('snippet'):
                print(f"   片段：{row['snippet']}")
    print(f"\n{log.summary()}")


def _iso(compact_date):
    return f"{compact_date[:4]}-{compact_date[4:6]}-{compact_date[6:]}" if compact_date and len(compact_date) == 8 else compact_date


# 2026-11-01 評估：常見法條(民法第184、179、767條)單獨搜尋有五、六千筆，依日期排序的前兩頁只涵蓋約一個月。
MANY_RESULTS = 200
# 「常一起引用的法條」只列出現在兩份以上判決者，最多這麼多條
SHARED_STATUTES_SHOWN = 10


def cmd_search_judgments(args):
    from engine.judgment_search import NETWORK_ERRORS, search_judgments
    from engine.search_log import BudgetExceeded
    log = _search_log(args)
    query = {'keywords': args.kw or [], 'case_cause': args.title, 'date_from': args.date_from, 'date_to': args.date_to,
             'pages': args.pages, 'fetch': args.fetch, 'sort': args.sort, 'exclude': getattr(args, 'exclude', None) or []}
    if log:
        try:
            log.check_search()
        except BudgetExceeded as error:
            log.append('search-judgments', query, 'budget_exceeded', issue=args.issue)
            print(f"budget_exceeded：{error}", file=sys.stderr)
            return 1
    try:
        r = search_judgments(args.kw or (), case_cause=args.title, date_from=args.date_from, date_to=args.date_to,
                             pages=args.pages, fetch=args.fetch, include_rulings=args.include_rulings,
                             min_size_kb=args.min_size, sort=args.sort, save_dir=args.save_dir,
                             snapshot=_snapshot(args), max_live_fetches=log.remaining_fetches() if log else None,
                             exclude=getattr(args, 'exclude', None) or ())
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    except NETWORK_ERRORS as error:
        if log:
            log.append('search-judgments', query, 'retrieval_unavailable', issue=args.issue)
        print(f"retrieval_unavailable：司法院裁判書查詢系統連線失敗（已重試；{error}），不代表查無判決", file=sys.stderr)
        return 1
    if log:
        log.append('search-judgments', r['query'], 'found', hits=r['total'], counts_as_search=True, issue=args.issue,
                   fetched=[{'jid': row['jid'], 'served_from': row['served_from']} for row in r['rows'] if row.get('fetched')])
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0
    terms = "、".join(f"「{k}」" for k in r["query"]["keywords"])
    scope = "；".join(filter(None, [f"全文 {terms}" if terms else "", f"案由「{args.title}」" if args.title else ""]))
    order = "裁判大小大到小" if args.sort == "size" else "裁判日期新到舊"
    print(f"最高法院民事裁判｜{scope}｜共 {r['total']} 筆，讀取 {r['pages_read']}/{r['page_count']} 頁（{len(r['rows'])} 筆，{order}）")
    print(f"查詢時間 {r['fetched_at']}；來源 司法院裁判書查詢系統")
    if r["total"] > MANY_RESULTS and args.sort == "date":
        print(f"結果超過 {MANY_RESULTS} 筆，依日期排序時前幾頁只涵蓋最近幾個月；建議加要件詞縮小範圍，"
              "或改用 --sort size 找長篇實體判決。")
    if r["unverifiable"]:
        print(f"其中 {r['unverifiable']} 筆不是最高法院民事字號（TPSV），查證引擎不支援，標為「不可引用」。")
    for i, row in enumerate(r["rows"], 1):
        size = f"{row['size_kb']}K" if row["size_kb"] else "大小未提供"
        flag = "" if row["verifiable"] else "｜不可引用"
        print(f"\n{i}. {row['citation']}｜{size}｜{_iso(row['doc_date'])}｜{row['case_cause']}{flag}")
        if row.get("snippet"):
            print(f"   片段：{row['snippet']}")
        if row.get("fetch_error"):
            print(f"   全文：{row['fetch_error']}")
        elif row.get("fetched"):
            procedural = "；程序駁回" if row["procedural_only"] else ""
            print(f"   主文：{row['disposition'] or '未擷取到'}{procedural}｜全文來源：{SOURCE_LABEL.get(row.get('served_from'), '')}")
            print(f"   實體法條：{'、'.join(row['statutes']) or '無'}")
            for sentence in row["matched_sentences"]:
                print(f"   命中：{sentence}")
        print(f"   {row['url']}")
    shared = [c for c in r["statute_counts"] if c["judgments"] >= 2][:SHARED_STATUTES_SHOWN]
    if shared:
        fetched = sum(1 for row in r["rows"] if row.get("fetched"))
        print(f"\n抓回的 {fetched} 份判決常一起引用的實體法條（可檢查有沒有漏掉該一起主張的補充性法條）：")
        print("、".join(f"{c['statute']}（{c['judgments']} 份）" for c in shared))
    if r["saved_to"]:
        print(f"\n已存檔：{r['saved_to']}")
    if log:
        print(f"\n{log.summary()}")
    return 0


def cmd_search_statutes(args):
    from engine.law_lookup import search_statutes
    try:
        r = search_statutes(args.kw, law_name=args.law, max_laws=args.laws)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    log = _search_log(args)
    if log and r["status"] != "unknown_law":
        log.append('search-statutes', {'keyword': args.kw, 'law_name': args.law, 'laws': args.laws}, r["status"],
                   hits=r.get("total_laws"))
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0 if r["status"] == "found" else 1
    if r["status"] == "unknown_law":
        print(f"{args.law}：{r['reason']}", file=sys.stderr)
        if r.get("suggestions"):
            print("你是不是要找：" + "、".join(r["suggestions"]), file=sys.stderr)
        return 2
    if r["status"] == "retrieval_unavailable":
        print(f"retrieval_unavailable：{r['reason']}", file=sys.stderr)
        return 1
    if not args.law:
        print(f"條文含「{r['keyword']}」的法規共 {r['total_laws']} 部（官網列表順序，非相關度）：")
        print("、".join(law["law_name"] for law in r["laws"]))
        if r["total_laws"] > len(r["laws"]):
            print(f"（只列出前 {len(r['laws'])} 部）")
        print(f"以下展開前 {len(r['expanded'])} 部；要看其他法規的條文，加 --law 法規名稱。")
    for law in r["expanded"]:
        warning = "｜已廢止" if law.get("abandoned") else ""
        print(f"\n【{law['law_name']}】命中 {len(law['articles'])} 條{warning}｜{law['url']}")
        for article in law["articles"]:
            print(f"\n第 {article['article_no']} 條\n{article['text']}")
    return 0


def cmd_retrieval_rules(args):
    from engine import retrieval_rules
    try:
        r = retrieval_rules.build(args.phase, side=args.side, case_dir=args.case_dir, exclude=getattr(args, 'exclude', None))
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(r, ensure_ascii=False, indent=2) if args.json else r['text'])
    return 0


TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.claude', 'skills', 'legal-debate', 'templates')
PLACEHOLDER_RE = re.compile(r'\{([A-Z][A-Z_]*)\}')


def cmd_prompt(args):
    """把範本填好寫成檔，只印路徑。主 agent 不讀範本全文，subagent 自己 Read 這個檔，填法也不靠模型照抄。
    --phase 時檢索規則與該角色的快照、紀錄路徑由 retrieval_rules 帶入(範本有用到的才帶)。佔位符沒填完或 --set 了範本沒有的都拒絕。"""
    from engine import retrieval_rules
    try:
        if any('=' not in item for item in args.set or []):
            raise ValueError('--set 要寫成 KEY=VALUE')
        given = dict(item.split('=', 1) for item in args.set or [])
        with open(os.path.join(TEMPLATES_DIR, f'{args.template}.txt'), 'r', encoding='utf-8') as f:
            template = f.read()
        found = {}
        if args.phase:
            r = retrieval_rules.build(args.phase, side=args.side, case_dir=args.case_dir, exclude=args.exclude)
            found = {'RETRIEVAL_RULES': r['text'], 'RETRIEVAL_CACHE_DIR': r.get('snapshot'), 'SEARCH_LOG_PATH': r.get('log')}
    except (ValueError, OSError) as error:
        print(f"拒絕產生：{error}", file=sys.stderr)
        return 2
    wanted = set(PLACEHOLDER_RE.findall(template))
    values = {**{k: v for k, v in found.items() if k in wanted and v}, **given}
    missing, unknown = sorted(wanted - values.keys()), sorted(given.keys() - wanted)
    if missing or unknown:
        print('拒絕產生：' + '；'.join(([f"沒有填 {'、'.join(missing)}"] if missing else [])
                                   + ([f"範本沒有 {'、'.join(unknown)}"] if unknown else [])), file=sys.stderr)
        return 2
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        f.write(PLACEHOLDER_RE.sub(lambda m: values[m.group(1)], template))
    print(args.out)
    return 0


def main():
    parser = argparse.ArgumentParser(description="LegalDebate 落地 CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("case", help="落地案件輸入")
    p.add_argument("--json", required=True)
    p.set_defaults(fn=cmd_case)

    p = sub.add_parser("precheck", help="印出起訴前檢查的提示(程序類型、調解、時效),不呼叫 LLM")
    p.add_argument("--case-id", required=True)
    p.set_defaults(fn=cmd_precheck)

    p = sub.add_parser("role-view", help="印出某角色可讀的案件資料")
    p.add_argument("--case-id", required=True)
    p.add_argument("--role", choices=("plaintiff", "defendant"), required=True)
    p.add_argument("--out", help="寫成這個檔，只印路徑")
    p.set_defaults(fn=cmd_role_view)

    p = sub.add_parser("record", help="落地攻防論證或法官訊問(JSON 檔)")
    p.add_argument("--json", required=True)
    p.add_argument("--snapshot", help="案件的快照根目錄；判例落地查證讀雙方讀過的同一版本全文")
    p.set_defaults(fn=cmd_record)

    p = sub.add_parser("finalize", help="機械彙整(雙方讓步條件+引用清單差異)，印出評估錨點")
    p.add_argument("--case-id", required=True)
    p.add_argument("--for-judge", action="store_true", help="只印給法官讀的讓步條件與程序事項")
    p.set_defaults(fn=cmd_finalize)

    p = sub.add_parser("issues", help="依案件的商工查核結果印出法官應依職權調查的程序事項")
    p.add_argument("--case-id", required=True)
    p.set_defaults(fn=cmd_issues)

    p = sub.add_parser("public-args", help="印出法官與對手摘要可讀的論證(濾掉內部檢討)")
    p.add_argument("--case-id", required=True)
    p.add_argument("--through-stage", type=int, choices=(1, 2, 3), default=3)
    p.add_argument("--out", help="寫成這個檔，只印路徑")
    p.set_defaults(fn=cmd_public_args)

    p = sub.add_parser("check-judge", help="落地前檢查法官輸出(整批訊問或評估)，不寫入資料庫")
    p.add_argument("--case-id", required=True)
    p.add_argument("--json", required=True)
    p.set_defaults(fn=cmd_check_judge)

    p = sub.add_parser("verify", help="引用查證")
    p.add_argument("citations", nargs="+")
    p.add_argument('--precedent-notes', help='判例文件日期、案由及原文摘句 JSON 檔')
    p.add_argument('--snapshot', help='案件的快照根目錄；比對雙方角色讀過的同一版本全文與條文')
    p.add_argument('--read-by', choices=('plaintiff', 'defendant'),
                   help='查某一方書狀的引用：該方沒用 judgment 讀過全文的判決回 not_read_by_side，不放行')
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("verdict", help="落地法官判決書")
    p.add_argument("--case-id", required=True)
    p.add_argument("--json", required=True)
    p.set_defaults(fn=cmd_verdict)

    p = sub.add_parser("pleading", help="落地訴狀草稿")
    p.add_argument("--case-id", required=True)
    p.add_argument("--draft-file", required=True)
    p.add_argument("--citations", required=True, help="JSON 檔:此份訴狀引用的 citation_text 陣列")
    p.add_argument("--side", choices=("plaintiff", "defendant"), default="plaintiff",
                   help="哪一方的書狀:plaintiff=民事起訴狀(預設)、defendant=民事答辯狀")
    p.set_defaults(fn=cmd_pleading)

    p = sub.add_parser("complaint", help="書狀交換流程:檢查並落地起訴狀 v1(正文由程式組成)")
    p.add_argument("--case-id", required=True)
    p.add_argument("--json", required=True, help="撰狀 subagent 輸出的起訴狀 JSON")
    p.add_argument("--check", action="store_true", help="只檢查並印出組成後的正文，不落地")
    p.add_argument("--review-json", help="判決實質核對結果 JSON 陣列:[{citation, supports, reason}]")
    p.add_argument("--snapshot", help="案件的快照根目錄;引用判決時用來核對原告讀過全文(UI 執行時由環境變數提供)")
    p.set_defaults(fn=cmd_complaint)

    p = sub.add_parser("pleading-source", help="印出某一方的撰狀素材(Stage 3 原文、對造摘要、引用查證狀態)")
    p.add_argument("--case-id", required=True)
    p.add_argument("--side", choices=("plaintiff", "defendant"), required=True)
    p.set_defaults(fn=cmd_pleading_source)

    p = sub.add_parser("serve", help="啟動 UI 後端(預設只綁本機 127.0.0.1)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--no-browser", action="store_true", help="不自動開啟瀏覽器")
    p.add_argument("--model", help="即時執行使用的 Claude 模型(預設 claude-sonnet-5-5,主 agent 與 subagent 相同)")
    p.add_argument("--budget-usd", type=float, help="即時執行每次的花費上限(美元，預設 15)")
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("export-demo", help="匯出錄製紀錄 fixture 到 demo/")
    p.add_argument("--live-checks", action="store_true",
                   help="另對 DB 中無 published 紀錄的引用實際連線查證並記錄(需要網路)")
    p.add_argument("--party-checks", action="store_true", help="匯出既有商工實際查詢結果供離線重播")
    p.set_defaults(fn=cmd_export_demo)

    p = sub.add_parser("party", help="依統編即時查核商工登記當事人")
    p.add_argument("--ban", required=True)
    p.add_argument("--case-id")
    p.add_argument("--role", choices=("plaintiff", "defendant"))
    p.add_argument("--name", help="選填的預期名稱，供比對登記名稱")
    p.add_argument("--no-persist", action="store_true")
    p.set_defaults(fn=cmd_party)

    p = sub.add_parser("article", help="依法規名稱與條號查現行條文(7 天內讀快取，否則上網)")
    p.add_argument("query", nargs="+", help="例如：民法 33、民法 191之2、民法第191條之2")
    p.add_argument("--json", action="store_true", help="輸出結構化結果")
    _retrieval_options(p)
    p.set_defaults(fn=cmd_article)

    p = sub.add_parser("search-judgments", help="上網搜尋最高法院民事裁判(司法院裁判書查詢系統)")
    p.add_argument("--kw", action="append", help="全文關鍵字，可重複指定(皆須命中)")
    p.add_argument("--title", help="案由，例如：損害賠償")
    p.add_argument("--from", dest="date_from", help="裁判日期起，YYYY-MM-DD")
    p.add_argument("--to", dest="date_to", help="裁判日期迄，YYYY-MM-DD")
    p.add_argument("--pages", type=int, default=2, help="最多讀幾頁結果(每頁 20 筆，上限 5)")
    p.add_argument("--fetch", type=int, default=0, help="抓前幾份判決全文並整理(上限 10)")
    p.add_argument("--include-rulings", action="store_true", help="抓全文時也包含裁定(預設只抓判決)")
    p.add_argument("--min-size", type=int, help="裁判內容大小下限(K)，用來濾掉短篇程序裁定")
    p.add_argument("--sort", choices=("date", "size"), default="date",
                   help="date=裁判日期新到舊(預設)；size=裁判大小大到小，長篇多為實體判決，但全文較長且年代較舊")
    p.add_argument("--save-dir", help="把查詢結果與抓到的全文存到此資料夾")
    p.add_argument("--json", action="store_true", help="輸出結構化結果")
    _retrieval_options(p, judgments=True)
    p.set_defaults(fn=cmd_search_judgments)

    p = sub.add_parser("search-statutes", help="依關鍵字上網搜尋法規條文(全國法規資料庫)")
    p.add_argument("--kw", required=True, help="條文關鍵字，例如：知有損害")
    p.add_argument("--law", help="只搜這部法規，例如：民法")
    p.add_argument("--laws", type=int, default=3, help="未指定 --law 時展開前幾部法規的條文(上限 5)")
    p.add_argument("--json", action="store_true", help="輸出結構化結果")
    p.add_argument("--log", help="檢索紀錄檔(JSON Lines)；只記錄，不計入搜尋預算")
    p.set_defaults(fn=cmd_search_statutes)

    p = sub.add_parser("judgment", help="依裁判字號或 JID 讀判決全文(快照→快取→預先內容→上網)")
    p.add_argument("target", help="例如：111年度台上字第1069號、最高法院111年度台上字第1069號，或 JID")
    p.add_argument("--doc-date", help="同字號多份文件時指定裁判日期 YYYYMMDD")
    p.add_argument("--json", action="store_true", help="輸出結構化結果(含原文與去換行版)")
    _retrieval_options(p, judgments=True)
    p.set_defaults(fn=cmd_judgment)

    p = sub.add_parser("retrieval-rules", help="印出該階段的檢索規則(給調度員填範本的 {RETRIEVAL_RULES})")
    p.add_argument("--phase", required=True,
                   help="p1、p2、p4、p5(或 complaint、scenario、answer、brief、closing)、stage1～3；不檢索的 p3、p6、verify")
    p.add_argument("--side", choices=("plaintiff", "defendant"),
                   help="與 --case-dir 一起給時印出該角色的 --snapshot 與 --log 路徑")
    p.add_argument("--case-dir", help="案件資料夾，例如 database/live_runs/case-<案件ID>")
    p.add_argument("--exclude", action="append",
                   help="示範案的來源裁判(字號或 JID，可重複)；帶進角色與法官的 search-judgments、judgment 指令")
    p.add_argument("--json", action="store_true", help="輸出結構化結果(含規則全文、預算與路徑)")
    p.set_defaults(fn=cmd_retrieval_rules)

    p = sub.add_parser("prompt", help="把範本填好寫成檔，只印路徑(subagent 自己讀，主 agent 不經手全文)")
    p.add_argument("template", help="templates/ 下的範本名，例如 stage1_prompt")
    p.add_argument("--out", required=True)
    p.add_argument("--set", action="append", metavar="KEY=VALUE", help="填一個佔位符，可重複")
    p.add_argument("--phase", help="同 retrieval-rules;帶入 {RETRIEVAL_RULES}、{RETRIEVAL_CACHE_DIR}、{SEARCH_LOG_PATH}")
    p.add_argument("--side", choices=("plaintiff", "defendant"))
    p.add_argument("--case-dir")
    p.add_argument("--exclude", action="append", help="示範案的來源裁判(字號或 JID，可重複)")
    p.set_defaults(fn=cmd_prompt)

    args = parser.parse_args()
    if args.cmd in ('record', 'verify') and args.snapshot:
        # record 的判例落地查證在 engine/role_protocol.py 內呼叫查證引擎，以環境變數把快照傳下去。
        from engine.verify import SNAPSHOT_ENV
        os.environ[SNAPSHOT_ENV] = os.path.abspath(args.snapshot)
    sys.exit(args.fn(args))


def _retrieval_options(p, judgments=False):
    p.add_argument("--snapshot", help="本角色的快照資料夾({RETRIEVAL_CACHE_DIR}，<快照根目錄>/plaintiff 或 defendant)")
    p.add_argument("--log", help="本角色本階段的檢索紀錄檔({SEARCH_LOG_PATH})；依檔名的階段(p1、p2、p4、p5 或 stage1～3)計算查詢預算")
    if judgments:
        p.add_argument("--issue", help="這次查詢針對的爭點 id(如 I1)，記入檢索紀錄")
        p.add_argument("--exclude", action="append",
                       help="不提供的裁判(字號或 JID，可重複)，例如示範案的來源裁判；同字號的每一份文件都排除")


if __name__ == "__main__":
    main()
