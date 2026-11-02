"""起訴狀的事實點(CF):對應檢查與正文標記。純函數、不碰 DB、不呼叫 LLM。

每一點事實要有案件證據清單裡的編號,或逐字引自律師填的事實經過(facts_summary),否則退回撰狀 subagent,
對應不到的改列 fact_gaps。這是結構規則,可以硬擋(規格第 7 節)。
編號寫進正文 `〔CF1〕`,律師在關卡 1 自由編輯後仍對得上;匯出時移除。
被告答辯對每個 CF 逐點表態(response_problems),同樣是結構規則,硬擋。
"""
import re

CF_ID_RE = re.compile(r"CF[1-9][0-9]*")
CF_TAG_RE = re.compile(r"[ \t　]*〔(CF[1-9][0-9]*)〕")


def compact(text):
    """只忽略空白與換行(含全形空白),不容許改寫。"""
    return re.sub(r"\s+", "", text or "")


def fact_point_problems(fact_points, *, evidence_ids, facts_summary):
    """回傳退回原因(每則點名 CF);空清單代表通過。"""
    if not isinstance(fact_points, list):
        return ["fact_points 必須是陣列"]
    if not fact_points:
        return ["fact_points 不可為空"]
    known, facts, seen, problems = set(evidence_ids or []), compact(facts_summary), set(), []
    for i, point in enumerate(fact_points, 1):
        if not isinstance(point, dict):
            problems.append(f"fact_points 第 {i} 筆不是物件")
            continue
        cf = point.get("id")
        if not isinstance(cf, str) or not CF_ID_RE.fullmatch(cf):
            problems.append(f"fact_points 第 {i} 筆的編號須為 CF1、CF2 的格式:{cf!r}")
            continue
        if cf in seen:
            problems.append(f"{cf} 編號重複")
            continue
        seen.add(cf)
        text = point.get("text")
        if not isinstance(text, str) or not text.strip():
            problems.append(f"{cf} 沒有寫事實內容")
        elif "〔CF" in text:
            problems.append(f"{cf} 的事實內容不要自己寫〔CF〕標記,程式組成正文時會加")
        ids = point.get("evidence_ids") or []
        if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
            problems.append(f"{cf} 的 evidence_ids 必須是證據編號陣列")
            continue
        unknown = [x for x in ids if x not in known]
        if unknown:
            problems.append(f"{cf} 引用不存在的證據編號 {'、'.join(unknown)}(案件證據清單:{'、'.join(sorted(known)) or '無'})")
        quote = point.get("statement_quote")
        if quote is not None and not isinstance(quote, str):
            problems.append(f"{cf} 的 statement_quote 必須是字串或 null")
            continue
        if quote and quote.strip() and compact(quote) not in facts:
            problems.append(f"{cf} 的 statement_quote 不是事實經過的逐字原文(只容許空白不同);"
                            "對應不到的事實請移到 fact_gaps")
        elif not ids and not (quote and quote.strip()):
            problems.append(f"{cf} 沒有證據編號,也沒有逐字引述事實經過;請補上,或把這點移到 fact_gaps")
    return problems


def paraphrase_warnings(fact_points, facts_summary):
    """只靠逐字引述對應的事實,`text` 本身卻不是原文時提醒人工核對:引述只證明原文有那一段,
    `text` 多寫或改寫的部分程式判斷不了是否忠實,所以只警告(自然語言規則)。"""
    facts = compact(facts_summary)
    return [f"{p['id']} 的事實內容不是事實經過的原文(引述只對到其中一段),請人工核對改寫是否忠實"
            for p in fact_points or [] if isinstance(p, dict) and not p.get("evidence_ids")
            and isinstance(p.get("text"), str) and compact(p["text"]).rstrip("。") not in facts]


STANCES = ("admit", "deny", "authenticity", "to_confirm")
GROUNDS = (None, "insufficient_proof", "alternative_explanation")


def response_problems(responses, *, complaint_text, fact_evidence):
    """答辯的逐點表態(規格 5.4):以傳入的起訴狀正文(律師確認版)裡的〔CF〕為準,每點有且只有一筆。
    fact_evidence 是 {CF: 證據編號},律師新增、沒有證據的 CF 不在裡面或為空。回傳退回原因;空清單代表通過。"""
    if not isinstance(responses, list):
        return ["responses 必須是陣列"]
    wanted, seen, problems = dict.fromkeys(cf_ids(complaint_text)), set(), []
    for i, item in enumerate(responses, 1):
        if not isinstance(item, dict):
            problems.append(f"responses 第 {i} 筆不是物件")
            continue
        cf, stance = item.get("fact_id"), item.get("stance")
        if cf not in wanted:
            problems.append(f"responses 第 {i} 筆的 {cf!r} 不在起訴狀正文的〔CF〕裡")
            continue
        if cf in seen:
            problems.append(f"{cf} 表態重複,每點只能有一筆")
            continue
        seen.add(cf)
        if stance not in STANCES:
            problems.append(f"{cf} 的 stance 只能是 {'、'.join(STANCES)}:{stance!r}")
            continue
        if item.get("ground") not in GROUNDS:
            problems.append(f"{cf} 的 ground 只能是 insufficient_proof、alternative_explanation 或 null:{item.get('ground')!r}")
        if stance == "admit" and not (fact_evidence or {}).get(cf):
            problems.append(f"{cf} 沒有證據編號,不能 admit;請改 deny 或 to_confirm")
        if item.get("ground") == "alternative_explanation" and item.get("hypothetical") is not True:
            problems.append(f"{cf} 提出另一解釋(alternative_explanation)屬推測,hypothetical 必須為 true")
        if stance != "admit" and not (isinstance(item.get("reason"), str) and item["reason"].strip()):
            problems.append(f"{cf} 的 stance 是 {stance},reason 不得為空")
    problems += [f"{cf} 沒有表態" for cf in wanted if cf not in seen]
    return problems


def strip_cf_tags(text):
    return CF_TAG_RE.sub("", text or "")


def cf_ids(text):
    return CF_TAG_RE.findall(text or "")
