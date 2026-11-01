"""fjud 測試：離線部分用 tests/fixtures/fjud/ 存下的官方頁面片段(2026-11-01)；network 類別實際連線 FJUD。"""
import os
import re

import pytest

import engine.fjud as fjud
import engine.verify as verify

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "fjud")
FORM = '<input id="__VIEWSTATE" value="vs"/><input id="__VIEWSTATEGENERATOR" value="g"/><input id="__EVENTVALIDATION" value="ev"/>'
TOKEN_PAGE = '<iframe src="qryresultlst.aspx?ty=JUDBOOK&amp;q=7d5a75fd"></iframe>'


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


class FakeSession:
    def __init__(self, list_html, token_page=TOKEN_PAGE):
        self.list_html, self.token_page, self.posts, self.gets = list_html, token_page, [], []

    def get(self, url, referer=None):
        self.gets.append(url)
        return FORM if url.endswith(".aspx") else self.list_html

    def post(self, url, data, referer=None):
        self.posts.append(data)
        return self.token_page


def test_result_list_rows_carry_type_size_date_cause_and_snippet():
    page = fjud.parse_result_page(fixture("result_list.html"))
    assert (page["total"], page["page_count"], len(page["rows"])) == (29, 2, 20)
    first = page["rows"][0]
    assert first["jid"] == "TPSV,111,台上,1069,20250716,1"
    assert first["citation"] == "最高法院111年度台上字第1069號民事判決"
    assert (first["doc_type"], first["size_kb"], first["doc_date"], first["case_cause"]) == ("判決", 11, "20250716", "請求損害賠償")
    assert "締約上過失" in first["snippet"] and "<" not in first["snippet"]
    # 只勾民事仍會混入最高法院家事類(TPSU)；舊裁判的 JID 沒有尾端序號。
    assert {row["jid"].split(",")[0] for row in page["rows"]} == {"TPSV", "TPSU"}
    old = next(row for row in page["rows"] if row["jid"] == "TPSV,106,台上,1362,20170906")
    assert old["doc_date"] == "20170906"


def test_full_text_takes_whole_nested_container():
    html = fixture("document.html")
    text = fjud.extract_full_text(html)
    assert text.startswith("最高法院民事判決\n111年度台上字第1069號")
    assert "締約上過失" in text and text.rstrip().endswith("日")
    assert len(re.sub(r"\s", "", text)) > 4000
    assert fjud.extract_case_cause(html) == "請求損害賠償"


def test_unrecognized_document_page_gives_empty_text():
    assert fjud.extract_full_text("<html><nav>首頁</nav></html>") == ""


def test_advanced_search_fills_form_and_reads_pages_up_to_limit():
    session = FakeSession(fixture("result_list.html"))
    result = fjud.advanced_search(["締約上過失", " "], case_cause="損害賠償", date_from="2021-01-01",
                                  date_to="2025-12-31", pages=5, min_size_kb=10, session=session)
    form = session.posts[0]
    assert (form["jud_court"], form["jud_sys"], form["jud_kw"], form["jud_title"]) == ("TPS", "V", "締約上過失", "損害賠償")
    assert (form["dy1"], form["dm1"], form["dd1"], form["dy2"]) == ("110", "1", "1", "114")
    assert form["KbStart"] == "10" and form["__VIEWSTATE"] == "vs"
    assert result["pages_read"] == 2 and len(result["rows"]) == 40 and result["total"] == 29
    assert session.gets[-1].endswith("&sort=DS&page=2")


def test_advanced_search_without_result_link_is_empty_not_error():
    result = fjud.advanced_search(["不存在的詞"], session=FakeSession("", token_page="<p>查無資料</p>"))
    assert result == {"total": 0, "page_count": 0, "pages_read": 0, "rows": []}


def test_citation_lookup_uses_number_fields(monkeypatch):
    calls = []
    def search(**kwargs):
        calls.append(kwargs)
        return {"rows": [{"jid": "TPSV,111,台上,1069,20250716,1"}]}
    monkeypatch.setattr(fjud, "advanced_search", search)
    assert verify._fjud_search("111", "台上", "1069") == ["TPSV,111,台上,1069,20250716,1"]
    assert calls[0]["citation"] == ("111", "台上", "1069") and calls[0]["pages"] == 1


def test_cache_fetch_uses_full_document(monkeypatch):
    from engine import retrieval_cache
    html = fixture("document.html")
    monkeypatch.setattr(fjud.Session, "get", lambda self, url, referer=None: html)
    entry = retrieval_cache.get_judgment("TPSV,111,台上,1069,20250716,1")
    assert entry["served_from"] == "live" and entry["case_cause"] == "請求損害賠償"
    assert verify._document_type(entry["text"]) == "判決" and len(entry["text"]) > 4000


def test_session_keeps_gap_between_requests(monkeypatch):
    clock, sleeps = [100.0], []
    monkeypatch.setattr(fjud.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(fjud.time, "sleep", lambda s: sleeps.append(round(s, 2)))
    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"ok"
    session = fjud.Session()
    monkeypatch.setattr(session._opener, "open", lambda req, timeout: Resp())
    session.get("https://example.invalid/a")
    clock[0] += 0.5
    session.get("https://example.invalid/b")
    assert sleeps == [1.0]


@pytest.mark.network
class TestFjudLive:
    def test_supreme_civil_keyword_search(self):
        result = fjud.advanced_search(["締約上過失"], pages=1)
        assert result["total"] >= 20
        assert all(row["jid"].startswith("TPS") for row in result["rows"])

    def test_online_text_matches_local_corpus(self):
        jid = "TPSV,114,台上,1584,20260415,1"
        with open(os.path.join("corpus", "judgments", jid + ".txt"), encoding="utf-8") as f:
            local = f.read()
        online = fjud.fetch_document(jid)["full_text"]
        assert re.sub(r"\s", "", online) == re.sub(r"\s", "", local)

    def test_non_local_citation_is_found_by_number_fields(self):
        result = verify.verify_judgment_citation("111", "台上", "1069", doc_date="20250716")
        assert result["status"] == "published" and result["jid"] == "TPSV,111,台上,1069,20250716,1"
