"""LegalDebate UI 後端(FastAPI)。

選 FastAPI 的理由：引擎與 DB 層都是 Python，同進程直接呼叫、不需重寫；請求/回應有型別驗證；
同一個進程順便以靜態檔服務 UI，「一條指令啟動」且不需 Node 或打包工具鏈；TestClient 讓 API 可在 CI 內測試。

刻意不提供任何寫入論證/判決的端點：論證由 Claude Code subagent 產生後經 `main.py record` 落地，
UI 只重播這些錄製紀錄，並真實執行機械環節(finalize / verify)。
"""
import os
import time
from typing import Literal
from urllib.parse import quote, urlsplit

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from database.db import default_db_path, make_session_factory
from database.schema import Case
from engine.verify import JUDGMENTS_DIR, STATUTES_DIR
from engine.gcis import validate_ban
from server import seed, services
from server.live_run import LiveRunManager

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


class PartyInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    ban: str | None = Field(default=None, max_length=12)


class CreateCaseRequest(BaseModel):
    case_id: str | None = Field(default=None, max_length=64)
    case_type: str = Field(min_length=1, max_length=60)
    facts_summary: str = Field(min_length=10, max_length=20000)
    claims: str = Field(min_length=2, max_length=5000)
    plaintiff: PartyInput
    defendant: PartyInput


class PleadingEditRequest(BaseModel):
    parent_id: int
    draft_text: str = Field(min_length=1, max_length=100000)
    mode: Literal["auto", "offline"] = "auto"
    timeout_sec: float = Field(default=6.0, ge=1.0, le=30.0)


class ReverifyRequest(BaseModel):
    mode: Literal["auto", "offline"] = "auto"
    timeout_sec: float = Field(default=6.0, ge=1.0, le=30.0)


class PartyCheckRequest(BaseModel):
    ban: str
    role: Literal["plaintiff", "defendant"] | None = None
    case_id: str | None = None
    input_name: str | None = None
    timeout_sec: float = Field(default=6.0, ge=1.0, le=30.0)
    persist: bool = True


LOOPBACK_CLIENTS = ("127.0.0.1", "::1")
LOOPBACK_HOSTNAMES = ("127.0.0.1", "localhost", "::1")


def _hostname(value):
    try:
        return urlsplit("//" + value).hostname if value else None
    except ValueError:
        return None


def _count_files(folder, suffix):
    try:
        return sum(1 for n in os.listdir(folder) if n.endswith(suffix))
    except OSError:
        return 0


def create_app(db_url=None, cases_dir=CASES_DIR, fixture_path=seed.FIXTURE_PATH,
               live_checks_path=seed.LIVE_CHECKS_PATH, party_checks_path=seed.PARTY_CHECKS_PATH,
               seed_on_empty=True, local_clients=LOOPBACK_CLIENTS, live=None):
    """live:即時執行設定(dict,見 LiveRunManager 參數)。預設停用；main.py serve 只在綁本機位址時啟用。"""
    app = FastAPI(title="LegalDebate UI API", docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
    factory = make_session_factory(db_url)
    app.state.seeded = None
    if seed_on_empty:
        with factory() as s:
            app.state.seeded = seed.seed_if_empty(s, fixture_path)
    app.state.recorded_checks = seed.load_recorded_checks(live_checks_path)
    app.state.recorded_party_checks = seed.load_recorded_party_checks(party_checks_path)
    live_opts = dict(live or {"enabled": False, "reason": "即時執行未啟用(只在以 python main.py serve 綁定本機位址時啟用)"})
    runner = app.state.live = LiveRunManager(factory, root=ROOT, db_url=db_url, **live_opts)
    app.router.on_shutdown.append(runner.shutdown)

    def get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    def local_only(request: Request):
        """新增的寫入端點(建立案件、即時執行、存訴狀版本)只接受本機瀏覽器。

        本服務沒有登入驗證：以 --host 0.0.0.0 啟動時，區網其他裝置只能看重播。另外檢查 Host 與 Origin，
        避免使用者瀏覽的其他網站(或 DNS rebinding)透過瀏覽器對本機 API 發出寫入請求。"""
        client = request.client.host if request.client else None
        if client not in local_clients:
            raise HTTPException(403, "此操作只接受本機(127.0.0.1)連線；其他裝置只能檢視")
        if _hostname(request.headers.get("host")) not in LOOPBACK_HOSTNAMES:
            raise HTTPException(403, "請以 http://127.0.0.1 或 http://localhost 開啟本頁後再操作")
        origin = request.headers.get("origin")
        if origin and origin != "null" and _hostname(urlsplit(origin).netloc) not in LOOPBACK_HOSTNAMES:
            raise HTTPException(403, "拒絕來自其他網站的請求")

    @app.get("/api/health")
    def health(db=Depends(get_db)):
        return {
            "status": "ok",
            "database": {"path": "database/legal_debate.db" if db_url is None else "(自訂資料庫)",
                         "cases": db.query(Case).count(),
                         "seeded_from_fixture": app.state.seeded},
            "corpus": {"judgments": _count_files(JUDGMENTS_DIR, ".txt"),
                       "statutes": _count_files(STATUTES_DIR, ".txt")},
            "live_generation": runner.availability(),
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

    @app.post("/api/cases", status_code=201, dependencies=[Depends(local_only)])
    def create_case(req: CreateCaseRequest, db=Depends(get_db)):
        parties = {}
        for role in ("plaintiff", "defendant"):
            p = getattr(req, role)
            ban = None
            if p.ban and p.ban.strip():
                ban = validate_ban(p.ban)
                if ban is None:
                    raise HTTPException(422, f"{'原告' if role == 'plaintiff' else '被告'}統一編號須為 8 位數字")
            parties[role] = {"name": p.name.strip(), "ban": ban}
        try:
            case_id = services.create_case(db, case_type=req.case_type, facts_summary=req.facts_summary,
                                           claims=req.claims, parties=parties,
                                           case_id=(req.case_id or "").strip() or None, cases_dir=cases_dir)
        except ValueError as e:
            raise HTTPException(409, str(e))
        return {"case_id": case_id, "parties": parties}

    @app.post("/api/cases/{case_id}/runs", status_code=201, dependencies=[Depends(local_only)])
    def start_run(case_id: str):
        try:
            return runner.start(case_id)
        except PermissionError as e:
            raise HTTPException(403, f"即時執行未啟用:{e}")
        except ValueError as e:
            raise HTTPException(409, str(e))

    @app.get("/api/runs/{run_id}")
    def run_status(run_id: int, since: int = Query(0, ge=0)):
        r = runner.get(run_id, since=since)
        if r is None:
            raise HTTPException(404, f"找不到執行 #{run_id}")
        return r

    @app.post("/api/runs/{run_id}/cancel", dependencies=[Depends(local_only)])
    def cancel_run(run_id: int):
        try:
            return runner.cancel(run_id)
        except ValueError as e:
            raise HTTPException(409, str(e))

    @app.post("/api/cases/{case_id}/pleadings", status_code=201, dependencies=[Depends(local_only)])
    def save_pleading(case_id: str, req: PleadingEditRequest, db=Depends(get_db)):
        if not req.draft_text.strip():
            raise HTTPException(422, "訴狀內容不可為空白")
        try:
            return services.save_pleading_edit(db, case_id, req.parent_id, req.draft_text, mode=req.mode,
                                               timeout=req.timeout_sec, recorded_checks=app.state.recorded_checks)
        except ValueError as e:
            raise HTTPException(404, str(e))

    @app.post("/api/cases/{case_id}/pleadings/{version_id}/reverify", dependencies=[Depends(local_only)])
    def reverify_pleading(case_id: str, version_id: int, req: ReverifyRequest, db=Depends(get_db)):
        v = services.reverify_pleading(db, case_id, version_id, mode=req.mode, timeout=req.timeout_sec,
                                       recorded_checks=app.state.recorded_checks)
        if v is None:
            raise HTTPException(404, f"找不到訴狀版本 #{version_id}")
        return v

    @app.get("/api/cases/{case_id}/pleadings/{version_id}/export")
    def export_pleading(case_id: str, version_id: int, db=Depends(get_db)):
        v = services.find_pleading_version(db, case_id, version_id)
        if v is None:
            raise HTTPException(404, f"找不到訴狀版本 #{version_id}")
        if not v["exportable"]:
            raise HTTPException(409, f"{v['label']} 有 {v['blocked_count']} 條引用未通過查證，未放行，不能匯出")
        kind = "lawyer" if v["source"] == "lawyer_edit" else "system"
        name = f"{case_id}_v{version_id}_{kind}.txt"
        body = "\ufeff" + services.export_pleading_text(case_id, v)  # BOM:Windows 記事本正確辨識 UTF-8
        return Response(body.encode("utf-8"), media_type="text/plain; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})

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
