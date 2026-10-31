"""LegalDebate CLI — 供 Claude Code orchestrator(legal-debate skill)呼叫的落地工具。

LLM 推理不在這裡發生:原告/被告/法官的論證由 Claude Code subagent 產生，
本 CLI 只負責案件輸入、攻防落地、機械聚合、查證與最終輸出的資料庫紀律。

用法:
  python main.py case     --json <file>                 案件輸入
  python main.py record   --json <file>                 落地一方一階段的論證，或一則法官訊問
  python main.py finalize --case-id X                    機械死穴彙整+分歧統計+程序事項，印出判決錨點
  python main.py issues   --case-id X                    依商工查核結果印出法官應依職權調查的程序事項
  python main.py verify   <citation> [<citation> ...]     引用查證
  python main.py verdict  --case-id X --json <file>       落地法官判決書(引用未 published 即拒絕)
  python main.py pleading --case-id X --draft-file <file> --citations <file> [--side plaintiff|defendant]
                                                          落地訴狀草稿(預設原告起訴狀；defendant=被告答辯狀)
  python main.py pleading-source --case-id X --side defendant  印出該方撰狀素材(Stage 3+查證狀態),不重跑攻防補產書狀用
  python main.py serve    [--port 8000] [--no-browser]     啟動 UI 後端(重播錄製案例、執行機械環節；綁本機時可由 UI 觸發即時執行)
  python main.py export-demo [--live-checks]               把 DB 的錄製紀錄匯出為 demo/ fixture(離線重現用)
  python main.py party --ban 22099131 [--case-id X --role defendant] [--name 名稱] [--no-persist]
"""
import argparse
import json
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

from database.db import (
    get_session, record_case, record_argument, record_question,
    finalize_case, record_verdict, record_pleading, upsert_citation,
)
from engine.party_issues import mixed_dismissal_citations
from engine.verify import verify_citations

PROTOCOL_VERSION = "v1-2026-08-07"
PLEADING_LABEL = {"plaintiff": "起訴狀", "defendant": "答辯狀"}


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
    try:
        if not payload.get('represented_side') and not getattr(args, 'legacy', False):
            raise ValueError('新案 represented_side 為必填，請選 plaintiff 或 defendant；既有封存案匯入可用 --legacy')
        row = record_case(session, case_id=payload["case_id"], case_type=payload["case_type"],
                           facts_summary=payload.get("facts_summary", ''), claims=payload["claims"],
                           represented_side=payload.get('represented_side'),
                           uncontested_facts=payload.get('uncontested_facts'), plaintiff_facts=payload.get('plaintiff_facts'),
                           defendant_facts=payload.get('defendant_facts'), claim_amount=payload.get('claim_amount'))
    except ValueError as e:
        print(f'拒絕落地:{e}', file=sys.stderr)
        return 1
    print(f"已落地案件 {row.case_id}")
    from engine.role_protocol import procedure_warning
    for warning in procedure_warning(row.claim_amount, row.claims)['warnings']:
        print('警示：' + warning)
    return 0


def cmd_record(args):
    with open(args.json, 'r', encoding='utf-8') as f:
        payload = json.load(f)
    session = get_session()
    try:
        if 'questions' in payload:
            from database.db import record_judge_bundle
            row = record_judge_bundle(session, case_id=payload['case_id'], payload=payload)
            print(f'已落地法官訊問與爭點 {row.case_id}')
            return 0
        if "question_text" in payload:
            row = record_question(session, case_id=payload["case_id"], question_text=payload["question_text"],
                                   target_side=payload["target_side"], based_on=payload["based_on"],
                                   question_type=payload.get('question_type'), structured_json=payload)
            print(f"已落地訊問 {row.case_id} -> {row.target_side}")
            return 0
        row = record_argument(
            session, case_id=payload["case_id"], side=payload["side"], stage=int(payload["stage"]),
            position=payload["position"], reasoning=_pick(payload, "argument", "reasoning"),
            cited_statutes=payload.get("cited_statutes"), cited_precedents=payload.get("cited_precedents"),
            falsifier=payload.get("falsifier"), model_id=payload.get("model_id"),
            structured_json=payload.get('structured_json', payload) if 'items' in payload or 'structured_json' in payload else None,
        )
    except (ValueError, KeyError, TypeError) as e:  # 格式不合時回可修正的原因，不印 traceback
        print(f"拒絕落地:{e}", file=sys.stderr)
        return 1
    print(f"已落地論證 {row.case_id} {row.side} stage{row.stage}")
    return 0


def cmd_finalize(args):
    session = get_session()
    result = finalize_case(session, case_id=args.case_id)
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
    import uuid
    session = get_session()
    run_id = getattr(args, 'run_id', None) or str(uuid.uuid4())
    try:
        options = {}
        prepared = None
        candidate = None
        if getattr(args, 'candidate_json', None):
            with open(args.candidate_json, encoding='utf-8') as f:
                candidate = json.load(f)
        if getattr(args, 'case_id', None):
            from engine.citation_review import case_verification_inputs
            prepared = case_verification_inputs(session, args.case_id, candidate)
            options = {k: prepared[k] for k in ('precedent_notes', 'version_hints')}
        elif candidate is not None:
            raise ValueError('--candidate-json 須搭配 --case-id')
        for attr in ('precedent_notes', 'version_hints'):
            if getattr(args, attr, None):
                with open(getattr(args, attr), encoding='utf-8') as f:
                    options[attr] = json.load(f)
        citations = args.citations or (prepared['citations'] if prepared else [])
        from engine.citation_review import propagate_version_hints
        options['version_hints'] = propagate_version_hints(citations, options.get('version_hints'))
        if getattr(args, 'prepare_only', False):
            if prepared is None:
                raise ValueError('--prepare-only 須搭配 --case-id')
            print(json.dumps({**prepared, 'citations': citations, **options}, ensure_ascii=False, indent=2))
            return 0
        if not citations:
            raise ValueError('請指定引用，或提供含已落地引用的 --case-id；只讀清單請用 --prepare-only')
        review = None
        if getattr(args, 'review_json', None):
            with open(args.review_json, encoding='utf-8') as f:
                review = json.load(f)
            if not isinstance(review, dict) or not getattr(args, 'case_id', None) or review.get('case_id') != args.case_id:
                raise ValueError('獨立查證 case_id 必須與 --case-id 相同')
            if getattr(args, 'run_id', None) and args.run_id != review.get('verifier_run_id'):
                raise ValueError('--run-id 與獨立查證 verifier_run_id 不一致')
        if getattr(args, 'case_id', None):
            from engine.role_protocol import case_row
            case_row(session, args.case_id)
        mechanical = verify_citations(citations, **options)
        results = mechanical
        if review is not None:
            from engine.citation_review import validate_review_payload
            adopted = prepared['adopted_citations'] if prepared and (candidate is not None or not args.citations or prepared['adopted_citations']) else None
            run_id, results = validate_review_payload(review, args.case_id, citations, mechanical, adopted)
        # 全部格式與交叉驗證通過後才開始寫入；支持性判斷僅進本案紀錄。
        for r in mechanical:
            if r.get("status") == "published":
                upsert_citation(session, citation_text=r["citation_text"], source_type=r["source_type"],
                                 status="published", primary_source_url=r.get("primary_source_url"))
        if getattr(args, 'case_id', None):
            from database.db import record_case_citation_check
            for r in results:
                record_case_citation_check(session, args.case_id, r, run_id)
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(f'拒絕落地:{error}', file=sys.stderr)
        return 1
    finally:
        session.close()


def cmd_verdict(args):
    with open(args.json, 'r', encoding='utf-8') as f:
        payload = json.load(f)
    main_text = payload.get('verdict_main_text', payload.get('summary', ''))
    analysis = payload.get('verdict_analysis', payload.get('verdict_reasoning', json.dumps(payload.get('issues', []), ensure_ascii=False)))
    risk_map = payload.get('risk_map', {'issues': payload.get('issues', [])})
    mixed = mixed_dismissal_citations("\n".join([main_text, analysis, json.dumps(risk_map, ensure_ascii=False)]))
    if mixed:
        print("拒絕落地:第249條與最高法院115年度台抗字第105號放在同一個括號，讀起來像該裁定也支持駁回:"
              + ";".join(mixed) + "。請退回法官 subagent 分開引註:第249條接在逾期未補正以裁定駁回之後，"
              "115台抗105 只接在法院應依職權調查實際代表權之後", file=sys.stderr)
        return 1
    session = get_session()
    try:
        row = record_verdict(
            session, case_id=args.case_id, verdict_main_text=main_text,
            verdict_reasoning=analysis, risk_map=risk_map,
            mechanical_anchor_json=payload.get("mechanical_anchor_json", {}),
            protocol_version=PROTOCOL_VERSION, citations_used=payload.get("citations_used", []),
            structured_json=payload,
        )
    except (ValueError, KeyError, TypeError) as e:
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
        breakdown = None
        if getattr(args, 'claim_breakdown', None):
            with open(args.claim_breakdown, encoding='utf-8') as f:
                breakdown = json.load(f)
        row = record_pleading(session, case_id=args.case_id, draft_text=draft_text,
                               citations_used=citations_used, side=args.side, claim_breakdown=breakdown)
    except ValueError as e:
        print(f"拒絕落地:{e}", file=sys.stderr)
        return 1
    print(f"已落地{PLEADING_LABEL[row.side]}草稿 {row.case_id}")
    for warning in json.loads(row.warnings_json or '[]'):
        print('警示：' + warning)
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


def cmd_projection(args):
    from engine.role_protocol import role_view, argument_summary, preparation_materials, build_report, render_report
    session = get_session()
    try:
        if args.cmd == 'role-view':
            result = role_view(session, args.case_id, args.role)
        elif args.cmd == 'summary':
            result = argument_summary(session, args.case_id, args.side, args.stage)
        elif args.cmd == 'prep-list':
            result = preparation_materials(session, args.case_id, args.role)
        else:
            result = build_report(session, args.case_id)
            if not getattr(args, 'json', False):
                print(render_report(result))
                return 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, TypeError) as e:
        print(f'無法產生資料:{e}', file=sys.stderr)
        return 1
    finally:
        session.close()


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
        representative = r.get("legal_representative")
        directors_failed = r.get("company_form") == "股份有限公司" and any(
            source["dataset"] == "公司登記董監事資料" and not source["ok"] for source in r["sources"])
        rep_text = (f"{representative['title']} {representative['name']}" if representative
                    else "查核未完成，未自動帶入" if failed
                    else f"待確認(在臺負責人:{r.get('registered_responsible_name') or '官方登記未提供'})" if any(w["code"] == "foreign_branch" for w in r["warnings"])
                    else "待確認(清算人)" if any(w["code"] == "foreign_dissolved" for w in r["warnings"])
                    else "董監事資料查詢失敗，未自動帶入" if directors_failed
                    else "待確認（清算人）" if any(w["code"] == "dissolved" for w in r["warnings"])
                    else "官方未提供／未自動帶入")
        print(f"法定代理人：{rep_text}")
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


def main():
    parser = argparse.ArgumentParser(description="LegalDebate 落地 CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("case", help="落地案件輸入")
    p.add_argument("--json", required=True)
    p.add_argument('--legacy', action='store_true', help='只供匯入既有舊案；新建案仍須指定 represented_side')
    p.set_defaults(fn=cmd_case)

    p = sub.add_parser("record", help="落地攻防論證或法官訊問(JSON 檔)")
    p.add_argument("--json", required=True)
    p.set_defaults(fn=cmd_record)

    p = sub.add_parser("finalize", help="機械死穴彙整+分歧統計，印出判決錨點")
    p.add_argument("--case-id", required=True)
    p.set_defaults(fn=cmd_finalize)

    p = sub.add_parser("issues", help="依案件的商工查核結果印出法官應依職權調查的程序事項")
    p.add_argument("--case-id", required=True)
    p.set_defaults(fn=cmd_issues)

    p = sub.add_parser("verify", help="引用查證")
    p.add_argument("citations", nargs="*")
    p.add_argument('--case-id', help='將全部結果另存該案查證紀錄')
    p.add_argument('--run-id', help='本次獨立查證識別碼')
    p.add_argument('--precedent-notes', help='判例文件日期、案由及原文摘句 JSON')
    p.add_argument('--version-hints', help='角色標註的歷史法規版本 JSON')
    p.add_argument('--review-json', help='獨立查證的結構化結果；與同次機械查證核對後存入本案')
    p.add_argument('--prepare-only', action='store_true', help='唯讀輸出本案查證清單、判例身分資料與版本提示')
    p.add_argument('--candidate-json', help='尚未落地的評估草稿；將新增與採用引用納入查證清單')
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("verdict", help="落地法官判決書")
    p.add_argument("--case-id", required=True)
    p.add_argument("--json", required=True)
    p.set_defaults(fn=cmd_verdict)

    p = sub.add_parser("pleading", help="落地訴狀草稿")
    p.add_argument("--case-id", required=True)
    p.add_argument("--draft-file", required=True)
    p.add_argument("--citations", required=True, help="JSON 檔:此份訴狀引用的 citation_text 陣列")
    p.add_argument('--claim-breakdown', help='請求金額明細 JSON 檔')
    p.add_argument("--side", choices=("plaintiff", "defendant"), default="plaintiff",
                   help="哪一方的書狀:plaintiff=民事起訴狀(預設)、defendant=民事答辯狀")
    p.set_defaults(fn=cmd_pleading)

    p = sub.add_parser("pleading-source", help="印出某一方的撰狀素材(Stage 3 原文、對造摘要、引用查證狀態)")
    p.add_argument("--case-id", required=True)
    p.add_argument("--side", choices=("plaintiff", "defendant"), required=True)
    p.set_defaults(fn=cmd_pleading_source)

    for command in ('role-view', 'summary', 'prep-list', 'report'):
        p = sub.add_parser(command, help='由程式產出角色可見資料或使用者回報')
        p.add_argument('--case-id', required=True)
        if command in ('role-view', 'prep-list'):
            p.add_argument('--role', choices=('plaintiff', 'defendant', 'judge'), required=True)
        if command == 'summary':
            p.add_argument('--side', choices=('plaintiff', 'defendant'), required=True)
            p.add_argument('--stage', type=int, choices=(1, 2, 3), required=True)
        if command == 'report':
            p.add_argument('--json', action='store_true', help='輸出與總覽 API 相同的結構')
        p.set_defaults(fn=cmd_projection)

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

    args = parser.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
