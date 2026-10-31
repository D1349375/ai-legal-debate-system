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

from database.schema import (
    Base, Case, DebateArgument, CourtQuestion, Verdict, CitationVerification, PleadingDraft, PartyCheck, LiveRun,
    CaseCitationCheck, JudgeBundle,
)
from engine.aggregate import compile_weak_points, disagreement, VALID_SIDES
from engine.party_issues import procedural_issues
from engine.verify import parse_citation

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


def record_case(session, *, case_id, case_type, facts_summary='', claims, parties=None, created_via=None,
                represented_side=None, uncontested_facts=None, plaintiff_facts=None, defendant_facts=None,
                claim_amount=None, protocol_version=None):
    if session.query(Case).filter_by(case_id=case_id).one_or_none():
        raise ValueError(f"{case_id} 已存在，不可覆寫")
    from engine.role_protocol import PROTOCOL_VERSION, procedure_warning
    if represented_side is not None and represented_side not in VALID_SIDES:
        raise ValueError('represented_side 必須是 plaintiff 或 defendant')
    if represented_side is None and any(v is not None for v in (uncontested_facts, plaintiff_facts, defendant_facts, claim_amount, protocol_version)):
        raise ValueError('新案 represented_side 為必填')
    procedure_warning(claim_amount, claims)
    if represented_side and not any((uncontested_facts, plaintiff_facts, defendant_facts)):
        if represented_side == 'plaintiff':
            plaintiff_facts = facts_summary
        else:
            defendant_facts = facts_summary
    if not facts_summary:
        facts_summary = '\n'.join(v for v in (uncontested_facts, plaintiff_facts, defendant_facts) if v)
    row = Case(case_id=case_id, case_type=case_type, facts_summary=facts_summary,
               claims=claims, created_at=_now_iso(), created_via=created_via,
               represented_side=represented_side, uncontested_facts=uncontested_facts,
               plaintiff_facts=plaintiff_facts, defendant_facts=defendant_facts, claim_amount=claim_amount,
               protocol_version=PROTOCOL_VERSION if represented_side else None,
               parties_json=json.dumps(parties, ensure_ascii=False) if parties else None)
    session.add(row)
    session.commit()
    return row


def record_argument(session, *, case_id, side, stage, position, reasoning,
                     cited_statutes=None, cited_precedents=None, falsifier=None, model_id=None,
                     structured_json=None):
    if side not in VALID_SIDES:
        raise ValueError(f"非法 side: {side}")
    if stage not in (1, 2, 3):
        raise ValueError("stage 只能是 1(爭點整理)/2(訊問攻防)/3(辯論終結)")
    case = session.query(Case).filter_by(case_id=case_id).one_or_none()
    from engine.role_protocol import is_v2, decoded, validate_argument
    data = None
    if is_v2(case):
        data = decoded(structured_json) if structured_json is not None else None
        if data is not None:
            data['cited_statutes'] = cited_statutes or []
            data['cited_precedents'] = cited_precedents or []
        data = validate_argument(session, case, side, stage, position, reasoning, data)
        if side == case.represented_side:
            if falsifier and falsifier.strip():
                raise ValueError('代理方 falsifier 必須留空，update_conditions 請寫 internal_notes')
            falsifier = None
        else:
            falsifier = json.dumps(data.get('defeat_conditions', []), ensure_ascii=False)
    elif stage in (2, 3) and not (falsifier and falsifier.strip()):
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
        structured_json=json.dumps(data, ensure_ascii=False) if data is not None else None,
    )
    session.add(row)
    session.commit()
    return row


def record_question(session, *, case_id, question_text, target_side, based_on, question_type=None,
                    structured_json=None, _commit=True):
    if target_side not in VALID_SIDES:
        raise ValueError(f"非法 target_side: {target_side}")
    if not based_on or not (based_on.strip() if isinstance(based_on, str) else based_on):
        raise ValueError("based_on 為必填，訊問須回溯至具體論點，不得憑空生成")
    case = session.query(Case).filter_by(case_id=case_id).one_or_none()
    from engine.role_protocol import is_v2, validate_question
    data = structured_json or {}
    if is_v2(case):
        data = {**data, **validate_question(session, case, question_text, target_side, based_on, question_type)}
    row = CourtQuestion(case_id=case_id, question_text=question_text, question_type=question_type,
                         target_side=target_side, based_on=based_on if isinstance(based_on, str) else json.dumps(based_on, ensure_ascii=False), created_at=_now_iso(),
                         structured_json=json.dumps(data, ensure_ascii=False) if data else None)
    session.add(row)
    if _commit:
        session.commit()
    return row


def record_judge_bundle(session, *, case_id, payload):
    from engine.role_protocol import case_row, validate_judge_bundle, validate_question
    case = case_row(session, case_id)
    if session.query(JudgeBundle).filter_by(case_id=case_id).one_or_none():
        raise ValueError(f'{case_id} 法官訊問已落地，不可覆寫')
    validate_judge_bundle(session, case, payload)
    for q in payload['questions']:
        validate_question(session, case, q['question_text'], q['target_side'], q['based_on'], q.get('question_type'))
    for q in payload['questions']:
        record_question(session, case_id=case_id, question_text=q['question_text'], target_side=q['target_side'],
                        based_on=q['based_on'], question_type=q.get('question_type'), structured_json=q, _commit=False)
    row = JudgeBundle(case_id=case_id, structured_json=json.dumps(payload, ensure_ascii=False), created_at=_now_iso())
    session.add(row)
    session.commit()
    return row


def _arg_to_dict(row):
    return {
        "side": row.side,
        "stage": row.stage,
        "position": row.position,
        "reasoning": row.reasoning,
        "falsifier": row.falsifier,
        "cited_statutes": json.loads(row.cited_statutes or "[]"),
        "cited_precedents": json.loads(row.cited_precedents or "[]"),
        **json.loads(row.structured_json or '{}'),
    }


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
    case = session.query(Case).filter_by(case_id=case_id).one_or_none()
    if case and case.represented_side:
        from engine.aggregate import aggregate_role_items
        from engine.role_protocol import judge_data
        questions = [{'id': r.id, 'target_side': r.target_side, 'question_type': r.question_type,
                      'question_text': r.question_text} for r in session.query(CourtQuestion).filter_by(case_id=case_id).order_by(CourtQuestion.id).all()]
        return aggregate_role_items([_arg_to_dict(r) for r in rows], case.represented_side, questions,
                                    judge_data(session, case_id).get('prep_items', []),
                                    procedural_issues(latest_party_checks(session, case_id)))
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
    if case.represented_side:
        from engine.role_protocol import facts_for, decoded, public_copy
        if side != case.represented_side:
            raise ValueError('新協議正式書狀僅可為代理方產生，對造請使用 report 的預演要點')
        own = stage3[side]
        data = decoded(own.structured_json)
        asserted = [public_copy(i) for i in data.get('items', []) if i['status'] == 'asserted']
        allowed_citations = list(dict.fromkeys(c for i in asserted for c in i.get('citations', [])))
        statuses = {_citation_key(r.citation_text): r.status for r in session.query(CaseCitationCheck).filter_by(case_id=case_id).order_by(CaseCitationCheck.id).all()}
        return {'case': {'case_id': case_id, 'case_type': case.case_type, 'claims': case.claims,
                         'represented_side': case.represented_side, 'facts': facts_for(case), 'claim_amount': case.claim_amount,
                         'parties': json.loads(case.parties_json) if case.parties_json else None},
                'side': side, 'document_label': '起訴狀骨架' if side == 'plaintiff' else '預先準備的答辯狀草稿（起訴前）',
                'own_stage3': {'claim_statement': data.get('claim_statement', ''),
                               **({'rebuttal': data.get('rebuttal', '')} if side == 'defendant' else {}),
                               'items': asserted,
                               'citations': [{'citation_text': c, 'status': statuses.get(_citation_key(c), 'no_record')} for c in allowed_citations]},
                'party_checks': latest_party_checks(session, case_id),
                'procedural_issues': procedural_issues(latest_party_checks(session, case_id))}
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
        "own_stage3": {"position": own.position, "argument": own.reasoning, "falsifier": own.falsifier,
                       "citations": citations(own), "model_id": own.model_id},
        "opponent_stage3_summary": None if opp is None else {
            "side": other, "position": opp.position, "citations": [c["citation_text"] for c in citations(opp)]},
        "party_checks": latest_party_checks(session, case_id),
        "procedural_issues": procedural_issues(latest_party_checks(session, case_id)),
        "existing_system_drafts": len(existing),
    }


def record_verdict(session, *, case_id, verdict_main_text, verdict_reasoning, risk_map,
                    mechanical_anchor_json, protocol_version, citations_used, structured_json=None):
    if session.query(Verdict).filter_by(case_id=case_id).one_or_none():
        raise ValueError(f"{case_id} 判決已落地，不可覆寫")
    from engine.role_protocol import is_v2, decoded, validate_verdict, PROTOCOL_VERSION
    case = session.query(Case).filter_by(case_id=case_id).one_or_none()
    data = None
    if is_v2(case):
        data = decoded(structured_json)
        anchors = finalize_case(session, case_id=case_id)
        data = validate_verdict(session, case, data, anchors)
        mechanical_anchor_json = anchors
        protocol_version = PROTOCOL_VERSION
        _assert_all_published(session, citations_used, case_id=case_id)
    else:
        _assert_all_published(session, citations_used)
    row = Verdict(
        case_id=case_id, verdict_main_text=verdict_main_text, verdict_reasoning=verdict_reasoning,
        risk_map=json.dumps(risk_map, ensure_ascii=False),
        mechanical_anchor_json=json.dumps(mechanical_anchor_json, ensure_ascii=False),
        protocol_version=protocol_version, created_at=_now_iso(),
        structured_json=json.dumps(data, ensure_ascii=False) if data is not None else None,
    )
    session.add(row)
    session.commit()
    return row


def pleading_side(row):
    """書狀屬於哪一方。side 欄位新增前落地的舊紀錄為 NULL,當時只產原告起訴狀，視同 plaintiff。"""
    return row.side or 'plaintiff'


def record_pleading(session, *, case_id, draft_text, citations_used, side='plaintiff', claim_breakdown=None):
    """side=plaintiff 為民事起訴狀骨架，defendant 為民事答辯狀骨架；兩方走同一道查證閘門。"""
    if side not in VALID_SIDES:
        raise ValueError(f"非法 side: {side}")
    case = session.query(Case).filter_by(case_id=case_id).one_or_none()
    breakdown = None
    warnings = []
    if case and case.represented_side:
        if side != case.represented_side:
            raise ValueError('正式書狀僅能為代理方產生，對造模擬請產預演要點（非書狀）')
        if side == 'plaintiff':
            import re
            banned = re.findall(r'被告主張|被告抗辯|被告自承|被告或將|本方|對造|stage|輪次|前輪|法官訊問|訊問攻防', draft_text, re.IGNORECASE)
            if banned:
                raise ValueError(f'起訴狀不得混入對方說法或模擬流程用語：{sorted(set(banned))}')
        from engine.role_protocol import validate_breakdown
        breakdown = validate_breakdown(session, case, claim_breakdown or [])
        warnings = breakdown['warnings']
        if breakdown['pending']:
            draft_text += '\n\n律師附註：待確認後再決定是否請求\n' + '\n'.join(f'{p["name"]}：{p["amount"]} 元（待確認；不計入訴之聲明）' for p in breakdown['pending'])
        _assert_all_published(session, citations_used, case_id=case_id)
    else:
        _assert_all_published(session, citations_used)
    row = PleadingDraft(case_id=case_id, draft_text=draft_text, side=side,
                         citation_verification_status='published', generated_at=_now_iso(),
                         claim_breakdown_json=json.dumps(breakdown, ensure_ascii=False) if breakdown is not None else None,
                         warnings_json=json.dumps(warnings, ensure_ascii=False) if warnings else None)
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
                        generated_at=_now_iso(), source='lawyer_edit', parent_id=parent_id,
                        citation_check_json=json.dumps(citation_check, ensure_ascii=False))
    session.add(row)
    session.commit()
    return row


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


def _assert_all_published(session, citations_used, case_id=None):
    if not citations_used:
        return
    from engine.verify import citation_warning
    historical = [c for c in citations_used if (citation_warning(c) or {}).get('status') == 'version_unverified']
    if historical:
        raise ValueError(f'歷史法規為 version_unverified，不能借用現行條文 published 紀錄：{historical}')
    if case_id is not None:
        latest = {}
        for row in session.query(CaseCitationCheck).filter_by(case_id=case_id).order_by(CaseCitationCheck.id).all():
            latest[_citation_key(row.citation_text)] = row
        unpublished = []
        for citation in citations_used:
            row = latest.get(_citation_key(citation))
            if row is None or row.status != 'published':
                unpublished.append(citation)
                continue
            metadata = json.loads(row.metadata_json or '{}')
            if metadata.get('supports_proposition') is False or metadata.get('document_identity') is False or metadata.get('existence') is False:
                unpublished.append(citation)
            elif parse_citation(citation)['type'] == 'judgment' and metadata.get('supports_proposition') is not True:
                unpublished.append(citation)
        if unpublished:
            raise ValueError(f'以下引用尚無本案最新 published 且支持命題的查證紀錄，拒絕落地：{unpublished}')
        return
    all_rows = session.query(CitationVerification).all()
    by_key = {}
    for r in all_rows:
        by_key.setdefault(_citation_key(r.citation_text), r.status)
    unpublished = [c for c in citations_used if by_key.get(_citation_key(c)) != 'published']
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


def record_case_citation_check(session, case_id, result, verifier_run_id=None):
    """每案每次保存查證，不覆寫其他案件或共用快取的實質支持判斷。"""
    import uuid
    if not session.query(Case).filter_by(case_id=case_id).one_or_none():
        raise ValueError(f'找不到案件 {case_id}')
    row = CaseCitationCheck(case_id=case_id, citation_text=result['citation_text'], status=result['status'],
                            source_file=result.get('source_file'), checked_at=_now_iso(),
                            verifier_run_id=verifier_run_id or str(uuid.uuid4()),
                            support_note=json.dumps(result.get('support_note') or result.get('reason') or result.get('error'), ensure_ascii=False),
                            metadata_json=json.dumps(result, ensure_ascii=False))
    session.add(row)
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
