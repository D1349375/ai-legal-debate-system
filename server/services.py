"""UI 後端的資料組裝與機械環節封裝。

本層只做兩件事：
1. 把 DB 裡「已落地的錄製紀錄」組成 UI 需要的結構(不改寫、不補寫任何論證內容)；
2. 真實執行機械環節(finalize / verify)，並如實回報來源與失敗狀態。

引擎本身不含 LLM 推理——原告/被告/法官的論證是過去由 Claude Code subagent 產生後
經 `main.py record` 落地，這裡回傳的論證內容全部是重播，呼叫端(UI)必須標示為錄製紀錄。
"""
import functools
import json
import os
import re
import time

from database.db import _citation_key, _find_citation_row, finalize_case, upsert_citation, record_party_check, latest_party_checks
from database.schema import (
    Case, CitationVerification, CourtQuestion, DebateArgument, PleadingDraft, Verdict,
)
from engine import verify as engine_verify
from engine import gcis, party_rules
from engine.aggregate import VALID_SIDES, disagreement
from engine.verify import (
    JUDGMENT_CITATION_RE, JUDGMENTS_DIR, STATUTE_CITATION_RE, STATUTE_PCODES, STATUTES_DIR,
    parse_citation,
)

SIDE_ORDER = {side: i for i, side in enumerate(VALID_SIDES)}

# 查證狀態(UI 只認這幾種，不得憑空新增其他「看起來通過」的狀態)：
#   published            權威來源比對通過(官網即時 / FJUD 即時 / 本地判決語料庫[司法院開放資料])
#   local_cache_only     官網即時查詢失敗，僅本地法典快取有此條——不等於通過，閘門不放行、不寫入 DB
#   not_found            權威來源明確回報查無(捏造/錯誤引用會落在這裡)
#   verification_failed  無法完成官方查證(網路逾時/離線/被略過)，既非通過也非查無
#   unparseable          格式無法解析為法條或裁判字號
#   unknown_law          法規不在查證引擎範圍
STATUSES = ("published", "local_cache_only", "not_found", "verification_failed",
            "unparseable", "unknown_law")

_ALLOWED_SOURCE_HOSTS = ("https://law.moj.gov.tw/", "https://judgment.judicial.gov.tw/")

_STATUTE_FILES = {
    "民法": "民法.txt", "公司法": "公司法.txt", "勞動基準法": "勞動基準法.txt",
    "勞基法": "勞動基準法.txt", "消費者保護法": "消費者保護法.txt", "刑法": "刑法.txt",
}  # 民事訴訟法無本地快取，只能走官網即時查證


def _rel_corpus_path(path):
    """對外只給相對路徑，不洩漏本機絕對路徑。"""
    name = os.path.basename(path)
    folder = os.path.basename(os.path.dirname(os.path.abspath(path)))
    return f"corpus/{folder}/{name}"


def _safe_url(url):
    return url if url and url.startswith(_ALLOWED_SOURCE_HOSTS) else None


def _json_list(raw):
    return json.loads(raw) if raw else []


# ───────────────────────── 案件讀取 ─────────────────────────

def _load_input_cases(cases_dir):
    """data/cases/*.json 中尚未落地進 DB 的案件輸入(只有案情，沒有任何攻防紀錄)。"""
    result = {}
    if not cases_dir or not os.path.isdir(cases_dir):
        return result
    for name in sorted(os.listdir(cases_dir)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(cases_dir, name), encoding="utf-8") as f:
                payload = json.load(f)
            result[payload["case_id"]] = payload
        except (OSError, ValueError, KeyError):
            continue
    return result


def _case_counts(session):
    counts = {}
    for cid, in session.query(DebateArgument.case_id).all():
        counts.setdefault(cid, {"arguments": 0, "questions": 0})["arguments"] += 1
    for cid, in session.query(CourtQuestion.case_id).all():
        counts.setdefault(cid, {"arguments": 0, "questions": 0})["questions"] += 1
    return counts


def list_cases(session, cases_dir=None):
    counts = _case_counts(session)
    verdict_ids = {c for c, in session.query(Verdict.case_id).all()}
    pleading_ids = {c for c, in session.query(PleadingDraft.case_id).all()}
    items = []
    db_ids = set()
    for row in session.query(Case).order_by(Case.created_at.desc()).all():
        db_ids.add(row.case_id)
        c = counts.get(row.case_id, {"arguments": 0, "questions": 0})
        if row.case_id in pleading_ids and row.case_id in verdict_ids:
            status = "completed"
        elif c["arguments"]:
            status = "in_progress"
        else:
            status = "case_only"
        items.append({
            "case_id": row.case_id, "case_type": row.case_type, "created_at": row.created_at,
            "facts_excerpt": row.facts_summary[:60], "source": "database", "status": status,
            "arguments": c["arguments"], "questions": c["questions"],
            "has_verdict": row.case_id in verdict_ids, "has_pleading": row.case_id in pleading_ids,
        })
    for cid, payload in _load_input_cases(cases_dir).items():
        if cid in db_ids:
            continue
        items.append({
            "case_id": cid, "case_type": payload.get("case_type", ""), "created_at": None,
            "facts_excerpt": payload.get("facts_summary", "")[:60], "source": "input_only",
            "status": "input_only", "arguments": 0, "questions": 0,
            "has_verdict": False, "has_pleading": False,
        })
    return items


def _citation_lookup(session):
    rows = session.query(CitationVerification).all()
    by_key = {}
    for r in rows:
        by_key.setdefault(_citation_key(r.citation_text), r)
    return by_key


def _db_record(row, asked_text):
    if row is None:
        return None
    return {
        "status": row.status, "verified_at": row.verified_at,
        "primary_source_url": _safe_url(row.primary_source_url),
        "db_citation_text": row.citation_text,
        "matched_by": "exact" if row.citation_text == asked_text else "normalized",
    }


def _arg_to_api(row):
    return {
        "side": row.side, "stage": row.stage, "position": row.position, "reasoning": row.reasoning,
        "cited_statutes": _json_list(row.cited_statutes), "cited_precedents": _json_list(row.cited_precedents),
        "falsifier": row.falsifier, "model_id": row.model_id, "created_at": row.created_at,
    }


def citation_changes(arguments):
    """每一方相鄰階段間「新增/撤回」的引用(純集合差，機械比對，不做語意判斷)。"""
    result = []
    for side in VALID_SIDES:
        by_stage = {}
        for a in arguments:
            if a["side"] == side:
                by_stage[a["stage"]] = set(a["cited_statutes"]) | set(a["cited_precedents"])
        for s_from, s_to in ((1, 2), (2, 3)):
            if s_from in by_stage and s_to in by_stage:
                result.append({
                    "side": side, "from_stage": s_from, "to_stage": s_to,
                    "added": sorted(by_stage[s_to] - by_stage[s_from]),
                    "dropped": sorted(by_stage[s_from] - by_stage[s_to]),
                })
    return result


def drift_detail(arguments):
    """position_drift 的計算明細(與 engine.aggregate.disagreement 同一公式，額外攤開集合供人工核對)。"""
    stage1 = [a for a in arguments if a["stage"] == 1]
    stage3 = [a for a in arguments if a["stage"] == 3]
    ratios = disagreement(stage1, stage3)
    detail = {}
    for side in VALID_SIDES:
        s1 = next((a for a in stage1 if a["side"] == side), None)
        s3 = next((a for a in stage3 if a["side"] == side), None)
        if s1 is None or s3 is None:
            detail[side] = {"ratio": None}
            continue
        set1 = set(s1["cited_statutes"]) | set(s1["cited_precedents"])
        set3 = set(s3["cited_statutes"]) | set(s3["cited_precedents"])
        detail[side] = {
            "ratio": ratios[side], "stage1_count": len(set1), "stage3_count": len(set3),
            "intersection": len(set1 & set3), "union": len(set1 | set3),
            "dropped": sorted(set1 - set3), "added": sorted(set3 - set1),
        }
    return detail


def _collect_citations(arguments, lookup, recorded_checks):
    entries = {}
    for a in sorted(arguments, key=lambda x: (x["stage"], SIDE_ORDER.get(x["side"], 9))):
        for text in a["cited_precedents"] + a["cited_statutes"]:
            entry = entries.setdefault(text, {"citation_text": text, "used_by": []})
            use = {"side": a["side"], "stage": a["stage"]}
            if use not in entry["used_by"]:
                entry["used_by"].append(use)
    citations = []
    for text, entry in entries.items():
        parsed = parse_citation(text)
        key = _citation_key(text)
        entry["kind"] = parsed["type"] if parsed["type"] != "unknown" else "unknown"
        entry["db_record"] = _db_record(lookup.get(key), text)
        entry["recorded_check"] = recorded_checks.get(key)
        citations.append(entry)
    order = {"judgment": 0, "statute": 1, "unknown": 2}
    citations.sort(key=lambda e: order[e["kind"]])
    return citations


def _anchor_check(stored_anchor, arguments):
    """把落地當時的 mechanical_anchor_json 與「現在重新機械計算」的結果比對(finalize 為決定性函數)。"""
    stage3 = [a for a in arguments if a["stage"] == 3]
    if len({a["side"] for a in stage3}) < len(VALID_SIDES):
        return None
    now = drift_detail(arguments)
    stored_drift = (stored_anchor or {}).get("position_drift", {})
    stored_falsifiers = {p.get("side"): p.get("falsifier") for p in (stored_anchor or {}).get("weak_points", [])}
    now_falsifiers = {a["side"]: a["falsifier"] for a in stage3}
    diffs, minor = [], []
    for side in VALID_SIDES:
        label = "原告" if side == "plaintiff" else "被告"
        if stored_drift.get(side) != now[side]["ratio"]:
            diffs.append(f"{label}立場位移度：落地時 {stored_drift.get(side)}，本次重新計算 {now[side]['ratio']}")
        stored_f, now_f = stored_falsifiers.get(side), now_falsifiers.get(side)
        if stored_f != now_f:
            if _strip_parens(stored_f) == _strip_parens(now_f):
                minor.append({"side": side, "stored": stored_f, "current": now_f,
                              "note": f"{label}方讓步條件的文字與最終階段原文略有出入(僅括號內文字不同)，實質內容一致"})
            else:
                diffs.append(f"{label}方讓步條件與落地時不同")
    return {"consistent": not diffs, "differences": diffs, "minor_differences": minor,
            "recomputed": {"position_drift": {s: now[s]["ratio"] for s in VALID_SIDES}}}


def _strip_parens(text):
    """去掉括號及其內容與空白，只用來判斷兩段文字是否僅差在括號補充語。"""
    return re.sub(r"[\s]+", "", re.sub(r"[（(][^）)]*[）)]", "", text or ""))


def _pleading_citation_check(draft_text, lookup):
    """由草稿文字重新解析其中引用，逐條對照 DB 查證紀錄(落地時的 citations 檔未存入 DB，故為重新解析)。"""
    seen, result = set(), []
    hits = [m.group(0) for m in STATUTE_CITATION_RE.finditer(draft_text)]
    hits += [m.group(0) for m in JUDGMENT_CITATION_RE.finditer(draft_text)]
    for text in hits:
        key = _citation_key(text)
        if key in seen:
            continue
        seen.add(key)
        result.append({"citation_text": text, "db_record": _db_record(lookup.get(key), text)})
    return result


def _progress(case_row, arguments, questions, verdict, pleading, citations):
    sides = lambda stage: len({a["side"] for a in arguments if a["stage"] == stage})  # noqa: E731
    published = sum(1 for c in citations if c["db_record"] and c["db_record"]["status"] == "published")

    def state(n, total):
        return "done" if n >= total else ("partial" if n else "pending")

    return [
        {"key": "case", "label": "案件輸入", "state": "done", "detail": ""},
        {"key": "stage1", "label": "Stage 1 爭點整理(雙方盲判)", "state": state(sides(1), 2), "detail": f"{sides(1)}/2 方"},
        {"key": "questions", "label": "法官訊問", "state": "done" if questions else "pending", "detail": f"{len(questions)} 則"},
        {"key": "stage2", "label": "Stage 2 訊問攻防", "state": state(sides(2), 2), "detail": f"{sides(2)}/2 方"},
        {"key": "stage3", "label": "Stage 3 辯論終結", "state": state(sides(3), 2), "detail": f"{sides(3)}/2 方"},
        {"key": "finalize", "label": "機械死穴彙整", "state": "ready" if sides(3) >= 2 else "pending",
         "detail": "可執行" if sides(3) >= 2 else "須雙方完成 Stage 3"},
        {"key": "verdict", "label": "法官爭點強弱評估", "state": "done" if verdict else "pending", "detail": ""},
        {"key": "verify", "label": "引用查證", "state": ("done" if citations and published == len(citations)
                                                        else ("partial" if published else "pending")),
         "detail": f"{published}/{len(citations)} 已查證通過"},
        {"key": "pleading", "label": "訴狀骨架初稿", "state": "done" if pleading else "pending", "detail": ""},
    ]


def get_case_detail(session, case_id, cases_dir=None, recorded_checks=None):
    recorded_checks = recorded_checks or {}
    case_row = session.query(Case).filter_by(case_id=case_id).one_or_none()
    if case_row is None:
        payload = _load_input_cases(cases_dir).get(case_id)
        if payload is None:
            return None
        return {
            "case": {"case_id": case_id, "case_type": payload.get("case_type", ""),
                     "facts_summary": payload.get("facts_summary", ""), "claims": payload.get("claims", ""),
                     "created_at": None, "source": "input_only"},
            "provenance": {"kind": "input_only", "model_ids": [], "first_recorded_at": None, "last_recorded_at": None},
            "arguments": [], "questions": [], "verdict": None, "pleading": None, "citations": [],
            "citation_changes": [], "drift_detail": None,
            "progress": _progress(None, [], [], None, None, []),
            "stats": {"arguments": 0, "questions": 0, "citations": 0, "citations_published": 0},
            "party_checks": latest_party_checks(session, case_id),
        }

    lookup = _citation_lookup(session)
    arguments = [_arg_to_api(r) for r in session.query(DebateArgument).filter_by(case_id=case_id).all()]
    arguments.sort(key=lambda a: (a["stage"], SIDE_ORDER.get(a["side"], 9)))
    questions = [
        {"seq": i + 1, "target_side": q.target_side, "question_text": q.question_text,
         "based_on": q.based_on, "created_at": q.created_at}
        for i, q in enumerate(session.query(CourtQuestion).filter_by(case_id=case_id)
                              .order_by(CourtQuestion.id).all())
    ]

    verdict_row = session.query(Verdict).filter_by(case_id=case_id).one_or_none()
    verdict = None
    if verdict_row is not None:
        anchor = json.loads(verdict_row.mechanical_anchor_json)
        verdict = {
            "verdict_main_text": verdict_row.verdict_main_text,
            "verdict_reasoning": verdict_row.verdict_reasoning,
            "risk_map": json.loads(verdict_row.risk_map), "mechanical_anchor": anchor,
            "protocol_version": verdict_row.protocol_version, "created_at": verdict_row.created_at,
            "anchor_check": _anchor_check(anchor, arguments),
        }

    pleading_row = (session.query(PleadingDraft).filter_by(case_id=case_id)
                    .order_by(PleadingDraft.id.desc()).first())
    pleading = None
    if pleading_row is not None:
        pleading = {
            "draft_text": pleading_row.draft_text, "generated_at": pleading_row.generated_at,
            "citation_verification_status": pleading_row.citation_verification_status,
            "draft_count": session.query(PleadingDraft).filter_by(case_id=case_id).count(),
            "citation_check": _pleading_citation_check(pleading_row.draft_text, lookup),
        }

    citations = _collect_citations(arguments, lookup, recorded_checks)
    stamps = sorted([a["created_at"] for a in arguments] + [q["created_at"] for q in questions])
    return {
        "case": {"case_id": case_row.case_id, "case_type": case_row.case_type,
                 "facts_summary": case_row.facts_summary, "claims": case_row.claims,
                 "created_at": case_row.created_at, "source": "database"},
        "provenance": {"kind": "recorded_replay" if arguments else "case_only",
                       "model_ids": sorted({a["model_id"] for a in arguments if a["model_id"]}),
                       "first_recorded_at": stamps[0] if stamps else None,
                       "last_recorded_at": stamps[-1] if stamps else None},
        "arguments": arguments, "questions": questions, "verdict": verdict, "pleading": pleading,
        "citations": citations, "citation_changes": citation_changes(arguments),
        "drift_detail": drift_detail(arguments) if any(a["stage"] == 3 for a in arguments) else None,
        "progress": _progress(case_row, arguments, questions, verdict, pleading, citations),
        "stats": {"arguments": len(arguments), "questions": len(questions), "citations": len(citations),
                  "citations_published": sum(1 for c in citations if c["db_record"]
                                             and c["db_record"]["status"] == "published")},
        "party_checks": latest_party_checks(session, case_id),
    }


# ───────────────────────── 商工登記當事人查核 ─────────────────────────

def party_check_one(session, ban, *, role=None, case_id=None, input_name=None, timeout=6.0,
                    persist=True, recorded_party_checks=None):
    started = time.perf_counter()
    calls = {}
    type_result = gcis.entity_type(ban, timeout=timeout)
    calls["entity_type"] = type_result
    if not type_result["ok"]:
        kind = "unresolved"  # 連線失敗絕不能當成「查無」
    else:
        types = {str(row.get("TYPE", "")).strip(): str(row.get("exist", "")).upper() == "Y"
                 for row in type_result["rows"]}
        kind = ("company" if types.get("公司") else "branch" if types.get("分公司")
                else "business" if types.get("商業") else "not_found")
    if kind == "company":
        calls["company"] = gcis.company_basic(ban, timeout=timeout)
        # 基本資料失敗時仍嘗試獨立資料集；成功時也保留各自的錯誤狀態。
        calls["directors"] = gcis.directors(ban, timeout=timeout)
        calls["branches"] = gcis.branches(ban, timeout=timeout)
    elif kind == "business":
        calls["business"] = gcis.business_basic(ban, timeout=timeout)
    result = party_rules.summarize(ban, kind, calls, input_name=input_name)
    api_failures = [{"dataset": gcis.DATASETS[key][1], "error": call["error"]}
                    for key, call in calls.items() if not call["ok"]]
    failures = api_failures.copy()
    missing_basic = kind in ("company", "business") and calls[kind]["ok"] and not calls[kind]["rows"]
    if missing_basic:
        failures.append({"dataset": gcis.DATASETS[kind][1],
                         "error": "類型資料顯示統編存在，但基本資料集查無此統編；無法完成欄位核對"})
    critical_failure = kind == "unresolved" or (kind in ("company", "business") and not calls[kind]["ok"])
    result["query_status"] = "failed" if critical_failure else "partial" if failures else "not_found" if kind == "not_found" else "ok"
    result["errors"] = failures
    result["live_attempt"] = {"tried": True,
                               "outcome": _classify_live_failure(api_failures[0]["error"]) if api_failures else "ok",
                               "error": api_failures[0]["error"] if api_failures else None}
    result["via"] = "gcis_live"
    result["fetched_at"] = max((call["fetched_at"] for call in calls.values() if call["fetched_at"]), default=None)
    result["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
    result["persisted"] = False
    if calls and all(not value["ok"] for value in calls.values()) and ban in (recorded_party_checks or {}):
        entry = recorded_party_checks[ban]
        original = entry["result"]
        historic_calls = {key: {**value, "dataset": key, "fetched_at": entry["fetched_at"] if value["ok"] else None}
                          for key, value in entry["raw"].items()}
        replay = party_rules.summarize(ban, original["entity_type"], historic_calls, input_name=input_name)
        replay.update(query_status="recorded", via="recorded", fetched_at=entry["fetched_at"],
                      live_attempt=result["live_attempt"], live_errors=failures,
                      elapsed_ms=result["elapsed_ms"], persisted=False)
        if persist:
            replay["persisted"] = True
            record_party_check(session, case_id=case_id, role=role, query_ban=ban, input_name=input_name,
                               result=replay, raw={"recorded": entry["raw"], "failed_live_attempt": calls},
                               via="recorded", fetched_at=entry["fetched_at"])
        return replay
    if persist:
        result["persisted"] = True
        record_party_check(session, case_id=case_id, role=role, query_ban=ban, input_name=input_name,
                           result=result, raw={key: {"rows": value["rows"], "url": value["url"],
                                                  "ok": value["ok"], "error": value["error"]}
                                               for key, value in calls.items()},
                           fetched_at=result["fetched_at"])
    return result


def party_search(keyword, *, timeout=6.0):
    fetched = gcis.search_companies(keyword, timeout=timeout)
    return {"ok": fetched["ok"], "error": fetched["error"], "fetched_at": fetched["fetched_at"],
            "source": {"dataset": gcis.DATASETS["keyword"][1], "url": fetched["url"],
                       "fetched_at": fetched["fetched_at"]},
            "attribution": f"{gcis.ATTRIBUTION} [{gcis.DATASETS['keyword'][1]}]" if fetched["ok"] else None,
            "candidates": [{"ban": str(row.get("Business_Accounting_NO", "")), "name": row.get("Company_Name"),
                            "status_text": row.get("Company_Status_Desc"),
                            "address": row.get("Company_Location"), "responsible_name": row.get("Responsible_Name")}
                           for row in fetched["rows"]]}


# ───────────────────────── finalize ─────────────────────────

def run_finalize(session, case_id):
    """真實執行機械死穴彙整(engine.aggregate)，不寫入 DB。缺 Stage 3 時 raise ValueError。"""
    started = time.perf_counter()
    result = finalize_case(session, case_id=case_id)
    arguments = [_arg_to_api(r) for r in session.query(DebateArgument).filter_by(case_id=case_id).all()]
    result["drift_detail"] = drift_detail(arguments)
    result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return result


# ───────────────────────── verify(本地優先 + 即時查詢逾時退回) ─────────────────────────

@functools.lru_cache(maxsize=None)
def _load_statute_cache(law_file):
    path = os.path.join(STATUTES_DIR, law_file)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        content = f.read()
    articles = {}
    for m in re.finditer(r"^### 第 (\d+(?:-\d+)?) 條\n(.*?)(?=^### |^## |\Z)", content, re.S | re.M):
        articles[m.group(1)] = m.group(2).strip()
    meta = {}
    meta_path = os.path.join(STATUTES_DIR, law_file.replace(".txt", "_source.json"))
    if os.path.isfile(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    return {"articles": articles, "meta": meta}


def _local_statute(law_name, article_no):
    law_file = _STATUTE_FILES.get(law_name)
    cache = _load_statute_cache(law_file) if law_file else None
    if not cache or article_no not in cache["articles"]:
        return None
    return {"text": cache["articles"][article_no], "law_file": law_file, "meta": cache["meta"]}


def _local_judgment(jyear, jcase, jno):
    prefix = f"TPSV,{jyear},{jcase},{jno},"
    if not os.path.isdir(JUDGMENTS_DIR):
        return None
    for name in os.listdir(JUDGMENTS_DIR):
        if name.startswith(prefix) and name.endswith(".txt"):
            return os.path.join(JUDGMENTS_DIR, name)
    return None


def _classify_live_failure(reason):
    return "timeout" if "timed out" in (reason or "").lower() or "逾時" in (reason or "") else "network_error"


def _live_query(fn, *args, timeout):
    """呼叫引擎的即時查證；引擎回傳 verification_failed 或丟出任何例外，一律轉成明確的失敗描述。"""
    try:
        r = fn(*args, timeout=timeout)
    except Exception as e:  # noqa: BLE001 - 任何連線層例外都不得讓 demo 中斷，且必須如實回報
        return None, {"tried": True, "outcome": _classify_live_failure(str(e)), "error": f"{type(e).__name__}: {e}"}
    if r.get("status") == "verification_failed":
        return None, {"tried": True, "outcome": _classify_live_failure(r.get("reason")), "error": r.get("reason")}
    return r, {"tried": True, "outcome": "ok", "error": None}


def verify_one(session, citation_text, *, mode="auto", timeout=6.0, persist=True,
               skip_live=False, recorded_checks=None):
    """單條引用查證。

    mode='auto'：本地判決語料庫優先；未命中或屬法條則即時查官方來源(逾 timeout 秒視為失敗)。
    mode='offline'：完全不連網，只比對本地快取(結果不會是 published[法條]，也不會寫入 DB)。
    skip_live：呼叫端(批次查證)已確認網路不通時，略過即時查詢、直接退回本地。
    回傳的 status/verified_via/live_attempt 皆為本次實際發生的事，不含任何預設或假設通過。
    """
    started = time.perf_counter()
    text = citation_text.strip()
    parsed = parse_citation(text)
    key = _citation_key(text)
    live_allowed = mode == "auto" and not skip_live
    skipped_outcome = "skipped_offline_mode" if mode == "offline" else "skipped_after_failure"

    prior = _db_record(_find_citation_row(session, text), text)
    out = {
        "citation_text": text, "source_type": parsed["type"] if parsed["type"] != "unknown" else None,
        "status": None, "verified_via": None, "primary_source_url": None, "note": None,
        "live_attempt": {"tried": False, "outcome": "not_attempted", "error": None},
        "previous_record": prior, "recorded_check": (recorded_checks or {}).get(key),
        "persisted": False, "mode": mode,
    }

    if parsed["type"] == "unknown":
        out["status"] = "unparseable"
        out["note"] = "無法解析為「法規第N條」或「最高法院N年度台X字第N號」格式"

    elif parsed["type"] == "statute":
        law, art = parsed["law_name"], parsed["article_no"]
        if law not in STATUTE_PCODES:
            out["status"] = "unknown_law"
            out["note"] = f"「{law}」不在查證引擎範圍"
        else:
            live = None
            if live_allowed:
                live, out["live_attempt"] = _live_query(engine_verify.verify_statute_citation, law, art, timeout=timeout)
            else:
                out["live_attempt"]["outcome"] = skipped_outcome
            if live is not None:
                out["status"] = live["status"]
                out["verified_via"] = "law_moj_live"
                out["primary_source_url"] = _safe_url(live.get("primary_source_url"))
                out["note"] = live.get("note")
                if live.get("matched_text"):
                    out["matched_excerpt"] = live["matched_text"][:300]
            else:
                local = _local_statute(law, art)
                if local is not None:
                    out["status"] = "local_cache_only"
                    out["verified_via"] = "local_statute_cache"
                    out["matched_excerpt"] = local["text"][:300]
                    meta = local["meta"]
                    out["local_cache"] = {"file": f"corpus/statutes/{local['law_file']}",
                                          "fetched_at": meta.get("fetched_at_utc"),
                                          "amendment_date": meta.get("amendment_date_roc")}
                    out["note"] = "官網即時查詢未完成；僅在本地法典快取找到此條文，未與官方原文比對，不放行"
                else:
                    out["status"] = "verification_failed"
                    out["note"] = ("官網即時查詢未完成，且本地無此法規快取，無法判定" if law not in _STATUTE_FILES
                                   else "官網即時查詢未完成，本地快取亦無此條號，無法判定")

    else:  # judgment
        jy, jc, jn = parsed["jyear"], parsed["jcase"], parsed["jno"]
        local_path = _local_judgment(jy, jc, jn)
        if local_path is not None:
            out["status"] = "published"
            out["verified_via"] = "local_corpus"
            out["local_file"] = _rel_corpus_path(local_path)
            out["note"] = "本地判決語料庫命中(司法院裁判書開放資料)，未連網"
        else:
            live = None
            if live_allowed:
                live, out["live_attempt"] = _live_query(engine_verify.verify_judgment_citation, jy, jc, jn, timeout=timeout)
            else:
                out["live_attempt"]["outcome"] = skipped_outcome
            if live is not None:
                out["status"] = live["status"]
                out["verified_via"] = "fjud_live"
                out["primary_source_url"] = _safe_url(live.get("primary_source_url"))
                out["note"] = live.get("note")
                if live["status"] == "not_found":
                    out["fjud_query"] = live.get("fjud_query")
                    out["fjud_hit_count"] = len(live.get("fjud_raw_hits", []))
            else:
                out["status"] = "verification_failed"
                out["note"] = "本地判決語料庫查無此字號；官方(司法院 FJUD)即時查詢未完成，無法確認是否存在，依零容忍原則不放行"

    out["gate"] = "pass" if out["status"] == "published" else "blocked"
    if persist and out["status"] == "published" and out["source_type"]:
        upsert_citation(session, citation_text=text, source_type=out["source_type"], status="published",
                        primary_source_url=out["primary_source_url"])
        out["persisted"] = True
    out["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
    return out
