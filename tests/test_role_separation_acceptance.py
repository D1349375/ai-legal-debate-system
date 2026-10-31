"""獨立驗收：以公開CLI/API/DB邊界驗證職責分離，期望值由計畫人工制定。

本檔由驗證 agent 維護，不依實作者的投影/驗證 helper 計算期望值。
"""
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from database.db import DB_URL_ENV, get_session, record_case, record_pleading
from database.schema import DebateArgument, PleadingDraft
from server.app import create_app


ROOT = Path(__file__).resolve().parents[1]
SECRET_OWN = "OWN_PRIVATE_SENTINEL_8d12"
SECRET_OPP = "OPP_PRIVATE_SENTINEL_d732"
SECRET_SOURCE = "HOLDOUT_SOURCE_SENTINEL_2c89"
CASE = {
    "case_id": "accept-c1", "case_type": "買賣價金", "represented_side": "plaintiff",
    "facts_summary": "原告交付機器，被告未給付價金。",
    "uncontested_facts": "〔書證：契約〕雙方於115年1月1日簽訂機器買賣契約。",
    "plaintiff_facts": "原告於115年1月2日交付機器。\n〔書證：email〕被告回覆零件短少正在盤點。",
    "defendant_facts": "被告曾表示零件短少。", "claim_amount": 500001,
    "claims": "被告應給付原告新臺幣500001元。", "source_note": SECRET_SOURCE,
    "plaintiff": {"name": "甲"}, "defendant": {"name": "乙"},
}


def cli(url, *args):
    env = {**os.environ, DB_URL_ENV: url, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, str(ROOT / "main.py"), *args], cwd=ROOT,
                          env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)


def land_json(url, tmp_path, command, payload, *args):
    path = tmp_path / f"{command}-{len(list(tmp_path.glob('*.json')))}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return cli(url, command, *args, "--json", str(path))


@pytest.fixture
def case_db(tmp_path):
    url = f"sqlite:///{tmp_path / 'acceptance.db'}"
    result = land_json(url, tmp_path, "case", CASE)
    assert result.returncode == 0, result.stdout + result.stderr
    return url


@pytest.fixture
def api_client(tmp_path):
    app = create_app(db_url=f"sqlite:///{tmp_path / 'api.db'}", cases_dir=str(tmp_path / "cases"),
                     seed_on_empty=False, local_clients=("testclient",))
    return TestClient(app, base_url="http://127.0.0.1:8000")


def argument(side="plaintiff", stage=1):
    item_id = "P1" if side == "plaintiff" else "D1"
    return {
        "case_id": CASE["case_id"], "side": side, "stage": stage,
        "position": "依卷內契約主張給付。" if side == "plaintiff" else "請求金額仍需依法核對。",
        "argument": "以卷內契約內容評估買賣價金請求。",
        "items": [{"id": item_id, "label": "契約約定之給付", "kind": "legal", "status": "asserted",
                   "elements": [{"element": "買賣契約成立", "state": "met", "source": "F1"}],
                   "needs_from_client": [], "citations": []}],
        "position_basis": [item_id], "internal_notes": {"strategy": SECRET_OWN if side == "plaintiff" else SECRET_OPP},
        "defeat_conditions": [], "cited_statutes": [], "cited_precedents": [], "precedent_notes": [],
        "claim_statement": "依契約請求價金。", "rebuttal": "REBUTTAL_SENTINEL_64ac",
    }


def assert_landed(url, tmp_path, payload):
    result = land_json(url, tmp_path, "record", payload)
    assert result.returncode == 0, result.stdout + result.stderr


def argument_count(url):
    s = get_session(url)
    try:
        return s.query(DebateArgument).count()
    finally:
        s.close()


@pytest.mark.parametrize("role", ["plaintiff", "defendant", "judge"])
def test_c04_role_view_is_a_read_only_projection_without_holdout(case_db, role):
    before = argument_count(case_db)
    first = cli(case_db, "role-view", "--case-id", CASE["case_id"], "--role", role)
    second = cli(case_db, "role-view", "--case-id", CASE["case_id"], "--role", role)
    assert first.returncode == second.returncode == 0, first.stderr
    assert first.stdout == second.stdout
    assert SECRET_SOURCE not in first.stdout and "source_note" not in first.stdout
    assert "F1" in first.stdout and "書證" in first.stdout and "契約" in first.stdout
    assert "起訴前" in first.stdout and "plaintiff" in first.stdout
    assert argument_count(case_db) == before


def test_c02_c03_fact_ids_stable_across_roles_and_opponent_is_attributed(case_db):
    outputs = [cli(case_db, "role-view", "--case-id", CASE["case_id"], "--role", role).stdout
               for role in ("plaintiff", "defendant", "judge")]
    ids = [set(re.findall(r"\bF\d+\b", out)) for out in outputs]
    assert ids[0] == ids[1] == ids[2] == {"F1", "F2", "F3", "F4"}
    assert all("轉述" in out for out in outputs)
    assert all("email" in out and "陳述" in out for out in outputs)


def test_c05_legacy_case_role_view_preserves_original_facts(tmp_path):
    url = f"sqlite:///{tmp_path / 'old.db'}"
    s = get_session(url)
    record_case(s, case_id="legacy", case_type="舊案", facts_summary="既有原始事實不可遺失", claims="請求")
    s.close()
    result = cli(url, "role-view", "--case-id", "legacy", "--role", "plaintiff")
    assert result.returncode == 0, result.stderr
    assert "既有原始事實不可遺失" in result.stdout and "陳述" in result.stdout


@pytest.mark.parametrize("side", [None, "judge", "", "PLAINTIFF"])
def test_c01_api_requires_valid_represented_side(api_client, side):
    payload = {k: v for k, v in CASE.items() if k not in ("source_note", "represented_side")}
    if side is not None:
        payload["represented_side"] = side
    result = api_client.post("/api/cases", json=payload)
    assert result.status_code == 422, result.text


@pytest.mark.parametrize("side", ["plaintiff", "defendant"])
def test_u01_api_preserves_three_fact_columns_and_represented_side(api_client, side):
    payload = {**CASE, "represented_side": side}
    result = api_client.post("/api/cases", json=payload)
    assert result.status_code == 201, result.text
    detail = api_client.get(f"/api/cases/{result.json()['case_id']}").json()
    assert detail["case"]["represented_side"] == side
    for name in ("uncontested_facts", "plaintiff_facts", "defendant_facts", "claim_amount"):
        assert detail["case"][name] == CASE[name]


@pytest.mark.parametrize("amount,expected", [(None, "待確認"), (100000, "小額"), (100001, "簡易"),
                                           (500000, "簡易"), (500001, "通常")])
def test_c06_procedure_boundaries_are_visible_without_blocking(api_client, amount, expected):
    payload = {**CASE, "claim_amount": amount}
    result = api_client.post("/api/cases", json=payload)
    assert result.status_code == 201, result.text
    detail = api_client.get(f"/api/cases/{result.json()['case_id']}").json()
    text = json.dumps({"create": result.json(), "detail": detail}, ensure_ascii=False)
    assert expected in text


@pytest.mark.parametrize("mutation", ["duplicate", "bad_status", "bad_kind", "bad_state", "unknown_fact",
                                      "unknown_basis", "uncertain_basis", "unknown_element_basis"])
def test_r01_r03_invalid_items_are_rejected_without_database_write(case_db, tmp_path, mutation):
    payload = argument()
    if mutation == "duplicate":
        payload["items"].append(copy.deepcopy(payload["items"][0]))
    elif mutation == "bad_status":
        payload["items"][0]["status"] = "admitted"
    elif mutation == "bad_kind":
        payload["items"][0]["kind"] = "made_up"
    elif mutation == "bad_state":
        payload["items"][0]["elements"][0]["state"] = "probably"
    elif mutation == "unknown_fact":
        payload["items"][0]["elements"][0]["source"] = "F999"
    elif mutation == "unknown_basis":
        payload["position_basis"] = ["P999"]
    elif mutation == "uncertain_basis":
        payload["items"][0]["status"] = "to_confirm"
    elif mutation == "unknown_element_basis":
        payload["items"][0]["elements"][0]["state"] = "unknown"
    result = land_json(case_db, tmp_path, "record", payload)
    assert result.returncode != 0, f"非法{mutation}卻被接受：{result.stdout}"
    assert argument_count(case_db) == 0


def test_r05_opponent_hypothesis_cannot_be_asserted(case_db, tmp_path):
    payload = argument("defendant")
    payload["items"][0]["kind"] = "factual_hypothesis"
    result = land_json(case_db, tmp_path, "record", payload)
    assert result.returncode != 0 and argument_count(case_db) == 0


@pytest.mark.parametrize("mutation", ["missing_item", "no_reason", "insufficient_information", "opponent_strategy",
                                      "nonexistent_fact", "nonexistent_opponent"])
def test_t01_t04_hypotheses_cannot_disappear_or_withdraw_without_basis(case_db, tmp_path, mutation):
    first = argument("defendant")
    first["items"].append({"id": "D2", "label": "若知悉日期符合要件則二年時效抗辯", "kind": "factual_hypothesis",
                           "status": "to_confirm", "elements": [{"element": "知悉日期待確認", "state": "unknown", "source": "F2"}],
                           "needs_from_client": [{"text": "待確認知悉日期", "holder": "opponent"}], "citations": []})
    assert_landed(case_db, tmp_path, first)
    second = copy.deepcopy(first)
    second["stage"] = 2
    item = second["items"][1]
    if mutation == "missing_item":
        second["items"].pop()
    else:
        item["status"] = "withdrawn"
        if mutation == "insufficient_information":
            item["withdraw_reason"] = {"type": "insufficient_information", "explanation": "日期資料不足"}
        elif mutation == "opponent_strategy":
            item["withdraw_reason"] = {"type": "strategy", "explanation": "不再爭執時效"}
        elif mutation == "nonexistent_fact":
            item["withdraw_reason"] = {"type": "record_negates", "fact_ids": ["F999"]}
        elif mutation == "nonexistent_opponent":
            item["withdraw_reason"] = {"type": "opponent_defeats", "item_ids": ["plaintiff:P999"]}
    result = land_json(case_db, tmp_path, "record", second)
    assert result.returncode != 0, result.stdout
    assert argument_count(case_db) == 1


def test_t08_summary_retains_pending_and_hides_internal_notes(case_db, tmp_path):
    payload = argument("defendant")
    payload["items"].append({"id": "D2", "label": "若通知有效則可主張瑕疵擔保，待確認", "kind": "factual_hypothesis",
                           "status": "to_confirm", "elements": [{"element": "若通知送達，日期待確認", "state": "unknown", "source": "F3"}],
                           "needs_from_client": [{"text": "通知送達日期待確認", "holder": "opponent"}], "citations": []})
    assert_landed(case_db, tmp_path, payload)
    result = cli(case_db, "summary", "--case-id", CASE["case_id"], "--side", "defendant", "--stage", "1")
    assert result.returncode == 0, result.stderr
    assert SECRET_OPP not in result.stdout and "internal_notes" not in result.stdout and "prep_items" not in result.stdout
    assert "to_confirm" in result.stdout and "unconfirmed_facts" in result.stdout
    assert "若通知送達，日期待確認" in result.stdout


def test_r06_each_role_only_sees_its_own_internal_notes(case_db, tmp_path):
    for side in ("plaintiff", "defendant"):
        assert_landed(case_db, tmp_path, argument(side))
    for role, visible, forbidden in [("plaintiff", SECRET_OWN, SECRET_OPP),
                                     ("defendant", SECRET_OPP, SECRET_OWN),
                                     ("judge", None, SECRET_OWN)]:
        result = cli(case_db, "role-view", "--case-id", CASE["case_id"], "--role", role)
        assert result.returncode == 0, result.stderr
        assert forbidden not in result.stdout
        if visible:
            assert visible in result.stdout
        else:
            assert SECRET_OPP not in result.stdout and "internal_notes" not in result.stdout


def test_r06_nested_internal_notes_cannot_escape_via_public_items(case_db):
    from database.db import record_argument
    from engine.role_protocol import role_view
    payload = argument()
    payload["items"][0]["internal_notes"] = {"strategy": "NESTED_PRIVATE_SENTINEL_a7d9"}
    s = get_session(case_db)
    try:
        try:
            record_argument(s, case_id=CASE["case_id"], side="plaintiff", stage=1, position=payload["position"],
                            reasoning=payload["argument"], structured_json=payload)
        except ValueError:
            assert s.query(DebateArgument).count() == 0
            return
        for role in ("defendant", "judge"):
            output = json.dumps(role_view(s, CASE["case_id"], role), ensure_ascii=False)
            assert "NESTED_PRIVATE_SENTINEL_a7d9" not in output, "item的額外私密欄位穿過角色投影"
    finally:
        s.close()


def test_t08_party_role_view_cannot_bypass_opponent_summary_with_full_text(case_db):
    from database.db import record_argument
    from engine.role_protocol import role_view
    s = get_session(case_db)
    try:
        for side in ("plaintiff", "defendant"):
            payload = argument(side)
            record_argument(s, case_id=CASE["case_id"], side=side, stage=1, position=payload["position"],
                            reasoning=f"{side}_FULL_PUBLIC_ARGUMENT_a73e", structured_json=payload)
        for role in ("plaintiff", "defendant"):
            output = role_view(s, CASE["case_id"], role)
            assert [a["side"] for a in output["arguments"]] == [role]
            other = "defendant" if role == "plaintiff" else "plaintiff"
            assert f"{other}_FULL_PUBLIC_ARGUMENT_a73e" not in json.dumps(output)
        judge = role_view(s, CASE["case_id"], "judge")
        assert {a["side"] for a in judge["arguments"]} == {"plaintiff", "defendant"}
    finally:
        s.close()


def judge_bundle(**overrides):
    return {"case_id": CASE["case_id"],
            "questions": [{"target_side": "plaintiff", "question_type": "factual",
                           "question_text": "契約原本由誰持有？", "based_on": "plaintiff:P1 請說明契約原本所在"}],
            "prep_items": [{"id": "J-PREP-1", "hypothesis": "對方可能提出檢測資料",
                            "affects": "plaintiff:P1", "prepare": "PREP_PRIVATE_SENTINEL_b83c",
                            "holder": "opponent", "is_hypothesis": True}],
            "issues": [{"issue_id": "I1", "label": "買賣價金是否應給付", "items": ["plaintiff:P1", "defendant:D1"]}],
            "uncontested_points": [], **overrides}


@pytest.mark.parametrize("mutation", ["opponent_factual", "unknown_item", "wrong_party", "false_admission",
                                      "prep_not_hypothesis", "prep_unknown_item", "single_party_uncontested"])
def test_j01_j05_judge_misstatements_and_invalid_preparation_are_rejected(case_db, tmp_path, mutation):
    for side in ("plaintiff", "defendant"):
        assert_landed(case_db, tmp_path, argument(side))
    payload = judge_bundle()
    question = payload["questions"][0]
    if mutation == "opponent_factual":
        question.update(target_side="defendant", based_on="defendant:D1 請說明事實")
    elif mutation == "unknown_item":
        question["based_on"] = "plaintiff:P999 請說明"
    elif mutation == "wrong_party":
        question["based_on"] = "defendant:D1 請說明"
    elif mutation == "false_admission":
        question["question_text"] = "原告已自承未給付，為何尚要求給付？"
    elif mutation == "prep_not_hypothesis":
        payload["prep_items"][0]["is_hypothesis"] = False
    elif mutation == "prep_unknown_item":
        payload["prep_items"][0]["affects"] = "plaintiff:P999"
    else:
        payload["uncontested_points"] = [{"text": "雙方不爭執機器有瑕疵", "item_ids": ["plaintiff:P1"]}]
    result = land_json(case_db, tmp_path, "record", payload)
    assert result.returncode != 0, result.stdout
    from database.schema import CourtQuestion, JudgeBundle
    s = get_session(case_db)
    try:
        assert s.query(CourtQuestion).count() == 0 and s.query(JudgeBundle).count() == 0
    finally:
        s.close()


def test_j03_preparation_is_only_available_to_represented_side(case_db, tmp_path):
    for side in ("plaintiff", "defendant"):
        assert_landed(case_db, tmp_path, argument(side))
    assert_landed(case_db, tmp_path, judge_bundle())
    for role in ("plaintiff", "defendant", "judge"):
        result = cli(case_db, "role-view", "--case-id", CASE["case_id"], "--role", role)
        assert result.returncode == 0, result.stderr
        assert "PREP_PRIVATE_SENTINEL_b83c" not in result.stdout and "prep_items" not in result.stdout
    own = cli(case_db, "prep-list", "--case-id", CASE["case_id"], "--role", "plaintiff")
    assert own.returncode == 0 and "PREP_PRIVATE_SENTINEL_b83c" in own.stdout
    opponent = cli(case_db, "prep-list", "--case-id", CASE["case_id"], "--role", "defendant")
    assert opponent.returncode != 0 and "PREP_PRIVATE_SENTINEL_b83c" not in opponent.stdout


def test_p01_pleading_source_omits_rebuttal_pending_and_private_material(case_db, tmp_path):
    for stage in (1, 2, 3):
        payload = argument(stage=stage)
        payload["items"].append({"id": "P2", "label": "PENDING_PRIVATE_SENTINEL_f91e，待確認", "kind": "evidence_gap",
                               "status": "to_confirm", "elements": [{"element": "資料待確認", "state": "unknown", "source": "F2"}],
                               "needs_from_client": [{"text": "補證待確認", "holder": "own_client"}], "citations": []})
        assert_landed(case_db, tmp_path, payload)
    result = cli(case_db, "pleading-source", "--case-id", CASE["case_id"], "--side", "plaintiff")
    assert result.returncode == 0, result.stderr
    assert "依契約請求價金。" in result.stdout and "P1" in result.stdout
    assert all(word not in result.stdout for word in ("REBUTTAL_SENTINEL", SECRET_OWN, "PENDING_PRIVATE_SENTINEL", "internal_notes", "prep_items", "to_confirm"))


def test_o01_o02_report_is_deterministic_and_shows_only_own_private_notes(case_db, tmp_path):
    for stage in (1, 2, 3):
        for side in ("plaintiff", "defendant"):
            payload = argument(side, stage)
            payload["items"].append({"id": "P2" if side == "plaintiff" else "D2", "label": "資料未足，待確認",
                                   "kind": "evidence_gap", "status": "to_confirm",
                                   "elements": [{"element": "應補充之書證待確認", "state": "unknown", "source": "F2"}],
                                   "needs_from_client": [{"text": "補充書證待確認", "holder": "own_client" if side == "plaintiff" else "opponent"}], "citations": []})
            assert_landed(case_db, tmp_path, payload)
    a = cli(case_db, "report", "--case-id", CASE["case_id"])
    b = cli(case_db, "report", "--case-id", CASE["case_id"])
    assert a.returncode == b.returncode == 0, a.stderr
    assert a.stdout == b.stdout
    assert SECRET_OWN in a.stdout and SECRET_OPP not in a.stdout
    assert "預測，非對方實際主張" in a.stdout and "待確認" in a.stdout
    labels = ["待確認與準備事項", "對方可能怎麼打", "逐爭點強弱表", "我方內部備註", "書狀骨架", "過程紀錄"]
    positions = [a.stdout.index(label) for label in labels]
    assert positions == sorted(positions)
    assert a.stdout.rstrip().endswith("本結果為爭點分析與書狀骨架初稿，非法院判決預測，語氣潤飾與正式訴狀撰寫仍需律師覆核。")


@pytest.mark.parametrize("word", ["被告主張", "被告抗辯", "被告自承", "被告或將", "本方", "對造", "Stage", "輪次", "前輪", "法官訊問", "訊問攻防"])
def test_p02_complaint_rejects_simulation_or_opponent_response_terms(case_db, word):
    s = get_session(case_db)
    try:
        with pytest.raises(ValueError):
            record_pleading(s, case_id=CASE["case_id"], side="plaintiff", draft_text=f"民事起訴狀\n{word}：內容", citations_used=[])
        assert s.query(PleadingDraft).count() == 0
    finally:
        s.close()


def test_p02_frozen_real_001_complaint_is_rejected(case_db):
    draft = (ROOT / "docs/live-run-records/codex-real-2026-10-31-001/pleading_draft_plaintiff.txt").read_text(encoding="utf-8")
    s = get_session(case_db)
    try:
        with pytest.raises(ValueError):
            record_pleading(s, case_id=CASE["case_id"], side="plaintiff", draft_text=draft, citations_used=[])
        assert s.query(PleadingDraft).count() == 0
    finally:
        s.close()


def test_p06_represented_plaintiff_cannot_generate_formal_defendant_pleading(case_db):
    s = get_session(case_db)
    try:
        with pytest.raises(ValueError):
            record_pleading(s, case_id=CASE["case_id"], side="defendant", draft_text="民事答辯狀\n原告之訴駁回", citations_used=[])
        assert s.query(PleadingDraft).count() == 0
    finally:
        s.close()


@pytest.fixture
def completed_case(case_db):
    """人工固定兩方六份輸出；不靠產品builder推算驗收期待。"""
    from database.db import record_argument, record_judge_bundle
    s = get_session(case_db)
    try:
        for stage in (1, 2, 3):
            for side in ("plaintiff", "defendant"):
                payload = argument(side, stage)
                payload["items"].append({"id": "P2" if side == "plaintiff" else "D2", "label": "日期資料待確認",
                                       "kind": "evidence_gap" if side == "plaintiff" else "factual_hypothesis",
                                       "status": "to_confirm", "elements": [{"element": "若具備要件日期則成立，待確認", "state": "unknown", "source": "F2"}],
                                       "needs_from_client": [{"text": "取得日期資料，待確認", "holder": "own_client" if side == "plaintiff" else "opponent"}],
                                       "citations": []})
                if side == "defendant":
                    payload["defeat_conditions"] = [{"item": "defendant:D1", "condition": "若代理方提出完整履約證據，此抗辯失效"}]
                record_argument(s, case_id=CASE["case_id"], side=side, stage=stage, position=payload["position"],
                                reasoning=payload["argument"], structured_json=payload)
            if stage == 1:
                record_judge_bundle(s, case_id=CASE["case_id"], payload=judge_bundle(questions=[], prep_items=[]))
    finally:
        s.close()
    return case_db


def verdict_data():
    return {"issues": [{"issue_id": "I1", "label": "買賣價金是否應給付", "own_items": ["plaintiff:P1@S3"],
                        "opponent_items": ["defendant:D1@S3"], "reference_grade": "中", "grade": "中", "grade_reason": None,
                        "basis": ["F1"], "inference": None, "to_prepare": []}],
            "summary": "plaintiff:P1@S3 與 defendant:D1@S3 之法律攻防尚需律師評估。",
            "anchor_responses": [{"ref": ref, "comment": "資料待確認，請依準備事項補充。"} for ref in
                                 ("pending:own_client:1", "pending:own_client:2", "pending:opponent:1", "pending:opponent:2", "defeat:defendant:1")],
            "citations_used": []}


def save_verdict(url, data):
    from database.db import record_verdict
    s = get_session(url)
    try:
        row = record_verdict(s, case_id=CASE["case_id"], verdict_main_text=data["summary"], verdict_reasoning="逐爭點評估。",
                             risk_map={}, mechanical_anchor_json={}, protocol_version="v2-role-separation-2026-10-31",
                             citations_used=[], structured_json=data)
        s.refresh(row)
        return row
    finally:
        s.close()


def test_v01_valid_evaluation_is_saved_with_original_item_text(completed_case):
    row = save_verdict(completed_case, verdict_data())
    stored = json.loads(row.structured_json)
    assert stored["issues"][0]["reference_grade"] == "中"
    assert stored["quoted_items"]["plaintiff:P1@S3"]["label"] == "契約約定之給付"


@pytest.mark.parametrize("mutation", ["unknown_item", "unknown_round", "wrong_party", "unqualified_pending", "false_admission",
                                      "same_source_corroboration", "item_only_corroboration", "missing_anchor", "grade_without_reason", "false_status_change"])
def test_v01_v06_evaluation_rejects_untraceable_or_overstated_claims(completed_case, mutation):
    payload = verdict_data()
    if mutation == "unknown_item":
        payload["summary"] = "plaintiff:P999@S3 已成立。"
    elif mutation == "unknown_round":
        payload["summary"] = "plaintiff:P1@S9 已成立。"
    elif mutation == "wrong_party":
        payload["issues"][0]["own_items"] = ["defendant:D1@S3"]
    elif mutation == "unqualified_pending":
        payload["summary"] = "defendant:D2@S3 已經證明時效成立。"
    elif mutation == "false_admission":
        payload["summary"] = "defendant:D1@S3 被告自承機器無瑕疵。"
    elif mutation == "same_source_corroboration":
        payload["summary"] = "F1 與 F1 相互印證交付完成。"
    elif mutation == "item_only_corroboration":
        payload["summary"] = "plaintiff:P1@S3 與 defendant:D1@S3 相互印證交付完成。"
    elif mutation == "missing_anchor":
        payload["anchor_responses"].pop()
    elif mutation == "grade_without_reason":
        payload["issues"][0]["grade"] = "高"
    elif mutation == "false_status_change":
        payload["summary"] = "defendant:D1@S1 → defendant:D1@S3 已改變立場。"
    with pytest.raises(ValueError):
        save_verdict(completed_case, payload)
    from database.schema import Verdict
    s = get_session(completed_case)
    try:
        assert s.query(Verdict).count() == 0
    finally:
        s.close()


def test_v06_reference_grade_high_medium_low_have_independent_examples():
    from engine.role_protocol import reference_grade
    fact_item = {"status": "asserted", "elements": [{"state": "met", "source": "F1"}]}
    unknown_item = {"status": "to_confirm", "elements": [{"state": "unknown", "source": "F1"}]}
    failed_item = {"status": "asserted", "elements": [{"state": "unmet", "source": "F1"}]}
    assert reference_grade([fact_item], []) == "高"
    assert reference_grade([fact_item], [fact_item]) == "中"
    assert reference_grade([unknown_item], []) == "中"
    assert reference_grade([failed_item], []) == "低"


def test_p04_p05_amount_breakdown_separates_pending_and_warns(completed_case):
    s = get_session(completed_case)
    try:
        row = record_pleading(s, case_id=CASE["case_id"], draft_text="民事起訴狀\n訴之聲明：被告應給付原告100元。",
                              citations_used=[], claim_breakdown=[
                                  {"name": "已確定價金", "amount": 100, "basis": ["F1"], "formula": None, "item": "plaintiff:P1@S3"},
                                  {"name": "待確認額外費用", "amount": 200, "basis": ["F2"], "formula": None, "item": "plaintiff:P2@S3"}])
        stored = json.loads(row.claim_breakdown_json)
        assert stored["total"] == 100
        assert [p["name"] for p in stored["items"]] == ["已確定價金"]
        assert [p["name"] for p in stored["pending"]] == ["待確認額外費用"]
        assert "待確認額外費用：200" in row.draft_text.split("律師附註", 1)[1]
        assert "200" not in row.draft_text.split("律師附註", 1)[0]
        assert any("不同" in w for w in json.loads(row.warnings_json))
        assert any("程序別" in w for w in json.loads(row.warnings_json))
    finally:
        s.close()


@pytest.mark.parametrize("mutation", ["invalid_fact", "invalid_item", "no_basis_or_formula", "past_round"])
def test_p04_amount_breakdown_requires_current_supported_items(completed_case, mutation):
    part = {"name": "買賣價金", "amount": 100, "basis": ["F1"], "formula": None, "item": "plaintiff:P1@S3"}
    if mutation == "invalid_fact":
        part["basis"] = ["F999"]
    elif mutation == "invalid_item":
        part["item"] = "plaintiff:P999@S3"
    elif mutation == "no_basis_or_formula":
        part["basis"] = []
    else:
        part["item"] = "plaintiff:P1@S1"
    s = get_session(completed_case)
    try:
        with pytest.raises(ValueError):
            record_pleading(s, case_id=CASE["case_id"], draft_text="民事起訴狀", citations_used=[], claim_breakdown=[part])
        assert s.query(PleadingDraft).count() == 0
    finally:
        s.close()


def test_q03_existing_published_gate_cannot_borrow_another_cases_check(case_db):
    from database.db import record_case_citation_check, upsert_citation
    s = get_session(case_db)
    try:
        record_case(s, case_id="accept-c2", case_type="另一案", represented_side="plaintiff",
                    plaintiff_facts="另一案之原告交付機器，被告未給付價金。", claims="請求給付")
        upsert_citation(s, citation_text="民法第184條", source_type="statute", status="published")
        record_case_citation_check(s, CASE["case_id"], {"citation_text": "民法第184條", "status": "published", "reason": "本案已查現行條文"}, "independent-a")
        with pytest.raises(ValueError):
            record_pleading(s, case_id="accept-c2", draft_text="民事起訴狀", citations_used=["民法第184條"])
        record_case_citation_check(s, "accept-c2", {"citation_text": "民法第184條", "status": "published", "reason": "另一案個別查證"}, "independent-b")
        row = record_pleading(s, case_id="accept-c2", draft_text="民事起訴狀", citations_used=["民法第184條"])
        assert row.case_id == "accept-c2"
    finally:
        s.close()


def test_q07_historical_205_cannot_borrow_current_article_publication(case_db):
    from database.db import record_case_citation_check, upsert_citation
    from engine.verify import verify_citations
    s = get_session(case_db)
    try:
        upsert_citation(s, citation_text="民法第205條", source_type="statute", status="published")
        historical = verify_citations(["108年民法第205條"])[0]
        assert historical["status"] == "version_unverified"
        record_case_citation_check(s, CASE["case_id"], historical, "historical-check")
        with pytest.raises(ValueError):
            record_pleading(s, case_id=CASE["case_id"], draft_text="民事起訴狀", citations_used=["108年民法第205條"])
        assert s.query(PleadingDraft).count() == 0
    finally:
        s.close()


def test_q03_latest_case_failure_cannot_be_hidden_by_old_published_check(case_db):
    from database.db import record_case_citation_check
    s = get_session(case_db)
    try:
        record_case_citation_check(s, CASE["case_id"], {"citation_text": "民法第184條", "status": "published", "reason": "前次通過"}, "before")
        record_case_citation_check(s, CASE["case_id"], {"citation_text": "民法第184條第1項", "status": "network_error", "reason": "本次查證失敗"}, "after")
        with pytest.raises(ValueError):
            record_pleading(s, case_id=CASE["case_id"], draft_text="民事起訴狀", citations_used=["民法第184條"])
        assert s.query(PleadingDraft).count() == 0
    finally:
        s.close()


def test_q05_final_precedent_requires_separate_substantive_support(case_db):
    from database.db import record_case_citation_check
    from engine.verify import verify_precedent_note
    note = {"citation": "最高法院114年度台上字第1945號", "doc_date": "20260513", "doc_type": "判決",
            "case_cause": "請求確認本票債權不存在等", "quote": "最高法院民事判決",
            "proposition": "本案契約效力之法律判斷", "analogy_reason": None}
    mechanical = verify_precedent_note(note)
    assert mechanical["status"] == "published"
    s = get_session(case_db)
    try:
        mechanical["citation_text"] = note["citation"]
        record_case_citation_check(s, CASE["case_id"], mechanical, "mechanical-only")
        with pytest.raises(ValueError):
            record_pleading(s, case_id=CASE["case_id"], draft_text="民事起訴狀", citations_used=[note["citation"]])
        independent = {**mechanical, "supports_proposition": True,
                       "support_note": "獨立查證角色已核對：僅採該裁判關於撤銷前效力之命題。"}
        record_case_citation_check(s, CASE["case_id"], independent, "independent-support")
        row = record_pleading(s, case_id=CASE["case_id"], draft_text="民事起訴狀", citations_used=[note["citation"]])
        assert row.id is not None
    finally:
        s.close()


def test_a01_a04_mechanical_anchors_preserve_three_holders_and_status_reasons():
    from engine.aggregate import aggregate_role_items
    p = {"side": "plaintiff", "stage": 1, "items": [{"id": "P1", "label": "價金請求", "kind": "legal", "status": "asserted",
         "elements": [{"element": "成立", "state": "met", "source": "F1"}],
         "needs_from_client": [{"text": "詢問日期", "holder": "own_client"}, {"text": "調閱影像", "holder": "third_party"}]}],
         "cited_statutes": ["民法第125條第1項"], "cited_precedents": [],
         "internal_notes": {"update_conditions": "DO_NOT_PUBLISH_a6a1"}}
    d = {"side": "defendant", "stage": 1, "items": [
         {"id": "D1", "label": "若日期成立可主張時效，待確認", "kind": "factual_hypothesis", "status": "to_confirm",
          "elements": [{"element": "知悉日期待確認", "state": "unknown", "source": "F2"}], "needs_from_client": []},
         {"id": "D2", "label": "法律抗辯", "kind": "legal", "status": "asserted", "elements": [], "needs_from_client": []}],
         "defeat_conditions": [{"item": "defendant:D1", "condition": "若提出中斷時效證明則失效"}],
         "cited_statutes": [], "cited_precedents": ["最高法院114年度台上字第1945號判決"]}
    p3, d3 = copy.deepcopy(p), copy.deepcopy(d)
    p3["stage"], d3["stage"] = 3, 3
    p3["cited_statutes"] = ["民法第125條"]
    d3["cited_precedents"] = ["最高法院114年度台上字第1945號裁定"]
    d3["items"][1].update(status="withdrawn", withdraw_reason={"type": "opponent_defeats", "item_ids": ["plaintiff:P1@S3"]})
    result = aggregate_role_items([p, d, p3, d3], "plaintiff", questions=[
        {"id": 1, "target_side": "plaintiff", "question_type": "factual", "question_text": "有無交付證據？"}],
        prep_items=[{"id": "J-PREP-1", "hypothesis": "對方可能持有影像", "prepare": "準備調閱", "holder": "opponent", "affects": "plaintiff:P1", "is_hypothesis": True}])
    assert set(result["pending"]) == {"own_client", "opponent", "third_party"}
    assert [r["text"] for r in result["pending"]["own_client"]] == ["詢問日期", "有無交付證據？"]
    assert [r["text"] for r in result["pending"]["third_party"]] == ["調閱影像"]
    assert len(result["pending"]["opponent"]) == 3
    assert result["citation_set_change"] == {"plaintiff": 0.0, "defendant": 0.0}
    assert result["status_changes"] == [{"item": "defendant:D2", "from_stage": 1, "to_stage": 3,
           "from_status": "asserted", "to_status": "withdrawn", "withdraw_reason": {"type": "opponent_defeats", "item_ids": ["plaintiff:P1@S3"]}}]
    assert result["defeat_conditions"][0]["item"] == "defendant:D1"
    assert "DO_NOT_PUBLISH_a6a1" not in json.dumps(result, ensure_ascii=False)
    assert "weak_points" not in result and "position_drift" not in result
