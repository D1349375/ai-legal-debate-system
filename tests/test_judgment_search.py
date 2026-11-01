"""judgment_search 與 search-judgments 指令測試：FJUD 連線以假資料替代，不連網。"""
import argparse
import json
import os
import urllib.error

import pytest

import engine.fjud as fjud
import engine.judgment_search as js
import main

FULL_TEXT = """最高法院民事判決
111年度台上字第1069號
    主  文
原判決除假執行部分外廢棄，發回臺灣高等法院。
    理  由
被上訴人無債務不履行、侵權行為或締約上過
失，民法第245條之1定有明文。
"""


def row(jid, doc_type="判決"):
    return {"jid": jid, "citation": f"最高法院{jid}民事{doc_type}", "doc_type": doc_type, "size_kb": 9,
            "doc_date": jid.split(",")[4], "case_cause": "請求損害賠償", "snippet": "…締約上過失…", "url": "u"}


@pytest.fixture
def fake_fjud(monkeypatch):
    calls = {"search": [], "fetch": []}
    rows = [row("TPSV,111,台上,1069,20250716,1"), row("TPSV,110,台上,1010,20210317,1", "裁定"),
            row("TPSU,99,台上,982,20100527"), row("TPSV,112,台上,2536,20240124,1")]
    def search(keywords, **kwargs):
        calls["search"].append((keywords, kwargs))
        return {"total": 4, "page_count": 1, "pages_read": 1, "rows": [dict(r) for r in rows]}
    def fetch(jid, session=None, timeout=None):
        calls["fetch"].append(jid)
        if jid.startswith("TPSV,112"):
            raise urllib.error.URLError("timed out")
        return {"jid": jid, "url": "u", "full_text": FULL_TEXT, "case_cause": "請求損害賠償"}
    monkeypatch.setattr(fjud, "advanced_search", search)
    monkeypatch.setattr(fjud, "fetch_document", fetch)
    monkeypatch.setattr(js.judgment_text, "law_names", lambda: {"民法": "民法"})
    monkeypatch.setattr("engine.law_lookup.time.sleep", lambda seconds: None)
    return calls


def test_fetch_only_verifiable_judgments_and_keep_list_on_fetch_failure(fake_fjud):
    result = js.search_judgments(["締約上過失"], fetch=3)
    # 連線失敗重試一次
    assert fake_fjud["fetch"] == ["TPSV,111,台上,1069,20250716,1"] + ["TPSV,112,台上,2536,20240124,1"] * 2
    first, ruling, family, failed = result["rows"]
    assert first["fetched"] and first["statutes"] == ["民法第245條之1"]
    assert first["disposition"].startswith("原判決除假執行部分外廢棄")
    assert "締約上過失" in first["matched_sentences"][0]
    assert "fetched" not in ruling and family["verifiable"] is False and result["unverifiable"] == 1
    assert failed["fetch_error"].startswith("連線失敗")


def test_include_rulings_fetches_rulings_too(fake_fjud):
    js.search_judgments(["締約上過失"], fetch=2, include_rulings=True)
    assert fake_fjud["fetch"] == ["TPSV,111,台上,1069,20250716,1", "TPSV,110,台上,1010,20210317,1"]


def test_save_dir_keeps_query_results_and_raw_text(fake_fjud, tmp_path):
    result = js.search_judgments(["締約上過失"], fetch=1, save_dir=str(tmp_path))
    with open(result["saved_to"], encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["query"]["keywords"] == ["締約上過失"] and saved["saved_to"] == result["saved_to"]
    assert open(os.path.join(tmp_path, "TPSV,111,台上,1069,20250716,1.txt"), encoding="utf-8").read() == FULL_TEXT


@pytest.mark.parametrize("kwargs,message", [
    ({"keywords": [" "]}, "至少要有一個關鍵字或案由"),
    ({"keywords": ["x"], "pages": 6}, "頁數"),
    ({"keywords": ["x"], "fetch": 11}, "全文份數"),
    ({"keywords": ["x"], "date_from": "2021/01/01"}, "起始日期"),
])
def test_invalid_requests_are_rejected_before_connecting(fake_fjud, kwargs, message):
    with pytest.raises(ValueError, match=message):
        js.search_judgments(**kwargs)
    assert fake_fjud["search"] == []


def args(**overrides):
    base = dict(kw=["締約上過失"], title=None, date_from=None, date_to=None, pages=1, fetch=1,
                include_rulings=False, min_size=None, sort="date", save_dir=None, json=False)
    return argparse.Namespace(**{**base, **overrides})


def test_size_sort_is_passed_to_fjud_and_invalid_sort_rejected(fake_fjud):
    js.search_judgments(["締約上過失"], sort="size")
    assert fake_fjud["search"][-1][1]["sort"] == fjud.SORT_SIZE
    with pytest.raises(ValueError, match="排序"):
        js.search_judgments(["締約上過失"], sort="relevance")


def test_cli_suggests_narrowing_when_date_sorted_results_are_many(fake_fjud, monkeypatch, capsys):
    original = fjud.advanced_search
    monkeypatch.setattr(fjud, "advanced_search", lambda kw, **k: {**original(kw, **k), "total": 6239})
    main.cmd_search_judgments(args(fetch=0))
    assert "建議加要件詞縮小範圍" in capsys.readouterr().out


def test_cli_text_output_marks_unverifiable_and_shows_fetched_details(fake_fjud, capsys):
    assert main.cmd_search_judgments(args()) == 0
    out = capsys.readouterr().out
    assert "共 4 筆" in out and "1 筆不是最高法院民事字號" in out and "不可引用" in out
    assert "實體法條：民法第245條之1" in out and "命中：" in out


def test_cli_network_failure_is_not_reported_as_no_result(monkeypatch, capsys):
    def down(*a, **k):
        raise urllib.error.URLError("unreachable")
    monkeypatch.setattr(fjud, "advanced_search", down)
    monkeypatch.setattr("engine.law_lookup.time.sleep", lambda seconds: None)
    assert main.cmd_search_judgments(args()) == 1
    assert "不代表查無判決" in capsys.readouterr().err


def test_fetched_texts_go_to_cache_and_are_not_fetched_again(fake_fjud, tmp_path):
    snapshot = tmp_path / "snapshot"
    js.search_judgments(["締約上過失"], fetch=1, snapshot=str(snapshot))
    again = js.search_judgments(["締約上過失"], fetch=1)
    assert fake_fjud["fetch"] == ["TPSV,111,台上,1069,20250716,1"]
    assert again["rows"][0]["served_from"] == "retrieval_cache"
    assert (snapshot / "judgments" / "TPSV,111,台上,1069,20250716,1.json").is_file()


def test_live_fetch_budget_skips_uncached_texts_but_keeps_list(fake_fjud):
    result = js.search_judgments(["締約上過失"], fetch=3, max_live_fetches=0)
    assert fake_fjud["fetch"] == []
    assert len(result["rows"]) == 4 and "已達本階段全文預算" in result["rows"][0]["fetch_error"]
