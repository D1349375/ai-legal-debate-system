"""兩件示範案的 v2 輸入(W8-1、W8-2):能用 `main.py case` 落地、不含被告抗辯、防污染清單齊全。"""
import json
import os
from types import SimpleNamespace

import pytest

import main
from database.db import case_payload, get_session
from database.schema import Case

CASES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "cases")
GCIS = os.path.join(CASES, "test-2026-11-03-v2-gcis-001.json")
E2E = os.path.join(CASES, "test-2026-11-03-v2-e2e-001.json")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("path", [GCIS, E2E])
def test_case_command_lands_it_as_v2(path, tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'demo.db'}"
    monkeypatch.setenv("LEGALDEBATE_DB_URL", url)
    assert main.cmd_case(SimpleNamespace(json=path)) == 0
    row = get_session(url).query(Case).one()
    payload = case_payload(row)
    data = load(path)
    assert payload["protocol"] == "v2" and payload["represented_side"] == "plaintiff"
    assert payload["parties"] == data["parties"] and payload["known_gaps"] == data["known_gaps"]
    assert "demo_audit" not in payload  # 防污染設定不進案件,角色讀不到


def test_e2e_facts_have_only_the_plaintiff_side():
    data = load(E2E)
    old = load(os.path.join(CASES, "test-2026-08-09-e2e-001.json"))
    for word in ("被告則抗辯", "抵償", "時效", "甲公司", "每坪"):
        assert word not in json.dumps(data, ensure_ascii=False), word
    # 刪掉抗辯段落,原告主張那一段逐字保留
    assert old["facts_summary"].startswith(data["facts_summary"])
    assert data["claims"] == old["claims"]
    assert data["claim_amount"] == 10_000_000 + 4_813_529 + 4_974_388


def test_gcis_facts_and_claims_are_unchanged():
    data = load(GCIS)
    old = load(os.path.join(CASES, "test-2026-10-27-gcis-001.json"))
    assert data["facts_summary"] == old["facts_summary"] and data["claims"] == old["claims"]
    assert data["parties"]["plaintiff"]["ban"] == "29112102"


@pytest.mark.parametrize("path", [GCIS, E2E])
def test_missing_inputs_are_gaps_not_filled_in(path):
    data = load(path)
    assert data["evidence"] == [] and data["opponent_known_responses"] == []
    gaps = "".join(data["known_gaps"])
    assert "證據清單" in gaps and "被告起訴前的反應" in gaps


def test_forbid_lists_cover_source_judgments_and_answer_files():
    e2e, gcis = load(E2E)["demo_audit"], load(GCIS)["demo_audit"]
    assert e2e["exclude"] == ["114年度台上字第1547號"] and gcis["exclude"] == ["114年度台上字第1987號"]
    for needle in ("114年度台上字第1547號", "台上,1547", "demo/recorded_cases.json",
                   "docs/zh/e2e-test-report-2026-08-09.md", "data/cases/test-2026-08-09-e2e-001.json"):
        assert needle in e2e["forbid"]
    for needle in ("114年度台上字第1987號", "台上,1987", "data/cases/test-2026-10-27-gcis-001.json"):
        assert needle in gcis["forbid"]
    for audit in (e2e, gcis):  # 檔名的寫法要真的對得上語料
        hits = [n for n in os.listdir(os.path.join(os.path.dirname(CASES), "..", "corpus", "judgments"))
                if any(f in n for f in audit["forbid"] if f.startswith("台上,"))]
        assert hits
