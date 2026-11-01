"""law_lookup 測試：官網頁面以假 HTML 或 tests/fixtures/law/ 的存檔片段代替；另核對 repo 內索引檔與查證引擎的
pcode 一致。network 類別實際連線全國法規資料庫。"""
import os
import ssl

import pytest

import engine.law_lookup as law_lookup
from engine.verify import STATUTE_PCODES

INDEX = {
    "民法": {"pcode": "B0000001", "level": "法律", "abandoned": False, "modified_date": "20260817"},
    "勞動基準法": {"pcode": "N0030001", "level": "法律", "abandoned": False, "modified_date": "20240731"},
    "勞動基準法施行細則": {"pcode": "N0030002", "level": "命令", "abandoned": False, "modified_date": "20240327"},
    "動員戡亂時期臨時條款": {"pcode": "A0000002", "level": "憲法", "abandoned": True, "modified_date": "19720323"},
}
ARTICLE_PAGE = ('<html><div class="law-reg-content"><div class="law-article"><div class="line-0000">'
                '受設立許可法人之董事或監察人…</div></div><div class="clearfix"></div></div></html>')
ABANDONED_PAGE = ('<html><div class="law-reg-content"><div class="col-data"><div class="text-pre">一、總統在動員戡亂時期，'
                  '為避免國家\n    或人民遭遇緊急危難</div></div><div class="clearfix"></div></div></html>')
SHELL_PAGE = '<html><footer>全國法規資料庫</footer></html>'


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(law_lookup.time, "sleep", lambda seconds: None)


def pages(monkeypatch, *responses):
    calls = []
    def fetch(pcode, article_no, timeout):
        calls.append((pcode, article_no))
        return responses[min(len(calls), len(responses)) - 1], "u"
    monkeypatch.setattr(law_lookup, "_fetch_article_page", fetch)
    return calls


@pytest.mark.parametrize("text,expected", [
    ("33", "33"), ("第33條", "33"), ("191之2", "191-2"), ("191-2", "191-2"),
    ("第191條之2", "191-2"), (" 第 191 條 之 2 ", "191-2"), ("三十三", None), ("33a", None),
])
def test_normalize_article_no(text, expected):
    assert law_lookup.normalize_article_no(text) == expected


@pytest.mark.parametrize("parts,expected", [
    (["民法", "33"], ("民法", "33")),
    (["民法", "第191條之2"], ("民法", "第191條之2")),
    (["民法第191條之2"], ("民法", "191之2")),
    (["勞動基準法施行細則第7條"], ("勞動基準法施行細則", "7")),
    (["民法"], None),
])
def test_split_query(parts, expected):
    assert law_lookup.split_query(parts) == expected


def test_engine_alias_resolves_to_official_name():
    assert law_lookup.resolve_law("勞基法", INDEX)["law_name"] == "勞動基準法"


def test_unknown_law_suggests_current_laws_only():
    result = law_lookup.lookup_article("勞動基準", "1", index=INDEX)
    assert result["status"] == "unknown_law"
    assert result["suggestions"][:2] == ["勞動基準法", "勞動基準法施行細則"]


def test_found_article_uses_flno_format(monkeypatch):
    calls = []
    def fetch(pcode, article_no, timeout):
        calls.append((pcode, article_no))
        return ARTICLE_PAGE, f"https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode={pcode}&flno={article_no}"
    monkeypatch.setattr(law_lookup, "_fetch_article_page", fetch)
    result = law_lookup.lookup_article("民法", "第191條之2", index=INDEX)
    assert calls == [("B0000001", "191-2")]
    assert result["status"] == "found"
    assert result["text"].startswith("第 191-2 條\n受設立許可法人")


def test_official_no_data_is_not_found(monkeypatch):
    calls = pages(monkeypatch, "<p>查無資料</p>")
    assert law_lookup.lookup_article("民法", "99999", index=INDEX)["status"] == "not_found"
    assert len(calls) == 1


def test_shell_page_is_rechecked_before_not_found(monkeypatch):
    calls = pages(monkeypatch, SHELL_PAGE)
    result = law_lookup.lookup_article("民法", "99999", index=INDEX)
    assert result["status"] == "not_found" and result["attempts"] == 2
    assert len(calls) == 2


def test_transient_shell_page_does_not_hide_existing_article(monkeypatch):
    pages(monkeypatch, SHELL_PAGE, ARTICLE_PAGE)
    result = law_lookup.lookup_article("民法", "191之2", index=INDEX)
    assert result["status"] == "found" and result["attempts"] == 2


def test_unknown_article_layout_is_not_reported_as_missing_article(monkeypatch):
    pages(monkeypatch, '<div class="law-reg-content"><table>改版</table></div>')
    result = law_lookup.lookup_article("民法", "191-2", index=INDEX)
    assert result["status"] == "unrecognized_page"
    assert "不代表條文不存在" in result["reason"]


def test_ssl_error_without_cache_is_retrieval_unavailable(monkeypatch):
    def fetch(*args, **kwargs):
        raise ssl.SSLEOFError("temporary EOF")
    monkeypatch.setattr(law_lookup, "_fetch_article_page", fetch)
    result = law_lookup.lookup_article("民法", "184", index=INDEX)
    assert result["status"] == "retrieval_unavailable" and "不代表查無資料" in result["reason"]


def test_abandoned_law_plain_text_layout_is_read_and_flagged(monkeypatch):
    pages(monkeypatch, ABANDONED_PAGE)
    result = law_lookup.lookup_article("動員戡亂時期臨時條款", "1", index=INDEX)
    assert result["status"] == "found" and result["abandoned"] is True
    assert result["text"] == "第 1 條\n一、總統在動員戡亂時期，為避免國家\n或人民遭遇緊急危難"


def test_repo_index_agrees_with_verify_engine_pcodes():
    index = law_lookup.load_law_index()
    assert len(index) > 10000
    for name, pcode in STATUTE_PCODES.items():
        resolved = law_lookup.resolve_law(name, index)
        assert resolved and resolved["pcode"] == pcode, name


LAW_FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "law")


def law_fixture(name):
    with open(os.path.join(LAW_FIXTURES, name), encoding="utf-8") as f:
        return f.read()


def test_law_list_and_content_search_pages_are_parsed():
    listing = law_lookup.parse_law_list(law_fixture("law_list.html"))
    assert listing["total"] == 22 and len(listing["laws"]) == 20
    assert listing["laws"][1] == {"law_name": "民法", "pcode": "B0000001", "modified_date": "20260817"}
    articles = law_lookup.parse_content_search(law_fixture("content_search.html"))
    assert [a["article_no"] for a in articles] == ["197", "244"]
    assert articles[0]["text"].startswith("因侵權行為所生之損害賠償請求權，自請求權人知有損害")
    assert "<mark>" not in articles[0]["text"] and articles[0]["text"].count("\n") == 1


def test_search_statutes_expands_first_laws_in_site_order(monkeypatch):
    urls = []
    def page(url, timeout):
        urls.append(url)
        return law_fixture("law_list.html") if "LawSearchResult" in url else law_fixture("content_search.html")
    monkeypatch.setattr(law_lookup, "_get_law_page", page)
    result = law_lookup.search_statutes("知有損害", max_laws=2, index=INDEX, gap=0)
    assert result["status"] == "found" and result["total_laws"] == 22
    assert [law["law_name"] for law in result["expanded"]] == ["中高齡者及高齡者就業促進法", "民法"]
    assert "pcode=B0000001" in urls[2] and len(urls) == 3


def test_search_statutes_in_one_law_and_unknown_law(monkeypatch):
    monkeypatch.setattr(law_lookup, "_get_law_page", lambda url, timeout: law_fixture("content_search.html"))
    result = law_lookup.search_statutes("知有損害", law_name="勞基法", index=INDEX)
    assert result["expanded"][0]["law_name"] == "勞動基準法"
    missing = law_lookup.search_statutes("知有損害", law_name="勞動基準", index=INDEX)
    assert missing["status"] == "unknown_law" and "勞動基準法" in missing["suggestions"]


def test_search_statutes_network_error_is_not_empty_result(monkeypatch):
    def down(url, timeout):
        raise ssl.SSLEOFError("EOF")
    monkeypatch.setattr(law_lookup, "_get_law_page", down)
    result = law_lookup.search_statutes("知有損害", index=INDEX)
    assert result["status"] == "retrieval_unavailable" and "不代表查無條文" in result["reason"]


@pytest.mark.parametrize("kwargs", [{"keyword": " "}, {"keyword": "x", "max_laws": 6}])
def test_search_statutes_rejects_bad_input(kwargs):
    with pytest.raises(ValueError):
        law_lookup.search_statutes(index=INDEX, **kwargs)


@pytest.mark.network
class TestLawSiteLive:
    def test_article_lookup(self):
        result = law_lookup.lookup_article("民法", "191之2")
        assert result["status"] == "found" and "汽車" in result["text"]

    def test_content_search_in_civil_code(self):
        result = law_lookup.search_statutes("知有損害", law_name="民法")
        assert "197" in [a["article_no"] for a in result["expanded"][0]["articles"]]
