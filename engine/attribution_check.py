"""法官轉述的決定性文字比對；僅供律師核對，不判定語意或阻擋落地。"""
import re
from difflib import SequenceMatcher

from engine.admission_check import _sentences

_PAIRS = {"「": "」", "『": "』", "“": "”", '"': '"'}
_SPEAKERS = re.compile(r"原告|被告|你方|對造")
_LEGAL_QUOTE = re.compile(r"第[一二三四五六七八九十百千零〇\d]+條|判決|裁定|判例|規定")
_NEGATED = re.compile(r"(?:並非|不構成|不等於|不是|非|不|未)\s*$")
_LEGAL_ADMISSION = re.compile(
    r"確定判決或\s*$|債務之\s*$|視為\s*$|時效中斷之\s*$"
    r"|第?\d+款\s*$|默示合意及\s*$"
)
_PUNCT = re.compile(r"[\s,，。;；:：、()（）『』「」“”\"!?！？/]")
_ELLIPSIS = re.compile(r"(?:……|…|\.\.\.)+")
_WARNING = {"other_side", "missing", "unquoted"}
_CLOSE_THRESHOLD = 0.60


def _norm(text):
    return _PUNCT.sub("", text)


def _quote_spans(text):
    """最外層引號的 (開引號位置, 關引號後一位)。『』在「」裡不結束外層；沒閉合的開引號當一般字。"""
    spans, stack = [], []
    for i, ch in enumerate(text):
        closing = [k for k, j in enumerate(stack) if _PAIRS[text[j]] == ch]
        if closing:
            # 內層漏寫關引號時，外層的關引號一併結束內層
            start = stack[closing[-1]]
            del stack[closing[-1]:]
            if not stack:
                spans.append((start, i + 1))
        elif ch in _PAIRS:
            stack.append(i)
    if stack:
        bad = stack[0] + 1
        spans += [(a + bad, b + bad) for a, b in _quote_spans(text[bad:])]
    return spans


def _strip_quotes(text):
    for a, b in reversed(_quote_spans(text)):
        text = text[:a] + text[b:]
    return text


def _split_outside_quotes(text):
    """在引號外的「。」與換行切句；引號裡的句號不切，否則開關引號會落在不同句而整個略過。"""
    inside = set()
    for a, b in _quote_spans(text):
        inside.update(range(a, b))
    sentences, start = [], 0
    for i, ch in enumerate(text):
        if ch in "。\n" and i not in inside:
            sentences.append(text[start:i + 1])
            start = i + 1
    sentences.append(text[start:])
    return sentences


def _speaker(prefix, target_side):
    # 引號裡可能提到另一方；找說話者前必須去掉同一句較早的引號。
    clean = _strip_quotes(prefix)
    found = list(_SPEAKERS.finditer(clean))
    if not found:
        return None, ""
    last = found[-1]
    word = last.group()
    if word == "原告":
        side = "plaintiff"
    elif word == "被告":
        side = "defendant"
    elif word == "你方":
        side = target_side
    else:
        side = {"plaintiff": "defendant", "defendant": "plaintiff"}.get(target_side)
    return side, clean[last.end():]


def _source_texts(sources, side):
    return list(sources.get("facts", [])) + list(sources.get(side, []))


def _score(quote, original):
    # 只計 2 字以上的連續相同片段：長句裡零散的單字會讓不存在的引句也達門檻(跨案件反例量測)。
    blocks = SequenceMatcher(None, quote, _norm(original), autojunk=False).get_matching_blocks()
    return sum(block.size for block in blocks if block.size >= 2) / max(len(quote), 1)


def _closest(quote, texts):
    candidates = [s.strip() for text in texts for s in _sentences(text) if s.strip()]
    return max(candidates, key=lambda s: _score(quote, s), default="")


def attribution_review(text, sources, target_side=None):
    """回傳轉述的分級與可對照原文；sources 同 attribution_sources(admission_sources 另加 "falsifier")。"""
    result = []
    # 分號連接的後半句常省略說話者（C1 的「並承認」即如此）。
    for sentence in _split_outside_quotes(text or ""):
        sentence = sentence.strip()
        for start, end in _quote_spans(sentence):
            side, between = _speaker(sentence[:start], target_side)
            if not side or ";" in between or "；" in between or _LEGAL_QUOTE.search(between):
                continue
            quote = sentence[start + 1:end - 1]
            parts = [_norm(p) for p in _ELLIPSIS.split(quote) if _norm(p)]
            if not parts:
                continue
            own = _source_texts(sources, side)
            other = _source_texts(sources, "defendant" if side == "plaintiff" else "plaintiff")
            if any(all(p in _norm(s) for p in parts) for s in own):
                level, snippet = "exact", ""
            elif len(parts) > 1:
                # 省略號表示摘錄；每一片段必須在同一份原文找到。
                if any(all(p in _norm(s) for p in parts) for s in other):
                    level, snippet = "other_side", _closest(max(parts, key=len), other)
                else:
                    level, snippet = "missing", ""
            else:
                nearest = _closest(max(parts, key=len), own)
                score = max((_score(p, nearest) for p in parts), default=0)
                if score >= _CLOSE_THRESHOLD:
                    level, snippet = "close", nearest
                elif any(all(p in _norm(s) for p in parts) for s in other):
                    level, snippet = "other_side", _closest(_norm(quote), other)
                else:
                    level, snippet = "missing", ""
            conditions = sources.get("falsifier", {}).get(side, [])
            if level == "missing" and conditions:
                # 法官範本要求逐條回應讓步條件；引到該方讓步條件(假設句，逐字或達近似門檻)時標明出處，不算警告。
                nearest = _closest(max(parts, key=len), conditions)
                if (any(all(p in _norm(s) for p in parts) for s in conditions)
                        or (len(parts) == 1 and _score(parts[0], nearest) >= _CLOSE_THRESHOLD)):
                    level, snippet = "falsifier", nearest
            result.append({"kind": "quote", "side": side, "sentence": sentence, "quote": quote,
                           "level": level, "source_snippet": snippet})

        for match in re.finditer("承認", sentence):
            side, between = _speaker(sentence[:match.start()], target_side)
            if not side or _NEGATED.search(between) or _LEGAL_ADMISSION.search(between):
                continue
            if re.match(r"\s*[「『“\"]", sentence[match.end():]):
                continue
            if sentence[match.end():].startswith("受領"):
                continue
            result.append({"kind": "unquoted_admission", "side": side, "sentence": sentence,
                           "quote": "", "level": "unquoted", "source_snippet": ""})
    return result


def attribution_warnings(items):
    return [item for item in items if item["level"] in _WARNING]
