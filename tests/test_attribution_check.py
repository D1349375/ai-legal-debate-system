"""T10：法官轉述只做可供律師核對的分級，不阻擋落地。"""
from engine.attribution_check import attribution_review


SOURCES = {
    "plaintiff": ["原告 Stage 2 須承認有明顯時效風險。原告 Stage 3 對這一計算表示「不爭執其計算方法」。",
                  "原告稱只有原告說過的句子。"],
    "defendant": ["被告 Stage 2 惟起訴日卷內未載,本方不寫成已逾期。",
                  "被告 Stage 1 甲均待原告舉證,被保全債權存在須有發生基礎。",
                  "被告表示第一片段與第二片段都已提出。"],
    "facts": ["原告與被告均確認契約已簽立。"],
}


def test_unquoted_admission_and_exclusions():
    text = "原告 Stage 2 民法第184條第1項降為純備位,並承認受民法第197條時效風險壓制。"
    result = attribution_review(text, SOURCES)
    assert len(result) == 1
    assert result[0]["kind"] == "unquoted_admission"
    assert result[0]["side"] == "plaintiff"
    assert result[0]["level"] == "unquoted"
    for excluded in (
        "對於讓步條件的逐條回應(均為假設句,非承認)。",
        "被保全債權的「成立」是否須經確定判決或承認。",
        "被告 Stage 3 已更正:不主張須確定判決或承認。",
        "被告並非承認該事實。",
        "被告承認「起訴日卷內未載」。",
    ):
        assert not [r for r in attribution_review(excluded, SOURCES) if r["kind"] == "unquoted_admission"]


def test_quote_exact_close_other_side_missing():
    cases = [
        ("原告 Stage 3 對這一計算表示「不爭執其計算方法」。", "exact"),
        ("被告 Stage 3 自己寫明「起訴日卷內未載,不寫成已逾期」。", "close"),
        ("被告表示「只有原告說過的句子」。", "other_side"),
        ("被告表示「雙方都未說過的句子」。", "missing"),
        ("被告表示「契約已簽立」。", "exact"),
    ]
    for text, level in cases:
        result = attribution_review(text, SOURCES)
        assert len(result) == 1, text
        assert result[0]["level"] == level, text
        assert result[0]["kind"] == "quote"
        if level in ("close", "other_side"):
            assert result[0]["source_snippet"]
        if level == "missing":
            assert result[0]["source_snippet"] == ""


def test_speaker_ignores_earlier_quotes_and_ellipsis():
    text = "被告 Stage 1:「甲均待原告舉證」、「被保全債權存在……須有發生基礎」。"
    result = attribution_review(text, SOURCES)
    assert [r["side"] for r in result] == ["defendant", "defendant"]
    assert result[1]["level"] == "exact"
    assert attribution_review("被告表示「第一片段……丙丁」。", SOURCES)[0]["level"] == "missing"


def test_statute_quote_is_not_party_attribution():
    assert attribution_review("原告依民法第245條規定「雙方都未說過的句子」。", SOURCES) == []


def test_semicolon_keeps_speaker_and_own_close_precedes_other_exact():
    sources = {"plaintiff": ["原告標記為「證據不明/資訊不足,需查證」。"],
               "defendant": ["被告標記為「證據不明,需查證」。"], "facts": []}
    text = "原告最終收斂為公司法第23條;民法第184條降為純備位,並承認受民法第197條時效風險壓制。"
    assert [r["level"] for r in attribution_review(text, sources)] == ["unquoted"]
    assert attribution_review("你方自己也寫「證據不明,需查證」。", sources, "plaintiff")[0]["level"] == "close"


def test_quote_at_start_of_new_clause_is_not_attributed_backward():
    text = "原告主張知悉時點為112年10月12日;「清算人甲的知悉是否歸屬公司」是原告自己也表示尚無案例可引的法律見解。"
    assert attribution_review(text, SOURCES) == []


def test_measured_legal_admission_uses_are_excluded():
    examples = (
        "原告主張部分清償構成民法第129條第1項第2款承認使時效中斷。",
        "原告129條1項2款承認中斷之論述目前站得住腳。",
        "原告以默示合意及承認佐證。",
        "被告未就部分清償是否構成時效中斷之承認此一論點回應。",
    )
    for text in examples:
        assert attribution_review(text, SOURCES) == [], text


def test_quote_containing_full_stop_is_checked():
    # C1 訊問 2 的 based_on(縮短):第一段引號內有「。」,不能因切句而略過
    sources = {"plaintiff": ["原告公司主張其因被告甲違法致公司遭裁處罰鍰200萬元,因而受損,得向被告甲請求賠償。"
                             "現有案件事實僅載「原告公司主張」,賠償責任是否成立為「證據不明/資訊不足,需查證」,待確認。"
                             "原告公司主張被告甲贈與時名下已無其他財產。"],
               "defendant": [], "facts": []}
    text = ("原告 Stage 1:「原告公司主張其因被告甲違法致公司遭裁處罰鍰200萬元……而受損,得向被告甲請求賠償。"
            "現有案件事實僅載『原告公司主張』,賠償責任是否成立……為『證據不明/資訊不足,需查證』,待確認」,"
            "以及「原告公司主張被告甲贈與時名下已無其他財產」。")
    result = attribution_review(text, sources)
    assert [(r["side"], r["level"]) for r in result] == [("plaintiff", "exact"), ("plaintiff", "exact")]
    assert "。現有案件事實" in result[0]["quote"]
    wrong = text.replace("得向被告甲請求賠償。", "得向被告乙請求返還借款。")
    assert attribution_review(wrong, sources)[0]["level"] == "missing"


def test_nested_quote_does_not_end_outer_quote():
    sources = {"plaintiff": [], "facts": [],
               "defendant": ["所謂「知悉」應否以清算人之知悉歸屬於公司,亦有疑義,待確認。除斥期間屬法院應依職權調查事項。"]}
    text = "被告 Stage 1:「所謂『知悉』應否以清算人之知悉歸屬於公司,亦有疑義,待確認。除斥期間屬法院應依職權調查事項」。"
    result = attribution_review(text, sources)
    assert len(result) == 1
    assert result[0]["quote"].endswith("應依職權調查事項")
    assert result[0]["level"] == "exact"
    wrong = attribution_review("被告表示「所謂『知悉』應以起訴狀送達翌日為準,不另計算」。", sources)
    assert [r["level"] for r in wrong] == ["missing"]


def test_unclosed_quote_does_not_swallow_later_quotes():
    result = attribution_review("被告稱「未閉合的引號。被告表示「契約已簽立」。", SOURCES)
    assert [(r["quote"], r["level"]) for r in result] == [("契約已簽立", "exact")]


def test_scattered_single_characters_do_not_make_a_close_quote():
    # 量測到的反例:另一案(車禍)的長句只靠零散單字就達 0.62,不存在的引句不能判成近似
    sources = {"defendant": [], "facts": [], "plaintiff": [
        "被告駕駛自小客車尾隨在後,因低頭操作手機分心而未保持安全距離、未注意車前狀況,追撞完全停等於停止線前之原告車輛,"
        "依道路交通事故初步分析研判表已明確認定被告為肇事主因、原告無肇事因素,被告就本件交通事故之發生具有過失,"
        "且其過失行為與原告所受車輛毀損、頸部扭傷(甩鞭症候群)及後續復健需求、薪資損失間具相當因果關係,"
        "原告之侵權行為損害賠償請求權已然成立,被告應就車輛維修費新臺幣8萬元、醫療復健費用新臺幣3萬5千元、"
        "薪資損失新臺幣2萬元(合計13萬5千元之財產上損害),暨精神慰撫金新臺幣5萬元(非財產上損害),共計18萬5千元,"
        "負賠償責任,並自起訴狀繕本送達翌日起至清償日止依法定利率年息5%給付利息。"]}
    assert attribution_review("原告表示「名下已無其他財產」。", sources)[0]["level"] == "missing"


def test_c1_lowest_close_quote_stays_close():
    sources = {"plaintiff": ["原告主張被保全債權只須於行為前有發生之基礎即屬已成立。"], "defendant": [], "facts": []}
    assert attribution_review("原告主張「須有發生基礎」。", sources)[0]["level"] == "close"


def test_quote_found_only_in_concession_condition_is_its_own_level():
    # W0 唯一的誤報:法官逐字引原告讓步條件。公開原文找不到、但該方 falsifier 逐字有 → 另列一級,不算警告
    from engine.attribution_check import attribution_warnings
    sources = {"plaintiff": ["原告主張已補正法定代理人。"], "defendant": [], "facts": [],
               "falsifier": {"plaintiff": ["若逾期未補正,起訴不合法,本方即撤回此部分主張。"], "defendant": ["被告的讓步條件。"]}}
    result = attribution_review("原告的讓步條件寫明「若逾期未補正,起訴不合法」。", sources)
    assert [r["level"] for r in result] == ["falsifier"]
    assert result[0]["source_snippet"].startswith("若逾期未補正")
    assert attribution_warnings(result) == []
    # 只在另一方的讓步條件 → 仍是 missing
    assert attribution_review("被告的讓步條件寫明「若逾期未補正,起訴不合法」。", sources)[0]["level"] == "missing"


def test_compressed_concession_condition_from_w0():
    # W0 的法官把讓步條件壓縮後引述;同一套近似規則套用到讓步條件
    sources = {"plaintiff": ["原告主張已補正法定代理人。"], "defendant": [], "facts": [],
               "falsifier": {"plaintiff": ["若查明罰鍰全屬公司自身違法所致,則被保全債權不成立;"
                                           "若清算人資料顯示丙無代表權且逾期未補正,則本案起訴不合法。"], "defendant": []}}
    result = attribution_review("原告的條件中「若逾期未補正,起訴不合法」這條,與程序事項最直接相關。", sources)
    assert [r["level"] for r in result] == ["falsifier"]
    assert "逾期未補正,則本案起訴不合法" in result[0]["source_snippet"]
