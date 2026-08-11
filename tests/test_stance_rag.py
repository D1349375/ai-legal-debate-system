"""stance_rag.py 邊界案例測試(比照 test_aggregate.py 的既有測試紀律)。"""
import pytest

from engine.stance_rag import build_stance_terms


class TestBuildStanceTerms:
    def test_plaintiff_generic_terms(self):
        terms = build_stance_terms("plaintiff")
        assert "請求權成立" in terms
        assert "有理由" in terms

    def test_defendant_generic_terms(self):
        terms = build_stance_terms("defendant")
        assert "欠缺請求權基礎" in terms
        assert "罹於時效" in terms

    def test_plaintiff_and_defendant_terms_disjoint(self):
        plaintiff_terms = set(build_stance_terms("plaintiff"))
        defendant_terms = set(build_stance_terms("defendant"))
        assert plaintiff_terms.isdisjoint(defendant_terms)

    def test_known_case_type_adds_supplementary_terms(self):
        terms = build_stance_terms("plaintiff", case_type="侵權行為")
        assert "過失" in terms
        assert "請求權成立" in terms  # 通用框架詞仍在

    def test_unknown_case_type_falls_back_to_generic_only(self):
        terms = build_stance_terms("plaintiff", case_type="不存在的案由")
        assert terms == build_stance_terms("plaintiff")

    def test_no_case_type_returns_generic_only(self):
        assert build_stance_terms("defendant", case_type=None) == build_stance_terms("defendant")

    def test_invalid_side_raises(self):
        with pytest.raises(ValueError):
            build_stance_terms("judge")

    def test_case_type_terms_differ_by_side(self):
        plaintiff_terms = build_stance_terms("plaintiff", case_type="勞資爭議")
        defendant_terms = build_stance_terms("defendant", case_type="勞資爭議")
        assert "違法解僱" in plaintiff_terms
        assert "違法解僱" not in defendant_terms
        assert "合法終止" in defendant_terms
