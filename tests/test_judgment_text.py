"""judgment_text 測試：純本機，部分用 repo 內的本地判決語料當真實樣本。"""
import glob
import re

import pytest

from engine import judgment_text as jt

NAMES = {"民法": "民法", "民事訴訟法": "民事訴訟法", "勞動基準法": "勞動基準法", "勞基法": "勞動基準法",
         "中華民國刑法": "中華民國刑法", "刑法": "刑法"}
RULING = """最高法院民事裁定
115年度台上字第1號
上  訴  人  甲
上列當事人間請求損害賠償事件，上訴人對於中華民國114年1月1日臺灣高等法院第二審判決，提起上訴，本院裁定如下：
    主  文
上訴人之上訴均駁回。
第三審訴訟費用由上訴人負擔。
    理  由
按上訴第三審法院，非以原判決違背法令為理由，不得為之，民事訴訟法第467條、第469條之1定有明文。
"""
JUDGMENT = """最高法院民事判決
115年度台上字第521號
    主  文
原判決除假執行部分外廢棄，發回臺灣高等法院高雄分院。
    理  由
上訴人依民法第184條第1項前段、同法第197條第2項規定請求，惟民法第197條第1項所稱「自請求權人知有損
害時起」之主觀要件，應以請求權人實際知悉損害為準。另依勞基法第11條及中華民國刑法第339條。
"""


def test_flatten_only_removes_whitespace_and_breaks_after_full_stops():
    flat = jt.flatten(JUDGMENT)
    assert re.sub(r"\s", "", flat) == re.sub(r"\s", "", JUDGMENT)
    assert "自請求權人知有損害時起" in flat
    assert all(line.endswith("。") for line in flat.splitlines()[:-1])


def test_disposition_and_procedural_ruling():
    assert jt.document_type(RULING) == "裁定"
    assert jt.disposition(RULING) == "上訴人之上訴均駁回。"
    assert jt.summarize(RULING, names=NAMES)["procedural_only"] is True


def test_remanding_judgment_is_not_procedural():
    summary = jt.summarize(JUDGMENT, names=NAMES)
    assert summary["doc_type"] == "判決"
    assert summary["disposition"] == "原判決除假執行部分外廢棄，發回臺灣高等法院高雄分院。"
    assert summary["procedural_only"] is False


@pytest.mark.parametrize("main,expected", [
    ("上訴駁回。", True), ("兩造上訴均駁回。", True), ("上訴及擴張之訴均駁回。", True),
    ("再抗告駁回。", True), ("原裁定廢棄。", False), ("本件移送於臺灣高等法院。", False),
])
def test_procedural_disposition_variants(main, expected):
    assert jt.is_procedural("裁定", main) is expected
    assert jt.is_procedural("判決", main) is False


def test_cited_statutes_resolves_same_law_aliases_and_boilerplate():
    substantive, boilerplate = jt.cited_statutes(JUDGMENT + RULING, NAMES)
    assert substantive == ["民法第184條", "民法第197條", "勞動基準法第11條", "中華民國刑法第339條"]
    assert boilerplate == ["民事訴訟法第467條", "民事訴訟法第469條之1"]


def test_defined_short_name_and_unknown_law_do_not_leak_into_same_law():
    text = ("依民法第184條請求。爰依104年2月4日修正前公平交易法（下稱修正前公平法）第31條、第32條請求，"
            "並無同法第19條第6款情形；修正前公平法第7條定有明文。又依某某自治規約第5條，及同法第9條。")
    names = dict(NAMES, 公平交易法="公平交易法")
    substantive, _ = jt.cited_statutes(text, names)
    assert substantive == ["民法第184條", "公平交易法第31條", "公平交易法第32條", "公平交易法第19條", "公平交易法第7條"]


def test_matched_sentences_finds_phrase_split_by_line_wrap():
    sentences = jt.matched_sentences(JUDGMENT, ["知有損害"])
    assert len(sentences) == 1 and "自請求權人知有損害時起" in sentences[0]
    assert jt.matched_sentences(JUDGMENT, [" "]) == []


def test_local_corpus_flatten_keeps_every_character():
    files = sorted(glob.glob("corpus/judgments/*.txt"))
    assert len(files) > 1000
    for path in files:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        assert re.sub(r"\s", "", jt.flatten(text)) == re.sub(r"\s", "", text), path


def test_real_law_names_map_engine_alias_to_official_name():
    names = jt.law_names()
    assert names["勞基法"] == "勞動基準法" and names["民法"] == "民法"
