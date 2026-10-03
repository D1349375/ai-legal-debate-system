"""LegalDebate CLI — 供 Claude Code orchestrator(legal-debate skill)呼叫的落地工具。

LLM 推理不在這裡發生:原告/被告/法官的論證由 Claude Code subagent 產生，
本 CLI 只負責案件輸入、攻防落地、機械聚合、查證與最終輸出的資料庫紀律。

用法:
  python main.py case     --json <file>                 案件輸入
  python main.py record   --json <file>                 落地一方一階段的論證，或一則法官訊問
  python main.py finalize --case-id X                    機械死穴彙整+分歧統計，印出判決錨點
  python main.py verify   <citation> [<citation> ...]     引用查證
  python main.py verdict  --case-id X --json <file>       落地法官判決書(引用未 published 即拒絕)
  python main.py pleading --case-id X --draft-file <file> --citations <file>  落地訴狀草稿
  python main.py serve    [--port 8000] [--no-browser]     啟動 UI 後端(重播錄製案例 + 真實執行機械環節)
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
from engine.verify import verify_citations

PROTOCOL_VERSION = "v1-2026-08-07"


def cmd_case(args):
    with open(args.json, 'r', encoding='utf-8') as f:
        payload = json.load(f)
    session = get_session()
    row = record_case(session, case_id=payload["case_id"], case_type=payload["case_type"],
                       facts_summary=payload["facts_summary"], claims=payload["claims"])
    print(f"已落地案件 {row.case_id}")
    return 0


def cmd_record(args):
    with open(args.json, 'r', encoding='utf-8') as f:
        payload = json.load(f)
    session = get_session()
    if "question_text" in payload:
        row = record_question(session, case_id=payload["case_id"], question_text=payload["question_text"],
                               target_side=payload["target_side"], based_on=payload["based_on"])
        print(f"已落地訊問 {row.case_id} -> {row.target_side}")
        return 0
    row = record_argument(
        session, case_id=payload["case_id"], side=payload["side"], stage=int(payload["stage"]),
        position=payload["position"], reasoning=payload["reasoning"],
        cited_statutes=payload.get("cited_statutes"), cited_precedents=payload.get("cited_precedents"),
        falsifier=payload.get("falsifier"), model_id=payload.get("model_id"),
    )
    print(f"已落地論證 {row.case_id} {row.side} stage{row.stage}")
    return 0


def cmd_finalize(args):
    session = get_session()
    result = finalize_case(session, case_id=args.case_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_verify(args):
    session = get_session()
    results = verify_citations(args.citations)
    for r in results:
        if r.get("status") == "published":
            upsert_citation(session, citation_text=r["citation_text"], source_type=r["source_type"],
                             status="published", primary_source_url=r.get("primary_source_url"))
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


def cmd_verdict(args):
    with open(args.json, 'r', encoding='utf-8') as f:
        payload = json.load(f)
    session = get_session()
    try:
        row = record_verdict(
            session, case_id=args.case_id, verdict_main_text=payload["verdict_main_text"],
            verdict_reasoning=payload["verdict_reasoning"], risk_map=payload["risk_map"],
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
                               citations_used=citations_used)
    except ValueError as e:
        print(f"拒絕落地:{e}", file=sys.stderr)
        return 1
    print(f"已落地訴狀草稿 {row.case_id}")
    return 0


def cmd_serve(args):
    import threading
    import webbrowser

    import uvicorn
    from server.app import create_app

    app = create_app()
    url = f"http://{args.host}:{args.port}/"
    if app.state.seeded:
        print(f"資料庫原本沒有案件，已由 demo/recorded_cases.json 匯入錄製紀錄:{app.state.seeded}")
    print(f"LegalDebate UI:{url}(Ctrl+C 結束)")
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
    p.set_defaults(fn=cmd_case)

    p = sub.add_parser("record", help="落地攻防論證或法官訊問(JSON 檔)")
    p.add_argument("--json", required=True)
    p.set_defaults(fn=cmd_record)

    p = sub.add_parser("finalize", help="機械死穴彙整+分歧統計，印出判決錨點")
    p.add_argument("--case-id", required=True)
    p.set_defaults(fn=cmd_finalize)

    p = sub.add_parser("verify", help="引用查證")
    p.add_argument("citations", nargs="+")
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("verdict", help="落地法官判決書")
    p.add_argument("--case-id", required=True)
    p.add_argument("--json", required=True)
    p.set_defaults(fn=cmd_verdict)

    p = sub.add_parser("pleading", help="落地訴狀草稿")
    p.add_argument("--case-id", required=True)
    p.add_argument("--draft-file", required=True)
    p.add_argument("--citations", required=True, help="JSON 檔:此份訴狀引用的 citation_text 陣列")
    p.set_defaults(fn=cmd_pleading)

    p = sub.add_parser("serve", help="啟動 UI 後端(預設只綁本機 127.0.0.1)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--no-browser", action="store_true", help="不自動開啟瀏覽器")
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
