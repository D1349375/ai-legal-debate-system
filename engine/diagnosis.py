"""P6 診斷(規格 5.7):`risk_map` 新鍵的結構檢查與勝訴機率類字樣警告。純函數、不碰 DB、不呼叫 LLM。

舊鍵(對原告不利之處、對被告不利之處、建議補強證據)照舊保留,這裡不檢查。新鍵每筆的欄位由本檔定義(待組長確認):

    issue_assessment:      [{issue_id, strength: 強|中|弱, reason}]   爭點整理表的每個爭點有且只有一筆
    evidence_todo:         [{issue_id, missing, why}]   issue_id 是爭點,或程序事項「官方事實層(<id>)」(程序先於實體)
    complaint_revisions:   [{fact_id: CF 或 null, kind: revise|add_alternative|delete, suggestion}]   revise 一定要有 fact_id
    fact_gaps:             [str]
    opponent_hypotheticals: [str]

結構規則硬擋(退回法官 subagent);勝訴機率類字樣是自然語言規則,只警告。
"""
import re

V2_KEYS = ("issue_assessment", "evidence_todo", "complaint_revisions", "fact_gaps", "opponent_hypotheticals")
STRENGTHS = ("強", "中", "弱")
REVISION_KINDS = ("revise", "add_alternative", "delete")
_PROCEDURAL_RE = re.compile(r"^官方事實層\([^()]+\)$")  # 和訊問 based_on 的程序事項前綴同一寫法

_PROB = r"(?:勝訴|敗訴|勝算|贏|輸|機率|機會|可能|把握|成功)"
_NUMBER = r"(?:\d+(?:\.\d+)?\s*[%％]|百分之[〇零一二兩三四五六七八九十百\d]+|[一二三四五六七八九十]成)"
WIN_PROBABILITY_RE = re.compile(
    r"勝訴機率|敗訴機率|勝訴率|敗訴率|勝訴可能性|敗訴可能性|勝算|勝率|贏面"
    rf"|{_NUMBER}[^。;；\n]{{0,6}}{_PROB}|{_PROB}[^。;；\n]{{0,6}}{_NUMBER}")


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _records(risk_map, key, fields, problems):
    value = risk_map.get(key)
    if not isinstance(value, list):
        problems.append(f"risk_map.{key} 必須是陣列")
        return []
    out = []
    for i, item in enumerate(value, 1):
        if not isinstance(item, dict):
            problems.append(f"risk_map.{key} 第 {i} 筆不是物件")
            continue
        for field in fields:
            if not _text(item.get(field)):
                problems.append(f"risk_map.{key} 第 {i} 筆的 {field} 不可空白")
        out.append((i, item))
    return out


def verdict_v2_problems(risk_map, *, issue_ids, fact_ids):
    """issue_ids 是爭點整理表的爭點 id;fact_ids 是確認版起訴狀正文的 CF。回傳退回原因;空清單代表通過。"""
    if not isinstance(risk_map, dict):
        return ["risk_map 必須是 JSON 物件"]
    problems, issues, facts = [], list(issue_ids or []), set(fact_ids or [])
    assessed = set()
    for i, item in _records(risk_map, "issue_assessment", ("reason",), problems):
        issue = item.get("issue_id")
        if issue not in issues:
            problems.append(f"risk_map.issue_assessment 第 {i} 筆的 issue_id {issue!r} 不在爭點整理表"
                            f"(爭點:{'、'.join(issues) or '無'})")
        elif issue in assessed:
            problems.append(f"risk_map.issue_assessment 的 {issue} 重複,每個爭點只能有一筆")
        else:
            assessed.add(issue)
        if item.get("strength") not in STRENGTHS:
            problems.append(f"risk_map.issue_assessment 第 {i} 筆的 strength 只能是 {'、'.join(STRENGTHS)}:"
                            f"{item.get('strength')!r}")
    if isinstance(risk_map.get("issue_assessment"), list):
        problems += [f"risk_map.issue_assessment 缺少爭點 {issue} 的評估" for issue in issues if issue not in assessed]
    for i, item in _records(risk_map, "evidence_todo", ("missing", "why"), problems):
        issue = item.get("issue_id")
        if issue not in issues and not (isinstance(issue, str) and _PROCEDURAL_RE.match(issue)):
            problems.append(f"risk_map.evidence_todo 第 {i} 筆的 issue_id {issue!r} 不在爭點整理表"
                            f"(程序事項寫「官方事實層(<id>)」)")
    for i, item in _records(risk_map, "complaint_revisions", ("suggestion",), problems):
        kind, fact = item.get("kind"), item.get("fact_id")
        if kind not in REVISION_KINDS:
            problems.append(f"risk_map.complaint_revisions 第 {i} 筆的 kind 只能是 {'、'.join(REVISION_KINDS)}:{kind!r}")
        if fact is None:
            if kind == "revise":
                problems.append(f"risk_map.complaint_revisions 第 {i} 筆是 revise,要寫要改哪一個 CF(fact_id)")
        elif fact not in facts:
            problems.append(f"risk_map.complaint_revisions 第 {i} 筆的 fact_id {fact!r} 不在確認版起訴狀"
                            f"(CF:{'、'.join(sorted(facts)) or '無'})")
    for key in ("fact_gaps", "opponent_hypotheticals"):
        value = risk_map.get(key)
        if not isinstance(value, list) or not all(_text(x) for x in value):
            problems.append(f"risk_map.{key} 必須是字串陣列(每筆不可空白)")
    return problems


def _strings(value, where):
    if isinstance(value, str):
        yield where, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(item, f"{where}.{key}")
    elif isinstance(value, list):
        for i, item in enumerate(value, 1):
            yield from _strings(item, f"{where}[{i}]")


def win_probability_warnings(payload):
    """診斷文字(verdict_main_text、verdict_analysis、risk_map 的所有字串)含勝訴機率類字樣時的警告。規格:不給勝訴機率。"""
    warnings = []
    for key in ("verdict_main_text", "verdict_analysis", "verdict_reasoning", "risk_map"):
        if key not in (payload or {}):
            continue
        for where, text in _strings(payload[key], key):
            hits = list(dict.fromkeys(m.group(0) for m in WIN_PROBABILITY_RE.finditer(text)))
            if hits:
                warnings.append(f"{where} 含勝訴機率類字樣「{'」「'.join(hits)}」;診斷只給爭點強弱,不給勝訴機率,請確認")
    return warnings
