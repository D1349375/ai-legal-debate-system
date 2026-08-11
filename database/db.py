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
    Base, Case, DebateArgument, CourtQuestion, Verdict, CitationVerification, PleadingDraft,
)
from engine.aggregate import compile_weak_points, disagreement, VALID_SIDES
from engine.verify import parse_citation

_DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'legal_debate.db')


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


def get_session(db_url=None):
    engine = create_engine(db_url or f"sqlite:///{_DB_FILE}")
    Base.metadata.create_all(engine)
    _sync_schema(engine)
    return sessionmaker(bind=engine)()


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def record_case(session, *, case_id, case_type, facts_summary, claims):
    if session.query(Case).filter_by(case_id=case_id).one_or_none():
        raise ValueError(f"{case_id} 已存在，不可覆寫")
    row = Case(case_id=case_id, case_type=case_type, facts_summary=facts_summary,
               claims=claims, created_at=_now_iso())
    session.add(row)
    session.commit()
    return row


def record_argument(session, *, case_id, side, stage, position, reasoning,
                     cited_statutes=None, cited_precedents=None, falsifier=None, model_id=None):
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


def record_pleading(session, *, case_id, draft_text, citations_used):
    _assert_all_published(session, citations_used)
    row = PleadingDraft(case_id=case_id, draft_text=draft_text,
                         citation_verification_status='published', generated_at=_now_iso())
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


def _assert_all_published(session, citations_used):
    if not citations_used:
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
