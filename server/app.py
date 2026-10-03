"""LegalDebate UI 後端(FastAPI)。

選 FastAPI 的理由：引擎與 DB 層都是 Python，同進程直接呼叫、不需重寫；請求/回應有型別驗證；
同一個進程順便以靜態檔服務 UI，「一條指令啟動」且不需 Node 或打包工具鏈；TestClient 讓 API 可在 CI 內測試。

刻意不提供任何寫入論證/判決的端點：論證由 Claude Code subagent 產生後經 `main.py record` 落地，
UI 只重播這些錄製紀錄，並真實執行機械環節(finalize / verify)。
"""
import os
import time
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from database.db import default_db_path, make_session_factory
from database.schema import Case
from engine.verify import JUDGMENTS_DIR, STATUTES_DIR
from engine.gcis import validate_ban
from server import seed, services

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_DIR = os.path.join(ROOT, "ui")
CASES_DIR = os.path.join(ROOT, "data", "cases")
UI_ENTRY = "legal_workspace_ui.html"


class NoCacheStaticFiles(StaticFiles):
    """本地 demo 工具，正確性比快取效能重要：一律要求瀏覽器每次重新驗證，
    避免改完 app.js/app.css 後畫面仍顯示舊版的錯覺(重開分頁即可看到最新版)。"""
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


class VerifyRequest(BaseModel):
    citations: list[str] = Field(min_length=1, max_length=60)
    mode: Literal["auto", "offline"] = "auto"
    timeout_sec: float = Field(default=6.0, ge=1.0, le=30.0)
    persist: bool = True
    skip_live: bool = False


class PartyCheckRequest(BaseModel):
    ban: str
    role: Literal["plaintiff", "defendant"] | None = None
    case_id: str | None = None
    input_name: str | None = None
    timeout_sec: float = Field(default=6.0, ge=1.0, le=30.0)
    persist: bool = True


def _count_files(folder, suffix):
    try:
        return sum(1 for n in os.listdir(folder) if n.endswith(suffix))
    except OSError:
        return 0


def create_app(db_url=None, cases_dir=CASES_DIR, fixture_path=seed.FIXTURE_PATH,
               live_checks_path=seed.LIVE_CHECKS_PATH, party_checks_path=seed.PARTY_CHECKS_PATH,
               seed_on_empty=True):
    app = FastAPI(title="LegalDebate UI API", docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
    factory = make_session_factory(db_url)
    app.state.seeded = None
    if seed_on_empty:
        with factory() as s:
            app.state.seeded = seed.seed_if_empty(s, fixture_path)
    app.state.recorded_checks = seed.load_recorded_checks(live_checks_path)
    app.state.recorded_party_checks = seed.load_recorded_party_checks(party_checks_path)

    def get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    @app.get("/api/health")
    def health(db=Depends(get_db)):
        return {
            "status": "ok",
            "database": {"path": "database/legal_debate.db" if db_url is None else "(自訂資料庫)",
                         "cases": db.query(Case).count(),
                         "seeded_from_fixture": app.state.seeded},
            "corpus": {"judgments": _count_files(JUDGMENTS_DIR, ".txt"),
                       "statutes": _count_files(STATUTES_DIR, ".txt")},
            "live_generation": {"enabled": False,
                                "note": "第一階段：UI 重播已錄製案例並真實執行機械環節；即時生成辯論屬第二階段，尚未啟用。"},
            "default_db_file": os.path.basename(default_db_path()),
        }

    @app.get("/api/cases")
    def cases(db=Depends(get_db)):
        return {"cases": services.list_cases(db, cases_dir)}

    @app.get("/api/cases/{case_id}")
    def case_detail(case_id: str, db=Depends(get_db)):
        detail = services.get_case_detail(db, case_id, cases_dir, app.state.recorded_checks)
        if detail is None:
            raise HTTPException(404, f"找不到案件:{case_id}")
        return detail

    @app.post("/api/cases/{case_id}/finalize")
    def finalize(case_id: str, db=Depends(get_db)):
        if db.query(Case).filter_by(case_id=case_id).one_or_none() is None:
            raise HTTPException(404, f"找不到案件:{case_id}(尚未落地進資料庫)")
        try:
            return services.run_finalize(db, case_id)
        except ValueError as e:
            raise HTTPException(409, str(e))

    @app.post("/api/verify")
    def verify(req: VerifyRequest, db=Depends(get_db)):
        started = time.perf_counter()
        results = [
            services.verify_one(db, c, mode=req.mode, timeout=req.timeout_sec, persist=req.persist,
                                skip_live=req.skip_live, recorded_checks=app.state.recorded_checks)
            for c in req.citations if c.strip()
        ]
        return {"results": results, "mode": req.mode, "timeout_sec": req.timeout_sec,
                "elapsed_ms": round((time.perf_counter() - started) * 1000)}

    @app.post("/api/party-check")
    def party_check(req: PartyCheckRequest, db=Depends(get_db)):
        ban = validate_ban(req.ban)
        if ban is None:
            raise HTTPException(422, "統一編號須為 8 位數字")
        return services.party_check_one(db, ban, role=req.role, case_id=req.case_id,
                                        input_name=req.input_name, timeout=req.timeout_sec,
                                        persist=req.persist, recorded_party_checks=app.state.recorded_party_checks)

    @app.get("/api/party-search")
    def party_search(q: str = Query(...), db=Depends(get_db)):
        if len(q.strip()) < 2:
            raise HTTPException(422, "公司名稱關鍵字至少 2 個字")
        return services.party_search(q.strip())

    @app.get("/", include_in_schema=False)
    def index():
        # 直接回傳頁面而非 redirect，網址列的 #/案件/分頁 才不會在跳轉中遺失
        return FileResponse(os.path.join(UI_DIR, UI_ENTRY), headers={"Cache-Control": "no-cache"})

    # 靜態資源(app.css / app.js)掛在根路徑，須在所有 /api 路由之後註冊
    app.mount("/", NoCacheStaticFiles(directory=UI_DIR), name="ui")
    return app
