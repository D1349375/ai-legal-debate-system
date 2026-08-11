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

    args = parser.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
