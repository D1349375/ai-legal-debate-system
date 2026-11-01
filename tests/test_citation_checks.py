"""Step 8 的可重現引用查證回歸，不依賴網路或共用資料庫。"""
import ssl

import pytest

import engine.law_lookup as law_lookup
import engine.verify as verify


def test_real_multi_document_citation_requires_date():
    result = verify.verify_judgment_citation("114", "台上", "1945")
    assert result["status"] == "ambiguous"
    assert len(result["candidates"]) >= 2


def test_explicit_date_selects_substantive_judgment():
    result = verify.verify_judgment_citation("114", "台上", "1945", doc_date="20260513")
    assert result["status"] == "published"
    assert result["doc_type"] == "判決"
    assert result["jtitle"] == "請求確認本票債權不存在等"
    assert "20260513" in result["source_file"]


@pytest.mark.parametrize("text,name", [
    ("銀行法第29條", "銀行法"),
    ("民法債編施行法第10條之1", "民法債編施行法"),
    ("民事訴訟法施行法第1條", "民事訴訟法施行法"),
])
def test_real_run_statutes_are_parsed_without_matching_law_suffix(text, name):
    assert verify.parse_citation(text)["law_name"] == name


def test_unsupported_law_is_distinct_from_unparseable():
    result = verify.verify_citations(["外星人保護法第1條", "不是法律引用"])
    assert [r["status"] for r in result] == ["unsupported_law", "unparseable"]


@pytest.mark.parametrize("citation,hint", [
    ("108年民法第205條", None),
    ("民法第205條（修正前）", None),
    ("民法第205條", "本案適用108年舊法"),
    ("民法第205條", {"applicable_version": "108年"}),
])
def test_old_version_never_fetches_or_passes_current_law(monkeypatch, citation, hint):
    def no_current_fetch(*args, **kwargs):
        pytest.fail("歷史版本不可用現行條文冒充")
    monkeypatch.setattr(law_lookup, "_fetch_article_page", no_current_fetch)
    result = verify.verify_citations([citation], version_hints={citation: hint})[0]
    assert result["status"] == "version_unverified"


def test_ssl_error_is_retried_once_then_network_error_not_not_found(monkeypatch):
    calls = []
    def fetch(*args, **kwargs):
        calls.append(1)
        raise ssl.SSLEOFError("temporary EOF")
    monkeypatch.setattr(law_lookup, "_fetch_article_page", fetch)
    monkeypatch.setattr(law_lookup.time, "sleep", lambda seconds: None)
    result = verify.verify_statute_citation("民法", "184")
    assert result["status"] == "network_error" and "不代表查無資料" in result["reason"]
    assert len(calls) == 2


def precedent_note(**changes):
    result = verify.verify_judgment_citation("114", "台上", "1945", doc_date="20260513")
    note = {"citation": "最高法院114年度台上字第1945號", "doc_date": "20260513",
            "doc_type": "判決", "case_cause": result["jtitle"],
            "quote": "最高法院民事判決", "proposition": "契約效力須區分撤銷前後", "analogy_reason": None}
    note.update(changes)
    return note


def test_document_type_and_quote_are_programmatically_checked():
    assert verify.verify_precedent_note(precedent_note())["status"] == "published"
    assert verify.verify_precedent_note(precedent_note(doc_type="裁定"))["status"] == "doc_type_mismatch"
    assert verify.verify_precedent_note(precedent_note(quote="完全不存在的摘句"))["status"] == "quote_not_found"


def test_different_cause_requires_analogy_and_remains_visible():
    assert verify.verify_precedent_note(precedent_note(case_cause="交通事故"))["status"] == "analogy_required"
    result = verify.verify_precedent_note(precedent_note(case_cause="交通事故", analogy_reason="僅類推相同的撤銷效力問題"))
    assert result["status"] == "needs_explanation"
    assert result["support_review_required"] is True


def test_medical_ruling_cannot_be_passed_off_as_traffic_judgment():
    result = verify.verify_precedent_note({
        "citation": "最高法院115年度台上字第447號", "doc_date": "20260416",
        "doc_type": "判決", "case_cause": "交通事故", "quote": "最高法院民事裁定",
        "proposition": "駕駛人有過失", "analogy_reason": "醫療案例與過失相似",
    })
    assert result["status"] == "doc_type_mismatch"
