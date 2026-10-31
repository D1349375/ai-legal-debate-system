"""Offline delivery checks; no model, network, product or database mutations."""
from pathlib import Path
import datetime as dt
import hashlib
import json
import re
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "docs/live-run-records"
PREFIX = "【環境說明】本 prompt 提到的 Read、Grep、Glob 工具,在你的環境中分別對應讀取檔案、rg 搜尋、列出檔案;語意與規則不變。"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def field(payload, pointer):
    if isinstance(payload, dict) and pointer in payload:
        return payload[pointer]
    parts = pointer[1:].split("/") if pointer.startswith("/") else pointer.split(".")
    for part in parts:
        part = part.replace("~1", "/").replace("~0", "~")
        payload = payload[int(part)] if isinstance(payload, list) else payload[part]
    return payload


def main():
    result = {"validated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "cases": [], "reports_sha256": {}, "local_links_checked": 0,
              "broken_links": [], "scope": "Integrity and literal quotes; labels require human review."}
    for suffix in ("001", "002"):
        run = BASE / ("codex-real-2026-10-31-" + suffix)
        annotations = read(run / "eval_annotations.json")
        if isinstance(annotations, dict):
            annotations = annotations["annotations"]
        checks = []
        for annotation in annotations:
            source = run / annotation.get("source_file", "pleading_draft_plaintiff.txt")
            assert source.resolve().is_relative_to(run.resolve())
            payload = read(source) if source.suffix == ".json" else {"text": source.read_text(encoding="utf-8-sig")}
            text = field(payload, annotation["field"])
            quote = annotation["quote"]
            assert isinstance(text, str) and quote in text and 20 <= len(quote) <= 120, annotation["id"]
            checks.append({"id": annotation["id"], "source": source.relative_to(run).as_posix(),
                           "field": annotation["field"], "length": len(quote), "offset": text.index(quote),
                           "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "valid": True})
        calls = [read(p) for p in sorted((run / "calls").glob("*/call_manifest.json"))]
        for call in calls:
            assert call["status"] != "running" and call.get("ended_at"), call["name"]
            prompt = (run / "calls" / call["name"] / "prompt.txt").read_bytes()
            assert prompt.decode("utf-8").startswith(PREFIX + "\n")
            assert hashlib.sha256(prompt).hexdigest() == call["prompt_sha256"]
        machine = read(run / "machine_checks.json")
        result["cases"].append({"case": suffix, "calls": len(calls), "all_role_processes_ended": True,
            "annotations": len(checks), "inference_annotations": sum(a["is_inference"] for a in annotations),
            "problem_chains": len({a["chain"] for a in annotations}), "source_file_quote_checks": checks,
            "legacy_checker_unrecognized_sources": [x["id"] for x in machine["annotations"]["items"] if not x["valid"]],
            "jsonl_parse_errors": machine["parse_errors"], "source_note_hits": len(machine["sensitive_strings"]["hits"])})
    reports = [BASE / "codex-real-cases-summary.md"] + [BASE / ("codex-real-2026-10-31-" + s) / "eval.md" for s in ("001", "002")]
    for report in reports:
        result["reports_sha256"][report.relative_to(ROOT).as_posix()] = hashlib.sha256(report.read_bytes()).hexdigest()
        text = report.read_text(encoding="utf-8")
        assert "gpt-6-astra" in text[:500] and "ultra" in text[:500]
        for match in re.finditer(r"\[[^\]]*\]\((?:<([^>]+)>|([^\n)]+))\)", text):
            target = match[1] or match[2]
            if target.startswith(("https://", "http://", "#", "codex://")):
                continue
            target = re.sub(r":\d+$", "", unquote(target.split("#", 1)[0]))
            path = Path(target)
            if not path.is_absolute():
                path = report.parent / path
            result["local_links_checked"] += 1
            if not path.exists():
                result["broken_links"].append({"report": report.name, "target": target})
    target = BASE / "codex-real-2026-10-31-001/delivery_validation.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"annotations": sum(x["annotations"] for x in result["cases"]),
                      "quote_checks_valid": True, "links_checked": result["local_links_checked"],
                      "broken_links": result["broken_links"]}, ensure_ascii=False))
    assert not result["broken_links"]


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
