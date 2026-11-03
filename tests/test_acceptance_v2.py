"""scripts/acceptance_v2.py:v2 實跑驗收的機械項目(docs/zh/v2-acceptance-checklist.md)。用假 Claude 跑完全程的案件。"""
import copy
import json
import os

import pytest

from scripts.acceptance_v2 import FAIL, PASS, SKIP, TODO, evaluate
from tests.test_gate import client, create_v2, db_url, run  # noqa: F401

CASE_FILE = {"demo_audit": {"exclude": ["114年度台上字第1987號"],
                            "forbid": ["114年度台上字第1987號", "台上,1987", "corpus/judgments", "data/cases/x.json"]}}


@pytest.fixture
def detail(client):  # noqa: F811
    case_id = create_v2(client)
    done = run(client, case_id)
    assert done["run"]["status"] == "succeeded", done["run"]["error"]
    return client.get(f"/api/cases/{case_id}").json()


def by_id(out):
    return {r["id"]: r for r in out["results"]}


def test_a_clean_full_run_passes_the_mechanical_items(detail):
    out = evaluate(detail, case_file=CASE_FILE, answers=["只有判決才有的字串"])
    r = by_id(out)
    for key in ("X1", "X1b", "X2", "X4", "X5", "X6", "X8a", "X8e", "X8f", "X9", "X9b", "X11"):
        assert r[key]["status"] == PASS, (key, r[key]["detail"])
    assert r["X10a"]["status"] == TODO and r["X10b"]["status"] == TODO
    assert set(out["manual_todo"]) == {"X10a", "X10b"}


def test_missing_answers_list_is_not_a_pass(detail):
    out = evaluate(detail, case_file=CASE_FILE, answers=None)
    assert by_id(out)["X8e"]["status"] == SKIP and "X8e" in out["unchecked"] and out["passed"] is False


def test_answer_strings_in_the_output_fail(detail):
    text = next(v["draft_text"] for v in detail["pleading_versions"] if v.get("pleading_type") == "answer")
    needle = text.strip().splitlines()[-1].strip()[:8]
    out = evaluate(detail, case_file=CASE_FILE, answers=[needle])
    assert by_id(out)["X8e"]["status"] == FAIL and out["passed"] is False


def test_source_citation_in_the_output_fails(detail):
    d = copy.deepcopy(detail)
    d["arguments"][0]["reasoning"] += "參最高法院114年度台上字第1987號判決。"
    assert by_id(evaluate(d, case_file=CASE_FILE, answers=[]))["X8f"]["status"] == FAIL


def test_uncovered_fact_point_fails(detail):
    d = copy.deepcopy(detail)
    d["pleadings"]["defendant"]["structured"]["responses"].pop()
    assert by_id(evaluate(d, case_file=CASE_FILE, answers=[]))["X5"]["status"] == FAIL


def test_undisputed_fact_without_admit_fails(detail):
    d = copy.deepcopy(detail)
    cf = d["pleadings"]["defendant"]["structured"]["responses"][0]
    cf["stance"] = "deny"
    d["issue_sheet"]["sheet"]["undisputed"] = [{"id": "U1", "text": "t", "source": [cf["fact_id"]]}]
    assert by_id(evaluate(d, case_file=CASE_FILE, answers=[]))["X6"]["status"] == FAIL


def test_win_probability_fails(detail):
    d = copy.deepcopy(detail)
    d["verdict"]["verdict_main_text"] += "原告勝訴機率約七成。"
    assert by_id(evaluate(d, case_file=CASE_FILE, answers=[]))["X11"]["status"] == FAIL


def test_three_safety_stops_on_one_agent_fail(detail):
    d = copy.deepcopy(detail)
    d["live_runs"][-1]["safety_stops"] = [{"who": "被告防禦分析", "at": "t"}] * 3
    assert by_id(evaluate(d, case_file=CASE_FILE, answers=[]))["X2"]["status"] == FAIL


def test_forbidden_read_in_the_stream_fails(detail, tmp_path):
    d = copy.deepcopy(detail)
    stream = tmp_path / "stream.jsonl"
    events = [
        {"type": "system", "subtype": "init", "cwd": str(tmp_path)},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "a1", "name": "Agent",
                                                       "input": {"description": "被告防禦分析", "prompt": "讀 defendant_view.json"}}]}},
        {"type": "assistant", "parent_tool_use_id": "a1", "message": {"content": [
            {"type": "tool_use", "id": "r1", "name": "Read", "input": {"file_path": str(tmp_path / "case.json")}}]}},
    ]
    stream.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events), encoding="utf-8")
    d["live_runs"] = [{**d["live_runs"][-1], "log_path": str(stream)}]
    r = by_id(evaluate(d, case_file=CASE_FILE, answers=[]))
    assert r["X8b"]["status"] == FAIL and "case.json" in r["X8b"]["detail"]
    assert r["X8c"]["status"] == FAIL and "法官" in r["X8c"]["detail"]  # 沒有法官 agent 就不能說隔離通過


def test_cli_exit_codes(detail, db_url, tmp_path):  # noqa: F811
    from scripts.acceptance_v2 import main
    case_file = tmp_path / "case.json"
    case_file.write_text(json.dumps(CASE_FILE, ensure_ascii=False), encoding="utf-8")
    assert main(["--case-id", "nope", "--case-file", str(case_file), "--db-url", db_url]) == 2
    code = main(["--case-id", detail["case"]["case_id"], "--case-file", str(case_file), "--db-url", db_url])
    assert code == 1  # 沒給答案字串清單，不能算通過
    assert os.path.exists(case_file)
