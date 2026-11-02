"""起訴狀 v1(確認版)與 v2 的逐行差異(規格 5.7「畫面顯示 v1 與 v2 差異,由伺服器用 difflib 產生」)。
純函數、不碰 DB;給 server/ 接線時直接呼叫。只比正文:【本稿產出說明】以後(給律師的事實缺口與附註)不比。"""
from difflib import SequenceMatcher


def _body_lines(text):
    from server.pleading_export import split_draft_note  # 正文與說明的切法和畫面、匯出同一套
    body = split_draft_note(text or "")[0]
    return [line.rstrip() for line in body.rstrip().splitlines()] if body.strip() else []


def complaint_diff(old_text, new_text):
    """回傳 {"lines": [{"op": "equal"|"delete"|"insert", "text", "old_no", "new_no"}], "added", "removed"}。
    行號從 1 起算,刪除的行沒有 new_no、新增的行沒有 old_no。改寫的一行以「先刪後增」表示。〔CF〕標記保留,律師對得上事實點。"""
    old, new = _body_lines(old_text), _body_lines(new_text)
    lines = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == "equal":
            lines += [{"op": "equal", "text": old[i], "old_no": i + 1, "new_no": j1 + k + 1}
                      for k, i in enumerate(range(i1, i2))]
            continue
        lines += [{"op": "delete", "text": old[i], "old_no": i + 1, "new_no": None} for i in range(i1, i2)]
        lines += [{"op": "insert", "text": new[j], "old_no": None, "new_no": j + 1} for j in range(j1, j2)]
    return {"lines": lines, "added": sum(d["op"] == "insert" for d in lines),
            "removed": sum(d["op"] == "delete" for d in lines)}
