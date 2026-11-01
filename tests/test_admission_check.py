"""engine/admission_check.py:自承類用語要引述到真實的事實陳述才放行。"""
from engine.admission_check import admission_problems, looks_factual, strings_in

SOURCES = {
    "plaintiff": ["原告名下已無其他財產可供清償。若被告提出單據,原告將重新評估。"],
    "defendant": ["被告於受領貨物後未在送貨單上記載任何異議。這是本案最大弱點。行車紀錄器資料未載,待確認。"],
    "facts": ["被告於警詢時稱當時原告的車慢慢往前挪動。"],
}


class TestAdmissionProblems:
    def test_real_statement_passes(self):
        assert admission_problems("被告自承「未在送貨單上記載任何異議」。", SOURCES) == []

    def test_case_facts_count_as_a_source(self):
        assert admission_problems("被告自陳「當時原告的車慢慢往前挪動」。", SOURCES) == []

    def test_no_quote_is_rejected(self):
        problems = admission_problems("被告已自認沒有行車紀錄器。", SOURCES)
        assert len(problems) == 1 and "沒有緊接引述" in problems[0]

    def test_quote_elsewhere_in_the_sentence_does_not_count(self):
        # 08-08-002 的真實句型:句中有別的引述,但「自承」後面接的是作者自己的轉述
        text = "被告主張「當時原告的車慢慢往前挪動」,惟已自承若無客觀補強證據此部分基礎薄弱。"
        assert len(admission_problems(text, SOURCES)) == 1

    def test_invented_quote_is_rejected(self):
        problems = admission_problems("被告坦承「現無行車紀錄器可以提出」。", SOURCES)
        assert "不在該方論證" in problems[0]

    def test_self_assessment_is_rejected(self):
        problems = admission_problems("被告自承「這是本案最大弱點」。", SOURCES)
        assert "不是事實陳述" in problems[0]

    def test_data_gap_is_rejected(self):
        assert "不是事實陳述" in admission_problems("被告自認「行車紀錄器資料未載」。", SOURCES)[0]

    def test_quote_from_the_other_side_is_rejected(self):
        # 原告論證裡的話,不能變成被告自承
        problems = admission_problems("被告自承「名下已無其他財產可供清償」。", SOURCES)
        assert "不在該方論證" in problems[0]

    def test_you_means_the_question_target(self):
        text = "你方自承「名下已無其他財產可供清償」,請說明。"
        assert admission_problems(text, SOURCES, target_side="plaintiff") == []
        assert len(admission_problems(text, SOURCES, target_side="defendant")) == 1

    def test_negation_passes(self):
        assert admission_problems("本案無此自認。", SOURCES) == []
        assert admission_problems("原告並未自承任何事實。", SOURCES) == []

    def test_precedent_description_passes(self):
        assert admission_problems("該案債務人自承欠債上億。", SOURCES) == []

    def test_legal_term_passes(self):
        assert admission_problems("依民事訴訟法第279條,訴訟上自認之事實無庸舉證。", SOURCES) == []

    def test_first_person_only_in_arguments(self):
        assert admission_problems("這點我必須坦承。", SOURCES, allow_first_person=True) == []
        assert len(admission_problems("這點我必須坦承。", SOURCES)) == 1

    def test_official_issue_id_is_untouched(self):
        # 組員分支把 plaintiff:dissolved 誤當主張編號拒絕(A2);main 不解析編號,不能出現同樣的錯
        text = "官方事實層(plaintiff:dissolved):程序補正(plaintiff:dissolved)尚未完成,請補提清算人就任聲報。"
        assert admission_problems(text, SOURCES, target_side="plaintiff") == []


def test_strings_in_reads_nested_risk_map():
    assert strings_in({"a": ["x", "y"], "b": {"c": "z"}, "d": 1}) == ["x", "y", "z"]


def test_looks_factual():
    assert looks_factual("請說明被告目前能否提出盤點紀錄")
    assert looks_factual("被告是否持有行車紀錄器")
    assert not looks_factual("依案件所載的 email,是否已足以特定瑕疵")
    assert not looks_factual("時效應自何時起算")
