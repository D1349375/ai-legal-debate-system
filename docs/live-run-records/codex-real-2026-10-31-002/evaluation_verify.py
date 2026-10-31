"""Post-run offline evidence checks for real-002. No network or database writes."""
import sys
sys.dont_write_bytecode = True
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUN = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from engine import verify

def deny_network(*args, **kwargs):
    raise RuntimeError("Evaluator network is disabled")
verify._fjud_search = deny_network
verify._fetch_single_article = deny_network

annotations = json.loads((RUN / "eval_annotations.json").read_text(encoding="utf-8-sig"))
exact = []
for item in annotations:
    text = (RUN / item["source_file"]).read_text(encoding="utf-8-sig")
    exact.append({"id": item["id"], "source_file": item["source_file"],
                  "quote_length": len(item["quote"]), "exact_substring": item["quote"] in text,
                  "length_valid": 20 <= len(item["quote"]) <= 120})

spec = importlib.util.spec_from_file_location("existing_audit", ROOT / "docs/live-run-records/codex-real-2026-10-31-001/audit_run.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
report = audit.audit(RUN)
needles = ["legaldebate_holdout", "李昀修", "鄭盛文", "林琬軒",
           "時效已於113年屆滿", "兩造自108年8月後即無往來", "受領時始終認係投資關係",
           "操盤人「JM」", "被告於108年7月18日", "紐約州紐約郡法院",
           "已提起上訴而繫屬臺灣高等法院", "110年11月30日"]
contamination_hits = []
docket_hits = []
for stream in sorted((RUN / "calls").glob("*/stream.jsonl")):
    for line_number, line in enumerate(stream.read_text(encoding="utf-8-sig").splitlines(), 1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        leaves = list(audit.strings(event))
        for needle in needles:
            locations = [field for field, value in leaves if needle in value]
            if locations:
                contamination_hits.append({"source": stream.relative_to(RUN).as_posix(), "line": line_number,
                                           "needle": needle, "locations": locations})
        if any("115年度重訴字第242號" in value for _, value in leaves):
            docket_hits.append({"source": stream.relative_to(RUN).as_posix(), "line":line_number})
(RUN / "evaluation_contamination.json").write_text(json.dumps({"method":"Exact selected holdout strings searched after all roles ended; docket separately allowed by source_note", "needles":needles, "holdout_hits":contamination_hits,"authorized_source_docket_hits":docket_hits},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
parser = {s: verify.parse_citation(s) for s in ["民法債編施行法第10條之1", "銀行法第29條", "銀行法第29條之1"]}
match = verify.verify_judgment_citation("114", "台上", "1945")
ids = [("113","2221"),("114","1071"),("114","1131"),("114","1738"),("114","1939"),("114","1945"),("114","2031"),("114","2167"),("115","192"),("115","207"),("115","459"),("115","521"),("115","561")]
files = []
for year, no in ids:
    for path in sorted((ROOT / "corpus/judgments").glob(f"TPSV,{year},台上,{no},*.txt")):
        raw = path.read_bytes()
        files.append({"source_file": path.relative_to(ROOT).as_posix(),
                      "bytes":len(raw), "sha256":hashlib.sha256(raw).hexdigest()})
(RUN / "evaluation_corpus_files.json").write_text(json.dumps(files,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

# Deduplicate canonical source fields; full heuristic extraction is retained by controller.
canonical = [f"{side}_s{stage}.json" for side in ("p","d") for stage in (1,2,3)] + ["judge_questions.json","verdict.json"]
admissions = [x for x in report["admissions"]["items"] if x["source"] in canonical]
facts = [x for x in report["fact_candidates"]["items"] if x["source"] in canonical]
summary = {
 "method": "Offline post-run reproduction. No new model roles, main.py, network or DB writes.",
 "annotation_quotes": exact, "existing_validator": report["annotations"],
 "parser_reproduction": parser,
 "judgment_file_reproduction": {k:v for k,v in match.items() if k!="matched_text"},
 "reproduction_caveat": "Current engine behavior is reproduced; missing actual Step8 raw verifier payload prevents proving identical runtime selection.",
 "corpus_unique_dockets": len(ids), "corpus_text_files": len(files),
 "canonical_admission_sentences": admissions,
 "canonical_fact_candidates": facts,
 "all_quote_checks_pass": all(x["exact_substring"] and x["length_valid"] for x in exact),
 "network": "No evaluator network calls"
}
(RUN / "evaluation_validation.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps({"annotation_checks":exact,"validator":report["annotations"],"parser":parser,"matched_file":match.get("source_file"),"corpus_text_files":len(files),"canonical_admission_sentences":len(admissions),"fact_candidates":len(facts)},ensure_ascii=False,indent=2))

