"""案件輸入 v2 的結構檢查:純函數、不碰 DB、不呼叫 LLM。內容只整理不改寫,事實一律來自使用者。"""
import datetime
import re

_EVIDENCE_ID_RE = re.compile(r"甲證[1-9][0-9]*(?:-[1-9][0-9]*)?")  # 司法院民事訴訟資料標準化須知:原告證據來源代號「甲」,編號恆定


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _list(value, name):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{name} 必須是清單")
    return value


def _date(value, name):
    """日期選填;有填就要是 YYYY-MM-DD,時效提示才算得出來。"""
    text = _text(value)
    if not text:
        return None
    try:
        datetime.date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"{name} 的日期須為 YYYY-MM-DD:{text}") from None
    return text


def clean_evidence(items):
    cleaned, seen = [], set()
    for item in _list(items, "evidence"):
        if not isinstance(item, dict):
            raise ValueError("evidence 的每一筆都必須是物件")
        evidence_id = _text(item.get("id"))
        if not _EVIDENCE_ID_RE.fullmatch(evidence_id):
            raise ValueError(f"證據編號須為「甲證1」的格式:{evidence_id or '(空白)'}")
        if evidence_id in seen:
            raise ValueError(f"證據編號重複:{evidence_id}")
        seen.add(evidence_id)
        description = _text(item.get("description"))
        if not description:
            raise ValueError(f"{evidence_id} 沒有寫證據內容")
        cleaned.append({"id": evidence_id, "type": _text(item.get("type")) or None, "date": _date(item.get("date"), evidence_id),
                        "description": description, "proves": _text(item.get("proves")) or None})
    return cleaned


def clean_opponent_responses(items):
    cleaned = []
    for item in _list(items, "opponent_known_responses"):
        if not isinstance(item, dict):
            raise ValueError("opponent_known_responses 的每一筆都必須是物件")
        text = _text(item.get("text"))
        if not text:
            raise ValueError("對方已知反應沒有寫內容")
        cleaned.append({"source": _text(item.get("source")) or None, "date": _date(item.get("date"), "對方已知反應"), "text": text})
    return cleaned


def clean_known_gaps(items):
    return [text for text in (_text(item) for item in _list(items, "known_gaps")) if text]


def clean_claim_amount(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("claim_amount 必須是非負整數或留空")
    return value


def clean_represented_side(value):
    """第一期只做原告模式,欄位先留著給被告模式。"""
    if value != "plaintiff":
        raise ValueError("目前只支援代理原告")
    return value
