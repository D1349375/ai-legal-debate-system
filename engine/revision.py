"""P6 起訴狀 v2(規格 5.7):被告推測的內容不得寫進 v2。純函數、不碰 DB、不呼叫 LLM。

被告推測的內容來自三處:答辯狀 `defenses` 中 `hypothetical: true` 的 `statement`;`responses` 中 `hypothetical: true`
或 `ground = alternative_explanation` 的 `reason`(另一解釋一定是推測,不依賴旗標);爭點整理表 `hypothetical: true`
的爭點 `defendant_defense`。

- 整段推測文字(去標點與空白後)出現在 v2 的 `fact_points` 或 `legal_argument`:結構規則,硬擋,退回改寫 subagent。
- 推測文字有連續 MIN_CLAUSE 字以上相同(不是整段):可能是改寫後引用,也可能是正當回應,只警告。
- 確認版起訴狀本來就有的文字是原告自己的話,不算被告推測。
- 太短的推測文字(去標點後少於 MIN_BLOCK 字)不比對,避免「已清償」這類字詞誤擋。
"""
import unicodedata
from difflib import SequenceMatcher

from engine.pleading_render import stored_complaint

MIN_BLOCK = 6  # 整段比對的最短長度
MIN_CLAUSE = 8  # 部分相同只警告的最短長度


def norm(text):
    """去掉空白與所有標點(Unicode 類別 P*),只比對文字本身。比 engine/admission_check.py 的 _norm 寬:那裡只去常見標點。"""
    return "".join(ch for ch in text or "" if not ch.isspace() and not unicodedata.category(ch).startswith("P"))


def opponent_hypotheticals(answer, sheet):
    """answer 是答辯狀的 structured_json(dict 或 None),sheet 是爭點整理表 JSON(dict 或 None)。回傳推測文字,依出現順序、不重複。"""
    texts = []
    for item in (answer or {}).get("defenses") or []:
        if isinstance(item, dict) and item.get("hypothetical") is True and isinstance(item.get("statement"), str):
            texts.append(item["statement"])
    for item in (answer or {}).get("responses") or []:
        if not isinstance(item, dict) or not isinstance(item.get("reason"), str):
            continue
        if item.get("hypothetical") is True or item.get("ground") == "alternative_explanation":
            texts.append(item["reason"])
    for item in (sheet or {}).get("issues") or []:
        if isinstance(item, dict) and item.get("hypothetical") is True and isinstance(item.get("defendant_defense"), str):
            texts.append(item["defendant_defense"])
    return list(dict.fromkeys(t.strip() for t in texts if t.strip()))


def _fields(payload):
    """v2 要比對的欄位:(標籤, 文字)。"""
    out = []
    for point in payload.get("fact_points") or []:
        if isinstance(point, dict) and isinstance(point.get("text"), str):
            out.append((f"fact_points {point.get('id')}", point["text"]))
    if isinstance(payload.get("legal_argument"), str):
        out.append(("legal_argument", payload["legal_argument"]))
    return out


def hypothetical_problems(payload, hypotheticals, *, confirmed_text=""):
    """整段推測文字寫進 v2 的 fact_points 或 legal_argument:回傳退回原因(硬擋);空清單代表通過。"""
    if not isinstance(payload, dict):
        return []
    known = norm(confirmed_text)
    problems = []
    for label, text in _fields(payload):
        body = norm(text)
        for guess in hypotheticals:
            key = norm(guess)
            if len(key) >= MIN_BLOCK and key in body and key not in known:
                problems.append(f"{label} 寫進了被告推測的內容「{guess}」;被告推測不得寫進起訴狀 v2,"
                                "要提醒律師的放 lawyer_notes 或 fact_gaps")
    return problems


def hypothetical_warnings(payload, hypotheticals, *, confirmed_text=""):
    """推測文字有連續 MIN_CLAUSE 字以上出現在 v2(但不是整段):只警告,請律師確認不是把被告推測改寫成原告主張。"""
    if not isinstance(payload, dict):
        return []
    known = norm(confirmed_text)
    warnings = []
    for label, text in _fields(payload):
        body = norm(text)
        for guess in hypotheticals:
            key = norm(guess)
            if len(key) >= MIN_BLOCK and key in body:
                continue  # 整段寫進去的已硬擋
            m = SequenceMatcher(None, key, body, autojunk=False).find_longest_match(0, len(key), 0, len(body))
            shared = key[m.a:m.a + m.size]
            if m.size >= MIN_CLAUSE and shared not in known:
                warnings.append(f"{label} 有一段和被告推測「{guess}」相同:「{shared}」,請確認不是把推測寫成原告主張")
    return warnings


def stored_revision(payload, parent_id):
    """落地進 structured_json 的內容:同 P1 起訴狀(stored_complaint),再加上 parent_id(確認版的 version_id)。"""
    return {**stored_complaint(payload), "parent_id": parent_id}
