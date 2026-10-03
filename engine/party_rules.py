"""商工公示事實的確定性摘要與程序警示；不產生新法律主張。"""
import datetime
import re

from engine import court_map, gcis

NORMAL = "核准設立"
FOREIGN_NORMAL = "核准登記"
ABNORMAL = {"解散", "廢止", "廢止登記", "撤銷"}
LIQUIDATED = {"解散已清算完結", "撤銷已清算完結"}
FOREIGN_PREFIXES = (
    "美商", "日商", "英商", "德商", "法商", "韓商", "港商", "香港商", "澳門商", "新加坡商",
    "荷蘭商", "瑞士商", "澳商", "加拿大商", "英屬維京群島商", "英屬開曼群島商",
    "開曼群島商", "英屬百慕達商", "百慕達商", "薩摩亞商", "馬來西亞商", "泰商",
    "義大利商", "比利時商", "盧森堡商", "紐西蘭商", "印度商", "瑞典商", "丹麥商",
    "西班牙商", "奧地利商", "菲律賓商", "越南商", "印尼商", "以色列商", "愛爾蘭商",
    "芬蘭商", "挪威商",
)


def _active_suspension(c):
    begin = gcis.roc_date_iso(c.get("Sus_Beg_Date"))
    end = gcis.roc_date_iso(c.get("Sus_End_Date"))
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    return bool(begin and begin <= today and (not end or today <= end))


RULES = [
    {"code": "rep_chairman", "level": None, "when": lambda c: c["basic_ok"] and c["normal"] and c["form"] == "股份有限公司", "message": "法定代理人帶入：董事長 {rep}", "legal_basis": ["公司法第208條"]},
    {"code": "rep_director", "level": None, "when": lambda c: c["basic_ok"] and c["normal"] and c["form"] == "有限公司", "message": "法定代理人帶入：董事／董事長 {rep}", "legal_basis": ["公司法第108條"]},
    {"code": "rep_mismatch", "level": "warn", "when": lambda c: c["basic_ok"] and c["normal"] and c["form"] == "股份有限公司" and bool(c["chairman"]) and bool(c["rep"]) and c["chairman"] != c["rep"], "message": "登記負責人與董監事名單的董事長不一致，請確認法定代理人", "legal_basis": ["公司法第208條"]},
    {"code": "foreign_branch", "level": "warn", "when": lambda c: c["basic_ok"] and c["form"] == "外國公司" and c["status"] == FOREIGN_NORMAL, "message": "此為外國公司在臺分公司登記(核准登記),屬正常營業狀態;登記之在中華民國境內負責人為 {rep_display}。外國公司與中華民國公司有同一之權利能力;當事人列法與法定代理人(在臺負責人或外國公司之代表人)需律師確認。管轄依其在中華民國之主事務所或主營業所", "legal_basis": ["公司法第4條", "公司法第372條", "民事訴訟法第2條"]},
    {"code": "foreign_dissolved", "level": "bad", "when": lambda c: c["basic_ok"] and c["form"] == "外國公司" and c["status"] in ABNORMAL, "message": "外國公司在臺分公司已{status}。應就在中華民國境內營業所生之債權債務清算了結;除外國公司另有指定清算人外,以其在中華民國境內之負責人或分公司經理人為清算人;未了之債務仍由外國公司清償。請律師確認", "legal_basis": ["公司法第380條"]},
    *[
        {"code": "dissolved", "level": "bad",
         "when": lambda c, form=form, statuses=statuses: c["basic_ok"] and c["form"] == form and c["status"] in statuses,
         "message": "對造已{status}。除合併、分割、破產外應行清算，於清算範圍內視為尚未解散；法定代理人應列清算人，不可照列原負責人。" + detail,
         "legal_basis": basis + (["公司法第26條之1"] if form != "其他" and statuses == {"廢止", "廢止登記", "撤銷"} else [])}
        for form, detail, basis in [
            ("股份有限公司", "股份有限公司原則上以解散前全體董事為清算人；章程另有規定或股東會另選者，從其選任；無法依此決定時，得聲請法院選派。登記資料已不顯示董事與清算人，請調閱解散前之公司變更登記表，並向法院查詢有無清算人就任聲報。清算人有數人而未推定代表者，各有對外代表權，書狀應列全體清算人或已推定之代表清算人。例外：公司與董事（含身兼清算人之前董事）間的訴訟，由監察人代表公司。",
             ["公司法第24條", "公司法第25條", "公司法第8條", "公司法第322條", "公司法第85條", "公司法第213條"]),
            ("有限公司", "有限公司原則上以全體股東為清算人；章程另有規定或經股東決議另選者，從其選任。登記資料已不顯示董事與清算人，請調閱解散前之公司變更登記表，並向法院查詢有無清算人就任聲報。清算人有數人而未推定代表者，各有對外代表權，書狀應列全體清算人或已推定之代表清算人。",
             ["公司法第24條", "公司法第25條", "公司法第8條", "公司法第113條", "公司法第79條", "公司法第85條"]),
            ("其他", "清算人依公司型態與章程而定，需律師確認；登記資料已不顯示董事與清算人。",
             ["公司法第24條", "公司法第25條"]),
        ]
        for statuses in [{"解散"}, {"廢止", "廢止登記", "撤銷"}]
    ],
    {"code": "ordered_dissolve", "level": "bad", "when": lambda c: c["basic_ok"] and c["status"] == "核准設立，但已命令解散", "message": "主管機關已命令解散，需確認是否已進入清算，以及法定代理人應如何列載", "legal_basis": ["公司法第24條"]},
    {"code": "merged", "level": "bad", "when": lambda c: c["basic_ok"] and c["status"] == "合併解散", "message": "已因合併而解散，權利義務由存續或新設公司承受，被告應改列存續或新設公司；訴訟中發生合併時，未委任訴訟代理人者程序當然停止；有訴訟代理人時不當然停止，但仍須承受。", "legal_basis": ["公司法第75條", "公司法第319條", "民事訴訟法第169條", "民事訴訟法第173條"]},
    {"code": "bankrupt", "level": "bad", "when": lambda c: c["basic_ok"] and c["status"] == "破產", "message": "已宣告破產。關於破產財團之訴訟，應以破產管理人為當事人（破產法第75條及實務見解），仍列破產公司可能當事人不適格；訴訟中受破產宣告者，關於破產財團之訴訟程序當然停止（有訴訟代理人亦同）。請律師確認。", "legal_basis": ["民事訴訟法第174條"]},
    {"code": "liquidated", "level": "warn", "when": lambda c: c["basic_ok"] and c["form"] != "外國公司" and c["status"] in LIQUIDATED, "message": "已登記清算完結。清算完結的聲報備查不等於法人格消滅；若仍有未了債務或訴訟，實務認法人格仍存續，可列清算人為法定代理人（參最高法院114年度台聲字第397號）。請律師確認。", "legal_basis": ["公司法第25條", "民法第40條"]},
    {"code": "withdrawn", "level": "warn", "when": lambda c: c["basic_ok"] and c["kind"] == "company" and c["form"] != "外國公司" and bool(c["status"]) and c["status"] not in {NORMAL, "核准設立，但已命令解散", "合併解散", "破產"} | ABNORMAL | LIQUIDATED, "message": "公司狀態非「核准設立」（{status}），需人工確認", "legal_basis": ["民事訴訟法第249條"]},
    {"code": "no_rep", "level": "warn", "when": lambda c: c["basic_ok"] and c["kind"] == "company" and c["form"] != "外國公司" and not c["normal"] and not c["rep"], "message": "官方登記未提供負責人，書狀的法定代理人欄不自動帶入", "legal_basis": ["民事訴訟法第116條"]},
    {"code": "suspended", "level": "warn", "when": lambda c: c["basic_ok"] and c["suspended"], "message": "公司停業中（{suspension_from}起）。停業不影響法人格與代表人，送達仍得向法定代理人為之；如有日後不能強制執行或甚難執行之虞，可評估聲請假扣押（須釋明請求及假扣押原因）。", "legal_basis": ["民事訴訟法第522條", "民事訴訟法第523條", "民事訴訟法第526條"]},
    {"code": "branch_entity", "level": "warn", "when": lambda c: c["kind"] == "branch", "message": "此統編為分公司。實務見解認分公司就其業務範圍內事項涉訟有當事人能力（最高法院40年台上字第39號判例），亦得以總公司為當事人；因分公司業務涉訟，得於分公司所在地法院起訴。請律師確認。", "legal_basis": ["民事訴訟法第6條"]},
    {"code": "business_entity", "level": "warn", "when": lambda c: c["basic_ok"] and c["kind"] == "business", "message": "此統編為商號，不是公司法人。獨資商號無當事人能力，應以商號主人（負責人）為當事人（最高法院42年台抗字第12號、43年台上字第601號判例）；合夥組織另需確認。請律師確認。", "legal_basis": ["民事訴訟法第40條"]},
    {"code": "name_mismatch", "level": "warn", "when": lambda c: c["basic_ok"] and bool(c["input_name"] and c["name"] and normalize_name(c["input_name"]) != normalize_name(c["name"])), "message": "輸入名稱「{input_name}」與登記名稱「{name}」不一致，書狀應以登記名稱為準", "legal_basis": ["民事訴訟法第116條"]},
    {"code": "not_found", "level": "bad", "when": lambda c: c["kind"] == "not_found", "message": "商工登記查無此統編", "legal_basis": []},
]


def normalize_name(value):
    return re.sub(r"\s+", "", str(value or "")).replace("台", "臺")


def _first(rows):
    return rows[0] if rows else {}


def _value(row, *keys):
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def summarize(ban, kind, results, *, input_name=None):
    """results 為 dataset key → gcis 回傳；失敗來源會帶 error，不混作查無。"""
    basic_result = results.get(kind, {}) if kind in ("company", "business") else {}
    basic_ok = bool(basic_result.get("ok") and basic_result.get("rows"))
    basic = _first(basic_result["rows"]) if basic_ok else {}
    director_rows = results.get("directors", {}).get("rows", [])
    branch_rows = results.get("branches", {}).get("rows", [])
    name = _value(basic, "Company_Name", "Business_Name", "Ban_Name")
    status = _value(basic, "Company_Status_Desc", "Business_Current_Status_Desc", "Business_Status_Desc", "Business_Status", "Business_Status_Name")
    rep = _value(basic, "Responsible_Name", "Responsible_Person_Name")
    address = _value(basic, "Company_Location", "Business_Location", "Business_Address")
    foreign = kind == "company" and basic_ok and (
        status == FOREIGN_NORMAL or bool(name and name.startswith(FOREIGN_PREFIXES)))
    form = ("外國公司" if foreign else "股份有限公司" if (name or "").endswith("股份有限公司")
            else "有限公司" if (name or "").endswith("有限公司") else "其他" if name else None)
    chairman = next((_value(d, "Person_Name") for d in director_rows if _value(d, "Person_Position_Name") == "董事長"), None)
    suspension = None
    if _active_suspension(basic):
        suspension = {"from": gcis.roc_date(basic.get("Sus_Beg_Date")), "to": gcis.roc_date(basic.get("Sus_End_Date"))}
    context = {"kind": kind, "basic_ok": basic_ok, "normal": status == NORMAL, "status": status or "未提供", "form": form,
               "rep": rep, "rep_display": rep or "官方登記未提供", "chairman": chairman, "suspended": bool(suspension),
               "suspension_from": suspension["from"] if suspension else None,
               "input_name": input_name, "name": name}
    legal_representative = None
    if kind == "company" and basic_ok and context["normal"] and rep:
        if form == "股份有限公司" and chairman == rep:
            legal_representative = {"name": rep, "title": "董事長", "basis": ["公司法第208條"]}
        elif form == "有限公司":
            legal_representative = {"name": rep, "title": "董事／董事長", "basis": ["公司法第108條"]}
    warnings = [{"code": rule["code"], "level": rule["level"],
                 "message": rule["message"].format(**context), "legal_basis": rule["legal_basis"]}
                for rule in RULES if rule["level"] and rule["when"](context)]
    if kind == "not_found":
        level = "bad"
    elif kind == "unresolved" or (kind in ("company", "business") and not basic_ok):
        level = "warn"
    elif any(w["level"] == "bad" for w in warnings):
        level = "bad"
    elif warnings or (kind == "company" and status != NORMAL):
        level = "warn"
    else:
        level = "ok"
    sources = [{"dataset": gcis.DATASETS[key][1], "url": value["url"], "fetched_at": value["fetched_at"],
                "ok": value["ok"], "error": value["error"]} for key, value in results.items()]
    used = [gcis.DATASETS[key][1] for key, value in results.items() if value["ok"]]
    branches = [{"ban": _value(row, "Branch_Office_Business_Accounting_NO"), "name": _value(row, "Branch_Office_Name"),
                 "manager": _value(row, "Branch_Office_Manager_Name"), "address": _value(row, "Branch_Office_Location"),
                 "status_text": _value(row, "Branch_Office_Status_Desc")} for row in branch_rows]
    return {
        "ban": ban, "entity_type": kind, "name": name, "status_text": status,
        "status_level": level, "company_form": form, "basic_data_available": basic_ok,
        "legal_representative": legal_representative, "registered_responsible_name": rep,
        "address": address,
        "capital": {"registered": basic.get("Capital_Stock_Amount"), "paid_in": basic.get("Paid_In_Capital_Amount")} if kind == "company" else None,
        "setup_date": gcis.roc_date(basic.get("Company_Setup_Date") or basic.get("Business_Setup_Approve_Date") or basic.get("Business_Setup_Date")),
        "last_change_date": gcis.roc_date(basic.get("Change_Of_Approval_Data") or basic.get("Change_Of_Approval_Date")),
        "suspension": suspension,
        "directors": [{"title": _value(row, "Person_Position_Name"), "name": _value(row, "Person_Name"),
                       "juristic_person": _value(row, "Juristic_Person_Name")} for row in director_rows],
        "branches": {"count": len(branches), "truncated": len(branches) >= 50, "items": branches},
        "warnings": warnings,
        "jurisdiction": court_map.jurisdiction(address, [b["address"] for b in branches if b["address"]]),
        "always_notes": ["登記資料為查詢當下的狀態，不代表簽約或起訴當時的狀態"],
        "sources": sources,
        "attribution": f"{gcis.ATTRIBUTION} [{ '、'.join(used) }]" if used else None,
    }
