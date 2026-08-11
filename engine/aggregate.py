"""機械聚合層:攻防弱點彙整與立場位移統計。

純函數、不碰 DB、不呼叫 LLM——同 DebateSystem 的邊界原則，法官 Stage 4 的判決敘述
不得偏離這裡算出來的錨點方向(見 database/schema.py 的 Verdict.mechanical_anchor_json)。

輸入的每個 argument 皆為 dict，欄位對應 database.schema.DebateArgument 落地後的內容
(cited_statutes/cited_precedents 已由呼叫端從 JSON 字串解析為 list，本檔案不處理 JSON)。
"""

VALID_SIDES = ("plaintiff", "defendant")


def compile_weak_points(stage3_arguments):
    """stage3_arguments: list of {side, reasoning, falsifier} → 排序過的弱點清單。

    每一方在 stage3 的 falsifier(「若對方補上何種證據，我方將讓步」)本質上就是
    這一方案件的弱點所在，機械彙整、不做語意判斷。排序鍵:有 falsifier 的排前面
    (代表這一方有明確、可稽核的弱點)，同層再依 side 字母序排列，確保結果決定性。
    """
    if not stage3_arguments:
        raise ValueError("stage3_arguments 不可為空")
    points = []
    for arg in stage3_arguments:
        side = arg.get("side")
        if side not in VALID_SIDES:
            raise ValueError(f"非法 side: {side}")
        points.append({
            "side": side,
            "falsifier": arg.get("falsifier"),
            "response_excerpt": arg.get("reasoning"),
        })
    points.sort(key=lambda p: (p["falsifier"] is None, p["side"]))
    return points


def disagreement(stage1_arguments, stage3_arguments):
    """依「引用法條/判例集合」在 stage1→stage3 間的變化量，衡量各方立場位移程度。

    position/reasoning 為自由文字，非結構化方向欄位(不同於 DebateSystem 的 Bullish/
    Bearish/Neutral)，無法在不呼叫 LLM 的前提下做語意比對；改用兩階段引用集合的
    Jaccard 距離作為機械可算的位移代理指標——新增/放棄的法律依據代表實質論證變化，
    單純用字遣詞不同則不計入。回傳 {side: drift_ratio}，drift_ratio 範圍 0-1，
    0 代表兩階段引用集合完全相同、1 代表完全不重疊。單方缺席任一階段時該方回傳 None。
    """
    def by_side(arguments):
        result = {}
        for arg in arguments:
            side = arg.get("side")
            if side not in VALID_SIDES:
                raise ValueError(f"非法 side: {side}")
            citations = set(arg.get("cited_statutes") or []) | set(arg.get("cited_precedents") or [])
            result[side] = citations
        return result

    s1 = by_side(stage1_arguments)
    s3 = by_side(stage3_arguments)

    drift = {}
    for side in VALID_SIDES:
        if side not in s1 or side not in s3:
            drift[side] = None
            continue
        set1, set3 = s1[side], s3[side]
        if not set1 and not set3:
            drift[side] = 0.0
            continue
        union = set1 | set3
        intersection = set1 & set3
        drift[side] = round(1 - len(intersection) / len(union), 4)
    return drift
