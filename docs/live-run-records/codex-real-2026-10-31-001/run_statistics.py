"""Summarize recorded process timings and reported usage; no legal assessment."""
from pathlib import Path
import datetime as dt
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[3]


def timestamp(value):
    return dt.datetime.fromisoformat(value) if value else None


def summarize(case_id):
    out = ROOT / "docs/live-run-records" / ("codex-" + case_id)
    rows, intervals, reported_usage, parse_errors = [], [], {}, []
    captured_at = dt.datetime.now(dt.timezone.utc)
    for path in sorted((out / "calls").glob("*/call_manifest.json")):
        meta = json.loads(path.read_text(encoding="utf-8"))
        start, end = timestamp(meta.get("started_at")), timestamp(meta.get("ended_at"))
        usage_events = []
        stream = path.parent / "stream.jsonl"
        if stream.exists():
            for n, line in enumerate(stream.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as error:
                    parse_errors.append({"call": meta["name"], "line": n, "error": str(error)})
                    continue
                if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
                    usage_events.append(event["usage"])
                    for key, value in event["usage"].items():
                        if isinstance(value, (int, float)):
                            reported_usage[key] = reported_usage.get(key, 0) + value
        if start:
            intervals.append((start, end or captured_at))
        rows.append({"call": meta["name"], "status": meta["status"],
                     "classification": meta.get("classification"), "exit_code": meta.get("exit_code"),
                     "started_at": meta.get("started_at"), "ended_at": meta.get("ended_at"),
                     "duration_seconds": round(((end or captured_at) - start).total_seconds(), 3) if start else None,
                     "last_message_exists": (path.parent / "last_message.txt").exists(),
                     "usage_events": usage_events})
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    state = json.loads((out / "run_manifest.json").read_text(encoding="utf-8"))
    result = {"case_id": case_id, "captured_at": captured_at.isoformat(),
              "calls": rows, "attempted_calls": sum(bool(r["started_at"]) for r in rows),
              "running_calls": [r["call"] for r in rows if r["status"] == "running"],
              "unadopted_environment_failures": [r["call"] for r in rows if r["classification"] == "environment_failure_not_adopted"],
              "wall_span_seconds": round((max(e for _, e in intervals) - min(s for s, _ in intervals)).total_seconds(), 3) if intervals else None,
              "any_actor_active_seconds": round(sum((e - s).total_seconds() for s, e in merged), 3),
              "sum_call_seconds": round(sum(r["duration_seconds"] or 0 for r in rows), 3),
              "reported_usage_sum": reported_usage,
              "calls_with_usage": sum(bool(r["usage_events"]) for r in rows),
              "usage_limitations": "Reported event usage only; aborted calls without usage are omitted. Cached input tokens are a subset, not extra input. No actual monetary charge is available.",
              "controller_command_count": len(state.get("commands", [])),
              "controller_command_errors": [r for r in state.get("commands", []) if r.get("exit_code") != 0],
              "parse_errors": parse_errors}
    target = out / "run_statistics.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"case_id": case_id, "attempted_calls": result["attempted_calls"], "running_calls": result["running_calls"], "saved": str(target)}, ensure_ascii=False))


if __name__ == "__main__":
    for case in sys.argv[1:] or ["real-2026-10-31-001", "real-2026-10-31-002"]:
        summarize(case)
