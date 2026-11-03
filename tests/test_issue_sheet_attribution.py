"""W5-7:T10 的轉述核對也要接在 v2 的 `issue-sheet`(原本只接 check-judge、record、verdict)。

法官在爭點整理表裡用引號轉述某一方的話,原句卻只在另一方的書狀裡(或兩方都沒有)時,印「轉述警告」;
只警告,不擋落地、不退回法官。沿用 tests/test_issue_sheet.py 的 v2 案件(起訴狀 + 模擬答辯狀)。
"""
import copy

from database.db import get_session, issue_sheet
from tests.test_issue_sheet import db_url, run, sheet  # noqa: F401  (db_url 是 fixture)


def test_quote_from_the_other_side_warns_but_lands(db_url, tmp_path):  # noqa: F811
    value = copy.deepcopy(sheet())
    # 「兩造約定三個月內返還」是原告起訴狀的話,法官說成被告講的
    value["issues"][0]["defendant_defense"] = "被告稱「兩造約定三個月內返還」,惟否認借貸"
    r = run(db_url, tmp_path, value)
    assert r.returncode == 0, r.stderr
    assert "轉述警告" in r.stderr and "other_side" in r.stderr
    assert issue_sheet(get_session(db_url), "v2") is not None


def test_question_quotes_use_the_target_side(db_url, tmp_path):  # noqa: F811
    value = copy.deepcopy(sheet())
    value["questions"][0]["question_text"] = "你方稱「兩造當場簽立借據」,有無證據?"  # 兩方書狀都沒有這句
    r = run(db_url, tmp_path, value, "--check")
    assert r.returncode == 0, r.stderr
    assert "轉述警告" in r.stderr and "missing" in r.stderr


def test_exact_quotes_print_no_warning(db_url, tmp_path):  # noqa: F811
    value = copy.deepcopy(sheet())
    value["issues"][0]["plaintiff_claim"] = "原告稱「兩造約定三個月內返還」"
    r = run(db_url, tmp_path, value)
    assert r.returncode == 0, r.stderr
    assert "轉述警告" not in r.stderr
