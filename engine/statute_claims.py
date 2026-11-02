"""找出附有內容描述的條文引用(T8):只抽取，不判斷。

`verify` 只確認條文存在;W0 的法官訊問寫「公司法第23條第3項(公司對負責人訴訟之代表人)」,
條文存在所以 published,但該項不是這個內容。查證 subagent 拿這份清單逐條用
`python main.py article` 讀條文，核對描述是否相符;相不相符由它判斷，這裡不比對內容。

認得三種寫法:
- 括號說明:「X法第N條(…)」。括號內是證據編號、「下稱」、「參照」等就不算描述。
- 依條文規定轉述:「依X法第N條規定，…」「X法第N條規定：「…」」,描述到句末(引號則到對應的右引號)。
- 前文轉述後稱定有明文:「…，X法第N條定有明文。」,描述是同一句引用之前的文字。
- 條文後引號:「X法第N條但書『…』」「X法第N條所稱「…」」,描述是引號內容。
- 括號引用前的說明:「損益相抵(民法第216條之1)」,括號裡只有條文時，描述是括號前到上一個標點的文字。
法規名稱只認名稱索引裡的(與 `verify` 相同);中文數字條號、索引外的法規不列出。
"""
import re

from engine.verify import STATUTE_CITATION_RE

_NUM = r'[0-9一二三四五六七八九十百]+'
# 條號後的項、款、目與前段、但書等，例如「第1項前段」「第2項第3款」
_SUFFIX_RE = re.compile(rf'(?:\s*第\s*{_NUM}\s*[項款目])*(?:\s*(?:前段|後段|但書|本文))?')
# 連寫的其他條號，例如「、第278條第1項」「及同法第185條」
_CHAINED_RE = re.compile(r'\s*[、及與暨和]\s*(?:同法)?\s*第\s*([0-9]+(?:-[0-9]+)?)\s*條(?:\s*之\s*([0-9]+))?')
_PAREN_RE = re.compile(r'\s*[（(]([^（()）]{1,80})[)）]')
_NOT_DESCRIPTION_RE = re.compile(r'^\s*(?:下稱|下同|原證|被證|證物|附件|見|同上)|參照\s*$|^[\s0-9年月日.、/-]+$')
_RULE_RE = re.compile(r'\s*(?:之)?(?:規定|明定)\s*[:：，,]?\s*')
_STATED_RE = re.compile(r'\s*(?:分別|亦)?(?:定有明文|著有明文|規定甚明)')
_SENTENCE_ENDS = '。；;\n'
_LEADING_RE = re.compile(r'^\s*(?:次按|又按|再按|按|又|另|且|依|即)\s*')
_QUOTE_RE = re.compile(r'\s*(?:所稱|所定|規定之|之)?\s*(「[^「」]{1,120}」|『[^『』]{1,120}』)')
_CLOSE_PAREN_RE = re.compile(r'\s*[)）]')
# 括號引用前的說明往前找到這些標點為止，最多 _BEFORE_PAREN_MAX 字
_CLAUSE_BREAKS = '，,;；。、:：\n「」『』()（）'
_BEFORE_PAREN_MAX = 60


def _strings(obj, path=""):
    if isinstance(obj, str):
        yield path or "全文", obj
    elif isinstance(obj, dict):
        for key, value in obj.items():
            yield from _strings(value, f"{path}.{key}" if path else str(key))
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            yield from _strings(value, f"{path}[{i}]")


def _citation_span(text, match):
    """→ (引用結束位置, 條號清單):把項款與連寫的其他條號一起算進引用。"""
    end = _SUFFIX_RE.match(text, match.end()).end()
    articles = [match.article_no]
    while (chained := _CHAINED_RE.match(text, end)):
        articles.append(chained.group(1) + (f"-{chained.group(2)}" if chained.group(2) else ""))
        end = _SUFFIX_RE.match(text, chained.end()).end()
    return end, articles


def _until_sentence_end(text, start):
    if text.startswith("「", start):
        close = text.find("」", start)
        if close != -1:
            return text[start:close + 1]
    ends = [i for i in (text.find(c, start) for c in _SENTENCE_ENDS) if i != -1]
    return text[start:min(ends) if ends else len(text)]


def _before_paren(text, start, end):
    """引用整個包在括號裡時，取括號前的那段說明。"""
    opening = start - 1
    while opening >= 0 and text[opening].isspace():
        opening -= 1
    if opening < 0 or text[opening] not in "(（" or not _CLOSE_PAREN_RE.match(text, end):
        return None
    lower = max(0, opening - _BEFORE_PAREN_MAX)
    clause_start = max([text.rfind(c, lower, opening) for c in _CLAUSE_BREAKS] + [lower - 1]) + 1
    return _LEADING_RE.sub("", text[clause_start:opening]).strip() or None


def _description(text, start, end):
    """→ (描述, 寫法) 或 None。"""
    paren = _PAREN_RE.match(text, end)
    if paren and not _NOT_DESCRIPTION_RE.search(paren.group(1)):
        return paren.group(1).strip(), "括號說明"
    quote = _QUOTE_RE.match(text, end)
    if quote:
        return quote.group(1), "條文後引號"
    rule = _RULE_RE.match(text, end)
    if rule:
        described = _until_sentence_end(text, rule.end()).strip()
        if described:
            return described, "依條文規定轉述"
    if _STATED_RE.match(text, end):
        sentence_start = max(text.rfind(c, 0, start) for c in _SENTENCE_ENDS) + 1
        described = _LEADING_RE.sub("", text[sentence_start:start]).rstrip(" ，,、")
        if described:
            return described, "前文轉述後稱定有明文"
    described = _before_paren(text, start, end)
    if described:
        return described, "括號引用前的說明"
    return None


def statute_claims(payload):
    """在字串或 JSON 結構(評估、書狀、訊問)裡找附有內容描述的條文引用。

    同一引用與描述出現在多處只列一次，`where` 列出所有位置(JSON 路徑，純文字為「全文」)。
    沒有描述的引用不列出。
    """
    found = {}
    for where, text in _strings(payload):
        for match in STATUTE_CITATION_RE.finditer(text):
            end, articles = _citation_span(text, match)
            described = _description(text, match.start(), end)
            if described is None:
                continue
            citation = text[match.start():end]
            key = (citation, described[0])
            if key not in found:
                found[key] = {"citation": citation, "law_name": match.law_name, "articles": articles,
                              "description": described[0], "form": described[1], "where": []}
            if where not in found[key]["where"]:
                found[key]["where"].append(where)
    return list(found.values())
