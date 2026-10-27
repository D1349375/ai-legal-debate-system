"""官方事實層 → 攻防推演：把商工查核警示轉成起訴審查時審判長應命補正的程序事項。

純函數、不碰 DB、不呼叫 LLM。只重組 party_rules 已產生的警示，另補該類程序瑕疵在民事訴訟法上的
處理方式(命補正、裁定或判決駁回)；不判斷實體爭點，也不補登記資料沒有的事實(例如清算人姓名)。

流程對齊實務(參最高法院115年度台抗字第105號裁定：一審發現原告公司已解散、登記清算人非起訴所列
代表人，即裁定限期補正、逾期後駁回；該駁回經廢棄確定，因法院須依職權調查實際代表權，不得僅憑登記)：這些事項在 Stage 1 之前由規則提出，原告在 Stage 1
一併補正，法官在 Stage 1 之後只就補正不足者追問。輸出也併入 finalize 的機械錨點。
"""
import re

from engine import party_rules

ROLE_LABEL = {"plaintiff": "原告", "defendant": "被告"}

# 程序類別 → (顯示名稱, 程序上的處理, 補充的程序法依據)；條文已於 2026-10-27 經全國法規資料庫查證，
# 裁定在本地判決語料庫(司法院裁判書開放資料)。
KINDS = {
    "representation": ("法定代理", "起訴狀應表明當事人及法定代理人；法人代表權有欠缺而可以補正者，審判長應定期間命其補正，"
                       "逾期未補正者，起訴不合法，以裁定駁回。公司負責人之登記僅屬對抗第三人之要件，代表權有爭議時，"
                       "法院仍應依職權調查實際代表權，不得僅憑登記認定（最高法院115年度台抗字第105號裁定）。",
                       ["民事訴訟法第244條", "民事訴訟法第49條", "民事訴訟法第52條", "民事訴訟法第249條", "公司法第12條",
                        "最高法院115年度台抗字第105號"]),
    "capacity": ("當事人能力", "原告或被告無當事人能力者，法院應以裁定駁回；其情形可以補正者，審判長應定期間先命補正。",
                 ["民事訴訟法第249條"]),
    "standing": ("當事人適格", "當事人不適格者，法院得不經言詞辯論，逕以判決駁回；其情形可以補正者，審判長應定期間先命補正。",
                 ["民事訴訟法第249條"]),
    "designation": ("當事人表明", "起訴狀應表明當事人及法定代理人。", ["民事訴訟法第244條"]),
    "strategy": ("執行風險", None, []),
}

# 被告法人欠缺法定代理人時，原告除補正外的程序途徑(民訴§52 準用§51Ⅰ；Ⅳ 限制其權限)；條文已於 2026-10-28 經全國法規資料庫查證。
DEFENDANT_SPECIAL_AGENT = ("被告法人無法定代理人或其法定代理人不能行代理權，恐致久延而受損害者，原告得聲請受訴法院之審判長選任特別代理人；"
                           "特別代理人於法定代理人承當訴訟以前代理被告為一切訴訟行為，但不得為捨棄、認諾、撤回或和解。",
                           ["民事訴訟法第51條"])

# 警示代碼 → (程序類別, 是否屬法院應依職權調查的事項, 命原告補正／說明的內容)。
# 當事人與法定代理人由原告於起訴狀列載，因此一律對原告；被告方在 Stage 1 也拿到同一份事項，可自行據以抗辯。
ASKS = {
    "dissolved": ("representation", True, "原告列載{party}之法定代理人是否為清算人？清算人為何人、依何資料認定？"),
    "foreign_dissolved": ("representation", True, "原告列載{party}之清算人為何人、依何資料認定？"),
    "ordered_dissolve": ("representation", True, "{party}是否已進入清算？原告列載之法定代理人依何資料認定？"),
    "liquidated": ("representation", True, "{party}就本件是否仍有未了事務？原告列載之法定代理人（清算人）為何人？"),
    "withdrawn": ("representation", True, "原告列載之{party}與其法定代理人是否仍屬適當？"),
    "no_rep": ("representation", True, "官方登記未提供{party}負責人，原告列載之法定代理人依何資料認定？"),
    "rep_mismatch": ("representation", True, "原告列載{party}之法定代理人依何資料認定？"),
    "foreign_branch": ("representation", True, "原告列載{party}之法定代理人為何人（在臺負責人或外國公司之代表人）？"),
    "reorganization": ("representation", True, "原告列載{party}之法定代理人是否為重整人？本件是否屬裁定重整後當然停止之因財產關係所生訴訟，"
                                               "或所涉債權是否屬非依重整程序不得行使之重整債權？"),
    "interim_manager": ("representation", True, "原告列載{party}之法定代理人是否為登記之臨時管理人？"),
    # 因合併而解散者不經清算、法人格消滅，告它是「無當事人能力」，不是當事人不適格
    "merged": ("capacity", True, "原告是否改列存續或新設公司為當事人？"),
    "bankrupt": ("standing", True, "本件請求是否屬破產財團之訴訟？如是，原告是否改以破產管理人為當事人？"),
    "business_entity": ("capacity", True, "原告是否已改列商號主人（負責人）為當事人？"),
    "branch_entity": ("designation", True, "原告以分公司或總公司為當事人？本件是否屬分公司業務範圍內事項？"),
    "name_mismatch": ("designation", True, "原告列載之{party}名稱是否依登記名稱更正？"),
    "not_found": ("designation", True, "原告列載之{party}是否已正確特定？"),
    "suspended": ("strategy", False, "原告是否評估於判決前聲請假扣押？"),
}

# 這些狀態的警示已說明法定代理人應如何列載，同一當事人的「未提供負責人」不再另成一則訊問。
SUBSUMES_NO_REP = {"dissolved", "foreign_dissolved", "ordered_dissolve", "liquidated", "withdrawn", "merged", "bankrupt",
                   "reorganization", "interim_manager"}

_RULE_ORDER = {rule["code"]: i for i, rule in enumerate(party_rules.RULES)}


def _dedupe(items):
    return list(dict.fromkeys(items))


def _registry_fact(role, result):
    label = ROLE_LABEL[role]
    who = f"{label}「{result['name']}」" if result.get("name") else label
    if result.get("entity_type") == "not_found":
        state = "商工登記查無此統編"
    elif result.get("entity_type") == "branch":
        state = "商工登記為分公司統編"
    else:
        state = f"商工登記狀態為「{result.get('status_text') or '未提供'}」"
    when = (f"錄製的查詢結果，查詢時間 {result.get('fetched_at')}" if result.get("via") == "recorded"
            else f"查詢時間 {result.get('fetched_at') or '未記錄'}")
    return f"{who}（統編 {result.get('ban')}）{state}（{when}）"


def procedural_issues(party_checks):
    """party_checks：{"plaintiff": 查核結果或 None, "defendant": ...}(即 latest_party_checks 的輸出)。

    回傳 {"issues": [...], "notes": [...], "parties": {...}}。notes 記錄未查核或查核未完成的當事人——
    沒有查核結果時不得推定當事人沒有程序問題，所以不能只回傳空的 issues。
    """
    issues, notes, parties = [], [], {}
    for role in ("plaintiff", "defendant"):
        label = ROLE_LABEL[role]
        result = (party_checks or {}).get(role)
        if not result:
            parties[role] = None
            notes.append(f"{label}尚未查核商工登記（自然人當事人無統編，不適用）；不得據此推定{label}無當事人能力或法定代理問題。")
            continue
        parties[role] = {"ban": result.get("ban"), "name": result.get("name"), "status_text": result.get("status_text"),
                         "query_status": result.get("query_status"), "via": result.get("via"),
                         "fetched_at": result.get("fetched_at")}
        if result.get("query_status") == "failed":
            errors = "、".join(e["dataset"] for e in result.get("errors") or []) or "連線失敗"
            notes.append(f"{label}商工查核未完成（{errors}）；不得推定{label}無程序問題，請重新查核。")
            continue
        if result.get("query_status") == "partial":
            errors = "、".join(e["dataset"] for e in result.get("errors") or [])
            notes.append(f"{label}部分資料集查詢失敗（{errors}）；缺漏的欄位不得視為查無。")
        codes = {w["code"] for w in result.get("warnings") or []}
        fact = _registry_fact(role, result)
        for w in result.get("warnings") or []:
            if w["code"] not in ASKS or (w["code"] == "no_rep" and codes & SUBSUMES_NO_REP):
                continue
            kind, ex_officio, ask = ASKS[w["code"]]
            kind_label, procedure, procedure_basis = KINDS[kind]
            if role == "defendant" and kind == "representation":
                procedure = procedure + DEFENDANT_SPECIAL_AGENT[0]
                procedure_basis = procedure_basis + DEFENDANT_SPECIAL_AGENT[1]
            issues.append({
                "id": f"{role}:{w['code']}", "party_role": role, "warning_code": w["code"], "level": w["level"],
                "kind": kind_label, "ex_officio": ex_officio, "target_side": "plaintiff",
                "fact": fact, "warning": w["message"],
                # 事項是原告自身的登記時，「原告列載原告之…」改說「自身」
                "question_text": f"{fact}。{ask.format(party='自身' if role == 'plaintiff' else label)}",
                "procedure": procedure,
                "legal_basis": _dedupe(list(w["legal_basis"]) + procedure_basis),
            })
    issues.sort(key=lambda i: (i["level"] != "bad", i["party_role"] != "defendant", _RULE_ORDER.get(i["warning_code"], 99)))
    return {"source": "經濟部商工登記開放資料，依固定規則轉換（非 AI 生成）", "stage": "起訴審查（Stage 1 之前）",
            "issues": issues, "notes": notes, "parties": parties}


def cured_in(text, issue_id):
    """原告 Stage 1 是否有「程序補正(<id>)」段落(全形或半形括號皆可)；只核對有沒有回應，不判斷補正是否足夠。"""
    return bool(re.search(r"程序補正\s*[（(]\s*" + re.escape(issue_id) + r"\s*[）)]", text or ""))
