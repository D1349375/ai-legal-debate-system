"""起訴前檢查:只提示、不下結論、不阻擋。"""
import datetime

import pytest

from engine.precheck import precheck

CONCLUSIONS = ("已罹於", "已消滅", "時效已完成", "應駁回", "應適用", "一定", "勝訴", "敗訴")


def codes(result):
    return {w["code"] for w in result["warnings"]}


def texts(result):
    return " ".join(w["message"] for w in result["warnings"])


@pytest.mark.parametrize("amount,expected", [
    (None, "待確認"), (100000, "可能小額"), (100001, "可能簡易"), (500000, "可能簡易"), (500001, "依金額屬通常程序範圍"),
])
def test_procedure_type_by_amount(amount, expected):
    r = precheck("買賣價金", "被告應給付原告價金", amount)
    assert r["procedure"]["type"] == expected
    assert "價額由法院核定" in r["procedure"]["message"]


def test_non_money_claim_under_100k_is_not_small_claim():
    r = precheck("確認僱傭關係", "確認兩造間僱傭關係存在", 80000)
    assert r["procedure"]["type"] == "可能簡易"
    assert "第436條之8" not in " ".join(r["procedure"]["legal_basis"])


def test_small_claim_message_states_its_limit():
    r = precheck("買賣價金", "被告應給付原告新臺幣5萬元", 50000)
    assert "金錢、代替物或有價證券" in r["procedure"]["message"]


def test_traffic_accident_flags_mediation_and_summary_procedure():
    r = precheck("車禍損害賠償", "被告應賠償原告", 900000)
    assert "民事訴訟法第403條第1項第7款" in [b for w in r["warnings"] for b in w["legal_basis"]]
    assert "民事訴訟法第427條第2項第11款" in [b for w in r["warnings"] for b in w["legal_basis"]]
    assert "第424條" in texts(r)


def test_property_claim_under_500k_flags_mediation_item_11():
    r = precheck("買賣價金", "被告應給付原告新臺幣30萬元", 300000)
    assert "民事訴訟法第403條第1項第11款" in [b for w in r["warnings"] for b in w["legal_basis"]]
    r = precheck("買賣價金", "被告應給付原告新臺幣60萬元", 600000)
    assert "民事訴訟法第403條第1項第11款" not in [b for w in r["warnings"] for b in w["legal_basis"]]


@pytest.mark.parametrize("case_type,basis", [
    ("返還借款", "民法第125條"), ("車禍損害賠償", "民法第197條"), ("買賣價金", "民法第127條第8款"), ("工程款", "民法第127條第7款"),
])
def test_prescription_hint_cites_candidate_article(case_type, basis):
    r = precheck(case_type, "請求", None)
    hint = next(w for w in r["warnings"] if w["code"] == "prescription")
    assert basis in hint["legal_basis"] and "可能涉及時效，請律師確認" in hint["message"]


def test_prescription_hint_uses_earliest_date_without_concluding():
    today = datetime.date(2026, 11, 1)
    evidence = [{"id": "甲證1", "description": "匯款單", "date": "2023-03-01"},
                {"id": "甲證2", "description": "對話", "date": "2010-01-15"},
                {"id": "甲證3", "description": "無日期", "date": None}]
    r = precheck("車禍損害賠償", "請求", None, evidence, today=today)
    hint = next(w for w in r["warnings"] if w["code"] == "prescription")
    assert "2010-01-15" in hint["message"] and "16.8 年" in hint["message"]
    assert not any(word in hint["message"] for word in CONCLUSIONS)


def test_no_warning_concludes_anything():
    r = precheck("車禍損害賠償", "被告應賠償原告", 80000,
                 [{"id": "甲證1", "description": "估價單", "date": "2000-01-01"}], today=datetime.date(2026, 11, 1))
    joined = texts(r) + r["procedure"]["message"]
    assert not any(word in joined for word in CONCLUSIONS)


def test_labor_case_points_to_other_law_without_judging():
    assert "labor" in codes(precheck("勞資爭議", "確認僱傭關係存在", None))
    assert "labor" not in codes(precheck("買賣價金", "給付價金", None))


def test_missing_evidence_warns_but_listed_evidence_does_not():
    assert "no_evidence" in codes(precheck("買賣價金", "給付價金", None))
    assert "no_evidence" not in codes(precheck("買賣價金", "給付價金", None, [{"id": "甲證1", "description": "契約"}]))


def test_unparseable_evidence_date_is_ignored():
    r = precheck("返還借款", "返還", None, [{"id": "甲證1", "description": "借據", "date": "去年春天"}])
    assert "最早日期" not in next(w for w in r["warnings"] if w["code"] == "prescription")["message"]


def test_result_says_it_is_only_a_hint():
    assert "只提示" in precheck("買賣價金", "給付價金", None)["note"]
