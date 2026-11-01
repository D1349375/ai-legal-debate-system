"""起訴前檢查:依案由、請求與金額提示可能要留意的程序與時效。純函數、不碰 DB、不呼叫 LLM。

只提示,不下結論,也不阻擋:訴訟標的價額由法院核定(民訴第77條之1),事件類型也要看實際事實。
案由關鍵字對照會誤判也會漏判,是我們自己寫的表,條文已核對,對照還沒有律師校對。
"""
import datetime
import re

CIVIL_PROCEDURE = "民事訴訟法"
CIVIL_CODE = "民法"
NOTE = "本檢查只提示可能要留意的事項，不是法律結論，也不阻擋後續流程；以律師判斷為準。"
_VALUE_NOTE = "訴訟標的價額由法院核定"
_NON_MONEY_RE = re.compile(r"確認|撤銷|塗銷|遷讓|拆除|移轉登記|分割|交付(?:房|土地|不動產)")

# 民訴第427條第2項:不問金額適用簡易程序的事件
_SUMMARY_EVENTS = (
    (1, "建築物或其他工作物定期租賃或定期借貸", r"定期租賃|定期借貸"),
    (2, "僱傭關係且僱傭期間在一年以下", r"僱傭|勞資|解僱|工資"),
    (3, "旅客與旅館、飲食店或運送人間的食宿、運送費或寄存物", r"旅館|飲食店|運送費"),
    (4, "請求保護占有", r"保護占有|占有回復"),
    (5, "定不動產界線或設置界標", r"界線|界標"),
    (6, "本於票據有所請求", r"票據|本票|支票|匯票"),
    (7, "本於合會有所請求", r"合會|標會"),
    (8, "利息、紅利、租金、退職金或其他定期給付", r"退職金|紅利|定期給付"),
    (9, "動產租賃或使用借貸", r"動產租賃|使用借貸"),
    (11, "道路交通事故", r"交通事故|車禍"),
)
# 民訴第403條第1項:起訴前應經法院調解的事件(第11款依金額另外判斷)
_MEDIATION_EVENTS = (
    (1, "相鄰關係", r"相鄰"),
    (2, "不動產界線或界標", r"界線|界標"),
    (3, "不動產共有物的管理、處分或分割", r"共有物|分割共有"),
    (4, "建築物區分所有", r"區分所有|公寓大廈"),
    (5, "增減不動產租金或地租", r"(?:增加|減少|減免|調整)(?:租金|地租)"),
    (6, "地上權的期間、範圍、地租", r"地上權"),
    (7, "道路交通事故或醫療糾紛", r"交通事故|車禍|醫療"),
    (8, "僱傭契約", r"僱傭|勞資|解僱|工資"),
    (9, "合夥", r"合夥"),
    (10, "配偶或親屬間的財產權", r"配偶|夫妻|親屬|家屬"),
)
# 依請求權性質提示可能適用的時效條文,先比對到者優先
_PRESCRIPTION = (
    (r"交通事故|車禍|侵權|損害賠償", ["民法第197條"], "侵權行為損害賠償：知有損害及賠償義務人時起 2 年，自行為時起 10 年"),
    (r"利息|紅利|租金|贍養費|退職金", ["民法第126條"], "定期給付：各期 5 年"),
    (r"工程款|承攬|報酬", ["民法第127條第7款"], "承攬人報酬：2 年"),
    (r"買賣|價金|貨款|商品", ["民法第127條第8款"], "商人商品代價：2 年"),
    (r"借款|借貸|不當得利", ["民法第125條"], "一般請求權：15 年"),
)
_LABOR_RE = re.compile(r"勞資|勞動|僱傭|解僱|工資")


def _basis(article, item=None, law=CIVIL_PROCEDURE, paragraph=None):
    return f"{law}第{article}" + (f"第{paragraph}項" if paragraph else "") + (f"第{item}款" if item else "")


def _procedure(claim_amount, claims):
    if claim_amount is None:
        return {"type": "待確認", "message": f"請求金額未填，無法提示程序類型；{_VALUE_NOTE}。",
                "legal_basis": [f"{CIVIL_PROCEDURE}第427條", f"{CIVIL_PROCEDURE}第77條之1"]}
    non_money = bool(_NON_MONEY_RE.search(claims or ""))
    if claim_amount <= 100000 and not non_money:
        return {"type": "可能小額", "message": "金額在 10 萬元以下，可能適用小額程序(限請求給付金錢、代替物或有價證券)；"
                                             f"本系統沒有模擬小額程序的簡化流程。{_VALUE_NOTE}。",
                "legal_basis": [f"{CIVIL_PROCEDURE}第436條之8", f"{CIVIL_PROCEDURE}第77條之1"]}
    if claim_amount <= 500000:
        return {"type": "可能簡易", "message": f"金額在 50 萬元以下，可能適用簡易程序；本系統沒有模擬簡易程序的簡化流程。{_VALUE_NOTE}。",
                "legal_basis": [f"{CIVIL_PROCEDURE}第427條第1項", f"{CIVIL_PROCEDURE}第77條之1"]}
    return {"type": "依金額屬通常程序範圍", "message": f"依填寫金額屬通常程序範圍；仍請確認是否屬不問金額適用簡易程序的事件。{_VALUE_NOTE}。",
            "legal_basis": [f"{CIVIL_PROCEDURE}第427條", f"{CIVIL_PROCEDURE}第77條之1"]}


def _earliest_date(evidence):
    dates = []
    for item in evidence or ():
        try:
            dates.append(datetime.date.fromisoformat(item.get("date") or ""))
        except ValueError:
            continue
    return min(dates) if dates else None


def precheck(case_type, claims, claim_amount=None, evidence=(), today=None):
    """回傳 {procedure, warnings, note}。warnings 每則有 code、message、legal_basis。"""
    text = f"{case_type or ''} {claims or ''}"
    warnings = []

    for item, label, pattern in _SUMMARY_EVENTS:
        if re.search(pattern, text):
            warnings.append({"code": "summary_event", "message": f"可能屬不問金額適用簡易程序的事件(第 {item} 款：{label})，請律師確認。",
                             "legal_basis": [_basis("427條", item, paragraph=2)]})

    mediation = [(item, label) for item, label, pattern in _MEDIATION_EVENTS if re.search(pattern, text)]
    if claim_amount is not None and claim_amount <= 500000 and not _NON_MONEY_RE.search(claims or ""):
        mediation.append((11, "財產權爭執且金額在 50 萬元以下"))
    for item, label in mediation:
        warnings.append({"code": "mediation", "message": f"可能屬起訴前應經法院調解的事件(第 {item} 款：{label})；無第406條第1項事由而逕行起訴，"
                                                         "依第424條視為調解之聲請，請律師確認。",
                         "legal_basis": [_basis("403條", item, paragraph=1), f"{CIVIL_PROCEDURE}第424條"]})

    hint = next(((articles, label) for pattern, articles, label in _PRESCRIPTION if re.search(pattern, text)), None)
    articles, label = hint if hint else (["民法第125條"], "依請求權性質而定，一般為 15 年")
    message = f"可能適用的時效：{label}。"
    earliest = _earliest_date(evidence)
    if earliest:
        years = ((today or datetime.date.today()) - earliest).days / 365.25
        message += f"證據清單最早日期 {earliest.isoformat()}，距今約 {years:.1f} 年。"
    warnings.append({"code": "prescription", "message": message + "可能涉及時效，請律師確認。", "legal_basis": articles})

    if _LABOR_RE.search(text):
        warnings.append({"code": "labor", "message": "勞動事件另有勞動事件法的規定，本系統不判斷，請律師確認。", "legal_basis": []})
    if not evidence:
        warnings.append({"code": "no_evidence", "message": "沒有證據清單：事實只能對應主張經過，也不會有預期不爭執事項。", "legal_basis": []})

    return {"procedure": _procedure(claim_amount, claims), "warnings": warnings, "note": NOTE}
