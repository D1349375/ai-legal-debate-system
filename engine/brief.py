"""P4 準備書狀與 P5 言詞辯論意旨狀(規格 5.6):依爭點整理表檢查每輪論證、由程式組成書狀。純函數、不碰 DB、不呼叫 LLM。

每輪論證的公開段落要依爭點組織，每段以「【爭點 I1】」開頭。非推測的爭點雙方都要有段落(硬擋);推測爭點不強制，
但寫進去時要保留「若被告能提出」「推測」這類字樣(只警告)。原告新增請求權基礎時提醒律師確認民事訴訟法第255條
(訴之變更、追加)或第256條(補充或更正),只警告，不從 cited_statutes 猜。
"""
import re

from engine.pleading_render import PENDING, numeral, party_lines
from engine.verify import parse_citation

ISSUE_MARK_RE = re.compile(r"【爭點\s*([A-Za-z]\w*)\s*】")
_GUESS_RE = re.compile(r"若被告能提出|推測|若|倘|假設")
_CAUSE_RE = re.compile(r"為請求(.+?)提起訴訟事")
TITLES = {2: "民事準備書狀", 3: "民事言詞辯論意旨狀"}
PLEADING_TYPE = {2: "brief", 3: "closing"}
_SUFFIX = {"plaintiff": "(模擬,回應系統模擬的答辯)", "defendant": "(模擬被告,非實際書狀)"}


def _issues(sheet):
    return [i for i in (sheet or {}).get("issues") or [] if isinstance(i, dict) and i.get("id")]


def paragraphs(text):
    """→ [(爭點編號, 段落文字)],依出現順序。第一個標記之前的文字不屬於任何爭點，不列。"""
    marks = list(ISSUE_MARK_RE.finditer(text or ""))
    return [(m.group(1), text[m.end():marks[i + 1].start() if i + 1 < len(marks) else len(text)].strip())
            for i, m in enumerate(marks)]


def round_problems(public_text, sheet):
    """每輪論證的爭點段落(硬擋,退回同一 subagent)。public_text 是濾掉內部檢討後的公開論證。"""
    known = {i["id"] for i in _issues(sheet)}
    written = {issue_id for issue_id, _ in paragraphs(public_text)}
    problems = [f"缺少【爭點 {i['id']}】段落(爭點:{i.get('text', '')}),非推測的爭點都要回應"
                for i in _issues(sheet) if not i.get("hypothetical") and i["id"] not in written]
    problems += [f"【爭點 {issue_id}】不是爭點整理表裡的爭點" for issue_id in sorted(written - known)]
    return problems


def basis_problems(basis):
    if not isinstance(basis, list) or not all(isinstance(b, str) for b in basis):
        return ["basis 必須是法條字串陣列"]
    return [f"basis 只能放法條,且要寫成「OO法第N條」:{b}" for b in basis if parse_citation(b)["type"] != "statute"]


def new_basis(side, basis, complaint_basis):
    """原告本輪 basis 裡起訴狀沒有的項目(被告沒有訴之變更追加的問題)。"""
    if side != "plaintiff":
        return []
    return [b for b in basis or [] if b not in set(complaint_basis or [])]


def round_warnings(public_text, sheet, *, side, basis, complaint_basis):
    """只警告:原告新增請求權基礎(第255條);推測爭點的段落沒有保留推測字樣。"""
    warnings = [f"本輪新增請求權基礎 {b}(起訴狀沒有),請律師確認屬民事訴訟法第255條訴之變更、追加,或第256條補充更正"
                for b in new_basis(side, basis, complaint_basis)]
    guessed = {i["id"] for i in _issues(sheet) if i.get("hypothetical")}
    warnings += [f"【爭點 {issue_id}】是推測爭點,段落沒有「若被告能提出」或「推測」這類字樣,請確認沒有寫成確定的事實"
                 for issue_id, text in paragraphs(public_text) if issue_id in guessed and not _GUESS_RE.search(text)]
    return warnings


def render_brief(public_text, *, side, round, sheet, case, party_checks, procedural, complaint_text, citations, new_basis):
    """依已落地的公開論證組成書狀。同一輸入一定得到同一份正文(不含時間戳)。不含內部檢討與 falsifier:呼叫端只傳公開論證。"""
    parties = case.get("parties") or {}
    title = TITLES[round]
    lines = [title + _SUFFIX[side], "案號:" + PENDING.format("法院分案後之案號"), "承辦股別:" + PENDING.format("股別"), ""]
    for role in ("plaintiff", "defendant"):
        lines += party_lines(role, parties.get(role), (party_checks or {}).get(role), procedural)
        lines.append("")
    cause = _CAUSE_RE.search(complaint_text or "")
    lines.append(f"為{cause.group(1) if cause else '原告起訴'}事件,依法提出{title.removeprefix('民事')}事:")
    issues = {i["id"]: i for i in _issues(sheet)}
    lines += ["一、爭點", "本狀依法院爭點整理表逐點陳述:"]
    lines += [f"({issue_id}){i.get('text', '')}" + ("(推測)" if i.get("hypothetical") else "") for issue_id, i in issues.items()]
    lines.append("二、陳述")
    for issue_id, text in paragraphs(public_text):
        issue = issues.get(issue_id, {})
        lines.append(f"【爭點 {issue_id}】{issue.get('text', '')}" + ("(推測)" if issue.get("hypothetical") else ""))
        lines.append(text)
    if citations:
        lines += ["三、引用", "、".join(citations)]
    lines += ["", "證物名稱及件數:", "(同起訴狀所附證物)" if side == "plaintiff" else "(模擬被告未附證物)", "",
              "此　致", PENDING.format("受理法院") + "　公鑒", "中華民國(待填)年(待填)月(待填)日"]
    signer = party_lines(side, parties.get(side), (party_checks or {}).get(side), procedural)
    lines.append("具狀人　" + signer[0])
    lines += ["　　　　" + line for line in signer if line.startswith("法定代理人")]
    lines.append("撰狀人　" + PENDING.format("訴訟代理人"))
    lines += ["", "---", "【本稿產出說明】給律師,不是書狀正文",
              "- 本狀回應的是系統模擬的對方書狀,不是實際收到的書狀"]
    lines += [f"- 本狀新增請求權基礎 {b}:請確認屬民事訴訟法第255條訴之變更、追加,或第256條補充更正" for b in new_basis]
    return "\n".join(lines) + "\n"
