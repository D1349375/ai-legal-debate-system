"""retrieval-rules 指令：各階段的檢索規則(調度員填範本的 {RETRIEVAL_RULES})。不連網。"""
import argparse
import json

import pytest

import main
from engine import retrieval_rules
from engine.search_log import PHASE_ALIASES, PHASES, phase_of

SEARCH_PHASES = sorted(PHASES)
NO_SEARCH_PHASES = sorted(retrieval_rules.NO_SEARCH)


def rules_args(phase, side=None, case_dir=None, json_output=False, exclude=None):
    return argparse.Namespace(phase=phase, side=side, case_dir=case_dir, json=json_output, exclude=exclude)


@pytest.mark.parametrize("phase", SEARCH_PHASES + NO_SEARCH_PHASES)
def test_every_phase_prints_rules(phase, capsys):
    assert main.cmd_retrieval_rules(rules_args(phase)) == 0
    text = capsys.readouterr().out
    assert text.startswith("檢索規則：") and "judgment" in text and "WebFetch" in text
    # 輸出會貼進範本；範本之後可能再經 str.format，不能有大括號
    assert "{" not in text and "}" not in text


@pytest.mark.parametrize("phase", SEARCH_PHASES)
def test_budget_numbers_come_from_search_log(phase):
    r = retrieval_rules.build(phase)
    label, searches, fetches = PHASES[phase]
    assert r["searches"] and r["budget"] == {"searches": searches, "fetches": fetches}
    assert f"search-judgments 最多 {searches} 次" in r["text"] and f"上網抓判決全文最多 {fetches} 份" in r["text"]
    assert label in r["text"] and "retrieval_unavailable" in r["text"] and "full_text_unavailable" in r["text"]


@pytest.mark.parametrize("phase", NO_SEARCH_PHASES)
def test_judge_and_verifier_do_not_search(phase):
    r = retrieval_rules.build(phase)
    assert not r["searches"] and r["budget"] is None
    assert "不搜尋" in r["text"] and "python main.py search-judgments" not in r["text"] and "<紀錄檔>" not in r["text"]


def test_verifier_reads_the_case_snapshot_root():
    r = retrieval_rules.build("verify", case_dir="database/live_runs/case-7")
    assert r["case_snapshot"] == "database/live_runs/case-7/retrieval_cache"
    assert "python main.py verify <引用...> --snapshot database/live_runs/case-7/retrieval_cache" in r["text"]


@pytest.mark.parametrize("alias", sorted(PHASE_ALIASES))
def test_aliases_give_the_same_rules_as_the_phase_code(alias):
    assert retrieval_rules.build(alias)["text"] == retrieval_rules.build(PHASE_ALIASES[alias])["text"]


def test_unknown_phase_is_an_error_listing_the_names(capsys):
    assert main.cmd_retrieval_rules(rules_args("p9")) == 2
    err = capsys.readouterr().err
    assert "未知階段：p9" in err and all(name in err for name in ("p1", "p3", "p6", "verify", "complaint"))


def test_side_and_case_dir_print_paths_whose_file_name_sets_the_budget(capsys):
    assert main.cmd_retrieval_rules(rules_args("answer", side="defendant", case_dir="database\\live_runs\\case-7\\",
                                               json_output=True)) == 0
    r = json.loads(capsys.readouterr().out)
    assert r["snapshot"] == "database/live_runs/case-7/retrieval_cache/defendant"
    assert r["log"] == "database/live_runs/case-7/search_logs/defendant_p2.jsonl"  # 劇本與答辯狀共用一檔
    assert phase_of(r["log"]) == "p2" and r["case_snapshot"] == "database/live_runs/case-7/retrieval_cache"
    assert f"--snapshot {r['snapshot']} --log {r['log']}" in r["text"] and "<紀錄檔>" not in r["text"]
    assert "plaintiff" not in r["text"]  # 不把對造的路徑給角色


def test_without_case_dir_paths_are_named_not_invented():
    text = retrieval_rules.build("p4")["text"]
    assert "--snapshot <快照資料夾> --log <紀錄檔> --issue <爭點id>" in text


def test_phase_and_side_must_match(capsys):
    assert main.cmd_retrieval_rules(rules_args("p1", side="defendant")) == 2
    assert "由原告檢索" in capsys.readouterr().err
    assert main.cmd_retrieval_rules(rules_args("p4", case_dir="database/live_runs/case-7")) == 2
    assert "--side" in capsys.readouterr().err


def test_source_judgment_exclusion_is_carried_into_judgment_commands():
    exclude = ["最高法院 111年度台上字第1069號", "TPSV,105,台簡上,33,20161026"]
    flags = "--exclude 105年度台簡上字第33號 --exclude 111年度台上字第1069號"
    for phase in ("p1", "p4", "p3"):
        r = retrieval_rules.build(phase, exclude=exclude)
        judgment_lines = [line for line in r["text"].splitlines()
                          if "main.py search-judgments" in line or "main.py judgment" in line]
        assert judgment_lines and all(flags in line for line in judgment_lines)
        assert "main.py article" in r["text"] and "--exclude" not in next(
            line for line in r["text"].splitlines() if "main.py article" in line)
    # 獨立查證不排除：角色若憑記憶引用了來源裁判，查證仍要能查
    assert retrieval_rules.build("verify", exclude=exclude)["exclude"] == []
    assert "--exclude" not in retrieval_rules.build("verify", exclude=exclude)["text"]


def test_unparseable_exclusion_is_rejected(capsys):
    assert main.cmd_retrieval_rules(rules_args("p1", exclude=["原案判決"])) == 2
    assert "--exclude 須為裁判字號" in capsys.readouterr().err


def test_rules_keep_the_agreed_legal_wording():
    p5 = retrieval_rules.build("p5")["text"]
    assert "不是法律禁止引用新法條" in p5
    assert "第255條" in retrieval_rules.build("p4")["text"]
    assert "第199條之1" in retrieval_rules.build("p6")["text"]
    assert "不是把侵權行為當保底" in retrieval_rules.build("p1")["text"]


def test_p1_rules_fit_analysis_then_complaint():
    # P1 先分析再撰狀：分析時還沒有起訴狀，也沒有 internal_analysis 這個欄位
    p1 = retrieval_rules.build("p1")["text"]
    assert "internal_analysis" not in p1 and "起訴狀選定" not in p1
    assert "分析與撰狀共用同一個紀錄檔與預算" in p1
    assert "不打算主張的候選請求權基礎只用 article 讀條文" in p1
    # 每個 subagent 各自讀進上下文：分析讀了全文也交不出摘句，撰狀還要重讀。讀全文只留給撰狀
    assert "分析只搜不讀全文" in p1 and "撰狀用 judgment 讀要引用的判決全文" in p1


def test_search_phases_explain_how_to_use_old_precedents():
    for phase in ("p1", "p2", "p4", "p5"):
        text = retrieval_rules.build(phase)["text"]
        assert "search-judgments --kw 73年台上字第1173號" in text and "precedent_leads" in text
    # 法官不搜尋，只知道舊裁判沒有全文
    p3 = retrieval_rules.build("p3")["text"]
    assert "民國85年以前的裁判一律沒有全文" in p3 and "search-judgments --kw 73年" not in p3
