"""立場驅動 RAG(對應實作規劃 1.4):依 side + case_type 組立場強制檢索詞。

純函數、不碰 DB/LLM/檔案 I/O,同 aggregate.py 的邊界原則。本檔案只負責「組詞」,
不做檢索本身——實際檢索由 subagent 拿著這些詞自行對 corpus/statutes、
corpus/judgments 做 Grep,理由見規劃文件「候選功能」章節:MVP 階段只需要立場關鍵字
組字串,不需要向量語意檢索,語料規模與用途都撐不起也用不到向量 RAG。

MVP 範圍僅民事(對齊五部民事法規與原告/被告律師框架);報告裡刑事的
「成立犯罪/無罪」立場詞留到 Phase 4(刑事模式)才需要，本檔案不處理刑事 side。
"""

VALID_SIDES = ("plaintiff", "defendant")

# 通用立場框架詞:不論案由，原告方一律導向「請求權成立」框架，被告方一律導向
# 「欠缺請求權基礎/抗辯成立」框架——這是原被告立場在任何民事案由下都成立的
# 最小公分母，見規劃文件 1.4 節原文。
_SIDE_FRAME_TERMS = {
    "plaintiff": ["請求權成立", "有理由", "應負賠償責任", "應予給付"],
    "defendant": ["欠缺請求權基礎", "罹於時效", "抗辯成立", "無理由"],
}

# case_type 專屬補充詞，依 database.schema.Case.case_type 欄位常見值對應(該欄位為
# 自由文字，非 enum，見 schema.py 註解「侵權行為/契約不履行/勞資爭議等」)。
# 未收錄的 case_type 不報錯，僅回退為通用框架詞——case_type 分類本來就是開放式的，
# 缺補充詞不代表輸入有誤。
_CASE_TYPE_TERMS = {
    "侵權行為": {
        "plaintiff": ["過失", "因果關係", "損害"],
        "defendant": ["過失相抵", "與有過失", "非可歸責"],
    },
    "契約不履行": {
        "plaintiff": ["債務不履行", "給付遲延", "解除契約"],
        "defendant": ["不可歸責事由", "同時履行抗辯", "契約無效"],
    },
    "勞資爭議": {
        "plaintiff": ["違法解僱", "積欠工資", "資遣費"],
        "defendant": ["合法終止", "懲戒解僱事由", "已為給付"],
    },
}


def build_stance_terms(side, case_type=None):
    """→ 依 side(必附加通用框架詞)+ case_type(有收錄才附加補充詞)組出的檢索詞列表。"""
    if side not in VALID_SIDES:
        raise ValueError(f"非法 side: {side}")
    terms = list(_SIDE_FRAME_TERMS[side])
    if case_type and case_type in _CASE_TYPE_TERMS:
        terms += _CASE_TYPE_TERMS[case_type][side]
    return terms
