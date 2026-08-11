from sqlalchemy import Column, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Case(Base):
    __tablename__ = 'cases'
    id = Column(Integer, primary_key=True)
    case_id = Column(String, nullable=False, unique=True)
    case_type = Column(String, nullable=False)  # 侵權行為/契約不履行/勞資爭議等
    facts_summary = Column(Text, nullable=False)
    claims = Column(Text, nullable=False)
    created_at = Column(String, nullable=False)

class DebateArgument(Base):
    __tablename__ = 'debate_arguments'
    __table_args__ = (UniqueConstraint('case_id', 'side', 'stage', name='uq_argument_key'),)
    id = Column(Integer, primary_key=True)
    case_id = Column(String, nullable=False)
    side = Column(String, nullable=False)  # plaintiff / defendant(法官不寫這張表，見 Verdict）
    stage = Column(Integer, nullable=False)  # 1=爭點整理 2=訊問攻防 3=辯論終結
    position = Column(Text, nullable=False)
    reasoning = Column(Text, nullable=False)
    cited_statutes = Column(Text, nullable=True)  # JSON array of citation strings
    cited_precedents = Column(Text, nullable=True)  # JSON array of citation strings
    falsifier = Column(Text, nullable=True)  # stage 2/3 必填
    model_id = Column(String, nullable=True)
    created_at = Column(String, nullable=False)

class CourtQuestion(Base):
    __tablename__ = 'court_questions'
    id = Column(Integer, primary_key=True)
    case_id = Column(String, nullable=False)
    question_text = Column(Text, nullable=False)
    target_side = Column(String, nullable=False)  # plaintiff / defendant
    based_on = Column(Text, nullable=False)  # 回溯至具體論點，禁止憑空生成
    created_at = Column(String, nullable=False)

class Verdict(Base):
    # 欄位名稱沿用「判決」框架,但語意已於 2026-08-08 改為「爭點強弱評估」:
    # 產品重心是幫律師判斷哪些爭點該優先寫進訴狀,不是預測法院會怎麼判。
    # verdict_main_text/verdict_reasoning 未來寫的是爭點強弱結論/分析,非判決主文/理由。
    __tablename__ = 'verdicts'
    __table_args__ = (UniqueConstraint('case_id', name='uq_verdict_case'),)
    id = Column(Integer, primary_key=True)
    case_id = Column(String, nullable=False)
    verdict_main_text = Column(Text, nullable=False)
    verdict_reasoning = Column(Text, nullable=False)
    risk_map = Column(Text, nullable=False)  # JSON:對原告不利之處/對被告不利之處/建議補強證據
    mechanical_anchor_json = Column(Text, nullable=False)  # aggregate.py 輸出，法官敘述不得矛盾
    protocol_version = Column(String, nullable=False)
    created_at = Column(String, nullable=False)

class CitationVerification(Base):
    __tablename__ = 'citation_verifications'
    __table_args__ = (UniqueConstraint('citation_text', name='uq_citation_text'),)
    id = Column(Integer, primary_key=True)
    citation_text = Column(String, nullable=False)  # 如「民法第184條」「最高法院115年度台上字第1037號」
    source_type = Column(String, nullable=False)  # statute / judgment
    status = Column(String, nullable=False, default='draft')  # draft / fact_checked / published
    primary_source_url = Column(String, nullable=True)
    verified_at = Column(String, nullable=True)
    verifier_run_id = Column(String, nullable=True)

class PleadingDraft(Base):
    __tablename__ = 'pleading_drafts'
    id = Column(Integer, primary_key=True)
    case_id = Column(String, nullable=False)
    draft_text = Column(Text, nullable=False)
    citation_verification_status = Column(String, nullable=False)  # 彙總所有引用的最低狀態
    generated_at = Column(String, nullable=False)

def init_db(db_path='sqlite:///database/legal_debate.db'):
    engine = create_engine(db_path)
    Base.metadata.create_all(engine)
    print(f"SQLite Database successfully initialized at {db_path}")

if __name__ == "__main__":
    init_db()
