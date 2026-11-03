"""DB 落地層:所有寫入走這裡。

紀律(對齊 DebateSystem 的既有邊界):
- 判斷/裁判落地即定案:record_argument / record_verdict 遇到既有紀錄一律報錯，不提供覆寫介面。
- record_verdict / record_pleading 是查證閘門的機械強制點:citations_used 中只要有一筆
  在 CitationVerification 裡不是 published 狀態，直接 raise，不是 warn——這把 Startup Guide
  的 Phase 2.5 精神變成資料庫層強制，不是文件規範，涵蓋訴狀與判決書兩種輸出。
"""
import datetime
import json
import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from engine.case_input import (
    clean_claim_amount, clean_evidence, clean_known_gaps, clean_opponent_responses, clean_represented_side,
)
from engine.fact_points import cf_ids
from engine.internal_review import strip_internal_review
from engine.precheck import precheck
from database.schema import (
    Base, Case, DebateArgument, CourtQuestion, Verdict, CitationVerification, PleadingDraft, PartyCheck, LiveRun,
    IssueSheet,
)
from engine.aggregate import compile_weak_points, disagreement, VALID_SIDES
from engine.party_issues import procedural_issues
from engine.verify import citation_warning, parse_citation

_DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'legal_debate.db')
# UI 觸發即時執行時，後端以此環境變數把自己使用的資料庫交給 Claude Code 子程序，
# 確保 subagent 經 main.py 落地的紀錄寫進同一顆資料庫(測試時則是暫存資料庫)。
DB_URL_ENV = 'LEGALDEBATE_DB_URL'


def _sync_schema(engine):
    """為已存在的 DB 檔案自動補上 schema.py 之後新增的欄位，同 DebateSystem 的既有作法。"""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            existing_cols = {c['name'] for c in inspector.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing_cols:
                    continue
                col_type = col.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col_type}'))
                print(f"[自動遷移] {table.name} 新增欄位 {col.name} ({col_type})")


def default_db_path():
    return _DB_FILE


def make_session_factory(db_url=None):
    """建立一次 engine、之後重複取 session(長駐程序用,如 server/;CLI 仍用 get_session)。"""
    engine = create_engine(db_url or os.environ.get(DB_URL_ENV) or f"sqlite:///{_DB_FILE}")
    Base.metadata.create_all(engine)
    _sync_schema(engine)
    return sessionmaker(bind=engine)


def get_session(db_url=None):
    return make_session_factory(db_url)()


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _dumps_or_none(value):
    return json.dumps(value, ensure_ascii=False) if value else None


def record_case(session, *, case_id, case_type, facts_summary, claims, parties=None, created_via=None,
                protocol=None, represented_side=None, claim_amount=None, evidence=None,
                opponent_responses=None, known_gaps=None):
    if session.query(Case).filter_by(case_id=case_id).one_or_none():
        raise ValueError(f"{case_id} 已存在，不可覆寫")
    if protocol not in (None, "v2"):
        raise ValueError(f"非法 protocol: {protocol}")
    if protocol == "v2":
        represented_side = clean_represented_side(represented_side)
    row = Case(case_id=case_id, case_type=case_type, facts_summary=facts_summary,
               claims=claims, created_at=_now_iso(), created_via=created_via,
               parties_json=json.dumps(parties, ensure_ascii=False) if parties else None,
               protocol=protocol, represented_side=represented_side, claim_amount=clean_claim_amount(claim_amount),
               evidence_json=_dumps_or_none(clean_evidence(evidence)),
               opponent_responses_json=_dumps_or_none(clean_opponent_responses(opponent_responses)),
               known_gaps_json=_dumps_or_none(clean_known_gaps(known_gaps)))
    session.add(row)
    session.commit()
    return row


def case_payload(row):
    """案件輸入的完整內容,給 UI、角色檔與即時執行的 case.json 用。"""
    return {"case_id": row.case_id, "case_type": row.case_type, "facts_summary": row.facts_summary, "claims": row.claims,
            "parties": json.loads(row.parties_json) if row.parties_json else None,
            "protocol": row.protocol, "represented_side": row.represented_side, "claim_amount": row.claim_amount,
            "evidence": json.loads(row.evidence_json) if row.evidence_json else [],
            "opponent_known_responses": json.loads(row.opponent_responses_json) if row.opponent_responses_json else [],
            "known_gaps": json.loads(row.known_gaps_json) if row.known_gaps_json else []}


def case_precheck(row):
    return precheck(row.case_type, row.claims, row.claim_amount, json.loads(row.evidence_json) if row.evidence_json else [])


def plaintiff_view(session, case_id):
    """原告方的角色檔:案件輸入全部、商工查核與程序事項、起訴前檢查。"""
    row = session.query(Case).filter_by(case_id=case_id).one_or_none()
    if row is None:
        raise ValueError(f"找不到案件 {case_id}")
    checks = latest_party_checks(session, case_id)
    return {"role": "plaintiff", "case": case_payload(row), "party_checks": checks,
            "procedural_issues": procedural_issues(checks), "precheck": case_precheck(row),
            "complaint": current_complaint(session, case_id)}


def defendant_view(session, case_id, complaint_id=None):
    """被告方的角色檔(規格 5.4):只有起訴狀這一面。給起訴狀正文(保留〔CF〕,去掉【本稿產出說明】)、正文各 CF
    用到的證據、對方已知反應、商工查核與程序事項;不給事實經過、已知缺口、原告分析、沒列進起訴狀的證據與證明目的。
    complaint_id 沒給時用 current_complaint(關卡 1 確認版;還沒確認時是最新系統原稿),和 answer、judge_role_view
    讀同一版。CF 以這一版正文為準,證據編號取自系統原稿的 fact_points,律師新增的 CF 沒有證據。"""
    from server.pleading_export import split_draft_note
    row = session.query(Case).filter_by(case_id=case_id).one_or_none()
    if row is None:
        raise ValueError(f"找不到案件 {case_id}")
    drafts = {d.id: d for d in session.query(PleadingDraft).filter_by(case_id=case_id, pleading_type="complaint").all()}
    if complaint_id is None:
        current = current_complaint(session, case_id)
        complaint_id = current["version_id"] if current else None
    complaint = drafts.get(complaint_id)
    if complaint is None or complaint.citation_verification_status != "published":
        raise ValueError(f"{case_id} 沒有可以給被告的起訴狀(#{complaint_id})")
    origin = complaint
    while origin.structured_json is None and origin.parent_id in drafts:
        origin = drafts[origin.parent_id]
    planned = {p["id"]: p.get("evidence_ids") or []
               for p in json.loads(origin.structured_json or "{}").get("fact_points") or []}
    text = split_draft_note(complaint.draft_text)[0]
    fact_evidence = {cf: planned.get(cf, []) for cf in cf_ids(text)}
    used = {e for ids in fact_evidence.values() for e in ids}
    evidence = [{k: e[k] for k in ("id", "type", "date", "description")}
                for e in json.loads(row.evidence_json or "[]") if e["id"] in used]
    checks = latest_party_checks(session, case_id)
    return {"role": "defendant", "case_id": case_id,
            "complaint": {"id": complaint.id, "source": complaint.source or "system", "text": text},
            "fact_evidence": fact_evidence, "evidence": evidence,
            "opponent_known_responses": json.loads(row.opponent_responses_json or "[]"),
            "party_checks": checks, "procedural_issues": procedural_issues(checks)}


def judge_role_view(session, case_id):
    """法官的角色檔(規格 5.5):起訴狀(關卡 1 確認版)、模擬答辯狀與逐點表態、起訴狀用到的證據、商工查核與程序事項,
    以及已落地的爭點整理表(P3 之後的步驟與續跑從這裡讀;還沒落地時是 None)。
    不給事實經過、已知缺口、對方已知反應、雙方的分析與內部檢討。起訴狀的部分沿用 defendant_view(同一套去除規則)。"""
    from server.pleading_export import split_draft_note
    current = current_complaint(session, case_id)
    if current is None:
        raise ValueError(f"{case_id} 沒有起訴狀")
    answer = latest_answer(session, case_id)
    if answer is None:
        raise ValueError(f"{case_id} 還沒有模擬答辯狀")
    view = defendant_view(session, case_id, complaint_id=current["version_id"])
    structured = json.loads(answer.structured_json or "{}")
    sheet = issue_sheet(session, case_id)
    return {"role": "judge", "case_id": case_id, "complaint": view["complaint"],
            "answer": {"id": answer.id, "text": split_draft_note(answer.draft_text)[0],
                       "responses": structured.get("responses") or [], "defenses": structured.get("defenses") or []},
            "evidence": view["evidence"], "party_checks": view["party_checks"],
            "procedural_issues": view["procedural_issues"], "issue_sheet": sheet["sheet"] if sheet else None}


def latest_answer(session, case_id):
    """流程產生的最新一份模擬答辯狀(不含律師編輯版);沒有時回傳 None。"""
    rows = [r for r in session.query(PleadingDraft).filter_by(case_id=case_id).order_by(PleadingDraft.id).all()
            if r.pleading_type == "answer" and r.source in (None, "system")]
    return rows[-1] if rows else None


def _pleading_admission_sources(session, case_id):
    """書狀交換流程裡書狀算誰的話(舊設計殘留第 1 項)。起訴狀正文全部是原告的話;答辯狀只有 admit 的 CF 原文、
    表態理由、抗辯與答辯理由是被告的話。答辯狀正文會逐點引述起訴狀(含否認的點),不能整份算被告的話。"""
    from engine.pleading_render import complaint_facts
    from server.pleading_export import split_draft_note
    current = current_complaint(session, case_id)
    if current is None:
        return [], []
    plaintiff = [split_draft_note(current["draft_text"])[0]]
    answer = latest_answer(session, case_id)
    if answer is None:
        return plaintiff, []
    structured = json.loads(answer.structured_json or "{}")
    facts = complaint_facts(plaintiff[0])
    responses = structured.get("responses") or []
    defendant = [facts[r["fact_id"]] for r in responses if r.get("stance") == "admit" and r.get("fact_id") in facts]
    defendant += [r["reason"] for r in responses if r.get("reason")]
    defendant += [d["statement"] for d in structured.get("defenses") or [] if d.get("statement")]
    defendant += [structured["legal_argument"]] if structured.get("legal_argument") else []
    return plaintiff, defendant


def record_argument(session, *, case_id, side, stage, position, reasoning,
                     cited_statutes=None, cited_precedents=None, falsifier=None, model_id=None, basis=None):
    if side not in VALID_SIDES:
        raise ValueError(f"非法 side: {side}")
    if stage not in (1, 2, 3):
        raise ValueError("stage 只能是 1(爭點整理)/2(訊問攻防)/3(辯論終結)")
    if stage in (2, 3) and not (falsifier and falsifier.strip()):
        raise ValueError(f"stage {stage} 須提供 falsifier")
    exists = session.query(DebateArgument).filter_by(
        case_id=case_id, side=side, stage=stage).one_or_none()
    if exists is not None:
        raise ValueError(f"{case_id} {side} stage{stage} 已落地，不可覆寫")
    row = DebateArgument(
        case_id=case_id, side=side, stage=stage, position=position, reasoning=reasoning,
        cited_statutes=json.dumps(cited_statutes or [], ensure_ascii=False),
        cited_precedents=json.dumps(cited_precedents or [], ensure_ascii=False),
        falsifier=falsifier, model_id=model_id, created_at=_now_iso(),
        basis_json=json.dumps(basis, ensure_ascii=False) if basis is not None else None,
    )
    session.add(row)
    session.commit()
    return row


def record_question(session, *, case_id, question_text, target_side, based_on):
    if target_side not in VALID_SIDES:
        raise ValueError(f"非法 target_side: {target_side}")
    if not based_on or not based_on.strip():
        raise ValueError("based_on 為必填，訊問須回溯至具體論點，不得憑空生成")
    row = CourtQuestion(case_id=case_id, question_text=question_text,
                         target_side=target_side, based_on=based_on, created_at=_now_iso())
    session.add(row)
    session.commit()
    return row


def _arg_to_dict(row):
    return {
        "side": row.side,
        "reasoning": row.reasoning,
        "falsifier": row.falsifier,
        "cited_statutes": json.loads(row.cited_statutes or "[]"),
        "cited_precedents": json.loads(row.cited_precedents or "[]"),
    }


def admission_sources(session, case_id):
    """自承類用語可以引述的原文:案件事實與雙方論證(不含 falsifier，那是假設句)。
    書狀交換流程(v2)的事實經過是原告律師寫的，只算原告的話；被告的話是律師記下的對方已知反應。"""
    case = session.query(Case).filter_by(case_id=case_id).one_or_none()
    sources = {"plaintiff": [], "defendant": [], "facts": [case.facts_summary] if case else []}
    if case and case.protocol == "v2":
        sources["plaintiff"], sources["facts"] = sources["facts"], []
        sources["defendant"] = [r["text"] for r in json.loads(case.opponent_responses_json or "[]")]
        plaintiff, defendant = _pleading_admission_sources(session, case_id)
        sources["plaintiff"] += plaintiff
        sources["defendant"] += defendant
    for row in session.query(DebateArgument).filter_by(case_id=case_id).all():
        sources[row.side] += [row.position or "", strip_internal_review(row.reasoning)]
    return sources


def public_arguments(session, *, case_id, through_stage=3):
    """法官與對手摘要可以讀的論證:濾掉內部檢討，不含 falsifier(讓步條件另由 judge_view 給法官)。"""
    rows = session.query(DebateArgument).filter_by(case_id=case_id).all()
    return [{"side": r.side, "stage": r.stage, "position": r.position, "argument": strip_internal_review(r.reasoning),
             "cited_statutes": json.loads(r.cited_statutes or "[]"), "cited_precedents": json.loads(r.cited_precedents or "[]")}
            for r in sorted(rows, key=lambda r: (r.stage, r.side)) if r.stage <= through_stage]


def finalize_case(session, *, case_id):
    """機械死穴彙整 + 分歧統計，回傳判決錨點(不落地成獨立資料表——結果直接作為
    record_verdict() 呼叫時 mechanical_anchor_json 的輸入，避免另開一張只為過渡用的表)。
    """
    rows = session.query(DebateArgument).filter_by(case_id=case_id).all()
    if not rows:
        raise ValueError(f"{case_id} 沒有任何攻防紀錄，無法 finalize")
    stage1 = [_arg_to_dict(r) for r in rows if r.stage == 1]
    stage3 = [_arg_to_dict(r) for r in rows if r.stage == 3]
    if len(stage3) < len(VALID_SIDES):
        raise ValueError(f"{case_id} 尚未雙方皆完成 stage3，無法 finalize")
    return {
        "weak_points": compile_weak_points(stage3),
        "position_drift": disagreement(stage1, stage3),
        # 官方事實層:依商工查核轉成的程序事項，法官評估須先處理，不得以實體理由略過
        "procedural_issues": procedural_issues(latest_party_checks(session, case_id)),
    }


def pleading_materials(session, *, case_id, side):
    """Step 9 撰狀素材(唯讀):該方 Stage 3 原文 + 對造 Stage 3 結構化摘要 + 當事人查核與程序事項。

    讓既有案件不重跑攻防就能補產另一方的書狀(例如答辯狀)。對造只給 position 與引用，不給完整論證原文，
    同 Step 4 的萃取紀律；每條引用附上目前查證狀態，只有 published 的能寫進書狀(record_pleading 會再擋一次)。
    """
    if side not in VALID_SIDES:
        raise ValueError(f"非法 side: {side}")
    case = session.query(Case).filter_by(case_id=case_id).one_or_none()
    if case is None:
        raise ValueError(f"找不到案件 {case_id}")
    stage3 = {r.side: r for r in session.query(DebateArgument).filter_by(case_id=case_id, stage=3).all()}
    if side not in stage3:
        raise ValueError(f"{case_id} {side} 尚未完成 stage3,沒有撰狀素材;須先跑完攻防")
    other = next(s for s in VALID_SIDES if s != side)
    status_by_key = {}
    for r in session.query(CitationVerification).all():
        status_by_key.setdefault(_citation_key(r.citation_text), r.status)

    def citations(row):
        cited = json.loads(row.cited_statutes or "[]") + json.loads(row.cited_precedents or "[]")
        return [{"citation_text": c, "status": status_by_key.get(_citation_key(c), "no_record")} for c in cited]

    own = stage3[side]
    opp = stage3.get(other)
    existing = [r for r in session.query(PleadingDraft).filter_by(case_id=case_id).all()
                if r.source in (None, 'system') and pleading_side(r) == side]
    return {
        "case": {"case_id": case.case_id, "case_type": case.case_type, "facts_summary": case.facts_summary,
                 "claims": case.claims, "parties": json.loads(case.parties_json) if case.parties_json else None},
        "side": side,
        "own_stage3": {"position": own.position, "argument": strip_internal_review(own.reasoning), "falsifier": own.falsifier,
                       "citations": citations(own), "model_id": own.model_id},
        "opponent_stage3_summary": None if opp is None else {
            "side": other, "position": opp.position, "citations": [c["citation_text"] for c in citations(opp)]},
        "party_checks": latest_party_checks(session, case_id),
        "procedural_issues": procedural_issues(latest_party_checks(session, case_id)),
        "existing_system_drafts": len(existing),
    }


def record_verdict(session, *, case_id, verdict_main_text, verdict_reasoning, risk_map,
                    mechanical_anchor_json, protocol_version, citations_used):
    if session.query(Verdict).filter_by(case_id=case_id).one_or_none():
        raise ValueError(f"{case_id} 判決已落地，不可覆寫")
    _assert_all_published(session, citations_used)
    row = Verdict(
        case_id=case_id, verdict_main_text=verdict_main_text, verdict_reasoning=verdict_reasoning,
        risk_map=json.dumps(risk_map, ensure_ascii=False),
        mechanical_anchor_json=json.dumps(mechanical_anchor_json, ensure_ascii=False),
        protocol_version=protocol_version, created_at=_now_iso(),
    )
    session.add(row)
    session.commit()
    return row


def pleading_side(row):
    """書狀屬於哪一方。side 欄位新增前落地的舊紀錄為 NULL,當時只產原告起訴狀，視同 plaintiff。"""
    return row.side or 'plaintiff'


# 每一方的主要書狀:原告是起訴狀、被告是答辯狀。舊流程 pleading_type 為 NULL,依 side 推定。
MAIN_PLEADING_TYPE = {"plaintiff": "complaint", "defendant": "answer"}


def is_main_pleading(row, side):
    """這一列是不是該方的主要書狀(起訴狀或答辯狀);模擬的準備書狀、言詞辯論意旨狀不算。"""
    return pleading_side(row) == side and row.pleading_type in (None, MAIN_PLEADING_TYPE[side])


PLEADING_TYPES = ("complaint", "answer", "brief", "closing")


def record_pleading(session, *, case_id, draft_text, citations_used, side='plaintiff', pleading_type=None, round=None,
                    is_simulated=None, structured=None):
    """side=plaintiff 為民事起訴狀骨架，defendant 為民事答辯狀骨架；兩方走同一道查證閘門。
    書狀交換流程另記 pleading_type、round、is_simulated 與模型交的結構化內容(structured);舊流程這些欄位為 NULL。"""
    if side not in VALID_SIDES:
        raise ValueError(f"非法 side: {side}")
    if pleading_type not in (None, *PLEADING_TYPES):
        raise ValueError(f"非法 pleading_type: {pleading_type}")
    _assert_all_published(session, citations_used)
    row = PleadingDraft(case_id=case_id, draft_text=draft_text, side=side,
                         citation_verification_status='published', generated_at=_now_iso(),
                         pleading_type=pleading_type, round=round, is_simulated=is_simulated,
                         structured_json=json.dumps(structured, ensure_ascii=False) if structured is not None else None)
    session.add(row)
    session.commit()
    return row


def record_pleading_edit(session, *, case_id, parent_id, draft_text, citation_check):
    """律師編輯版:另存一列新版本，原稿不動。

    與 record_pleading 不同，這裡不以例外擋下未通過的引用——律師的編輯不能因網路逾時就消失——
    而是照實把逐條查證結果存下來，有任何一條未通過即標為 blocked；匯出端點只放行 published。
    citation_check 由呼叫端(server/services.py)逐條實際查證後產生，這裡不做任何「假設通過」。
    """
    parent = session.get(PleadingDraft, parent_id)
    if parent is None or parent.case_id != case_id:
        raise ValueError(f"{case_id} 找不到要編輯的訴狀版本 #{parent_id}")
    if not draft_text.strip():
        raise ValueError("訴狀內容不可為空白")
    status = 'published' if all(c.get("gate") == "pass" for c in citation_check) else 'blocked'
    row = PleadingDraft(case_id=case_id, draft_text=draft_text, citation_verification_status=status,
                        side=pleading_side(parent),  # 編輯起訴狀得到的仍是起訴狀，答辯狀亦同
                        pleading_type=parent.pleading_type, round=parent.round, is_simulated=parent.is_simulated,
                        generated_at=_now_iso(), source='lawyer_edit', parent_id=parent_id,
                        citation_check_json=json.dumps(citation_check, ensure_ascii=False))
    session.add(row)
    session.commit()
    return row


GATES = ("complaint",)  # 關卡 1:律師確認起訴狀
GATE_ACTIONS = ("continue", "finish")  # 確認並繼續 / 到此結束
GATE_BY = ("ui", "auto")  # 在 UI 按下確認 / 無人值守執行未指定停止點，自動通過(未經律師確認)


def case_gates(row):
    try:
        gates = json.loads(row.gates_json) if row.gates_json else {}
    except ValueError:
        return {}
    return gates if isinstance(gates, dict) else {}


def system_complaints(session, case_id):
    """流程產生的起訴狀(書狀交換流程才有 pleading_type;不含律師編輯版),依落地順序。"""
    return [r for r in session.query(PleadingDraft).filter_by(case_id=case_id).order_by(PleadingDraft.id).all()
            if r.source in (None, 'system') and r.pleading_type == 'complaint']


def record_gate(session, *, case_id, gate, version_id, action, by, run_id=None, note=None, check=None):
    """記錄律師確認關卡。結構規則在這裡硬擋：只有書狀交換流程的案件有關卡；版本必須是該案件的起訴狀
    (系統原稿或律師編輯版)且查證放行；每個關卡只寫一次，不可覆寫。
    找不到案件或版本時 raise LookupError,其他違規 raise ValueError。
    check(row):呼叫端在結構檢查之後的額外檢查(server/services.py 用畫面同一套規則看引用目前是否仍放行)。"""
    if gate not in GATES:
        raise ValueError(f"非法關卡:{gate}")
    if action not in GATE_ACTIONS:
        raise ValueError(f"非法 action:{action}(只能是 continue、finish)")
    if by not in GATE_BY:
        raise ValueError(f"非法 by:{by}")
    case = session.query(Case).filter_by(case_id=case_id).one_or_none()
    if case is None:
        raise LookupError(f"找不到案件 {case_id}")
    if case.protocol != 'v2':
        raise ValueError("只有書狀交換流程(protocol v2)的案件有律師確認關卡")
    gates = case_gates(case)
    if gate in gates:
        raise ValueError(f"{case_id} 的關卡 1 已在 {gates[gate].get('recorded_at')} 記錄(版本 #{gates[gate].get('version_id')}),不可覆寫")
    row = session.get(PleadingDraft, version_id)
    if row is None or row.case_id != case_id:
        raise LookupError(f"{case_id} 找不到書狀版本 #{version_id}")
    if pleading_side(row) != 'plaintiff' or row.pleading_type != 'complaint':
        raise ValueError(f"版本 #{version_id} 不是起訴狀;關卡 1 只能確認起訴狀")
    if row.citation_verification_status != 'published':
        raise ValueError(f"版本 #{version_id} 有引用未通過查證，不能確認;請先重新查證或移除該引用")
    if check is not None:
        check(row)
    entry = {"action": action, "version_id": row.id, "source": "system" if row.source in (None, 'system') else row.source,
             "by": by, "recorded_at": _now_iso()}
    if run_id is not None:
        entry["run_id"] = run_id
    if note:
        entry["note"] = note
    case.gates_json = json.dumps({**gates, gate: entry}, ensure_ascii=False)
    session.commit()
    return entry


def current_complaint(session, case_id):
    """之後各步驟要讀的起訴狀：關卡 1 已記錄時是確認的那一版(可能是律師編輯版);還沒確認時是最新的系統原稿
    (confirmed=False)。舊流程案件或還沒有起訴狀時回傳 None。"""
    case = session.query(Case).filter_by(case_id=case_id).one_or_none()
    if case is None:
        return None
    gate = case_gates(case).get("complaint")
    if gate:
        row = session.get(PleadingDraft, gate["version_id"])
    else:
        rows = system_complaints(session, case_id)
        row = rows[-1] if rows else None
    if row is None:
        return None
    return {"version_id": row.id, "source": "system" if row.source in (None, 'system') else row.source,
            "confirmed": gate is not None, "gate": gate, "draft_text": row.draft_text}


def _citation_key(citation_text):
    """正規化引用字串為可比對的 identity tuple，供判斷「是否為同一法規/判決」。

    2026-08-09 端到端測試發現：原本以 citation_text 精確字串比對，導致「民法第129條」與
    「民法第129條第1項第2款」被視為兩筆不同的查證紀錄，即使兩者指向同一條文——subagent
    在不同階段對同一條文常有不同精確度的寫法(是否帶項款)，精確字串比對過嚴會造成不必要的
    重複查證，甚至誤擋已查證過的引用。改以 engine.verify.parse_citation() 解析後的
    (法規/裁判字別, 條號/年度案號號次) 比對「同一法條/判決」，忽略項款等格式差異。
    無法解析(unknown)者退回用原始字串本身當 key，行為與修正前一致。
    """
    parsed = parse_citation(citation_text)
    if parsed["type"] == "statute":
        return ("statute", parsed["law_name"], parsed["article_no"])
    if parsed["type"] == "judgment":
        return ("judgment", parsed["jyear"], parsed["jcase"], parsed["jno"])
    return ("unknown", citation_text)


def _find_citation_row(session, citation_text):
    """依正規化 key 找出既有 CitationVerification 紀錄，不再要求 citation_text 完全相同。
    仍優先嘗試精確字串比對(常見情況、免掃全表)，找不到才退而掃描全表比對正規化 key。"""
    row = session.query(CitationVerification).filter_by(citation_text=citation_text).one_or_none()
    if row is not None:
        return row
    key = _citation_key(citation_text)
    if key[0] == "unknown":
        return None
    for candidate in session.query(CitationVerification).all():
        if _citation_key(candidate.citation_text) == key:
            return candidate
    return None


def _assert_all_published(session, citations_used):
    if not citations_used:
        return
    all_rows = session.query(CitationVerification).all()
    by_key = {}
    for r in all_rows:
        by_key.setdefault(_citation_key(r.citation_text), r.status)
    # 舊版條文的 key 與現行條文相同，不能借現行條文的查證紀錄放行；已廢止與索引外的法規同樣不放行
    unpublished = [c for c in citations_used
                   if citation_warning(c) or by_key.get(_citation_key(c)) != 'published']
    if unpublished:
        raise ValueError(f"以下引用尚未查證為 published，拒絕落地: {unpublished}")


def upsert_citation(session, *, citation_text, source_type, status='draft',
                     primary_source_url=None, verifier_run_id=None):
    """citation_text 一旦被編輯(即重新 upsert 不同內容)，status 強制重置為 draft，
    這是把 Startup Guide 的 Phase 2.5 規則變成資料庫層強制，見本檔案頂端說明。

    2026-08-09 起改用 _find_citation_row()(正規化比對)而非精確字串比對來找既有紀錄，
    同一條文/判決不同精確度的引用字串會共用同一筆查證紀錄，見 _citation_key() 說明。"""
    row = _find_citation_row(session, citation_text)
    if row is None:
        row = CitationVerification(citation_text=citation_text, source_type=source_type)
        session.add(row)
    row.status = status
    row.primary_source_url = primary_source_url
    row.verifier_run_id = verifier_run_id
    row.verified_at = _now_iso() if status in ('fact_checked', 'published') else None
    session.commit()
    return row


def record_party_check(session, *, case_id=None, role=None, query_ban, input_name=None,
                       result, raw, via="gcis_live", fetched_at=None):
    if role not in (None, "plaintiff", "defendant"):
        raise ValueError(f"非法 role: {role}")
    if via not in ("gcis_live", "recorded"):
        raise ValueError(f"非法 via: {via}")
    row = PartyCheck(case_id=case_id, role=role, query_ban=query_ban, input_name=input_name,
                     entity_type=result["entity_type"], status_text=result.get("status_text"),
                     result_json=json.dumps(result, ensure_ascii=False), raw_json=json.dumps(raw, ensure_ascii=False),
                     via=via, fetched_at=fetched_at, created_at=_now_iso())
    session.add(row)
    session.commit()
    return row


def latest_party_checks(session, case_id):
    out = {"plaintiff": None, "defendant": None}
    for row in (session.query(PartyCheck).filter_by(case_id=case_id)
                .order_by(PartyCheck.id.desc()).all()):
        if row.role in out and out[row.role] is None:
            out[row.role] = {**json.loads(row.result_json), "via": row.via,
                             "fetched_at": row.fetched_at, "created_at": row.created_at}
    return out


def record_issue_sheet(session, *, case_id, sheet, complaint_id, answer_id):
    """P3 爭點整理表落地:整份 JSON 原樣存，每案一份，不可覆寫。結構檢查由呼叫端(main.py issue-sheet)先做。"""
    if session.query(IssueSheet).filter_by(case_id=case_id).first() is not None:
        raise ValueError(f"{case_id} 爭點整理表已落地，不可覆寫")
    row = IssueSheet(case_id=case_id, complaint_id=complaint_id, answer_id=answer_id,
                     sheet_json=json.dumps(sheet, ensure_ascii=False), created_at=_now_iso())
    session.add(row)
    session.commit()
    return row


def issue_sheet(session, case_id):
    """已落地的爭點整理表;沒有時回傳 None。"""
    row = session.query(IssueSheet).filter_by(case_id=case_id).first()
    if row is None:
        return None
    return {"id": row.id, "complaint_id": row.complaint_id, "answer_id": row.answer_id,
            "sheet": json.loads(row.sheet_json), "created_at": row.created_at}


def complaint_basis(session, case_id):
    """法官與雙方讀的那一版起訴狀(current_complaint)的請求權基礎清單。律師編輯版沒有結構化內容，往回找系統原稿。"""
    current = current_complaint(session, case_id)
    if current is None:
        return []
    row = session.get(PleadingDraft, current["version_id"])
    while row is not None and row.structured_json is None and row.parent_id is not None:
        row = session.get(PleadingDraft, row.parent_id)
    return json.loads(row.structured_json or "{}").get("basis") or [] if row is not None else []


def record_complaint_revision(session, *, case_id, parent_id, draft_text, citations_used, structured):
    """P6 起訴狀 v2(規格 5.7)落地:pleading_type=complaint、source=system_revision、round=2、is_simulated=0,
    parent_id 指向 current_complaint(關卡 1 確認版;還沒確認時是最新系統原稿)。v2 只是建議版,不會變成原稿或確認版
    (system_complaints、current_complaint 只看 source 為 NULL/system 的列與關卡紀錄)。每案一份,不可覆寫。
    結構檢查由呼叫端(main.py revision)先做;這裡硬擋版本鏈、不可覆寫與查證閘門。"""
    current = current_complaint(session, case_id)
    if current is None:
        raise ValueError(f"{case_id} 沒有起訴狀,不能產生 v2")
    if parent_id != current["version_id"]:
        raise ValueError(f"起訴狀 v2 要接在確認版(#{current['version_id']})之後,不是 #{parent_id}")
    if any(r.source == 'system_revision' and r.pleading_type == 'complaint'
           for r in session.query(PleadingDraft).filter_by(case_id=case_id).all()):
        raise ValueError(f"{case_id} 起訴狀 v2 已落地,不可覆寫")
    _assert_all_published(session, citations_used)
    row = PleadingDraft(case_id=case_id, draft_text=draft_text, side='plaintiff', citation_verification_status='published',
                        generated_at=_now_iso(), source='system_revision', parent_id=parent_id, pleading_type='complaint',
                        round=2, is_simulated=0,
                        structured_json=json.dumps({**structured, "parent_id": parent_id}, ensure_ascii=False))
    session.add(row)
    session.commit()
    return row
