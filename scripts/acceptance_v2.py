"""
v2 實跑驗收：照 docs/zh/v2-acceptance-checklist.md 跑程式判斷得了的項目，其餘列為人工或未檢查。

用法:

    python scripts/acceptance_v2.py --case-id <案件 ID> --case-file data/cases/<輸入檔>.json \\
        [--db-url sqlite:///...] [--answers <答案字串清單，放在 repo 以外>] [--json]

- 讀資料庫的案件明細(和 UI 的 /api/cases/<id> 同一份)與該案每次即時執行的 stream.jsonl。
- --case-file 取 demo_audit 的 forbid、exclude(資料庫不存這兩項)。
- --answers 是純文字檔，一行一個「只有讀過來源判決才寫得出來」的字串；沒給時 X8e 標「未檢查」。
- 結束碼:0 程式檢查的硬性項目全部通過(畫面與斷網重播仍待人工);1 有硬性項目不通過，或缺輸入沒檢查；2 讀不到案件或紀錄。

這支程式只做機械比對。自承類用語、引用是否支持論點、律師角度的評估都要人看；
稽核只看得到工具輸入，看不到模型讀到的內容。通過也只能說「沒有看到問題的跡象」。
"""
import argparse
import json
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# P0–P6 的落地步驟(server/live_run.py RUN_STEPS_V2 的 key);機械彙整、引用查證不算落地
STEPS = ("analysis", "complaint", "gate1", "defense", "answer", "issue_sheet",
         "stage2", "brief", "stage3", "closing", "verdict", "revision")
# X8b、X8c:被告、法官不該碰的檔(和 2026-11-03 #1–#5 的稽核同一份)
DEFENDANT_FORBID = ("case.json", "plaintiff_view", "p1_analysis", "complaint.json")
JUDGE_FORBID = ("case.json", "plaintiff_view", "defendant_view")
# 範本禁止的自承類用語。「承認」多半出現在「並非承認」這類否認句，列進來只會是雜訊
ADMISSION_RE = re.compile(r"自承|自認|自陳")
# 第 249 條與裁判字號寫在同一個括號裡(沿用 X9 原意)
PAREN_RE = re.compile(r"[（(][^（()）]*[)）]")

HARD, RECORD, MANUAL = "硬性", "記錄", "人工"
PASS, FAIL, SKIP, TODO, INFO = "過", "不過", "未檢查", "待人工", "—"


def _item(results, key, level, status, detail):
    results.append({"id": key, "level": level, "status": status, "detail": detail})


def _strings(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def output_texts(d):
    """模型產出的全部文字：論證、書狀、爭點整理表、法官訊問、診斷。不含案件輸入。"""
    texts = []
    for a in d.get("arguments") or []:
        texts += _strings({k: a.get(k) for k in ("position", "reasoning", "falsifier")})
    texts += [v.get("draft_text") or "" for v in d.get("pleading_versions") or []]
    if d.get("issue_sheet"):
        texts += _strings(d["issue_sheet"].get("sheet"))
    texts += _strings([{k: q.get(k) for k in ("question_text", "based_on")} for q in d.get("questions") or []])
    if d.get("verdict"):
        texts += _strings({k: d["verdict"].get(k) for k in ("verdict_main_text", "verdict_reasoning", "risk_map")})
    return [t for t in texts if t]


def _hits(texts, needles):
    out = []
    for needle in needles:
        for t in texts:
            i = t.find(needle)
            if i >= 0:
                out.append(f"「{needle}」:…{t[max(0, i - 20):i + len(needle) + 20]}…")
                break
    return out


def _complaint_v1(d):
    gate = ((d.get("gates") or {}).get("complaint") or {}).get("version_id")
    versions = d.get("pleading_versions") or []
    chosen = next((v for v in versions if v["id"] == gate), None)
    return chosen or next((v for v in versions if v.get("pleading_type") == "complaint" and v["source"] == "system"), None)


def check_flow(d, results):
    progress = {p["key"]: p for p in d.get("progress") or []}
    missing = [k for k in STEPS if (progress.get(k) or {}).get("state") != "done"]
    runs = [r for r in d.get("live_runs") or [] if r.get("kind") != "pleadings"]
    last = runs[-1] if runs else None
    ok = not missing and last is not None and last["status"] == "succeeded"
    _item(results, "X1", HARD, PASS if ok else FAIL,
          ("全部步驟落地" if not missing else "未落地:" + "、".join(missing)) +
          (f";最後一次執行 #{last['id']} {last['status']}" if last else ";沒有即時執行紀錄"))

    systems = [v for v in d.get("pleading_versions") or [] if v["source"] in ("system", "system_revision")]
    blocked = [f"#{v['id']}({v.get('pleading_type') or '書狀'})" for v in systems if not v.get("exportable") or v.get("blocked_count")]
    _item(results, "X1b", HARD, PASS if systems and not blocked else FAIL,
          f"系統產生的書狀 {len(systems)} 份" + (",未放行:" + "、".join(blocked) if blocked else ",全部放行"))

    stops = [s.get("who") or "?" for r in runs for s in r.get("safety_stops") or []]
    worst = Counter(stops).most_common(1)
    _item(results, "X2", HARD, FAIL if worst and worst[0][1] >= 3 else PASS,
          f"安全分類器中止共 {len(stops)} 次" + (f",最多是「{worst[0][0]}」{worst[0][1]} 次" if worst else ""))

    rows, total_cost = [], 0.0
    for r in runs:
        cost = r.get("cost_usd")
        total_cost += cost or 0
        rows.append(f"#{r['id']} {r['status']} {r.get('started_at')}→{r.get('ended_at')}"
                    + (f" {cost:.2f} 美元" if cost is not None else " 花費未記錄")
                    + (f"(從{r['resume_from']}續跑)" if r.get("resume_from") else ""))
    _item(results, "X3", RECORD, INFO, f"{len(runs)} 次執行，合計 {total_cost:.2f} 美元;" + ";".join(rows))
    models = sorted({m for r in runs for m in ((r.get("tokens") or {}).get("by_model") or {})})
    _item(results, "X3b", RECORD, INFO, "實際模型:" + ("、".join(models) or "沒有回報"))


def check_pleadings(d, results):
    complaints = [v for v in d.get("pleading_versions") or []
                  if v.get("pleading_type") == "complaint" and v["source"] in ("system", "system_revision")]
    lint = [f"#{v['id']}:" + "、".join(f"{w['word']}×{w['count']}" for w in v["lint_warnings"])
            for v in complaints if v.get("lint_warnings")]
    _item(results, "X4", HARD, FAIL if lint or not complaints else PASS,
          "；".join(lint) if lint else f"起訴狀 {len(complaints)} 份沒有流程用語" if complaints else "沒有起訴狀")
    _item(results, "X4b", MANUAL, INFO, "起訴狀 v1 有沒有被告的主張：人工對照 opponent_known_responses")

    answer = (d.get("pleadings") or {}).get("defendant") or {}
    responses = (answer.get("structured") or {}).get("responses") or []
    stance = {r.get("fact_id"): r.get("stance") for r in responses}
    facts = set(answer.get("complaint_facts") or {})
    if not responses or not facts:
        _item(results, "X5", HARD, FAIL, "沒有答辯狀的逐點表態或起訴狀的〔CF〕")
    else:
        lack, extra = sorted(facts - set(stance)), sorted(set(stance) - facts)
        _item(results, "X5", HARD, PASS if not lack and not extra else FAIL,
              f"CF {len(facts)} 點、表態 {len(stance)} 點" + (f";沒表態:{'、'.join(lack)}" if lack else "")
              + (f";起訴狀沒有:{'、'.join(extra)}" if extra else ""))

    sheet = (d.get("issue_sheet") or {}).get("sheet")
    if sheet is None:
        _item(results, "X6", HARD, FAIL, "沒有爭點整理表")
    else:
        undisputed = sheet.get("undisputed") or []
        bad = [f"{u.get('id')}←{cf}({stance.get(cf) or '沒有表態'})" for u in undisputed
               for cf in (u.get("source") or []) if stance.get(cf) != "admit"]
        bad += [f"{u.get('id')} 沒有來源" for u in undisputed if not u.get("source")]
        _item(results, "X6", HARD, FAIL if bad else PASS,
              "；".join(bad) if bad else f"不爭執事項 {len(undisputed)} 項都追溯得到 admit" if undisputed
              else "不爭執事項 0 項(答辯狀沒有 admit;不算失敗，紀錄要寫)")

    texts = [(f"書狀 #{v['id']}", v.get("draft_text") or "") for v in d.get("pleading_versions") or []]
    if d.get("issue_sheet"):
        texts.append(("爭點整理表", d["issue_sheet"].get("text") or ""))
    found = []
    for where, text in texts:
        for m in ADMISSION_RE.finditer(text):
            found.append(f"{where}:…" + re.sub(r"\s+", " ", text[max(0, m.start() - 15):m.end() + 30]) + "…")
    _item(results, "X7", MANUAL, INFO, f"自承類用語 {len(found)} 處，逐一人工對照：" + (" ／ ".join(found) if found else "無"))

    warn = sum(q.get("attribution_warning_count") or 0 for q in d.get("questions") or [])
    warn += (d.get("verdict") or {}).get("attribution_warning_count") or 0
    _item(results, "X7b", RECORD, INFO, f"訊問與診斷的轉述警告 {warn} 則(爭點整理表的轉述警告看 issue-sheet --check 的輸出)")

    check_parties(d, _complaint_v1(d), results)

    from engine.diagnosis import WIN_PROBABILITY_RE
    pool = _strings({k: (d.get("verdict") or {}).get(k) for k in ("verdict_main_text", "verdict_reasoning", "risk_map")})
    pool += [v.get("draft_text") or "" for v in complaints if v["source"] == "system_revision"]
    hits = sorted({m.group(0) for t in pool for m in WIN_PROBABILITY_RE.finditer(t)})
    _item(results, "X11", HARD, FAIL if hits else PASS, "勝訴機率類字樣:" + ("、".join(hits) if hits else "無"))
    _item(results, "X12", MANUAL, INFO, "引用是否支持論點：每份書狀至少抽一則判決，對照 precedent_notes 的 quote")


def check_parties(d, complaint, results):
    if complaint is None:
        _item(results, "X9", HARD, FAIL, "沒有起訴狀 v1")
        _item(results, "X9b", HARD, FAIL, "沒有起訴狀 v1")
        return
    text = complaint.get("draft_text") or ""
    head = text.split("訴之聲明")[0]
    problems, reps = [], []
    for side, label in (("plaintiff", "原告"), ("defendant", "被告")):
        r = (d.get("party_checks") or {}).get(side)
        if not r or r.get("query_status") != "ok" or r.get("basic_data_available") is False:
            continue
        for key, name in (("name", "名稱"), ("ban", "統編")):
            if r.get(key) and r[key] not in head:
                problems.append(f"{label}{name}「{r[key]}」不在當事人欄")
        rep = (r.get("legal_representative") or {}).get("name")
        if rep:
            reps.append(rep)
            if rep not in head:
                problems.append(f"{label}法定代理人「{rep}」(商工登記)不在當事人欄")
    for line in head.splitlines():
        if "法定代理人" in line and "待" not in line and not any(rep in line for rep in reps):
            problems.append(f"法定代理人寫了登記上沒有的人：{line.strip()}")
    _item(results, "X9", HARD, FAIL if problems else PASS,
          "；".join(problems) if problems else f"起訴狀 #{complaint['id']} 當事人欄與商工登記一致，登記沒有的寫待查明")
    mixed = [m.group(0) for m in PAREN_RE.finditer(text) if "第249條" in m.group(0) and "字第" in m.group(0)]
    _item(results, "X9b", HARD, FAIL if mixed else PASS, "；".join(mixed) if mixed else "第 249 條沒有和裁判字號寫在同一個括號")


def _stream_path(run, root):
    path = run.get("log_path")
    if not path:
        return None
    return path if os.path.isabs(path) else os.path.join(root, path)


def check_isolation(d, case_file, answers, root, results):
    from scripts.audit_run import audit, load_events
    audit_conf = case_file.get("demo_audit") or {}
    forbid = list(audit_conf.get("forbid") or [])
    runs = [r for r in d.get("live_runs") or [] if r.get("kind") != "pleadings"]
    streams = [(r["id"], _stream_path(r, root)) for r in runs]
    unreadable = [f"#{rid}" for rid, p in streams if not p or not os.path.exists(p)]
    events = {rid: load_events(p) for rid, p in streams if p and os.path.exists(p)}
    if not events:
        for key in ("X8a", "X8b", "X8c"):
            _item(results, key, HARD, SKIP, "讀不到任何執行的 stream.jsonl")
    else:
        note = f"(讀不到 {'、'.join(unreadable)})" if unreadable else ""
        for key, agent, needles in (("X8a", None, forbid), ("X8b", "被告", DEFENDANT_FORBID), ("X8c", "法官", JUDGE_FORBID)):
            if not needles:
                _item(results, key, HARD, SKIP, "案件檔沒有 demo_audit.forbid")
                continue
            violations, matched = [], 0
            for rid, ev in events.items():
                report = audit(ev, forbid=needles, agent_filter=agent)
                matched += sum(1 for a in report["agents"] if agent is None or agent in a["name"])
                violations += [f"#{rid} {v['agent']} {v['tool']}:{v['input'][:80]}" for v in report["violations"]]
            if agent and not matched:
                _item(results, key, HARD, FAIL, f"沒有名稱含「{agent}」的 agent,無法確認隔離{note}")
            else:
                _item(results, key, HARD, FAIL if violations or unreadable else PASS,
                      ("；".join(violations) if violations else f"{len(events)} 次執行沒有命中") + note)
        denied = [f"#{rid} {a['name']}×{a['denied']}" for rid, ev in events.items()
                  for a in audit(ev)["agents"] if a.get("denied")]
        _item(results, "X8d", RECORD, INFO, "讀取被拒:" + ("、".join(denied) if denied else "0 次"))

    texts = output_texts(d)
    if answers is None:
        _item(results, "X8e", HARD, SKIP, "沒有給 --answers(答案字串清單)")
    else:
        hits = _hits(texts, answers)
        _item(results, "X8e", HARD, FAIL if hits else PASS,
              ("；".join(hits) + "(逐筆判斷是自己推出來的還是看過答案)") if hits else f"答案字串 {len(answers)} 個都沒出現在產出")
    sources = [s for s in dict.fromkeys(list(audit_conf.get("exclude") or []) + forbid)
               if "/" not in s and "\\" not in s and not s.endswith(".json")]
    if not sources:
        _item(results, "X8f", HARD, SKIP, "案件檔沒有來源字號")
    else:
        hits = _hits(texts, sources)
        _item(results, "X8f", HARD, FAIL if hits else PASS, "；".join(hits) if hits else f"來源字號 {len(sources)} 種寫法都沒出現在產出")


def evaluate(d, *, case_file, answers=None, root=ROOT):
    """→ {"results": [...], "passed": bool}。passed 只在所有硬性項目都是「過」時為 True。"""
    results = []
    check_flow(d, results)
    check_pleadings(d, results)
    check_isolation(d, case_file, answers, root, results)
    _item(results, "X10a", HARD, TODO, "畫面：瀏覽器逐一開 v2 的 8 個分頁，深色、淺色各一次")
    _item(results, "X10b", HARD, TODO, "斷網重播：照 v2-wiring.md 第 3 節")
    order = {k: i for i, k in enumerate(["X1", "X1b", "X2", "X3", "X3b", "X4", "X4b", "X5", "X6", "X7", "X7b",
                                        "X8a", "X8b", "X8c", "X8d", "X8e", "X8f", "X9", "X9b", "X10a", "X10b", "X11", "X12"])}
    results.sort(key=lambda r: order.get(r["id"], 99))
    hard = [r for r in results if r["level"] == HARD]
    # passed:程式檢查的硬性項目全部過、沒有因缺輸入而沒檢查。待人工的項目另列，做完才能對外說通過
    return {"results": results, "passed": all(r["status"] in (PASS, TODO) for r in hard),
            "failed": [r["id"] for r in hard if r["status"] == FAIL],
            "unchecked": [r["id"] for r in hard if r["status"] == SKIP],
            "manual_todo": [r["id"] for r in hard if r["status"] == TODO]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="v2 實跑驗收(程式判斷得了的項目)")
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--case-file", required=True, help="案件輸入檔(取 demo_audit 的 forbid、exclude)")
    parser.add_argument("--db-url", help="預設同 main.py(環境變數 LEGALDEBATE_DB_URL)")
    parser.add_argument("--answers", help="答案字串清單，一行一個；放在 repo 以外")
    parser.add_argument("--root", default=ROOT, help="執行紀錄 log_path 的相對起點(預設 repo 根目錄)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    from database.db import get_session
    from server.services import get_case_detail
    try:
        with open(args.case_file, encoding="utf-8") as f:
            case_file = json.load(f)
        answers = None
        if args.answers:
            with open(args.answers, encoding="utf-8") as f:
                answers = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        with get_session(args.db_url) as s:
            d = get_case_detail(s, args.case_id)
    except (OSError, ValueError) as e:
        print(f"讀不到輸入:{e}", file=sys.stderr)
        return 2
    if d is None or d["case"].get("source") != "database":
        print(f"資料庫沒有案件 {args.case_id}", file=sys.stderr)
        return 2
    if d["case"].get("protocol") != "v2":
        print(f"案件 {args.case_id} 不是書狀交換流程(v2)", file=sys.stderr)
        return 2

    out = evaluate(d, case_file=case_file, answers=answers, root=args.root)
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for r in out["results"]:
            print(f"[{r['status']:<3}] {r['id']:<5} {r['level']}  {r['detail']}")
        print()
        if out["passed"]:
            print("結論：程式檢查的硬性項目全部通過。還要人工完成 " + "、".join(out["manual_todo"]) +
                  ",並看完人工項目，才能寫「通過」(稽核只看工具輸入;單次結果)")
        else:
            print("結論：不通過" + (f";不過:{'、'.join(out['failed'])}" if out["failed"] else "")
                  + (f";未檢查:{'、'.join(out['unchecked'])}" if out["unchecked"] else ""))
    return 0 if out["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
