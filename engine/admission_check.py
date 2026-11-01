"""自承類用語的機械檢查:純函數、不碰 DB、不呼叫 LLM。

法官要寫某方「自承/自認/自陳/坦承」，必須緊接引述該方原句，原句要逐字出現在該方論證或
案件資料，且不是假設句、自我評估或「資料未載」(2026-11-01 查到錄製案件把這些寫成承認)。
只能確認原句存在，無法判斷解讀是否正確，換個詞(例如「被告已表示」)也檢查不到。
"""
import re

_WORD = r"(?:自承|自認|自陳|坦承)"
ADMISSION_RE = re.compile(_WORD)
_QUOTED_RE = re.compile(r"[^,，。;；『「“\"]{0,6}[『「“\"]([^』」”\"]{4,})[』」”\"]")
_NEGATED_RE = re.compile(r"(?:並未|未曾|沒有|無此|不構成|不等於|不得寫成|未|無|非)[^,，。;；]{0,2}$")
_PRECEDENT_RE = re.compile(r"(?:該案|該判決|該裁定|另案)[^,，。;；]{0,12}$")
_LEGAL_TERM_RE = re.compile(r"自認之效力|訴訟上自認|裁判上自認|第279條")
_FIRST_PERSON_RE = re.compile(r"(?:我|本方)[^,，。;；]{0,6}$")
_SPEAKER_RE = re.compile(r"原告|被告|你方")
# 原句有這些字，就是假設、自我評估或資料缺口，不是對事實的陳述
_SOFT_RE = re.compile(r"若|倘|如果|假設|縱使|除非|弱點|風險|不利|薄弱|待確認|待查|未載|資料未|尚未確認|未見")
_FACTUAL_RE = re.compile(r"是否持有|能否提出|可否提出|有無(?:提出|證據)|有沒有|是否(?:保有|存有|握有)|手上")
_SIDE_OF = {"原告": "plaintiff", "被告": "defendant"}


def _sentences(text):
    return [s for s in re.split(r"(?<=[。;；\n])", text or "") if s.strip()]


def _norm(text):
    return re.sub(r"[\s,，。;；:：、『』「」“”\"]", "", text)


def _source_sentences(sources, speaker):
    sides = [speaker] if speaker in ("plaintiff", "defendant") else ["plaintiff", "defendant"]
    texts = list(sources.get("facts", []))
    for side in sides:
        texts += sources.get(side, [])
    return [s for text in texts for s in _sentences(text)]


def _speaker(prefix, target_side):
    found = _SPEAKER_RE.findall(prefix)
    if not found:
        return None
    return target_side if found[-1] == "你方" else _SIDE_OF[found[-1]]


def admission_problems(text, sources, target_side=None, allow_first_person=False):
    """回傳不成立的自承類用語(問題說明的 list)，空 list 代表沒有問題。

    sources: {"plaintiff": [...], "defendant": [...], "facts": [...]}，論證不含 falsifier(假設句)。
    target_side: 訊問的對象，用來解讀句中的「你方」。
    allow_first_person: 雙方論證裡「我坦承」是自己說的話，不算轉述對方。
    """
    problems = []
    for sentence in _sentences(text):
        if _LEGAL_TERM_RE.search(sentence):
            continue
        for match in ADMISSION_RE.finditer(sentence):
            prefix = sentence[:match.start()]
            if _NEGATED_RE.search(prefix) or _PRECEDENT_RE.search(prefix):
                continue
            if allow_first_person and _FIRST_PERSON_RE.search(prefix):
                continue
            snippet = sentence[max(0, match.start() - 20):match.end() + 30].strip()
            quote = _QUOTED_RE.match(sentence, match.end())
            if not quote:
                problems.append(f"「{snippet}」沒有緊接引述原句")
                continue
            target = _norm(quote.group(1))
            found = [s for s in _source_sentences(sources, _speaker(prefix, target_side)) if target in _norm(s)]
            if not found:
                problems.append(f"「{snippet}」引述的原句不在該方論證或案件資料")
            elif all(_SOFT_RE.search(s) for s in found):
                problems.append(f"「{snippet}」的原句是假設、自我評估或資料缺口，不是事實陳述")
    return problems


def strings_in(value):
    """取出巢狀 dict/list 裡的所有字串(risk_map 是巢狀結構，直接轉 JSON 會把引號跳脫)。"""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        value = list(value.values())
    if isinstance(value, list):
        return [s for v in value for s in strings_in(v)]
    return []


def looks_factual(question_text):
    """疑似要被告回答事實的訊問。靠關鍵字，會誤判，只能用來警告。"""
    return bool(_FACTUAL_RE.search(question_text or ""))
