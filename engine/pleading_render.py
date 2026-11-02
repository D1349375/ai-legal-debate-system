"""由程式組成書狀正文:模型只交內容,當事人欄、聲明框架、證物欄、此致由這裡組。純函數、不碰 DB、不呼叫 LLM。

結構照司法院「民事起訴狀(一般)」參考範例(corpus/pleadings/reference/)。商工查核結果直接進當事人欄,不經模型;
有 bad 等級程序事項時,法定代理人一律寫「清算人(待查明:…)」之類的待查寫法,不照列登記負責人,也不寫任何姓名。
"""
from engine import fact_points as cf
from engine.party_issues import cured_in
from engine.verify import parse_citation

ROLE_LABEL = {"plaintiff": "原告", "defendant": "被告"}
BASIS_ROLE = {"primary": "先位", "alternative": "備位", "concurrent": "併列"}
NUMERALS = "一二三四五六七八九十"
PENDING = "(待填:{})"
# 有這些程序事項時,法定代理人欄的寫法(engine/party_issues.py 的 warning_code);其餘 bad 等級事項用 _REP_PENDING_DEFAULT
_REP_PENDING = {
    "dissolved": "清算人(待查明:清算人為何人及其依據)",
    "foreign_dissolved": "清算人(待查明:清算人為何人及其依據)",
    "ordered_dissolve": "法定代理人(待查明:是否已進入清算,清算人為何人)",
    "reorganization": "重整人(待查明:登記之重整人與重整監督人許可)",
    "interim_manager": "臨時管理人(待查明:登記之臨時管理人)",
}
_REP_PENDING_DEFAULT = "法定代理人(待查明:依商工登記警示確認)"

COMPLAINT_KEYS = ("cause", "prayers", "claim_basis", "fact_points", "legal_argument", "procedural_statements", "basis",
                  "citations", "precedent_notes", "fact_gaps", "lawyer_notes")


def numeral(n):
    if n <= 10:
        return NUMERALS[n - 1]
    return ("" if n < 20 else NUMERALS[n // 10 - 1]) + "十" + ("" if n % 10 == 0 else NUMERALS[n % 10 - 1])


def representative_text(result):
    """商工查核結果的法定代理人顯示文字。與 ui/app.js partyRepresentativeText 一致,改一邊要一起改。"""
    if result.get("entity_type") == "branch":
        return "本功能未查詢分公司登記資料"
    if result.get("query_status") == "failed":
        return "查核未完成，未自動帶入"
    if result.get("basic_data_available") is False:
        return "基本資料未取得，未自動帶入"
    rep = result.get("legal_representative")
    if rep:
        return f"{rep['title']} {rep['name']}"
    codes = {w.get("code") for w in result.get("warnings") or []}
    if "foreign_branch" in codes:
        return f"待確認(在臺負責人:{result.get('registered_responsible_name') or '官方登記未提供'})"
    if "foreign_dissolved" in codes:
        return "待確認(清算人)"
    if "dissolved" in codes:
        return "待確認（清算人）"
    if result.get("company_form") == "股份有限公司" and any(
            s.get("dataset") == "公司登記董監事資料" and not s.get("ok") for s in result.get("sources") or []):
        return "董監事資料查詢失敗，未自動帶入"
    return "官方未提供／未自動帶入"


def _bad_representation_issue(role, procedural):
    return next((i for i in (procedural or {}).get("issues") or []
                 if i["party_role"] == role and i["level"] == "bad" and i["kind"] == "法定代理"), None)


def party_lines(role, party_input, check, procedural):
    """當事人欄。check 是該方最新商工查核結果(沒查核為 None):有查核照登記帶入;沒查核照實留待填。"""
    label = ROLE_LABEL[role]
    entered = (party_input or {}).get("name")
    if not check:
        return [f"{label}　{entered or PENDING.format('姓名或名稱')}", "　住所或營業所:" + PENDING.format("地址"),
                "　(未提供統一編號,未查核商工登記;如為法人,法定代理人待填)"]
    lines = [f"{label}　{check.get('name') or entered or PENDING.format('名稱')}"]
    if check.get("ban"):
        lines.append(f"　統一編號:{check['ban']}")
    lines.append("　營業所:" + (check.get("address") or PENDING.format("地址,商工登記未提供")))
    issue = _bad_representation_issue(role, procedural)
    if issue:
        rep = _REP_PENDING.get(issue["warning_code"], _REP_PENDING_DEFAULT)
    elif check.get("legal_representative") and check.get("query_status") != "failed":
        rep = representative_text(check)
    else:
        rep = PENDING.format("法定代理人;商工查核:" + representative_text(check))
    lines.append(f"法定代理人　{rep}")
    return lines


def _list_of_str(value):
    return isinstance(value, list) and all(isinstance(x, str) and x.strip() for x in value)


def complaint_problems(payload, *, case, procedural, analysis_text):
    """起訴狀 JSON 的結構檢查(硬擋)。case 是 case_payload;procedural 是程序事項;analysis_text 是原告分析的公開段落。"""
    if not isinstance(payload, dict):
        return ["起訴狀輸出必須是 JSON 物件"]
    problems = []
    if not isinstance(payload.get("cause"), str) or not payload["cause"].strip():
        problems.append("cause(案由)不可空白")
    if not _list_of_str(payload.get("prayers")) or not payload["prayers"]:
        problems.append("prayers(訴之聲明)必須是非空的字串陣列")
    if not isinstance(payload.get("legal_argument"), str) or not payload["legal_argument"].strip():
        problems.append("legal_argument 不可空白")
    for key in ("citations", "fact_gaps", "lawyer_notes"):
        if not isinstance(payload.get(key, []), list) or not all(isinstance(x, str) for x in payload.get(key, [])):
            problems.append(f"{key} 必須是字串陣列")
    basis = payload.get("basis")
    if not _list_of_str(basis) or not basis:
        problems.append("basis(請求權基礎清單)必須是非空的法條陣列")
        basis = []
    for b in basis:
        if parse_citation(b)["type"] != "statute":
            problems.append(f"basis 只能放法條,且要寫成「OO法第N條」:{b}")
    used = []
    claim_basis = payload.get("claim_basis")
    if not isinstance(claim_basis, list) or not claim_basis:
        problems.append("claim_basis 必須是非空陣列")
        claim_basis = []
    for i, item in enumerate(claim_basis, 1):
        if not isinstance(item, dict):
            problems.append(f"claim_basis 第 {i} 筆不是物件")
            continue
        if item.get("role") not in BASIS_ROLE:
            problems.append(f"claim_basis 第 {i} 筆的 role 只能是 {'、'.join(BASIS_ROLE)}:{item.get('role')!r}")
        if not _list_of_str(item.get("basis")) or not item["basis"]:
            problems.append(f"claim_basis 第 {i} 筆的 basis 必須是非空的法條陣列")
        else:
            used += item["basis"]
    if basis and used and set(basis) != set(used):
        problems.append("basis 要等於 claim_basis 各筆 basis 的聯集:basis 有 " + "、".join(basis)
                        + ";claim_basis 有 " + "、".join(dict.fromkeys(used)))
    problems += cf.fact_point_problems(payload.get("fact_points"), evidence_ids=[e["id"] for e in case.get("evidence") or []],
                                       facts_summary=case.get("facts_summary"))
    statements = payload.get("procedural_statements", [])
    if not isinstance(statements, list) or not all(isinstance(s, dict) and isinstance(s.get("id"), str)
                                                   and isinstance(s.get("text"), str) and s["text"].strip()
                                                   for s in statements):
        problems.append("procedural_statements 每筆都要有 id 與 text")
        statements = []
    issue_ids = {i["id"] for i in (procedural or {}).get("issues") or []}
    answered = {s["id"] for s in statements}
    for issue in (procedural or {}).get("issues") or []:
        if not issue["ex_officio"]:
            continue
        if issue["id"] not in answered:
            problems.append(f"procedural_statements 缺少起訴審查事項 {issue['id']} 的說明")
        if not cured_in(analysis_text, issue["id"]):
            problems.append(f"原告分析沒有「程序補正({issue['id']})」段落,先退回分析 subagent 補寫")
    for extra in sorted(answered - issue_ids):
        problems.append(f"procedural_statements 的 {extra} 不是本案的起訴審查事項")
    notes = payload.get("precedent_notes", [])
    if not isinstance(notes, list) or not all(isinstance(n, dict) and isinstance(n.get("citation"), str) for n in notes):
        problems.append("precedent_notes 每筆都要是含 citation 的物件")
        notes = []
    noted = {_key(n["citation"]) for n in notes}
    citations = payload.get("citations") if isinstance(payload.get("citations"), list) else []
    for c in citations:
        if isinstance(c, str) and parse_citation(c)["type"] == "judgment" and _key(c) not in noted:
            problems.append(f"正式引用的判決要附 precedent_notes(全文原句與命題):{c}")
    cited = {_key(c) for c in citations if isinstance(c, str)}
    for n in notes:
        if _key(n["citation"]) not in cited:
            problems.append(f"precedent_notes 的 {n['citation']} 沒有列在 citations")
    return problems


def _key(citation):
    parsed = parse_citation(citation)
    if parsed["type"] == "judgment":
        return (parsed["jyear"], parsed["jcase"], parsed["jno"])
    return citation


def render_complaint(payload, *, case, party_checks, procedural):
    """依已通過 complaint_problems 的 JSON 組成起訴狀正文。事實缺口與律師附註放在正文後的【本稿產出說明】,
    畫面與匯出都會和正文分開(server/pleading_export.py split_draft_note)。"""
    parties = case.get("parties") or {}
    amount = case.get("claim_amount")
    lines = ["民事起訴狀", "案號:" + PENDING.format("法院分案後之案號"), "承辦股別:" + PENDING.format("股別"),
             "訴訟標的金額或價額:" + (f"新臺幣{amount:,}元" if amount is not None else PENDING.format("價額由法院核定")), ""]
    for role in ("plaintiff", "defendant"):
        lines += party_lines(role, parties.get(role), (party_checks or {}).get(role), procedural)
        lines.append("")
    lines += [f"為請求{payload['cause']}提起訴訟事:", "訴之聲明"]
    lines += [f"{numeral(i)}、{p}" for i, p in enumerate(payload["prayers"], 1)]
    lines += ["", "事實及理由", "一、事實"]
    points = payload["fact_points"]
    lines += [f"({numeral(i)}){p['text'].strip()}〔{p['id']}〕" for i, p in enumerate(points, 1)]
    lines.append("二、請求權基礎")
    for i, item in enumerate(sorted(payload["claim_basis"], key=lambda b: b.get("seq") or 0), 1):
        target = f"({item['prayer']})" if item.get("prayer") else ""
        lines.append(f"({numeral(i)}){BASIS_ROLE[item['role']]}:{'、'.join(item['basis'])}{target}")
    lines += ["三、理由", payload["legal_argument"].strip()]
    statements = payload.get("procedural_statements") or []
    if statements:
        lines.append("四、程序事項")
        lines += [f"({numeral(i)}){s['text'].strip()}" for i, s in enumerate(statements, 1)]
    used = {e for p in points for e in p.get("evidence_ids") or []}
    evidence = [e for e in case.get("evidence") or [] if e["id"] in used]
    lines += ["", "證物名稱及件數:"]
    lines += [f"{e['id']}:{e['description']}" for e in evidence] or ["(本狀事實尚未附證據,待律師補列)"]
    lines += ["", "此　致", PENDING.format("受理法院") + "　公鑒", "中華民國(待填)年(待填)月(待填)日"]
    plaintiff = party_lines("plaintiff", parties.get("plaintiff"), (party_checks or {}).get("plaintiff"), procedural)
    lines.append("具狀人　" + plaintiff[0])
    lines += ["　　　　" + line for line in plaintiff if line.startswith("法定代理人")]
    lines.append("撰狀人　" + PENDING.format("訴訟代理人"))
    gaps, notes = payload.get("fact_gaps") or [], payload.get("lawyer_notes") or []
    if gaps or notes:
        lines += ["", "---", "【本稿產出說明】給律師,不是起訴狀正文"]
        lines += [f"- 事實缺口(待確認):{g}" for g in gaps]
        lines += [f"- 律師附註:{n}" for n in notes]
    return "\n".join(lines) + "\n"


def stored_complaint(payload):
    """落地進 structured_json 的內容:只留規格列出的欄位,模型多給的欄位不存。"""
    return {key: payload.get(key) for key in COMPLAINT_KEYS if key in payload}
