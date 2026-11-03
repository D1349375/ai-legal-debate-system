"""對手摘要的機械檢查(T9):純函數、不碰 DB、不呼叫 LLM、只產生警告。

W0 實跑時，主 agent 寫給對手的摘要把被告「被告若主張更早知悉，則由被告就更早知悉負反證責任。」選成最強論點;
那是條件句，也是舉證責任的讓步句，對方因此把它寫成被告「自承」。摘要檔由主 agent 寫，原本沒有程式檢查點。

只能確認：最強論點是該方該階段公開論證裡的原句、沒有條件或讓步字樣、引用都在該方該階段的清單裡、
書狀交換流程取的是對造 stage 2。選的句子是不是「最強」、是不是「正面主張」，程式判斷不了，換個詞就檢查不到。
"""
import re
import unicodedata

from engine.admission_check import _SOFT_RE, _norm

VALID_SIDES = ("plaintiff", "defendant")

# 條件或讓步的開頭詞。_SOFT_RE 已有 若、倘、如果、假設、縱使、除非 與自我評估字樣，這裡補上它沒有的連詞。
_CONDITION_RE = re.compile(r"即使|縱然|縱令|倘若|設若|假若|假使|如謂|若謂")
# 舉證責任分配的說明(不是對事實的主張)。「由…舉證」放最後，讓「負反證責任」這類完整詞先被指出
_BURDEN_RES = (re.compile(r"負(?:舉證|反證|證明)(?:之)?責任?"), re.compile(r"(?:舉證|反證|證明)之責"),
               re.compile(r"(?:舉證|反證|證明)責任(?:分配|之分配|在於|歸)"), re.compile(r"由[^,，。;；]{0,12}(?:舉證|反證)"))


def validate_summary(data):
    """檢查摘要檔的最小格式，回傳補好預設值的 dict。格式錯誤丟 ValueError(訊息就是要印給使用者的原因)。"""
    if not isinstance(data, dict):
        raise ValueError("摘要檔最外層必須是 JSON 物件")
    if data.get("side") not in VALID_SIDES:
        raise ValueError("side 必須是 plaintiff 或 defendant(被摘要的那一方)")
    stage = data.get("stage")
    if isinstance(stage, bool) or stage not in (1, 2, 3):
        raise ValueError("stage 必須是整數 1、2 或 3")
    # T9:實跑的摘要檔寫的是 strongest_point_verbatim,兩個名字都收;兩個都給又不同就不知道該檢查哪一句
    verbatim = data.get("strongest_point_verbatim")
    if verbatim is not None:
        if data.get("strongest_point") not in (None, verbatim):
            raise ValueError("strongest_point 與 strongest_point_verbatim 不同,只留一個")
        data = {**data, "strongest_point": verbatim}
    for key in ("position", "strongest_point"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f"{key} 必須是非空字串")
    for key in ("cited_statutes", "cited_precedents"):
        value = data.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ValueError(f"{key} 必須是字串清單")
    if not isinstance(data.get("no_clear_claim", False), bool):
        raise ValueError("no_clear_claim 必須是 true 或 false")
    return {**data, "cited_statutes": data.get("cited_statutes", []), "cited_precedents": data.get("cited_precedents", []),
            "no_clear_claim": data.get("no_clear_claim", False)}


def _compare_form(text):
    """比對用字串:全形轉半形後，去掉空白與標點(同 admission_check 的 _norm)。"""
    return _norm(unicodedata.normalize("NFKC", text or ""))


_SENTENCE_END_RE = re.compile(r"[。！？!?；;\n]+")


def _is_whole_sentences(point, text):
    """point 是不是 text 裡完整的一句或連續幾句。只比子字串的話，去掉「惟…待確認」的前半句也會過。"""
    target = _compare_form(point)
    sentences = [s for s in (_compare_form(x) for x in _SENTENCE_END_RE.split(text or "")) if s]
    for i in range(len(sentences)):
        joined = ""
        for s in sentences[i:]:
            joined += s
            if joined == target:
                return True
            if not target.startswith(joined):
                break
    return False


def _wording_matches(sentence):
    """回傳 (條件或讓步字樣, 舉證責任分配字樣) 兩個 list。"""
    soft = sorted({m.group(0) for regex in (_SOFT_RE, _CONDITION_RE) for m in regex.finditer(sentence)})
    burden, spans = [], []
    for regex in _BURDEN_RES:
        for m in regex.finditer(sentence):
            if not any(m.start() < end and start < m.end() for start, end in spans):  # 已被前面的詞涵蓋的不重複列
                burden.append(m.group(0))
                spans.append(m.span())
    return soft, burden


def summary_warnings(summary, arguments, protocol=None):
    """回傳警告(字串 list)，空 list 代表沒有問題。

    summary: validate_summary 的結果。arguments: public_arguments 的回傳(已濾掉內部檢討)。
    protocol: 案件的 protocol，"v2" 是書狀交換流程。
    """
    warnings = []
    side, stage, point = summary["side"], summary["stage"], summary["strongest_point"]

    if protocol == "v2" and stage != 2:
        warnings.append(f"書狀交換流程的對手摘要只該取對造 stage 2(規格 5.6)，這份取的是 stage {stage}")

    rows = [r for r in arguments if r["side"] == side and r["stage"] == stage]
    if not rows:
        warnings.append(f"資料庫沒有{side} stage {stage} 的公開論證，無法比對最強論點與引用")
    else:
        texts = [t for r in rows for t in (r.get("position"), r.get("argument"))]
        if not any(_is_whole_sentences(point, t) for t in texts):
            warnings.append(f"最強論點不是原句:「{point}」不是{side} stage {stage} 公開論證(position 或論證本文)裡完整的一句或連續幾句，"
                            "不得改寫、合併或只取半句")
        listed = {key: {_compare_form(c) for r in rows for c in r.get(key) or []} for key in ("cited_statutes", "cited_precedents")}
        for key, label in (("cited_statutes", "法條"), ("cited_precedents", "判例")):
            extra = [c for c in summary[key] if _compare_form(c) not in listed[key]]
            if extra:
                warnings.append(f"摘要的{label}有不在{side} stage {stage} 引用清單的項目:" + "、".join(f"「{c}」" for c in extra))

    if summary["no_clear_claim"]:
        warnings.append("摘要標了「無明確主張句」，最強論點是最接近 position 的一句，不是正面主張句，請律師留意")
    else:
        soft, burden = _wording_matches(point)
        found = [f"條件或讓步字樣:{'、'.join(soft)}"] if soft else []
        found += [f"舉證責任分配:{'、'.join(burden)}"] if burden else []
        if found:
            warnings.append("最強論點含" + "；".join(found) + "。應選該方正面主張句(主張某要件成立或不成立、某法律效果);"
                            "找不到時選最接近 position 的一句並標「無明確主張句」，不要改寫")
    return warnings
