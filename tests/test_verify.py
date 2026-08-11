"""verify.py 測試。parse_citation 為純本機邏輯，無網路依賴；TestStatuteLiveVerification 與
TestJudgmentLiveVerification 會實際連線 law.moj.gov.tw / judgment.judicial.gov.tw(FJUD)，
僅在有網路時跑得動。verify_judgment_citation 於 2026-08-09 起，本地種子語料庫未命中時會
即時查證 FJUD(見 engine/verify.py)，不再是純本機邏輯，相關測試已移至網路測試類別。
"""
import pytest

from engine.verify import parse_citation, verify_judgment_citation, verify_statute_citation


class TestParseCitation:
    def test_statute_citation(self):
        assert parse_citation("民法第184條") == {"type": "statute", "law_name": "民法", "article_no": "184"}

    def test_statute_citation_with_subsection_no(self):
        result = parse_citation("民法第9-1條")
        assert result == {"type": "statute", "law_name": "民法", "article_no": "9-1"}

    def test_statute_citation_with_zhi_subsection(self):
        """「之N」子條文寫法(如「第191條之2」)是 subagent 實際會產出的格式，2026-08-08 端到端
        測試發現舊版正規式會丟掉「之2」，把它誤判成單純的「第191條」(完全不同的條文)並回傳
        published——比查不到還危險的靜默誤判，須固定測試防止回歸。"""
        result = parse_citation("民法第191條之2")
        assert result == {"type": "statute", "law_name": "民法", "article_no": "191-2"}

    def test_judgment_citation(self):
        result = parse_citation("最高法院115年度台上字第1037號")
        assert result == {"type": "judgment", "jyear": "115", "jcase": "台上", "jno": "1037"}

    def test_judgment_citation_without_court_name_prefix(self):
        result = parse_citation("115年度台簡抗字第236號")
        assert result == {"type": "judgment", "jyear": "115", "jcase": "台簡抗", "jno": "236"}

    def test_judgment_citation_taijianshang(self):
        """字別原為列舉白名單(台上/台簡抗/台抗),2026-08-09 端到端測試發現本地語料庫實際涵蓋
        7種字別,「台簡上」(簡易訴訟第二審上訴,語料庫中最常見的字別之一)不在白名單內,
        會被誤判為 unparseable——跟「之N子條文」是同一類白名單漏掉真實變體的錯誤,
        須固定測試防止回歸。"""
        result = parse_citation("最高法院115年度台簡上字第8號")
        assert result == {"type": "judgment", "jyear": "115", "jcase": "台簡上", "jno": "8"}

    def test_judgment_citation_other_case_types(self):
        """本地語料庫另涵蓋台再/台簡聲/台聲三種字別,一併鎖定不得誤判為 unparseable。"""
        assert parse_citation("最高法院114年度台再字第1號") == {
            "type": "judgment", "jyear": "114", "jcase": "台再", "jno": "1"}
        assert parse_citation("最高法院114年度台簡聲字第1號") == {
            "type": "judgment", "jyear": "114", "jcase": "台簡聲", "jno": "1"}
        assert parse_citation("最高法院114年度台聲字第1號") == {
            "type": "judgment", "jyear": "114", "jcase": "台聲", "jno": "1"}

    def test_unparseable_text(self):
        assert parse_citation("被告顯係推諉卸責之詞") == {"type": "unknown"}


class TestVerifyJudgmentCitation:
    def test_seed_corpus_hit_is_published(self):
        result = verify_judgment_citation("115", "台上", "1037")
        assert result["status"] == "published"
        assert result["verified_via"] == "local_corpus"
        assert "最高法院" in result["matched_text"]


@pytest.mark.network
class TestJudgmentLiveVerification:
    """本地種子語料庫(corpus/judgments)未命中時，2026-08-09 起改為即時查證 FJUD，
    不再直接回報 not_in_phase1_seed_corpus 了事——這三個測試鎖定新行為，防止回歸。"""

    def test_real_citation_outside_local_corpus_falls_back_to_fjud(self):
        # 109年為真實存在但確定不在本地語料庫範圍(語料庫僅涵蓋112-115年)的裁判，
        # 用來測試「本地未命中→FJUD即時查證成功」這條新路徑。
        result = verify_judgment_citation("109", "台上", "2000")
        assert result["status"] == "published"
        assert result["verified_via"] == "fjud_live"
        assert result["jid"].startswith("TPSV,109,台上,2000,")
        assert "primary_source_url" in result

    def test_nonexistent_citation_is_not_found_not_seed_corpus_message(self):
        # 舊行為會回報 not_in_phase1_seed_corpus(誠實但不判斷真偽)；新行為應實際查證
        # 並回報 not_found(查無此裁判)，兩者語意不同，不可混淆。
        result = verify_judgment_citation("999", "台上", "99999")
        assert result["status"] == "not_found"
        assert result["fjud_raw_hits"] == []

    def test_fjud_result_jid_matching_rejects_mismatched_hits(self):
        # 已知本地命中的字號，直接改走本地路徑不會觸發此函式，這裡測試 _jid_matches 的
        # 邏輯本身：確保比對是嚴格逐欄位相符，不會誤採年度/字別/字號不同的相近結果。
        from engine.verify import _jid_matches
        assert _jid_matches("TPSV,115,台上,1037,20260722,1", "115", "台上", "1037") is True
        assert _jid_matches("TPSV,115,台上,1038,20260722,1", "115", "台上", "1037") is False
        assert _jid_matches("TPSV,114,台上,1037,20260722,1", "115", "台上", "1037") is False


@pytest.mark.network
class TestStatuteLiveVerification:
    def test_known_current_article_is_published(self):
        result = verify_statute_citation("民法", "184")
        assert result["status"] == "published"
        assert "損害賠償責任" in result["matched_text"]

    def test_nonexistent_article_number_is_not_found(self):
        # 遠超民法實際條文範圍(現行條文至第1225條)，用來測試「查無資料」路徑，
        # 不誤判為 published，避免查證引擎對不存在的法條照樣蓋章通過。
        result = verify_statute_citation("民法", "99999")
        assert result["status"] == "not_found"

    def test_unknown_law_name(self):
        result = verify_statute_citation("外星人保護法", "1")
        assert result["status"] == "unknown_law"
