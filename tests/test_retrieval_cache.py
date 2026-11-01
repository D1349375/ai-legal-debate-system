"""檢索快取、實跑快照、斷網處理與法條名稱索引(階段三)。全部以假連線替代，不連網。

斷網測試對應計畫第九節第 4 項：快取命中照常可用；快取沒有時回報 retrieval_unavailable／network_error，
不退回本地法規、不標 published。
"""
import json
import ssl
import urllib.error

import pytest

from engine import fjud, law_lookup, retrieval_cache, verify

JID = "TPSV,111,台上,1069,20250716,1"
TEXT = "最高法院民事判決\n111年度台上字第1069號\n主文\n原判決廢棄。\n理由\n按締約上過失責任，以契約未成立為前提。"
ARTICLE_PAGE = ('<div class="law-reg-content"><div class="law-article"><div class="line-0000">'
                '因故意或過失，不法侵害他人之權利者，負損害賠償責任。</div></div><div class="clearfix"></div></div>')


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(law_lookup.time, "sleep", lambda seconds: None)


@pytest.fixture
def fjud_calls(monkeypatch):
    calls = {"fetch": [], "search": []}

    def fetch(jid, timeout=None, session=None):
        calls["fetch"].append(jid)
        return {"jid": jid, "url": fjud.document_url(jid), "full_text": TEXT, "case_cause": "請求損害賠償"}

    def search(citation=None, pages=1, timeout=None, **kwargs):
        calls["search"].append(citation)
        return {"rows": [{"jid": JID}] if citation == ("111", "台上", "1069") else []}
    monkeypatch.setattr(fjud, "fetch_document", fetch)
    monkeypatch.setattr(fjud, "advanced_search", search)
    return calls


@pytest.fixture
def offline(monkeypatch):
    """模擬斷網：判決與條文的所有連線都失敗。"""
    calls = []

    def down(*args, **kwargs):
        calls.append(args)
        raise urllib.error.URLError("[Errno 11001] getaddrinfo failed")
    monkeypatch.setattr(fjud, "fetch_document", down)
    monkeypatch.setattr(fjud, "advanced_search", down)
    monkeypatch.setattr(law_lookup, "_fetch_article_page", down)
    return calls


def article_pages(monkeypatch, page=ARTICLE_PAGE):
    calls = []

    def fetch(pcode, flno, timeout=None):
        calls.append((pcode, flno))
        return page, f"https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode={pcode}&flno={flno}"
    monkeypatch.setattr(law_lookup, "_fetch_article_page", fetch)
    return calls


MINFA = {"law_name": "民法", "pcode": "B0000001", "level": "法律", "abandoned": False, "modified_date": "20260817"}


# ───────────── 判決 ─────────────

def test_live_judgment_is_cached_and_recorded_in_snapshot(fjud_calls, tmp_path):
    snapshot = tmp_path / "snap"
    first = retrieval_cache.get_judgment(JID, snapshot=str(snapshot))
    again = retrieval_cache.get_judgment(JID)
    assert first["served_from"] == "live" and again["served_from"] == "retrieval_cache"
    assert fjud_calls["fetch"] == [JID]
    recorded = json.loads((snapshot / "judgments" / f"{JID}.json").read_text(encoding="utf-8"))
    assert recorded["snapshot_source"] == "live" and recorded["sha256"] == first["sha256"] and recorded["fetched_at"]
    assert retrieval_cache.get_judgment(JID, snapshot=str(snapshot))["served_from"] == "run_snapshot"


def test_corpus_is_read_only_preloaded_content_without_fetch_time(fjud_calls, tmp_path):
    jid = "TPSV,114,台上,1945,20260513,1"
    entry = retrieval_cache.get_judgment(jid, snapshot=str(tmp_path / "snap"))
    assert entry["served_from"] == "corpus" and entry["fetched_at"] is None and entry["case_cause"]
    assert fjud_calls["fetch"] == []
    assert retrieval_cache.cache_counts()["judgments"] == 0  # 預先內容不複製進長期快取
    manifest = retrieval_cache.snapshot_manifest(str(tmp_path / "snap"))
    assert [(m["jid"], m["snapshot_source"]) for m in manifest["judgments"]] == [(jid, "corpus")]
    assert "text" not in manifest["judgments"][0]


def test_offline_without_cache_is_retrieval_unavailable_after_one_retry(offline):
    with pytest.raises(retrieval_cache.RetrievalUnavailable, match="不代表查無資料"):
        retrieval_cache.get_judgment(JID)
    assert len(offline) == 2


def test_offline_with_cache_still_serves_the_judgment(fjud_calls, monkeypatch):
    retrieval_cache.get_judgment(JID)
    monkeypatch.setattr(fjud, "fetch_document", lambda *a, **k: pytest.fail("快取命中不應連網"))
    assert retrieval_cache.get_judgment(JID)["text"] == TEXT


def test_budget_refusal_still_reads_cached_texts(fjud_calls):
    with pytest.raises(retrieval_cache.LiveFetchNotAllowed):
        retrieval_cache.get_judgment(JID, allow_live=False)
    retrieval_cache.get_judgment(JID)
    assert retrieval_cache.get_judgment(JID, allow_live=False)["served_from"] == "retrieval_cache"


def test_cached_text_does_not_settle_which_documents_a_citation_has(offline):
    """同字號同一天可有多份(115台上192 有 20260325 的序號 1、2)；快取只有一份時不能當成唯一，要上網確認。"""
    retrieval_cache.store_judgment(JID, TEXT, "請求損害賠償", fjud.document_url(JID))
    with pytest.raises(retrieval_cache.RetrievalUnavailable):
        retrieval_cache.judgment_candidates("111", "台上", "1069")
    result = verify.verify_judgment_citation("111", "台上", "1069", doc_date="20250716")
    assert result["status"] == "network_error"


def test_same_day_documents_stay_ambiguous_even_with_a_date():
    result = verify.verify_judgment_citation("115", "台上", "192", doc_date="20260325")
    assert result["status"] == "ambiguous" and len(result["candidates"]) == 2


def test_candidates_from_fjud_are_recorded_in_snapshot(fjud_calls, tmp_path):
    snapshot = str(tmp_path / "snap")
    assert retrieval_cache.judgment_candidates("111", "台上", "1069", snapshot=snapshot)["served_from"] == "live"
    assert retrieval_cache.judgment_candidates("111", "台上", "1069", snapshot=snapshot)["served_from"] == "run_snapshot"
    assert fjud_calls["search"] == [("111", "台上", "1069")]


# ───────────── 條文 ─────────────

def test_article_is_cached_for_seven_days(monkeypatch, seed_article):
    calls = article_pages(monkeypatch)
    assert retrieval_cache.get_article(MINFA, "184")["served_from"] == "live"
    assert retrieval_cache.get_article(MINFA, "184")["served_from"] == "retrieval_cache"
    assert len(calls) == 1
    seed_article("B0000001", "184", days_old=8)
    refreshed = retrieval_cache.get_article(MINFA, "184")
    assert refreshed["served_from"] == "live" and len(calls) == 2


def test_stale_article_is_not_used_when_offline(offline, seed_article):
    seed_article("B0000001", "184", days_old=8)
    with pytest.raises(retrieval_cache.RetrievalUnavailable, match="超過 7 天"):
        retrieval_cache.get_article(MINFA, "184")


def test_missing_article_is_not_cached(monkeypatch):
    calls = article_pages(monkeypatch, page="<html>全國法規資料庫</html>")
    assert retrieval_cache.get_article(MINFA, "99999")["status"] == "not_found"
    assert retrieval_cache.cache_counts()["statutes"] == 0 and len(calls) == 2  # 空殼頁重查一次


# ───────────── 查證(斷網測試) ─────────────

def test_statute_verification_offline_never_falls_back_to_local_code(offline):
    result = verify.verify_statute_citation("民法", "184")
    assert result["status"] == "network_error" and "不代表查無資料" in result["reason"]


def test_statute_verification_uses_fresh_cache_and_notes_fetch_time(offline, seed_article):
    seed_article("B0000001", "184", days_old=3)
    result = verify.verify_statute_citation("民法", "184")
    assert result["status"] == "published" and result["verified_via"] == "retrieval_cache" and result["fetched_at"]
    assert offline == []


def test_statute_verification_rejects_stale_cache_offline(offline, seed_article):
    seed_article("B0000001", "184", days_old=8)
    assert verify.verify_statute_citation("民法", "184")["status"] == "network_error"


def test_judgment_verification_offline_is_network_error_not_published(offline):
    result = verify.verify_judgment_citation("111", "台上", "1069", doc_date="20250716")
    assert result["status"] == "network_error" and "非查無此判決" in result["note"]


def test_role_read_and_verification_share_one_fetch_and_one_text(fjud_calls, tmp_path):
    snapshot = str(tmp_path / "snap")
    read = retrieval_cache.get_judgment(JID, snapshot=snapshot)  # 角色以 judgment 指令讀全文
    note = {"citation": "最高法院111年度台上字第1069號", "doc_date": "20250716", "doc_type": "判決",
            "case_cause": "損害賠償", "quote": "按締約上過失責任，以契約未成立為前提。", "proposition": "締約上過失"}
    result = verify.verify_precedent_note(note, snapshot=snapshot)
    assert result["status"] == "published" and result["verified_via"] == "run_snapshot"
    assert result["full_text"] == read["text"] and fjud_calls["fetch"] == [JID]


def test_verification_reads_snapshot_offline_for_replay(fjud_calls, tmp_path, monkeypatch, isolated_retrieval_cache):
    snapshot = str(tmp_path / "snap")
    verify.verify_judgment_citation("111", "台上", "1069", snapshot=snapshot)
    retrieval_cache.get_judgment(JID, snapshot=snapshot)
    monkeypatch.setenv(retrieval_cache.CACHE_ENV, str(tmp_path / "empty-cache"))  # 換一台沒有長期快取的機器
    monkeypatch.setattr(fjud, "advanced_search", lambda *a, **k: pytest.fail("重播不應連網"))
    monkeypatch.setattr(fjud, "fetch_document", lambda *a, **k: pytest.fail("重播不應連網"))
    result = verify.verify_judgment_citation("111", "台上", "1069", snapshot=snapshot)
    assert result["status"] == "published" and result["verified_via"] == "run_snapshot" and result["full_text"] == TEXT


def test_snapshot_env_is_used_when_no_flag_is_given(fjud_calls, tmp_path, monkeypatch):
    monkeypatch.setenv(verify.SNAPSHOT_ENV, str(tmp_path / "snap"))
    verify.verify_judgment_citation("111", "台上", "1069")
    assert (tmp_path / "snap" / "citations").is_dir()


# ───────────── 法條名稱索引 ─────────────

@pytest.mark.parametrize("text,law", [
    ("依土地法第34條之1", "土地法"),
    ("民法債編施行法第10條之1", "民法債編施行法"),
    ("上訴人依公司法第23條第2項", "公司法"),
    ("消保法第7條", "消保法"),
    ("中華民國刑法第339條", "中華民國刑法"),
    ("民法 第184條", "民法"),
])
def test_longest_index_name_is_taken(text, law):
    assert verify.parse_citation(text)["law_name"] == law


def test_index_laws_are_supported_and_aliases_resolve(monkeypatch):
    calls = article_pages(monkeypatch)
    result = verify.verify_statute_citation("消保法", "7")
    assert result["status"] == "published" and result["official_name"] == "消費者保護法"
    assert calls == [("J0170001", "7")]


def test_abandoned_law_is_version_unverified_without_fetching(monkeypatch):
    monkeypatch.setattr(law_lookup, "_fetch_article_page", lambda *a, **k: pytest.fail("廢止法規不得用官網條文放行"))
    result = verify.verify_citations(["動員戡亂時期臨時條款第1條"])[0]
    assert result["status"] == "version_unverified" and "已廢止" in result["note"]


def test_unknown_name_is_still_unsupported_law():
    assert verify.citation_warning("外星人保護法第1條")["status"] == "unsupported_law"


def test_finder_offers_regex_like_matches():
    text = "原告依民法第184條第1項前段、第185條及公司法第23條第2項請求"
    matches = list(verify.STATUTE_CITATION_RE.finditer(text))
    assert [m.group(0) for m in matches] == ["民法第184條", "公司法第23條"]
    assert text[matches[1].start():matches[1].end()] == "公司法第23條"


def test_ssl_error_is_retried(monkeypatch):
    calls = []

    def flaky(pcode, flno, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            raise ssl.SSLEOFError("EOF")
        return ARTICLE_PAGE, "https://law.moj.gov.tw/x"
    monkeypatch.setattr(law_lookup, "_fetch_article_page", flaky)
    assert verify.verify_statute_citation("民法", "184")["status"] == "published" and len(calls) == 2


# ───────────── 快照依角色分開 ─────────────

def test_side_snapshots_do_not_reveal_what_the_other_side_read(fjud_calls, tmp_path):
    root = tmp_path / "case-snap"
    retrieval_cache.get_judgment(JID, snapshot=str(root / "plaintiff"))  # 原告讀過
    seen_by_defendant = retrieval_cache.get_judgment(JID, snapshot=str(root / "defendant"))
    # 被告讀同一份時取自長期快取，看不出原告讀過；內容仍是同一版本
    assert seen_by_defendant["served_from"] == "retrieval_cache"
    assert seen_by_defendant["sha256"] == retrieval_cache.peek_judgment(JID, str(root / "plaintiff"))[0]["sha256"]
    recorded = json.loads((root / "defendant" / "judgments" / f"{JID}.json").read_text(encoding="utf-8"))
    assert recorded["snapshot_source"] == "retrieval_cache" and fjud_calls["fetch"] == [JID]
    assert not (root / "judgments").exists()  # 角色只寫自己的子資料夾，不寫案件根目錄


def test_verification_with_case_root_reads_both_sides(fjud_calls, tmp_path, monkeypatch):
    root = tmp_path / "case-snap"
    retrieval_cache.get_judgment(JID, snapshot=str(root / "defendant"))
    verify.verify_judgment_citation("111", "台上", "1069", snapshot=str(root / "defendant"))
    monkeypatch.setenv(retrieval_cache.CACHE_ENV, str(tmp_path / "empty-cache"))
    monkeypatch.setattr(fjud, "advanced_search", lambda *a, **k: pytest.fail("快照已有，不應連網"))
    monkeypatch.setattr(fjud, "fetch_document", lambda *a, **k: pytest.fail("快照已有，不應連網"))
    result = verify.verify_judgment_citation("111", "台上", "1069", snapshot=str(root))
    assert result["status"] == "published" and result["verified_via"] == "run_snapshot"
    manifest = retrieval_cache.snapshot_manifest(str(root))
    assert {(m["jid"], m["scope"]) for m in manifest["judgments"]} == {(JID, "defendant")}


def test_retrieval_commands_ignore_the_case_root_env(fjud_calls, tmp_path, monkeypatch):
    """環境變數指向案件根目錄(查證用)；角色漏給 --snapshot 時不得把讀過的判決記到雙方都看得到的根目錄。"""
    import argparse
    import main
    root = tmp_path / "case-snap"
    monkeypatch.setenv(verify.SNAPSHOT_ENV, str(root))
    args = argparse.Namespace(target=JID, doc_date=None, json=True, snapshot=None, log=None, issue=None)
    assert main.cmd_judgment(args) == 0
    assert not (root / "judgments").exists()
