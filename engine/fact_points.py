"""起訴狀的事實點(CF):對應檢查與正文標記。純函數、不碰 DB、不呼叫 LLM。

每一點事實要有案件證據清單裡的編號,或逐字引自律師填的事實經過(facts_summary),否則退回撰狀 subagent,
對應不到的改列 fact_gaps。這是結構規則,可以硬擋(規格第 7 節)。
編號寫進正文 `〔CF1〕`,律師在關卡 1 自由編輯後仍對得上;匯出時移除。
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


def strip_cf_tags(text):
    return CF_TAG_RE.sub("", text or "")


def cf_ids(text):
    return CF_TAG_RE.findall(text or "")


def new_paragraphs_without_cf(parent_text, text):
    """律師版比上一版多出的段落(以行為單位，去頭尾空白比對)中沒有〔CF…〕標記的。
    這些段落不會進逐點表態；只提示，不阻擋確認(規格 5.3)。"""
    old = {line.strip() for line in (parent_text or "").splitlines()}
    return [line.strip() for line in (text or "").splitlines()
            if line.strip() and line.strip() not in old and not CF_TAG_RE.search(line)]
