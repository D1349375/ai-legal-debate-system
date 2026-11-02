"""P3 法官的爭點整理表(規格 5.5):結構檢查與官方四張表的文字版。純函數、不碰 DB、不呼叫 LLM。

結構問題硬擋(退回法官 subagent);推測標示不一致、要被告回答事實這類只警告。
四張表照司法院民事訴訟標準化須知例示:聲明與請求權基礎清單、預期不爭執事項、爭點整理表、證據清單。
"""
import re

from engine import fact_points as cf
from engine.admission_check import looks_factual
from engine.verify import parse_citation

KINDS = ("fact", "law", "defense")  # 事實爭點、法律爭點、抗辯
BURDENS = ("plaintiff", "defendant", "undetermined")
SIDES = ("plaintiff", "defendant")
OFFICIAL_PREFIX = "官方事實層("
BURDEN_LABEL = {"plaintiff": "原告", "defendant": "被告", "undetermined": "未定"}
_ISSUE_REF_RE = re.compile(r"^\s*([A-Za-z]\w*)\s*[:：]")


def _str(value):
    return isinstance(value, str) and value.strip() != ""


def _str_list(value):
    return isinstance(value, list) and all(isinstance(x, str) for x in value)


def _list_of(sheet, key, problems):
    value = sheet.get(key, [])
    if not isinstance(value, list):
        problems.append(f"{key} 必須是陣列")
        return []
    bad = [i for i, item in enumerate(value, 1) if not isinstance(item, dict)]
    problems += [f"{key} 第 {i} 筆不是物件" for i in bad]
    return [item for item in value if isinstance(item, dict)]


def _ids(items, label, problems):
    seen = []
    for i, item in enumerate(items, 1):
        if not _str(item.get("id")):
            problems.append(f"{label} 第 {i} 筆沒有 id")
        elif item["id"] in seen:
            problems.append(f"{label} 的 id {item['id']} 重複")
        else:
            seen.append(item["id"])
    return seen


def issue_sheet_problems(sheet, *, complaint_text, responses, evidence_ids):
    """結構檢查(硬擋)。complaint_text 是法官讀的起訴狀(關卡 1 確認版),responses 是答辯狀的逐點表態,
    evidence_ids 是起訴狀用到的證據編號。回傳退回原因;空清單代表通過。"""
    if not isinstance(sheet, dict):
        return ["爭點整理表必須是 JSON 物件"]
    problems = []
    cfs = set(cf.cf_ids(complaint_text))
    stance = {r.get("fact_id"): r.get("stance") for r in responses or [] if isinstance(r, dict)}
    evidence_ids = set(evidence_ids or [])

    def evidence(label, value):
        if not _str_list(value):
            problems.append(f"{label} 必須是字串陣列")
            return
        problems.extend(f"{label} 的證據編號 {e} 不在起訴狀的證據清單" for e in value if e not in evidence_ids)

    undisputed = _list_of(sheet, "undisputed", problems)
    _ids(undisputed, "undisputed", problems)
    for item in undisputed:
        label = item.get("id") or "undisputed"
        if not _str(item.get("text")):
            problems.append(f"{label} 的 text 不可空白")
        source = item.get("source")
        if not _str_list(source) or not source:
            problems.append(f"{label} 的 source 必須是非空的 CF 編號陣列")
            source = []
        for fact in source:
            if fact not in cfs:
                problems.append(f"{label} 的來源 {fact} 不在起訴狀的〔CF〕裡")
            elif stance.get(fact) != "admit":
                problems.append(f"{label} 的來源 {fact} 被告表態是 {stance.get(fact) or '未表態'},不是 admit,不能列為不爭執事項")
        evidence(f"{label} 的 evidence", item.get("evidence", []))

    issues = _list_of(sheet, "issues", problems)
    issue_ids = _ids(issues, "issues", problems)
    for item in issues:
        label = item.get("id") or "issues"
        if item.get("kind") not in KINDS:
            problems.append(f"{label} 的 kind 只能是 {'、'.join(KINDS)}:{item.get('kind')!r}")
        if not _str(item.get("text")):
            problems.append(f"{label} 的 text 不可空白")
        if not _str_list(item.get("from", [])):
            problems.append(f"{label} 的 from 必須是 CF 編號陣列")
        else:
            problems += [f"{label} 參照的 {fact} 不在起訴狀的〔CF〕裡" for fact in item.get("from", []) if fact not in cfs]
        for key in ("plaintiff_claim", "defendant_defense"):
            if not isinstance(item.get(key, ""), str):
                problems.append(f"{label} 的 {key} 必須是字串")
        evidence(f"{label} 的 plaintiff_evidence", item.get("plaintiff_evidence", []))
        evidence(f"{label} 的 defendant_evidence", item.get("defendant_evidence", []))
        basis = item.get("legal_basis", [])
        if not _str_list(basis):
            problems.append(f"{label} 的 legal_basis 必須是字串陣列")
        else:
            problems += [f"{label} 的 legal_basis 只能放法條,且要寫成「OO法第N條」:{b}"
                         for b in basis if parse_citation(b)["type"] != "statute"]
        if item.get("burden") not in BURDENS:
            problems.append(f"{label} 的 burden 只能是 {'、'.join(BURDENS)}:{item.get('burden')!r}")
        if not isinstance(item.get("hypothetical"), bool):
            problems.append(f"{label} 的 hypothetical 必須是 true 或 false")

    for i, item in enumerate(_list_of(sheet, "clarifications", problems), 1):
        label = f"clarifications 第 {i} 筆"
        if item.get("target_side") not in SIDES:
            problems.append(f"{label} 的 target_side 只能是 plaintiff 或 defendant")
        if not _str(item.get("question")):
            problems.append(f"{label} 的 question 不可空白")
        if not isinstance(item.get("basis", ""), str):
            problems.append(f"{label} 的 basis 必須是字串")
        if item.get("based_on") not in issue_ids:
            problems.append(f"{label} 的 based_on 要指到存在的爭點:{item.get('based_on')!r}")

    for i, item in enumerate(_list_of(sheet, "questions", problems), 1):
        label = f"questions 第 {i} 筆"
        if item.get("target_side") not in SIDES:
            problems.append(f"{label} 的 target_side 只能是 plaintiff 或 defendant")
        if not _str(item.get("question_text")):
            problems.append(f"{label} 的 question_text 不可空白")
        based_on = item.get("based_on")
        if not _str(based_on):
            problems.append(f"{label} 的 based_on 不可空白")
        elif not based_on.startswith(OFFICIAL_PREFIX):
            ref = _ISSUE_REF_RE.match(based_on)
            if not ref or ref.group(1) not in issue_ids:
                problems.append(f"{label} 的 based_on 要以存在的爭點編號開頭(例如「I1:…」)"
                                f"或「{OFFICIAL_PREFIX}<id>):」:{based_on!r}")
    return problems


def issue_sheet_warnings(sheet, *, responses):
    """只警告:來自被告推測表態的爭點沒標 hypothetical;要被告回答事實的訊問(被告沒有本人的事實)。"""
    guessed = {r["fact_id"] for r in responses or [] if isinstance(r, dict) and r.get("fact_id")
               and (r.get("hypothetical") is True or r.get("ground") == "alternative_explanation")}
    warnings = []
    for item in sheet.get("issues") or []:
        hit = [f for f in item.get("from") or [] if f in guessed]
        if hit and item.get("hypothetical") is not True:
            warnings.append(f"{item.get('id')} 來自被告推測的表態({'、'.join(hit)}),hypothetical 應為 true")
    for item in sheet.get("questions") or []:
        if (item.get("target_side") == "defendant" and not (item.get("based_on") or "").startswith(OFFICIAL_PREFIX)
                and looks_factual(item.get("question_text"))):
            warnings.append(f"這則訊問看起來要被告回答事實,模擬被告沒有本人的事實,請確認是否改成給原告的準備題:"
                            f"{item.get('question_text')}")
    return warnings


def _section(text, start, stops):
    lines = (text or "").splitlines()
    if start not in [line.strip() for line in lines]:
        return []
    out = []
    for line in lines[[line.strip() for line in lines].index(start) + 1:]:
        if not line.strip() or line.strip() in stops or line.strip().startswith(stops):
            break
        out.append(line.strip())
    return out


def _cell(value):
    return (value or "").replace("|", "／").replace("\n", " ") or "—"


def render_issue_sheet(sheet, *, complaint_text, evidence):
    """四張表的文字版。聲明與請求權基礎從起訴狀正文取(反映律師編輯),證據清單取起訴狀用到的證據。推測的爭點標「(推測)」。"""
    lines = ["表一　聲明與請求權基礎", "訴之聲明:"]
    lines += _section(complaint_text, "訴之聲明", ("事實及理由",)) or ["(起訴狀未列)"]
    lines.append("請求權基礎:")
    lines += _section(complaint_text, "二、請求權基礎", ("三、",)) or ["(起訴狀未列)"]
    lines += ["", "表二　預期不爭執事項"]
    lines += [f"{u.get('id')}　{u.get('text')}(來源 {'、'.join(u.get('source') or [])};證據 "
              f"{'、'.join(u.get('evidence') or []) or '無'})" for u in sheet.get("undisputed") or []] or ["(無)"]
    lines += ["", "表三　爭點整理表",
              "| 序次 | 爭點 | 原告主張 | 原告證據 | 被告抗辯 | 被告證據 | 法律依據 | 舉證責任 |",
              "|---|---|---|---|---|---|---|---|"]
    for item in sheet.get("issues") or []:
        text = item.get("text", "") + ("(推測)" if item.get("hypothetical") else "")
        lines.append("| " + " | ".join(_cell(v) for v in (
            item.get("id"), text, item.get("plaintiff_claim"), "、".join(item.get("plaintiff_evidence") or []),
            item.get("defendant_defense"), "、".join(item.get("defendant_evidence") or []),
            "、".join(item.get("legal_basis") or []), BURDEN_LABEL.get(item.get("burden"), item.get("burden")))) + " |")
    lines += ["", "表四　證據清單", "| 編號 | 種類 | 日期 | 內容 |", "|---|---|---|---|"]
    lines += ["| " + " | ".join(_cell(e.get(k)) for k in ("id", "type", "date", "description")) + " |"
              for e in evidence or []] or ["(起訴狀未附證據)"]
    clarifications = sheet.get("clarifications") or []
    if clarifications:
        lines += ["", "闡明"]
        lines += [f"- 對{'原告' if c.get('target_side') == 'plaintiff' else '被告'}({c.get('based_on')}):"
                  f"{c.get('question')}" + (f"(依據:{c['basis']})" if c.get("basis") else "") for c in clarifications]
    questions = sheet.get("questions") or []
    if questions:
        lines += ["", "訊問"]
        lines += [f"- 對{'原告' if q.get('target_side') == 'plaintiff' else '被告'}({q.get('based_on')}):"
                  f"{q.get('question_text')}" for q in questions]
    return "\n".join(lines) + "\n"
