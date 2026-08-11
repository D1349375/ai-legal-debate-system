"""aggregate.py 邊界案例測試(比照 DebateSystem 的既有測試紀律:不要只跑 smoke test)。"""
import pytest

from engine.aggregate import compile_weak_points, disagreement


def arg(side, reasoning="論述內容", falsifier=None, cited_statutes=None, cited_precedents=None):
    return {"side": side, "reasoning": reasoning, "falsifier": falsifier,
            "cited_statutes": cited_statutes, "cited_precedents": cited_precedents}


class TestCompileWeakPoints:
    def test_both_sides_with_falsifier(self):
        points = compile_weak_points([
            arg("defendant", falsifier="若原告補上匯款單據，我方將放棄時效抗辯"),
            arg("plaintiff", falsifier="若被告提出書面合意變更給付方式之證據，我方將撤回本項請求"),
        ])
        assert [p["side"] for p in points] == ["defendant", "plaintiff"]  # falsifier 皆有，依 side 字母序

    def test_falsifier_missing_sorts_last(self):
        points = compile_weak_points([
            arg("plaintiff", falsifier=None),
            arg("defendant", falsifier="若……我方讓步"),
        ])
        assert points[0]["side"] == "defendant"
        assert points[1]["side"] == "plaintiff"

    def test_single_side_present(self):
        points = compile_weak_points([arg("plaintiff", falsifier="讓步條件")])
        assert len(points) == 1 and points[0]["side"] == "plaintiff"

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            compile_weak_points([])

    def test_invalid_side_raises(self):
        with pytest.raises(ValueError):
            compile_weak_points([arg("judge")])


class TestDisagreement:
    def test_identical_citations_zero_drift(self):
        stage1 = [arg("plaintiff", cited_statutes=["民法第184條"])]
        stage3 = [arg("plaintiff", cited_statutes=["民法第184條"])]
        assert disagreement(stage1, stage3) == {"plaintiff": 0.0, "defendant": None}

    def test_completely_different_citations_full_drift(self):
        stage1 = [arg("plaintiff", cited_statutes=["民法第184條"])]
        stage3 = [arg("plaintiff", cited_statutes=["民法第227條"])]
        assert disagreement(stage1, stage3) == {"plaintiff": 1.0, "defendant": None}

    def test_partial_overlap(self):
        stage1 = [arg("defendant", cited_statutes=["民法第125條"], cited_precedents=["最高法院115年度台上字第1037號"])]
        stage3 = [arg("defendant", cited_statutes=["民法第125條", "民法第144條"])]
        ratio = disagreement(stage1, stage3)["defendant"]
        assert 0 < ratio < 1

    def test_no_citations_either_stage_zero(self):
        stage1 = [arg("plaintiff")]
        stage3 = [arg("plaintiff")]
        assert disagreement(stage1, stage3)["plaintiff"] == 0.0

    def test_side_missing_from_one_stage_is_none(self):
        stage1 = [arg("plaintiff", cited_statutes=["民法第184條"]), arg("defendant", cited_statutes=["民法第125條"])]
        stage3 = [arg("plaintiff", cited_statutes=["民法第184條"])]  # defendant 未進入 stage3
        result = disagreement(stage1, stage3)
        assert result["defendant"] is None
        assert result["plaintiff"] == 0.0

    def test_invalid_side_raises(self):
        with pytest.raises(ValueError):
            disagreement([arg("judge")], [arg("judge")])
