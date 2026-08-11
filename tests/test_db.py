"""database/db.py 測試，聚焦 2026-08-09 新增的引用正規化比對邏輯(_citation_key/
_find_citation_row/_assert_all_published/upsert_citation)。皆使用記憶體 SQLite，
不觸碰真實專案資料庫，純本機邏輯無網路依賴。
"""
import pytest

from database.db import get_session, upsert_citation, _assert_all_published, _citation_key


@pytest.fixture
def session():
    return get_session(db_url="sqlite:///:memory:")


class TestCitationKey:
    def test_same_statute_different_subsection_same_key(self):
        assert _citation_key("民法第129條") == _citation_key("民法第129條第1項第2款")

    def test_different_statute_article_different_key(self):
        assert _citation_key("民法第129條") != _citation_key("民法第130條")

    def test_judgment_with_and_without_court_prefix_same_key(self):
        assert _citation_key("最高法院115年度台上字第1037號") == _citation_key("115年度台上字第1037號")

    def test_different_judgment_case_type_different_key(self):
        # 案由字別不同(台上 vs 台簡上)即使年度號次相同，仍是不同裁判，不得視為同一筆
        assert _citation_key("115年度台上字第8號") != _citation_key("115年度台簡上字第8號")

    def test_unknown_falls_back_to_raw_text(self):
        assert _citation_key("被告顯係推諉卸責之詞") == ("unknown", "被告顯係推諉卸責之詞")


class TestUpsertCitationNormalizedMatching:
    def test_reupsert_with_different_subsection_reuses_same_row(self, session):
        """2026-08-09 端到端測試實際踩到的情境：Stage1 用「民法第129條第1項第2款」查證
        為 published，法官 verdict 卻用簡式「民法第129條」——修正前會被視為未查證。"""
        upsert_citation(session, citation_text="民法第129條第1項第2款",
                         source_type="statute", status="published",
                         primary_source_url="https://law.moj.gov.tw/x")
        # 不應該再另建一筆，且 published 狀態應被「看見」
        _assert_all_published(session, ["民法第129條"])  # 不拋例外即為通過

    def test_unrelated_article_still_blocks(self, session):
        upsert_citation(session, citation_text="民法第129條", source_type="statute",
                         status="published")
        with pytest.raises(ValueError, match="拒絕落地"):
            _assert_all_published(session, ["民法第130條"])

    def test_judgment_citation_court_prefix_variants_reuse_same_row(self, session):
        upsert_citation(session, citation_text="115年度台上字第1037號",
                         source_type="judgment", status="published")
        _assert_all_published(session, ["最高法院115年度台上字第1037號"])

    def test_draft_status_still_blocks(self, session):
        upsert_citation(session, citation_text="民法第129條第1項第2款",
                         source_type="statute", status="draft")
        with pytest.raises(ValueError, match="拒絕落地"):
            _assert_all_published(session, ["民法第129條"])
