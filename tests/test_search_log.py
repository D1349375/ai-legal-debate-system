"""檢索紀錄(--log)、每輪查詢預算與 judgment 讀全文指令。FJUD 以假資料替代，不連網。"""
import argparse
import json

import pytest

import main
from engine import fjud, judgment_search, law_lookup
from engine.search_log import PHASES, BudgetExceeded, SearchLog

STAGE2 = {"searches": PHASES["stage2"][1], "fetches": PHASES["stage2"][2]}

TEXT = "最高法院民事判決\n主文\n上訴駁回。\n理由\n按締約上過失責任，以契約未成立為前提。"


@pytest.fixture
def fake_fjud(monkeypatch):
    calls = {"search": 0, "fetch": []}
    jids = [f"TPSV,11{i},台上,{100 + i},2025010{i},1" for i in range(1, 8)]

    def search(keywords=(), citation=None, **kwargs):
        calls["search"] += 1
        if citation:
            return {"total": 1, "page_count": 1, "pages_read": 1,
                    "rows": [{"jid": j} for j in jids if j.split(",")[1:4] == list(citation)]}
        rows = [{"jid": j, "citation": j, "doc_type": "判決", "size_kb": 9, "doc_date": j.split(",")[4],
                 "case_cause": "損害賠償", "snippet": "…", "url": "u"} for j in jids]
        return {"total": len(rows), "page_count": 1, "pages_read": 1, "rows": rows}

    def fetch(jid, timeout=None, session=None):
        calls["fetch"].append(jid)
        return {"jid": jid, "url": fjud.document_url(jid), "full_text": TEXT, "case_cause": "損害賠償"}
    monkeypatch.setattr(fjud, "advanced_search", search)
    monkeypatch.setattr(fjud, "fetch_document", fetch)
    monkeypatch.setattr(judgment_search.judgment_text, "law_names", lambda: {"民法": "民法"})
    monkeypatch.setattr(law_lookup.time, "sleep", lambda seconds: None)
    return calls, jids


def search_args(log, fetch=0, **overrides):
    base = dict(kw=["締約上過失"], title=None, date_from=None, date_to=None, pages=1, fetch=fetch,
                include_rulings=False, min_size=None, sort="date", save_dir=None, json=False, snapshot=None, log=log,
                issue=None, exclude=None)
    return argparse.Namespace(**{**base, **overrides})


def judgment_args(target, log=None, doc_date=None, snapshot=None, issue=None, exclude=None):
    return argparse.Namespace(target=target, doc_date=doc_date, json=False, snapshot=snapshot, log=log, issue=issue,
                              exclude=exclude)


def entries(path):
    return [json.loads(line) for line in open(path, encoding="utf-8")]


@pytest.mark.parametrize("name,phase,searches,fetches", [
    ("plaintiff_p1.jsonl", "p1", 8, 10),
    ("defendant_p2.jsonl", "p2", 8, 10),
    ("defendant-answer.jsonl", "p2", 8, 10),
    ("plaintiff_p4.jsonl", "p4", 4, 5),
    ("defendant_closing.jsonl", "p5", 2, 3),
    ("plaintiff_stage1.jsonl", "stage1", 8, 10),
    ("defendant-stage3.jsonl", "stage3", 4, 5),
    ("search.jsonl", None, 4, 5),
    ("plaintiff_p3.jsonl", None, 4, 5),  # 法官階段不檢索，沒有自己的預算
])
def test_phase_and_budget_come_from_file_name(tmp_path, name, phase, searches, fetches):
    log = SearchLog(str(tmp_path / name))
    assert log.phase == phase and log.budget == {"searches": searches, "fetches": fetches}


def test_side_name_is_not_mistaken_for_a_phase(tmp_path):
    assert SearchLog(str(tmp_path / "plaintiff.jsonl")).phase is None


def test_search_budget_is_enforced_by_the_command(fake_fjud, tmp_path, capsys):
    path = str(tmp_path / "plaintiff_stage2.jsonl")
    for _ in range(STAGE2["searches"]):
        assert main.cmd_search_judgments(search_args(path)) == 0
    assert main.cmd_search_judgments(search_args(path)) == 1
    assert "已達本階段搜尋預算" in capsys.readouterr().err
    statuses = [e["status"] for e in entries(path)]
    assert statuses == ["found"] * 4 + ["budget_exceeded"] and fake_fjud[0]["search"] == 4


def test_only_live_judgment_fetches_count_toward_fetch_budget(fake_fjud, tmp_path, capsys):
    calls, jids = fake_fjud
    path = str(tmp_path / "plaintiff_stage2.jsonl")
    assert main.cmd_search_judgments(search_args(path, fetch=3)) == 0
    assert SearchLog(path).fetches_used == 3
    # 已在快取的三份不計入；預算剩 2 份，第六、七份不抓
    assert main.cmd_search_judgments(search_args(path, fetch=7)) == 0
    log = SearchLog(path)
    assert log.fetches_used == 5 and len(calls["fetch"]) == 5
    assert "上網抓全文 5/5 份" in capsys.readouterr().out


def test_judgment_reads_cached_text_after_budget_but_refuses_new_fetch(fake_fjud, tmp_path, capsys):
    calls, jids = fake_fjud
    path = str(tmp_path / "defendant_stage3.jsonl")
    assert main.cmd_search_judgments(search_args(path, fetch=5)) == 0
    assert main.cmd_judgment(judgment_args(jids[0], log=path)) == 0
    out = capsys.readouterr().out
    assert "來源：長期快取" in out and "按締約上過失責任，以契約未成立為前提。" in out
    assert main.cmd_judgment(judgment_args(jids[6], log=path)) == 1
    assert "已達本階段全文預算" in capsys.readouterr().err
    assert entries(path)[-1]["status"] == "budget_exceeded" and len(calls["fetch"]) == 5


def test_judgment_by_citation_requires_date_when_ambiguous(fake_fjud, capsys):
    assert main.cmd_judgment(judgment_args("最高法院114年度台上字第1945號")) == 2
    assert "請加 --doc-date" in capsys.readouterr().err
    assert main.cmd_judgment(judgment_args("114年度台上字第1945號", doc_date="20260513")) == 0
    out = capsys.readouterr().out
    assert "來源：預先內容" in out and "請求確認本票債權不存在等" in out
    assert fake_fjud[0]["fetch"] == []


def test_judgment_by_citation_outside_corpus_goes_online_once(fake_fjud, tmp_path, capsys):
    calls, jids = fake_fjud
    snapshot = str(tmp_path / "snap")
    assert main.cmd_judgment(judgment_args("111年度台上字第101號", snapshot=snapshot)) == 0
    assert main.cmd_judgment(judgment_args("111年度台上字第101號", snapshot=snapshot)) == 0
    assert "來源：本次實跑快照" in capsys.readouterr().out
    assert calls["fetch"] == [jids[0]] and calls["search"] == 1


def test_judgment_offline_without_cache_says_not_a_missing_judgment(monkeypatch, tmp_path, capsys):
    import urllib.error

    def down(*a, **k):
        raise urllib.error.URLError("offline")
    monkeypatch.setattr(fjud, "advanced_search", down)
    monkeypatch.setattr(law_lookup.time, "sleep", lambda seconds: None)
    path = str(tmp_path / "plaintiff_stage1.jsonl")
    assert main.cmd_judgment(judgment_args("111年度台上字第101號", log=path)) == 1
    assert "不代表查無資料" in capsys.readouterr().err
    assert entries(path)[-1]["status"] == "retrieval_unavailable"


def test_unreadable_judgment_page_is_its_own_status(fake_fjud, monkeypatch, tmp_path, capsys):
    calls, jids = fake_fjud
    monkeypatch.setattr(fjud, "fetch_document", lambda jid, timeout=None, session=None: {
        "jid": jid, "url": fjud.document_url(jid), "full_text": "", "case_cause": "損害賠償"})
    path = str(tmp_path / "plaintiff_p1.jsonl")
    assert main.cmd_judgment(judgment_args(jids[0], log=path)) == 1
    err = capsys.readouterr().err
    assert err.startswith("full_text_unavailable") and "不代表引用寫錯" in err
    assert entries(path)[-1]["status"] == "full_text_unavailable" and SearchLog(path).fetches_used == 0
    rows = judgment_search.search_judgments(["締約上過失"], fetch=1)["rows"]
    assert rows[0]["fetch_error"].startswith("full_text_unavailable") and not rows[0].get("fetched")


def test_source_judgment_is_left_out_of_search_results(fake_fjud, tmp_path, capsys):
    """示範案改編自真實判決：來源裁判不出現在列表、不抓全文；字號與 JID 都可指定，不分文件日期。"""
    calls, jids = fake_fjud
    path = str(tmp_path / "plaintiff_p1.jsonl")
    args = search_args(path, fetch=3, exclude=["最高法院111年度台上字第101號", jids[1]])
    assert main.cmd_search_judgments(args) == 0
    out = capsys.readouterr().out
    assert "111年度台上字第101號" not in out and jids[0] not in out and jids[1] not in out
    assert calls["fetch"] == jids[2:5]
    logged = entries(path)[-1]
    assert logged["query"]["exclude"] == ["最高法院111年度台上字第101號", jids[1]]
    assert judgment_search.search_judgments(["締約上過失"], exclude=[jids[0]])["excluded"] == 1


def test_excluded_judgment_cannot_be_read_by_citation_or_jid(fake_fjud, tmp_path, capsys):
    calls, jids = fake_fjud
    path = str(tmp_path / "defendant_p2.jsonl")
    for target in ("111年度台上字第101號", "TPSV,111,台上,101,20990101"):
        assert main.cmd_judgment(judgment_args(target, log=path, exclude=[jids[0]])) == 1
        assert capsys.readouterr().err.startswith("excluded")
    assert calls == {"search": 0, "fetch": []}  # 連字號查詢都不做
    assert [e["status"] for e in entries(path)] == ["excluded", "excluded"]
    assert main.cmd_judgment(judgment_args(jids[2], log=path, exclude=[jids[0]])) == 0


def test_unparseable_exclusion_is_a_usage_error(fake_fjud, capsys):
    assert main.cmd_search_judgments(search_args(None, exclude=["原案判決"])) == 2
    assert main.cmd_judgment(judgment_args("111年度台上字第101號", exclude=["原案判決"])) == 2
    assert "--exclude 須為裁判字號" in capsys.readouterr().err
    assert fake_fjud[0] == {"search": 0, "fetch": []}


def test_statute_reads_are_logged_but_not_counted(tmp_path):
    log = SearchLog(str(tmp_path / "plaintiff_stage1.jsonl"))
    log.append("article", {"law_name": "民法", "article_no": "184"}, "found",
               fetched=[{"key": "B0000001_184", "kind": "statute", "served_from": "live"}])
    log.append("search-statutes", {"keyword": "知有損害"}, "found", hits=3)
    assert log.fetches_used == 0 and log.searches_used == 0
    with pytest.raises(BudgetExceeded):
        for _ in range(PHASES["stage1"][1] + 1):
            log.check_search()
            log.append("search-judgments", {}, "found", counts_as_search=True)


def test_issue_id_is_recorded_for_search_and_judgment(fake_fjud, tmp_path):
    calls, jids = fake_fjud
    path = str(tmp_path / "plaintiff_p4.jsonl")
    assert main.cmd_search_judgments(search_args(path, fetch=1, issue="I2")) == 0
    assert main.cmd_judgment(judgment_args(jids[0], log=path, issue="I2")) == 0
    logged = entries(path)
    assert [e["issue"] for e in logged] == ["I2", "I2"] and {e["phase"] for e in logged} == {"p4"}


def test_shared_statutes_across_fetched_judgments_are_listed(fake_fjud, monkeypatch, capsys):
    statutes = iter([["民法第184條", "民法第191條之2", "民法第195條"], ["民法第184條", "民法第195條"],
                     ["民法第184條", "民法第217條"]])
    original = judgment_search.judgment_text.summarize
    monkeypatch.setattr(judgment_search.judgment_text, "summarize",
                        lambda text, kw, names: {**original(text, kw, names), "statutes": next(statutes)})
    result = judgment_search.search_judgments(["車禍"], fetch=3)
    assert result["statute_counts"][:2] == [{"statute": "民法第184條", "judgments": 3},
                                             {"statute": "民法第195條", "judgments": 2}]
    monkeypatch.setattr(judgment_search, "search_judgments", lambda *a, **k: result)
    assert main.cmd_search_judgments(search_args(None)) == 0
    out = capsys.readouterr().out
    assert "常一起引用的實體法條" in out and "民法第184條（3 份）、民法第195條（2 份）" in out
    assert "民法第217條（1 份）" not in out  # 只出現在一份判決的不列
