#!/usr/bin/env python3
"""Offline run bookkeeping. No models, network calls, or legal conclusions.

Run with --run-dir DIR [--needles-json FILE]. The optional needle file is a
JSON array of nonempty strings, or {"needles": [...]} (entries may instead be
{"id": "label", "text": "literal"}). Needle contents are never read implicitly.
Annotations may be an array or {"annotations": [...]}; dotted fields, numeric
array indexes and JSON pointers are supported. All findings require review.
"""

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


ADMISSION_WORDS = ("自承", "自認", "坦承", "不爭執", "已承認", "不否認", "迄未回應", "未爭執")
NUMBER = r"[0-9０-９一二三四五六七八九十百千萬億零〇壹貳參肆伍陸柒捌玖拾佰仟兩,.，．]+"
FACT_PATTERNS = {
    "date": re.compile(
        r"(?:民國|中華民國|西元)?\s*\d{2,4}年\d{1,2}月(?:\d{1,2}[日號])?"
        r"|\d{4}[-/]\d{1,2}[-/]\d{1,2}"
        r"|[一二三四五六七八九十]{1,3}月[一二三四五六七八九十]{1,3}日"
    ),
    "amount": re.compile(
        rf"(?:(?:新[臺台]幣|[臺台]幣|NT\$|NTD|TWD|US\$|USD|人民幣|美元|\$)\s*{NUMBER}(?:元|圓)?)"
        rf"|(?:{NUMBER}\s*(?:元|圓))", re.I
    ),
    "person": re.compile(
        r"(?:原告|被告|證人|法定代理人|訴訟代理人|承審法官|清算人)[：:\s]*"
        r"(?P<value>[甲乙丙丁戊己庚辛壬癸](?:○○|ＯＯ|OO)?|[A-Z](?:\s*公司)?|[\u4e00-\u9fff]{2,4})"
        r"(?=[，。；：:\s]|主張|表示|稱|於|提出|已|未|之|的|及|與|$)"
    ),
    "evidence": re.compile(
        r"(?:[A-Za-z0-9\u4e00-\u9fff（）()_-]{0,18})"
        r"(?:契約書|買賣契約|承攬契約|鑑定報告|診斷證明書|診斷證明|估價單|收據|發票|匯款紀錄|"
        r"轉帳紀錄|對話紀錄|通訊紀錄|報案紀錄|事故現場圖|照片|錄音|錄影|存證信函)"
        r"|(?:原證|被證|甲證|乙證|證物)[一二三四五六七八九十0-9０-９]+"
    ),
}
NETWORK_TOOL = re.compile(
    r"(?:^|[._:/])(?:web|browser|browse|search_query|web_search|internet|fetch|"
    r"http_request|navigate|open_url)(?:$|[._:/])|playwright|puppeteer|search_service", re.I
)
NETWORK_COMMAND = re.compile(
    r"\b(?:curl(?:\.exe)?|wget(?:\.exe)?|Invoke-WebRequest|Invoke-RestMethod|"
    r"iwr|irm|Start-BitsTransfer|ssh|scp|sftp)\b"
    r"|\bgit\s+(?:clone|fetch|pull|push|ls-remote)\b"
    r"|\b(?:requests|urllib|httpx|aiohttp|socket|http\.client)\s*[.(]"
    r"|\b(?:fetch|urlopen|urlretrieve)\s*\("
    r"|certutil[^\r\n]*-urlcache|https?://", re.I
)
OUTPUT_PATTERNS = (
    "p_s*.json", "d_s*.json", "q*.json", "verdict*.json", "stage*.json",
    "s[123]_*.json", "*_stage[123]*.json", "judge*.json",
    "pleading_draft_*.txt", "calls/*/last_message.txt",
)
REQUIRED_ANNOTATION = (
    "id", "step", "field", "quote", "pattern", "category", "evidence",
    "is_inference", "severity", "chain",
)


def strings(value, location="$"):
    """Yield JSON string leaves with their exact field paths."""
    if isinstance(value, str):
        yield location, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from strings(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from strings(child, f"{location}[{index}]")


def objects(value, location="$"):
    if isinstance(value, dict):
        yield location, value
        for key, child in value.items():
            yield from objects(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from objects(child, f"{location}[{index}]")


def source_name(path, run_dir):
    try:
        return path.relative_to(run_dir).as_posix()
    except ValueError:
        return path.name


def read_text(path, errors, label):
    try:
        raw = path.read_bytes()
    except OSError as exc:
        errors.append({"kind": "read_error", "source": label, "error": str(exc)})
        return None
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        errors.append({"kind": "utf8_decode_error", "source": label,
                       "byte_start": exc.start, "byte_end": exc.end,
                       "recovery": "UTF-8 replacement characters; findings may be incomplete"})
        return raw.decode("utf-8-sig", errors="replace")


def read_json(path, errors, label):
    text = read_text(path, errors, label)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        errors.append({"kind": "json_parse_error", "source": label,
                       "line": exc.lineno, "column": exc.colno, "error": exc.msg})
        return None


def step_name(label, payload=None):
    label = label.lower().replace("-", "_")
    short = re.search(r"(?:^|[/_])([pd])_s([123])(?:\D|$)", label)
    side = "plaintiff" if short and short[1] == "p" else "defendant" if short else None
    stage = short[2] if short else None
    if not side:
        side = next((name for name in ("plaintiff", "defendant") if name in label), None)
    if not stage:
        match = re.search(r"(?:stage|s)_?([123])(?:\D|$)", label)
        stage = match[1] if match else None
    if isinstance(payload, dict):
        side = payload.get("side", side)
        if "stage" in payload:
            stage = str(payload["stage"])
    if side in ("plaintiff", "defendant") and stage in ("1", "2", "3"):
        return f"s{stage}_{side}"
    if "verdict" in label or isinstance(payload, dict) and "verdict_main_text" in payload:
        return "verdict"
    if "pleading" in label:
        return f"pleading_{side}" if side else "pleading"
    if (re.fullmatch(r"q\d*(?:\.json)?", Path(label).name)
            or "question" in label or isinstance(payload, dict) and "questions" in payload):
        return "judge_questions"
    if "judge" in label and stage in ("1", "2"):
        return "judge_questions"
    return label.rsplit("/", 1)[-1].removesuffix(".json").removesuffix(".txt")


def load_needles(path, errors):
    if path is None:
        return None
    data = read_json(path, errors, "needles-json")
    if isinstance(data, dict):
        data = data.get("needles")
    if not isinstance(data, list):
        errors.append({"kind": "needles_format_error", "source": "needles-json",
                       "error": "Expected an array or an object with a needles array"})
        return None
    result = []
    for index, item in enumerate(data):
        text = item.get("text") if isinstance(item, dict) else item
        identity = item.get("id", str(index)) if isinstance(item, dict) else str(index)
        if not isinstance(text, str) or not text:
            errors.append({"kind": "needles_format_error", "index": index,
                           "error": "Needle must be a nonempty string"})
        else:
            result.append((identity, text))
    return result


def scan_event(event, locator, needles, network, hits):
    def decode_arguments(value):
        if isinstance(value, list):
            return [decode_arguments(child) for child in value]
        if not isinstance(value, dict):
            return value
        expanded = {}
        for key, child in value.items():
            if key in ("arguments", "input", "parameters") and isinstance(child, str):
                try:
                    parsed = json.loads(child)
                except json.JSONDecodeError:
                    pass
                else:
                    if isinstance(parsed, (dict, list)):
                        child = {"decoded_json": parsed}
            expanded[key] = decode_arguments(child)
        return expanded

    event = decode_arguments(event)
    leaves = list(strings(event))
    if needles is not None:
        for identity, needle in needles:
            locations = [field for field, text in leaves if needle in text]
            if locations:
                hits.append({**locator, "needle_id": identity, "locations": locations})
    for location, obj in objects(event):
        names = []
        for key in ("tool", "tool_name", "recipient_name", "name", "server", "type"):
            if isinstance(obj.get(key), str):
                names.append((key, obj[key]))
        for key, name in names:
            if NETWORK_TOOL.search(name):
                network.append({**locator, "location": f"{location}.{key}",
                                "call_name": name, "kind": "network_tool_candidate"})
        for key in ("command", "cmd", "script"):
            command = obj.get(key)
            if isinstance(command, list):
                command = " ".join(str(part) for part in command)
            if isinstance(command, str) and NETWORK_COMMAND.search(command):
                network.append({**locator, "location": f"{location}.{key}",
                                "call_name": obj.get("type", "shell"),
                                "kind": "shell_network_candidate", "command": command})
        for key in ("code", "javascript", "js"):
            code = obj.get(key)
            if not isinstance(code, str):
                continue
            calls = re.findall(r"\b([A-Za-z_][\w.]*)\s*\(", code)
            names = [name for name in calls if NETWORK_TOOL.search(name)
                     or name in ("cua.createBrowserTab", "cua.getBrowser")]
            if names or NETWORK_COMMAND.search(code):
                network.append({**locator, "location": f"{location}.{key}",
                                "call_name": names or obj.get("type", "code"),
                                "kind": "network_code_candidate", "code": code})


def field_value(payload, field):
    if not isinstance(field, str) or not field:
        raise KeyError("field must be a nonempty string")
    if isinstance(payload, dict) and field in payload:
        return payload[field]
    if field.startswith("/"):
        parts = [x.replace("~1", "/").replace("~0", "~") for x in field[1:].split("/")]
    else:
        field = re.sub(r"\[(\d+)\]", r".\1", field.removeprefix("$."))
        parts = field.split(".")
    value = payload
    for part in parts:
        if isinstance(value, list) and part.isdigit():
            value = value[int(part)]
        elif isinstance(value, dict):
            value = value[part]
        else:
            raise KeyError(part)
    return value


def check_annotations(path, outputs, errors):
    if not path.is_file():
        return {"status": "N/A", "reason": "eval_annotations.json absent", "items": []}
    data = read_json(path, errors, "eval_annotations.json")
    if isinstance(data, dict):
        data = data.get("annotations")
    if not isinstance(data, list):
        return {"status": "invalid", "reason": "Expected annotations array", "items": []}
    items = []
    for index, annotation in enumerate(data):
        problems = []
        matches = []
        if not isinstance(annotation, dict):
            items.append({"index": index, "valid": False, "errors": ["annotation is not an object"]})
            continue
        missing = [key for key in REQUIRED_ANNOTATION if key not in annotation]
        if missing:
            problems.append("missing fields: " + ", ".join(missing))
        quote = annotation.get("quote")
        if not isinstance(quote, str):
            problems.append("quote must be a string")
        elif not 20 <= len(quote) <= 120:
            problems.append("quote length must be 20-120 Unicode characters inclusive")
        if "is_inference" in annotation and type(annotation["is_inference"]) is not bool:
            problems.append("is_inference must be a JSON boolean")
        if annotation.get("pattern") not in ("P1", "P2", "P3", "P4", "P5", "其他"):
            problems.append("invalid pattern")
        if annotation.get("category") not in ("LLM幻覺", "流程有誤", "兩者"):
            problems.append("invalid category")
        if annotation.get("severity") not in ("高", "中", "低"):
            problems.append("invalid severity")
        target = step_name(str(annotation.get("step", "")))
        candidates = [output for output in outputs if output["step"] == target]
        if not candidates:
            problems.append("step has no corresponding available output")
        found_field = False
        for output in candidates:
            try:
                value = field_value(output["payload"], annotation.get("field"))
            except (KeyError, IndexError, TypeError):
                continue
            found_field = True
            if isinstance(value, str) and isinstance(quote, str) and quote in value:
                matches.append({"source": output["source"], "field": annotation.get("field"),
                                "offset": value.index(quote)})
        if candidates and not found_field:
            problems.append("field absent from corresponding outputs")
        elif candidates and not matches:
            problems.append("quote is not a literal substring of a corresponding string field")
        items.append({"index": index, "id": annotation.get("id"), "step": annotation.get("step"),
                      "field": annotation.get("field"), "quote_length": len(quote) if isinstance(quote, str) else None,
                      "valid": not problems, "matches": matches, "errors": problems})
    return {"status": "checked" if data else "N/A", "reason": "no annotations" if not data else None,
            "items": items, "scope": "Mechanical validity only; error labels and evidence are not adjudicated"}


def audit(run_dir, needles_path=None):
    errors, outputs, network, hits = [], [], [], []
    needles = load_needles(needles_path, errors)
    case_path = run_dir / "case.json"
    case = read_json(case_path, errors, "case.json") if case_path.is_file() else None
    baseline = "\n".join(text for key in ("facts_summary", "claims")
                         for _, text in strings(case.get(key))) if isinstance(case, dict) else ""

    def add_output(source, payload):
        if isinstance(payload, dict) and "plaintiff" in payload and "defendant" in payload:
            for side in ("plaintiff", "defendant"):
                if isinstance(payload[side], dict):
                    add_output(source + ":" + side, {**payload[side], "side": side})
            return
        outputs.append({"source": source, "step": step_name(source, payload), "payload": payload})

    paths = sorted({path for pattern in OUTPUT_PATTERNS for path in run_dir.glob(pattern) if path.is_file()})
    for path in paths:
        label = source_name(path, run_dir)
        text = read_text(path, errors, label)
        if text is None or not text.strip():
            continue
        candidate = text.strip()
        if candidate.startswith("```") and candidate.endswith("```"):
            candidate = "\n".join(candidate.splitlines()[1:-1])
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError as exc:
            if path.suffix == ".json":
                errors.append({"kind": "json_parse_error", "source": label,
                               "line": exc.lineno, "column": exc.colno, "error": exc.msg})
                continue
            payload = {"text": text}
        add_output(label, payload)

    streams = sorted(run_dir.glob("calls/*/stream.jsonl"))
    event_count = 0
    for path in streams:
        label = source_name(path, run_dir)
        text = read_text(path, errors, label)
        if text is None:
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            locator = {"source": label, "call": path.parent.name, "line": line_number}
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append({"kind": "jsonl_parse_error", **locator,
                               "column": exc.colno, "error": exc.msg})
                if needles is not None:
                    for identity, needle in needles:
                        if needle in line:
                            hits.append({**locator, "needle_id": identity,
                                         "locations": ["raw unparsed line"], "unparsed": True})
                continue
            event_count += 1
            locator["event_type"] = event.get("type") if isinstance(event, dict) else None
            scan_event(event, locator, needles, network, hits)
            for location, obj in objects(event):
                if obj.get("type") == "agent_message" or obj.get("role") == "assistant" and obj.get("type") == "message":
                    content = obj.get("text", obj.get("content"))
                    if isinstance(content, str) and content.strip():
                        try:
                            payload = json.loads(content)
                        except json.JSONDecodeError:
                            payload = {"text": content}
                        add_output(f"{label}:{line_number}:{location}", payload)

    facts, admissions, citation_sources = [], [], {}
    text_count = 0
    for output in outputs:
        for field, text in strings(output["payload"]):
            if not text.strip():
                continue
            text_count += 1
            origin = {"source": output["source"], "step": output["step"], "field": field}
            for kind, pattern in FACT_PATTERNS.items():
                for match in pattern.finditer(text):
                    name = "value" if kind == "person" else 0
                    value = match.group(name).strip()
                    facts.append({**origin, "kind": kind, "candidate": value,
                                  "offset": match.start(name),
                                  "in_input": value in baseline if baseline else None})
            for sentence_match in re.finditer(r"[^。！？!?\n]+[。！？!?]?", text):
                sentence = sentence_match.group().strip()
                terms = [word for word in ADMISSION_WORDS if word in sentence]
                if terms:
                    admissions.append({**origin, "sentence": sentence, "terms": terms,
                                       "offset": sentence_match.start(),
                                       "in_input": sentence in baseline if baseline else None,
                                       "provenance": "requires_manual_review"})
        for location, obj in objects(output["payload"]):
            for key in ("cited_statutes", "cited_precedents", "citations_used"):
                if not isinstance(obj.get(key), list):
                    continue
                for index, citation in enumerate(obj[key]):
                    if isinstance(citation, str):
                        citation_sources.setdefault(citation, []).append({"source": output["source"],
                            "step": output["step"], "field": f"{location}.{key}[{index}]"})

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(run_dir),
        "method": "Offline heuristic candidates and exact string comparisons; no hallucination verdicts",
        "coverage": {"case_available": isinstance(case, dict), "baseline_characters": len(baseline),
                     "streams": [source_name(path, run_dir) for path in streams],
                     "parsed_events": event_count, "output_documents": len(outputs),
                     "output_string_fields": text_count,
                     "output_sources": [{"source": x["source"], "step": x["step"]} for x in outputs],
                     "status": "available" if text_count else "N/A",
                     "limitations": "Missing/unreadable logs and parse failures prevent complete coverage"},
        "network": {"status": "candidates_for_review" if network else "no_candidates_detected" if event_count else "N/A",
                    "scope": "Heuristic tool names and shell command text; not proof of executed network traffic",
                    "candidates": network},
        "sensitive_strings": {"status": "checked" if needles is not None and event_count else "N/A",
                              "reason": "No explicit needles supplied, invalid needles, or no parsed events" if needles is None or not event_count else None,
                              "needle_count": len(needles) if needles is not None else None,
                              "hits": hits},
        "fact_candidates": {"status": "candidates_for_review" if text_count and baseline else "N/A",
                            "heuristic": True, "comparison": "literal substring of facts_summary + claims",
                            "limitations": "Incomplete extraction; wording/number variants and legal hypotheses may appear absent. Absence does not establish fabrication.",
                            "items": facts},
        "admissions": {"status": "candidates_for_review" if text_count else "N/A",
                       "scope": "Keyword sentences only; trace opposing statements and factual basis manually",
                       "items": admissions},
        "citations": {"status": "collected" if citation_sources else "no_citations_in_available_outputs" if text_count else "N/A",
                      "unique": sorted(citation_sources), "occurrences": citation_sources,
                      "verification": {"status": "N/A", "reason": "Deduplication does not verify existence, publication status, or substantive relevance"}},
        "annotations": check_annotations(run_dir / "eval_annotations.json", outputs, errors),
        "parse_errors": errors,
        "hallucination_assessment": {"status": "N/A", "reason": "No automated hallucination judgment. Zero output is unavailable evidence, never zero hallucinations."},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--needles-json", type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    if not run_dir.is_dir():
        parser.error("--run-dir must name an existing directory")
    report = audit(run_dir, args.needles_json)
    target = run_dir / "machine_checks.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(str(target))


if __name__ == "__main__":
    main()
