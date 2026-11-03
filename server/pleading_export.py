"""系統產生版訴狀匯出時的顯示層清理，與 ui/app.js 訴狀分頁的規則一致(TEXT_JARGON、splitDraftNote、
cleanDraftNote、pleadingDoc 的標題處理)：畫面上不顯示的內部備註，匯出也不帶。只產生匯出文字，資料庫原文不動。

改動任一邊的規則時，另一邊要一起改。
例外:正文的事實點編號〔CF1〕畫面照顯示(律師編輯與逐點表態要用),只有匯出移除(server/services.py export_pleading_text)。
"""
import re

_A = r"(?<![A-Za-z0-9_])"  # JS 的 \b 只認 ASCII 字元；Python 的 \b 會把中文當字元，所以改用明確的 ASCII 邊界
_Z = r"(?![A-Za-z0-9_])"
# 順序有意義：先代換較長的複合代號，再代換其後可能單獨殘留的字詞
TEXT_JARGON = [
    (r"taiwan-legal-pleading(\s*Skill)?", "系統潤飾規則"),
    (r"legal-debate\s*skill", "系統流程"),
    (r"engine/verify\.py", "查證程式"),
    (r"LegalDebate\s*系統\s*Stage\s*3", "系統攻防推演最終階段"),
    (r"position/reasoning\s*原文", "主張與理由原文"),
    (r"position\s*\+\s*reasoning", "主張與理由"),
    (r"position_drift", "引用清單差異"),
    (r"weak_points?", "雙方讓步條件"),
    (_A + r"falsifier" + _Z, "讓步條件"),
    (_A + r"plaintiff" + _Z, "原告方"),
    (_A + r"defendant" + _Z, "被告方"),
    (r"Phase\s*[12]" + _Z, "後續階段"),
    (_A + r"Step(\d+)" + _Z, r"步驟\1"),
    (_A + r"Skill" + _Z, "潤飾規則"),
    (_A + r"published" + _Z, "已通過"),
]
TEXT_JARGON = [(re.compile(p, re.I), r) for p, r in TEXT_JARGON]
NOTE_START = re.compile(r"-{2,}\s*\n\s*(?=【)|【(?:骨架版聲明|本稿產出說明)")
SUBTITLE = "骨架版初稿．尚未經法律用語潤飾．須經律師審核後使用"
DEFENSE_SUBTITLE = SUBTITLE + "．模擬答辯，非針對實際起訴狀"
# 模擬流程用語不該出現在書狀正文。只警告不阻擋：律師可能合法引述被告在存證信函等處的說法。
_FLOW_WORDS = r"stage|輪次|前輪|法官訊問|訊問攻防|本方|對造"
_LINT = {"plaintiff": re.compile(r"被告主張|被告抗辯|被告自承|被告或將|" + _FLOW_WORDS, re.I),
         "defendant": re.compile(_FLOW_WORDS, re.I)}  # 答辯狀本來就要寫「原告主張」


def delabel_jargon(text):
    for pattern, repl in TEXT_JARGON:
        text = pattern.sub(repl, text)
    return text


def split_draft_note(text):
    m = NOTE_START.search(text)
    return (text[:m.start()], text[m.start():]) if m else (text, None)


def lint_pleading(draft_text, side="plaintiff"):
    """回傳書狀正文(不含系統補充說明)命中的模擬用語與次數，依第一次出現的順序排列。"""
    counts = {}
    for hit in _LINT[side].findall(split_draft_note(draft_text)[0]):
        word = "Stage" if hit.lower() == "stage" else hit
        counts[word] = counts.get(word, 0) + 1
    return [{"word": word, "count": count} for word, count in counts.items()]


def clean_draft_note(raw):
    text = delabel_jargon(raw)
    text = re.sub(r"【(?:骨架版聲明|本稿產出說明)[^】]*】", "", text)
    text = re.sub(r"(?m)^-{2,}\s*$", "", text)
    lines = [re.sub(r"^[-•]\s*", "", line).strip() for line in text.split("\n")]
    lines = [line for line in lines if line and line != "。" and not re.fullmatch(r"骨架版[,，]?.*潤飾[。.]?", line)]
    return "\n".join(lines)


ROUND_TITLES = {"brief": "民事準備書狀", "closing": "民事言詞辯論意旨狀"}


def system_draft_for_export(draft_text, side="plaintiff", pleading_type=None):
    """回傳 (訴狀正文, 系統補充說明或 None)。標題後的括號說明(早期稿在此寫內部代號)改為與畫面相同的副標題。
    準備書狀、言詞辯論意旨狀標題後的「(模擬…)」是如實標示,移到副標題保留,不刪(審查 W6-8)。"""
    body, note = split_draft_note(draft_text)
    lines = delabel_jargon(body).strip().split("\n")
    title = 0
    while title < len(lines) - 1 and (not lines[title].strip() or re.fullmatch(r"【[^】]*】", lines[title].strip())):
        title += 1
    paren = re.search(r"[（(]([\s\S]*)[）)]\s*$", lines[title])
    lines[title] = re.sub(r"[（(][\s\S]*[）)]\s*$", "", lines[title]).strip() or ROUND_TITLES.get(pleading_type) or (
        "民事答辯狀" if side == "defendant" else "民事起訴狀")
    if pleading_type in ROUND_TITLES:
        subtitle = SUBTITLE + ("．" + paren.group(1).strip() if paren and "模擬" in paren.group(1) else "．模擬書狀")
    else:
        subtitle = DEFENSE_SUBTITLE if side == "defendant" else SUBTITLE
    lines.insert(title + 1, subtitle)
    return "\n".join(lines), (clean_draft_note(note) or None) if note else None
