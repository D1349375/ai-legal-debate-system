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

from database.db import (
    _citation_key, _find_citation_row, _now_iso, finalize_case, upsert_citation, record_case, record_party_check,
    record_pleading_edit, latest_party_checks,
)
from sqlalchemy import func

from database.schema import (
    Case, CitationVerification, CourtQuestion, DebateArgument, LiveRun, PartyCheck, PleadingDraft, Verdict,
)
from engine import verify as engine_verify
from engine import gcis, party_rules
from engine.aggregate import VALID_SIDES, disagreement
from engine.party_issues import cured_in, procedural_issues
from server.live_run import run_to_dict
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
}  # 民事訴訟法、企業併購法無本地快取，只能走官網即時查證


def _rel_corpus_path(path):
    """對外只給相對路徑，不洩漏本機絕對路徑。"""
    name = os.path.basename(path)
    folder = os.path.basename(os.path.dirname(os.path.abspath(path)))
    return f"corpus/{folder}/{name}"


def _safe_url(url):
    return url if url and url.startswith(_ALLOWED_SOURCE_HOSTS) else None


def _json_list(raw):
    return json.loads(raw) if raw else []


# ───────────────────────── 建立案件(UI) ─────────────────────────

CASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


def _next_case_id(session):
    """ui-YYYYMMDD-NNN:只含英數與連字號，可安全放進檔名與 Claude Code 指令。"""
    prefix = "ui-" + _now_iso()[:10].replace("-", "") + "-"
    taken = {cid for cid, in session.query(Case.case_id).filter(Case.case_id.like(prefix + "%")).all()}
    n = 1
    while f"{prefix}{n:03d}" in taken:
        n += 1
    return f"{prefix}{n:03d}"


def create_case(session, *, case_type, facts_summary, claims, parties, case_id=None, cases_dir=None):
    """UI 建立案件:只落地使用者輸入的文字，不補寫任何案情。統編查核由呼叫端另以 party_check_one 進行。"""
    case_id = case_id or _next_case_id(session)
    if not CASE_ID_RE.match(case_id):
        raise ValueError("案件 ID 只能使用英數字、點、底線、連字號(3–64 字，首字為英數字)")
    if case_id in _load_input_cases(cases_dir):
        raise ValueError(f"{case_id} 已是 data/cases 中的案件輸入，請換一個 ID")
    row = record_case(session, case_id=case_id, case_type=case_type.strip(), facts_summary=facts_summary.strip(),
                      claims=claims.strip(), parties=parties, created_via="ui")
    return row.case_id


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
    run_status = {}
    for cid, status in session.query(LiveRun.case_id, LiveRun.status).order_by(LiveRun.id).all():
        run_status[cid] = status
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
            "created_via": row.created_via, "last_run_status": run_status.get(row.case_id),
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


def _provenance_kind(arguments):
    if not arguments:
        return "case_only"
    live = sum(1 for a in arguments if a["origin"]["kind"] == "live")
    return "live_generated" if live == len(arguments) else "mixed" if live else "recorded_replay"


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


# ───────────────────────── 訴狀版本(系統產生版 / 律師編輯版) ─────────────────────────

# 嚴格規則(STATUTE_CITATION_RE / JUDGMENT_CITATION_RE)只認得查證引擎範圍內的寫法。律師自由編輯時可能寫其他法規、
# 中文數字或下級審字號——這些「看起來像引用、但系統認不得」的文字不能因為認不得就默默放行，一律列為無法查證。
_LOOSE_STATUTE_RE = re.compile(r"[一-鿿]{1,15}法第\s*[0-9０-９一二三四五六七八九十百千零〇]+\s*條"
                               r"(?:\s*之\s*[0-9０-９一二三四五六七八九十]+)?")
_LOOSE_JUDGMENT_RE = re.compile(r"[0-9０-９一二三四五六七八九十百]+\s*年度?\s*[一-鿿]{1,4}\s*字\s*第\s*"
                                r"[0-9０-９一二三四五六七八九十百千]+\s*號")
_CUT_CHARS = "依按據及與並且另又同如即參照見項款目之第、，,"  # 法規名之前常見的連接字，截在最後一個之後
UNRECOGNIZED_NOTE = ("系統無法辨識此引用寫法，無法查證；請改寫為「法規名第N條」或「最高法院N年度台X字第N號」"
                     "(查證範圍限民法、民事訴訟法等 8 部法規與最高法院裁判)")


def extract_citations(text):
    """依出現順序列出草稿中的引用(同一法條/判決只列一次)。recognized=False 表示看起來像引用但查證引擎認不得。"""
    found, spans = [], []
    for rx in (STATUTE_CITATION_RE, JUDGMENT_CITATION_RE):
        for m in rx.finditer(text):
            found.append((m.start(), m.group(0).strip(), True))
            spans.append(m.span())
    for rx in (_LOOSE_STATUTE_RE, _LOOSE_JUDGMENT_RE):
        for m in rx.finditer(text):
            if any(m.start() < e and s < m.end() for s, e in spans):
                continue
            t = m.group(0)
            head = t.split("法第", 1)[0] if "法第" in t else ""
            cut = max((head.rfind(ch) for ch in _CUT_CHARS), default=-1)
            if 0 <= cut < len(head) - 1:
                t = t[cut + 1:]
            found.append((m.start(), t, False))
            spans.append(m.span())
    out, seen = [], set()
    for _, t, ok in sorted(found):
        key = _citation_key(t) if ok else ("unrecognized", t)
        if key not in seen:
            seen.add(key)
            out.append({"citation_text": t, "recognized": ok, "key": key})
    return out


def _is_system(row):
    return row.source in (None, "system")


def _db_check(citations, lookup):
    """依資料庫現有查證紀錄判定每條引用是否放行(系統產生版用；不連網)。"""
    out = []
    for c in citations:
        rec = _db_record(lookup.get(c["key"]), c["citation_text"]) if c["recognized"] else None
        status = rec["status"] if rec else ("unparseable" if not c["recognized"] else "no_record")
        out.append({"citation_text": c["citation_text"], "recognized": c["recognized"], "status": status,
                    "gate": "pass" if status == "published" else "blocked", "db_record": rec,
                    "note": None if c["recognized"] else UNRECOGNIZED_NOTE})
    return out


def pleading_version(row, lookup, origin):
    if _is_system(row):
        check = _db_check(extract_citations(row.draft_text), lookup)
        blocked = [c for c in check if c["gate"] != "pass"]
        status = "published" if not blocked else "blocked"
        version_origin = origin(row.generated_at)
    else:
        check = json.loads(row.citation_check_json or "[]")
        blocked = [c for c in check if c["gate"] != "pass"]
        status = row.citation_verification_status
        version_origin = {"kind": "lawyer_edit"}
    return {"id": row.id, "source": "system" if _is_system(row) else "lawyer_edit", "parent_id": row.parent_id,
            "label": ("系統產生版" if _is_system(row) else "律師編輯版") + f" #{row.id}",
            "generated_at": row.generated_at, "draft_text": row.draft_text, "origin": version_origin,
            "status": status, "citation_check": check, "blocked_count": len(blocked),
            "exportable": status == "published" and not blocked}


def _verify_entries(session, citations, *, parent_keys, mode, timeout, recorded_checks, lookup):
    entries, skip_live = [], False
    for c in citations:
        change = "unchanged" if c["key"] in parent_keys else "added"
        rec = _db_record(lookup.get(c["key"]), c["citation_text"]) if c["recognized"] else None
        if change == "unchanged" and rec and rec["status"] == "published":
            entries.append({"citation_text": c["citation_text"], "recognized": True, "change": change,
                            "status": "published", "gate": "pass", "verified_now": False,
                            "verified_via": "previous_record", "db_record": rec,
                            "note": f"沿用原稿引用，查證紀錄已通過({rec['verified_at']})"})
            continue
        r = verify_one(session, c["citation_text"], mode=mode, timeout=timeout, persist=True,
                       skip_live=skip_live, recorded_checks=recorded_checks)
        if r["live_attempt"]["outcome"] in ("timeout", "network_error"):
            skip_live = True  # 同 UI 批次查證：網路不通後其餘改走本地，不逐條等逾時
        entries.append({"citation_text": c["citation_text"], "recognized": c["recognized"], "change": change,
                        "status": r["status"], "gate": r["gate"], "verified_now": True,
                        "verified_via": r["verified_via"], "primary_source_url": r["primary_source_url"],
                        "live_attempt": r["live_attempt"],
                        "note": r["note"] if c["recognized"] else UNRECOGNIZED_NOTE})
    return entries


def save_pleading_edit(session, case_id, parent_id, draft_text, *, mode="auto", timeout=6.0, recorded_checks=None):
    """律師編輯版另存新版本。新增或改動的引用(及原本就未通過者)當場重新查證；未通過者照實標示，該版本不得匯出。"""
    parent = session.get(PleadingDraft, parent_id)
    if parent is None or parent.case_id != case_id:
        raise ValueError(f"{case_id} 找不到要編輯的訴狀版本 #{parent_id}")
    parent_citations = extract_citations(parent.draft_text)
    citations = extract_citations(draft_text)
    entries = _verify_entries(session, citations, parent_keys={c["key"] for c in parent_citations}, mode=mode,
                              timeout=timeout, recorded_checks=recorded_checks, lookup=_citation_lookup(session))
    new_keys = {c["key"] for c in citations}
    row = record_pleading_edit(session, case_id=case_id, parent_id=parent_id, draft_text=draft_text,
                               citation_check=entries)
    version = pleading_version(row, _citation_lookup(session), None)
    version["removed_citations"] = [c["citation_text"] for c in parent_citations if c["key"] not in new_keys]
    return version


def reverify_pleading(session, case_id, version_id, *, mode="auto", timeout=6.0, recorded_checks=None):
    """對某版本中尚未放行的引用重新查證(例如上次網路不通)。內文不變；律師版更新它存下的查證結果，
    系統版的結果寫入 citation_verifications(同 CLI verify),原稿列本身不改寫。"""
    row = session.get(PleadingDraft, version_id)
    if row is None or row.case_id != case_id:
        return None
    lookup = _citation_lookup(session)
    citations = extract_citations(row.draft_text)
    if _is_system(row):
        pending = [c for c, chk in zip(citations, _db_check(citations, lookup)) if chk["gate"] != "pass"]
        _verify_entries(session, pending, parent_keys=set(), mode=mode, timeout=timeout,
                        recorded_checks=recorded_checks, lookup=lookup)
    else:
        old = {e["citation_text"]: e for e in json.loads(row.citation_check_json or "[]")}
        keep = [old[c["citation_text"]] for c in citations if old.get(c["citation_text"], {}).get("gate") == "pass"]
        redo = [c for c in citations if old.get(c["citation_text"], {}).get("gate") != "pass"]
        fresh = _verify_entries(session, redo, parent_keys=set(), mode=mode, timeout=timeout,
                                recorded_checks=recorded_checks, lookup=lookup)
        for e in fresh:
            e["change"] = old.get(e["citation_text"], {}).get("change", e["change"])
        order = {c["citation_text"]: i for i, c in enumerate(citations)}
        entries = sorted(keep + fresh, key=lambda e: order[e["citation_text"]])
        row.citation_check_json = json.dumps(entries, ensure_ascii=False)
        row.citation_verification_status = "published" if all(e["gate"] == "pass" for e in entries) else "blocked"
        session.commit()
    return find_pleading_version(session, case_id, version_id)


def find_pleading_version(session, case_id, version_id):
    row = session.get(PleadingDraft, version_id)
    if row is None or row.case_id != case_id:
        return None
    return pleading_version(row, _citation_lookup(session), _origin_resolver(_runs_for(session, case_id)))


def export_pleading_text(case_id, version):
    """匯出純文字。端點只對全部引用放行的版本呼叫；檔尾附版本、來源與查證資訊，與正文分開。"""
    o = version["origin"]
    source = ("律師在 UI 編輯後另存" + (f"(基於 #{version['parent_id']})" if version["parent_id"] else "")
              if o["kind"] == "lawyer_edit" else
              f"本次即時生成(UI 執行 #{o['run_id']},本機 Claude Code)" if o["kind"] == "live" else
              "錄製紀錄(過去由 Claude Code subagent 產生後落地)")
    lines = [version["draft_text"].rstrip(), "", "─" * 24, "匯出資訊(非訴狀正文)",
             f"案件:{case_id}", f"版本:{version['label']}", f"來源:{source}",
             f"產生／存檔時間:{version['generated_at']}", f"匯出時間:{_now_iso()}",
             f"引用查證:{len(version['citation_check'])} 條，全部已查證通過"]
    lines += [f"  - {c['citation_text']}:已查證通過" for c in version["citation_check"]]
    lines += ["聲明：本稿為爭點分析後的訴狀骨架或其編輯稿，非法律意見，須經執業律師審核後方可使用。",
              "查證僅確認條文／裁判字號存在，未比對判決全文是否支持該論點。"]
    return "\n".join(lines) + "\n"


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


def procedural_view(session, case_id, party_checks, arguments, questions, last_recorded_at, verdict):
    """起訴審查的程序事項 + 「錄製的攻防／評估是否真的處理過這些事項」的機械比對。

    只看標記，不做語意判斷：原告 Stage 1 有沒有「程序補正(<id>)」段落(cured_in)、法官追問的
    based_on 有沒有寫入該 id。沒有就如實標為未回應，並區分「攻防錄製時根本還沒查核」與「查核後仍未回應」。
    補正是否「足夠」屬法官判斷，這裡不評。
    """
    view = procedural_issues(party_checks)
    plaintiff_s1 = next((a for a in arguments if a["side"] == "plaintiff" and a["stage"] == 1), None)
    s1_text = f"{plaintiff_s1['position']}\n{plaintiff_s1['reasoning']}" if plaintiff_s1 else ""
    for issue in view["issues"]:
        issue["cured_in_stage1"] = cured_in(s1_text, issue["id"])
        issue["followed_up_in"] = [q["seq"] for q in questions if issue["id"] in (q["based_on"] or "")]
    required = [i for i in view["issues"] if i["ex_officio"]]
    first_checked = (session.query(func.min(PartyCheck.created_at))
                     .filter(PartyCheck.case_id == case_id).scalar())
    if not required:
        debate = "no_issues"
    elif all(i["cured_in_stage1"] for i in required):
        debate = "answered"
    elif any(i["cured_in_stage1"] for i in required):
        debate = "partial"
    elif plaintiff_s1 is None:
        debate = "no_debate"
    elif first_checked and last_recorded_at and first_checked > last_recorded_at:
        debate = "predates_check"
    else:
        debate = "not_answered"
    view["coverage"] = {
        "debate": debate, "first_checked_at": first_checked, "debate_last_recorded_at": last_recorded_at,
        "verdict": None if verdict is None else
        ("included" if "procedural_issues" in (verdict["mechanical_anchor"] or {}) else "not_included"),
    }
    return view


def _origin_resolver(runs):
    """依 UI 即時執行的起訖時間判斷一筆落地紀錄的來源。落在某次執行期間 = 該次即時生成；
    其餘一律視為錄製紀錄(過去在 Claude Code 對話中產生後經 CLI 落地)。"""
    def origin(created_at):
        for r in runs:
            if created_at and created_at >= r["started_at"] and (r["ended_at"] is None or created_at <= r["ended_at"]):
                return {"kind": "live", "run_id": r["id"], "run_status": r["status"]}
        return {"kind": "recorded"}
    return origin


def _runs_for(session, case_id):
    return [run_to_dict(r) for r in session.query(LiveRun).filter_by(case_id=case_id).order_by(LiveRun.id).all()]


def get_case_detail(session, case_id, cases_dir=None, recorded_checks=None):
    recorded_checks = recorded_checks or {}
    case_row = session.query(Case).filter_by(case_id=case_id).one_or_none()
    if case_row is None:
        payload = _load_input_cases(cases_dir).get(case_id)
        if payload is None:
            return None
        party_checks = latest_party_checks(session, case_id)
        return {
            "case": {"case_id": case_id, "case_type": payload.get("case_type", ""),
                     "facts_summary": payload.get("facts_summary", ""), "claims": payload.get("claims", ""),
                     "created_at": None, "source": "input_only"},
            "provenance": {"kind": "input_only", "model_ids": [], "first_recorded_at": None, "last_recorded_at": None},
            "arguments": [], "questions": [], "verdict": None, "pleading": None, "pleading_versions": [], "citations": [],
            "citation_changes": [], "drift_detail": None,
            "progress": _progress(None, [], [], None, None, []),
            "stats": {"arguments": 0, "questions": 0, "citations": 0, "citations_published": 0},
            "party_checks": party_checks, "live_runs": [],
            "procedural_issues": procedural_view(session, case_id, party_checks, [], [], None, None),
        }

    lookup = _citation_lookup(session)
    runs = _runs_for(session, case_id)
    origin = _origin_resolver(runs)
    arguments = [{**_arg_to_api(r), "origin": origin(r.created_at)}
                 for r in session.query(DebateArgument).filter_by(case_id=case_id).all()]
    arguments.sort(key=lambda a: (a["stage"], SIDE_ORDER.get(a["side"], 9)))
    questions = [
        {"seq": i + 1, "target_side": q.target_side, "question_text": q.question_text,
         "based_on": q.based_on, "created_at": q.created_at, "origin": origin(q.created_at)}
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
            "origin": origin(verdict_row.created_at),
            "anchor_check": _anchor_check(anchor, arguments),
        }

    pleading_rows = session.query(PleadingDraft).filter_by(case_id=case_id).order_by(PleadingDraft.id).all()
    system_rows = [r for r in pleading_rows if _is_system(r)]
    pleading = None
    if system_rows:
        pleading_row = system_rows[-1]
        pleading = {
            "id": pleading_row.id,
            "draft_text": pleading_row.draft_text, "generated_at": pleading_row.generated_at,
            "origin": origin(pleading_row.generated_at),
            "citation_verification_status": pleading_row.citation_verification_status,
            "draft_count": len(system_rows),
            "citation_check": _pleading_citation_check(pleading_row.draft_text, lookup),
        }
    pleading_versions = [pleading_version(r, lookup, origin) for r in pleading_rows]

    citations = _collect_citations(arguments, lookup, recorded_checks)
    stamps = sorted([a["created_at"] for a in arguments] + [q["created_at"] for q in questions])
    party_checks = latest_party_checks(session, case_id)
    return {
        "case": {"case_id": case_row.case_id, "case_type": case_row.case_type,
                 "facts_summary": case_row.facts_summary, "claims": case_row.claims,
                 "created_at": case_row.created_at, "source": "database",
                 "created_via": case_row.created_via,
                 "parties": json.loads(case_row.parties_json) if case_row.parties_json else None},
        "provenance": {"kind": _provenance_kind(arguments),
                       "model_ids": sorted({a["model_id"] for a in arguments if a["model_id"]}),
                       "first_recorded_at": stamps[0] if stamps else None,
                       "last_recorded_at": stamps[-1] if stamps else None},
        "arguments": arguments, "questions": questions, "verdict": verdict, "pleading": pleading,
        "pleading_versions": pleading_versions,
        "citations": citations, "citation_changes": citation_changes(arguments),
        "drift_detail": drift_detail(arguments) if any(a["stage"] == 3 for a in arguments) else None,
        "progress": _progress(case_row, arguments, questions, verdict, pleading, citations),
        "stats": {"arguments": len(arguments), "questions": len(questions), "citations": len(citations),
                  "citations_published": sum(1 for c in citations if c["db_record"]
                                             and c["db_record"]["status"] == "published")},
        "party_checks": party_checks,
        "live_runs": runs,
        "procedural_issues": procedural_view(session, case_id, party_checks, arguments, questions,
                                             stamps[-1] if stamps else None, verdict),
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


def party_search(keyword, *, timeout=6.0, scope="active"):
    """scope=active:核准設立(一次查詢);scope=inactive:其他 32 種狀態(逐一查詢，較慢，可能部分失敗)。"""
    fetched = (gcis.search_companies_inactive(keyword, timeout=timeout) if scope == "inactive"
               else gcis.search_companies(keyword, timeout=timeout))
    candidates = [{"ban": str(row.get("Business_Accounting_NO", "")), "name": row.get("Company_Name"),
                   "status_text": row.get("Company_Status_Desc"),
                   # 只有「核准設立」(外國公司「核准登記」)算正常；狀態缺漏也不當正常
                   "status_normal": row.get("Company_Status_Desc") in (party_rules.NORMAL, party_rules.FOREIGN_NORMAL),
                   "address": row.get("Company_Location"), "responsible_name": row.get("Responsible_Name")}
                  for row in fetched["rows"]]
    return {"ok": fetched["ok"], "error": fetched["error"], "scope": scope,
            "failed_statuses": fetched.get("failed_statuses", []), "fetched_at": fetched["fetched_at"],
            "source": {"dataset": gcis.DATASETS["keyword"][1], "url": fetched["url"],
                       "fetched_at": fetched["fetched_at"]},
            "attribution": f"{gcis.ATTRIBUTION} [{gcis.DATASETS['keyword'][1]}]" if fetched["ok"] else None,
            "candidates": candidates}


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
