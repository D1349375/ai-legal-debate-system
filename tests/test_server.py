"""UI 後端(server/)測試。所有網路行為皆以 monkeypatch 取代，不依賴外網，CI 可穩定重現。"""
import json
import shutil

import pytest
from fastapi.testclient import TestClient

from database.db import (
    get_session, make_session_factory, record_argument, record_case, record_pleading,
    record_question, record_verdict, upsert_citation,
)
from engine import verify as engine_verify
from server import seed, services
from server.app import create_app

FABRICATED = "最高法院105年度台簡上字第33號"


def _arg(session, side, stage, statutes, precedents=None, falsifier="若對方補證據則讓步"):
    record_argument(
        session, case_id="c1", side=side, stage=stage, position=f"{side} s{stage} 立場",
        reasoning=f"{side} s{stage} 推理", cited_statutes=statutes, cited_precedents=precedents or [],
        falsifier=None if stage == 1 else falsifier, model_id=None)


@pytest.fixture(scope="module")
def template_db(tmp_path_factory):
    """建一次範本資料庫(每次 commit 在 Windows 上很慢)，每個測試再複製一份，互不污染。"""
    path = tmp_path_factory.mktemp("template") / "template.db"
    _build_case_db(f"sqlite:///{path}")
    return path


@pytest.fixture
def db_url(template_db, tmp_path):
    target = tmp_path / "test.db"
    shutil.copyfile(template_db, target)
    return f"sqlite:///{target}"


def _build_case_db(url):
    s = get_session(url)
    record_case(s, case_id="c1", case_type="消費借貸爭議", facts_summary="事實摘要", claims="請求")
    _arg(s, "plaintiff", 1, ["民法第474條", "民法第478條"], [FABRICATED])
    _arg(s, "defendant", 1, ["民法第144條"])
    record_question(s, case_id="c1", question_text="是否合意每坪75萬元?", target_side="defendant",
                    based_on="被告Stage1主張每坪75萬元")
    _arg(s, "plaintiff", 2, ["民法第474條"], [FABRICATED, "最高法院115年度台簡上字第8號"])
    _arg(s, "defendant", 2, ["民法第144條", "民法第738條"])
    _arg(s, "plaintiff", 3, ["民法第474條", "民法第478條"])
    _arg(s, "defendant", 3, ["民法第144條", "民法第738條"])
    for text, kind in (("民法第474條", "statute"), ("民法第478條", "statute"), ("民法第144條", "statute"),
                       ("民法第738條", "statute")):
        upsert_citation(s, citation_text=text, source_type=kind, status="published",
                        primary_source_url="https://law.moj.gov.tw/x")
    anchor = services.run_finalize(s, "c1")
    anchor.pop("drift_detail")
    anchor.pop("elapsed_ms")
    record_verdict(s, case_id="c1", verdict_main_text="主文", verdict_reasoning="一、甲。二、乙。",
                   risk_map={"對原告不利之處": ["a"], "對被告不利之處": ["b"], "建議補強證據": ["c"]},
                   mechanical_anchor_json=anchor, protocol_version="v1", citations_used=["民法第474條"])
    record_pleading(s, case_id="c1", draft_text="依民法第474條及民法第738條…", citations_used=["民法第474條"])
    s.close()
    s.get_bind().dispose()


@pytest.fixture
def client(db_url, tmp_path):
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    (cases_dir / "only.json").write_text(json.dumps(
        {"case_id": "only-1", "case_type": "侵權行為", "facts_summary": "僅有案情", "claims": "請求賠償"},
        ensure_ascii=False), encoding="utf-8")
    app = create_app(db_url=db_url, cases_dir=str(cases_dir), live_checks_path=str(tmp_path / "none.json"),
                     seed_on_empty=False)
    return TestClient(app)


@pytest.fixture
def no_network(monkeypatch):
    """任何實際連線嘗試都算測試失敗——用於證明離線模式/本地命中確實沒有連網。"""
    def boom(*a, **k):
        raise AssertionError("不該連網")
    monkeypatch.setattr(engine_verify, "verify_statute_citation", boom)
    monkeypatch.setattr(engine_verify, "verify_judgment_citation", boom)


class TestCases:
    def test_list_includes_db_and_input_only(self, client):
        cases = {c["case_id"]: c for c in client.get("/api/cases").json()["cases"]}
        assert cases["c1"]["source"] == "database" and cases["c1"]["status"] == "completed"
        assert cases["c1"]["arguments"] == 6 and cases["c1"]["questions"] == 1
        assert cases["only-1"]["source"] == "input_only" and cases["only-1"]["arguments"] == 0

    def test_detail_groups_recorded_content(self, client):
        d = client.get("/api/cases/c1").json()
        assert d["provenance"]["kind"] == "recorded_replay"
        assert [(a["stage"], a["side"]) for a in d["arguments"]] == [
            (1, "plaintiff"), (1, "defendant"), (2, "plaintiff"), (2, "defendant"),
            (3, "plaintiff"), (3, "defendant")]
        assert d["questions"][0]["seq"] == 1 and d["questions"][0]["based_on"].startswith("被告Stage1")
        assert d["verdict"]["risk_map"]["建議補強證據"] == ["c"]
        assert d["pleading"]["draft_text"].startswith("依民法第474條")

    def test_citation_inventory_and_db_status(self, client):
        cites = {c["citation_text"]: c for c in client.get("/api/cases/c1").json()["citations"]}
        assert cites["民法第474條"]["db_record"]["status"] == "published"
        assert cites[FABRICATED]["db_record"] is None
        assert cites[FABRICATED]["kind"] == "judgment"
        assert {"side": "plaintiff", "stage": 2} in cites[FABRICATED]["used_by"]

    def test_citation_changes_detect_withdrawal(self, client):
        changes = client.get("/api/cases/c1").json()["citation_changes"]
        p23 = next(c for c in changes if c["side"] == "plaintiff" and c["from_stage"] == 2)
        assert set(p23["dropped"]) == {FABRICATED, "最高法院115年度台簡上字第8號"}
        assert p23["added"] == ["民法第478條"]

    def test_anchor_check_is_consistent_with_recompute(self, client):
        check = client.get("/api/cases/c1").json()["verdict"]["anchor_check"]
        assert check["consistent"] is True and check["differences"] == []

    def test_anchor_check_minor_wording_difference_is_reported_not_hidden(self, db_url, client):
        """落地錨點的 falsifier 若只差在括號補充語，不算實質不一致，但必須如實列出。"""
        check = client.get("/api/cases/c1").json()["verdict"]["anchor_check"]
        assert check["consistent"] is True and check["minor_differences"] == []

        s = make_session_factory(db_url)()
        from database.schema import DebateArgument
        row = s.query(DebateArgument).filter_by(case_id="c1", side="plaintiff", stage=3).one()
        row.falsifier = "若對方補證據則讓步(尤其是否及於全部)"
        s.commit()
        s.close()
        check = client.get("/api/cases/c1").json()["verdict"]["anchor_check"]
        assert check["consistent"] is True
        assert check["minor_differences"][0]["side"] == "plaintiff"
        assert "尤其是否及於全部" in check["minor_differences"][0]["current"]

    def test_anchor_check_detects_tampering(self, db_url, client):
        s = make_session_factory(db_url)()
        from database.schema import Verdict
        v = s.query(Verdict).one()
        anchor = json.loads(v.mechanical_anchor_json)
        anchor["position_drift"]["plaintiff"] = 0.99
        v.mechanical_anchor_json = json.dumps(anchor)
        s.commit()
        s.close()
        check = client.get("/api/cases/c1").json()["verdict"]["anchor_check"]
        assert check["consistent"] is False and "原告立場位移度" in check["differences"][0]

    def test_pleading_citation_check_reparses_draft(self, client):
        checks = {c["citation_text"]: c for c in client.get("/api/cases/c1").json()["pleading"]["citation_check"]}
        assert checks["民法第474條"]["db_record"]["status"] == "published"
        assert checks["民法第738條"]["db_record"]["status"] == "published"

    def test_input_only_case_has_no_recorded_content(self, client):
        d = client.get("/api/cases/only-1").json()
        assert d["provenance"]["kind"] == "input_only" and d["arguments"] == [] and d["verdict"] is None

    def test_unknown_case_404(self, client):
        assert client.get("/api/cases/nope").status_code == 404
        assert client.post("/api/cases/nope/finalize").status_code == 404


class TestFinalize:
    def test_matches_engine_and_exposes_drift_sets(self, client):
        r = client.post("/api/cases/c1/finalize").json()
        assert [p["side"] for p in r["weak_points"]] == ["defendant", "plaintiff"]
        d = r["drift_detail"]["plaintiff"]
        assert r["position_drift"]["plaintiff"] == d["ratio"]
        assert d["ratio"] == round(1 - d["intersection"] / d["union"], 4) == 0.3333
        assert d["dropped"] == [FABRICATED] and d["added"] == []
        assert r["drift_detail"]["defendant"]["dropped"] == [] and r["drift_detail"]["defendant"]["added"] == ["民法第738條"]

    def test_incomplete_case_returns_409_with_reason(self, db_url, client):
        s = get_session(db_url)
        record_case(s, case_id="c2", case_type="侵權行為", facts_summary="f", claims="c")
        record_argument(s, case_id="c2", side="plaintiff", stage=1, position="p", reasoning="r")
        s.close()
        r = client.post("/api/cases/c2/finalize")
        assert r.status_code == 409 and "stage3" in r.json()["detail"]


class TestVerify:
    def _verify(self, client, citations, **kw):
        body = {"citations": citations, **kw}
        return client.post("/api/verify", json=body).json()["results"]

    def test_local_judgment_hit_needs_no_network(self, client, no_network):
        r = self._verify(client, ["最高法院115年度台簡上字第8號"])[0]
        assert r["status"] == "published" and r["verified_via"] == "local_corpus"
        assert r["local_file"].startswith("corpus/judgments/") and ":" not in r["local_file"]
        assert r["live_attempt"]["tried"] is False and r["gate"] == "pass"

    def test_statute_live_success_is_published_and_persisted(self, client, monkeypatch, db_url):
        monkeypatch.setattr(engine_verify, "verify_statute_citation", lambda law, art, timeout: {
            "status": "published", "law_name": law, "article_no": art,
            "primary_source_url": f"https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=B0000001&flno={art}",
            "matched_text": "第 197 條 ..."})
        r = self._verify(client, ["民法第197條"])[0]
        assert r["status"] == "published" and r["verified_via"] == "law_moj_live"
        assert r["persisted"] is True and r["live_attempt"]["outcome"] == "ok"
        from database.schema import CitationVerification
        s = get_session(db_url)
        assert s.query(CitationVerification).filter_by(citation_text="民法第197條").one().status == "published"

    def test_statute_live_timeout_falls_back_to_local_cache_and_is_not_published(self, client, monkeypatch, db_url):
        monkeypatch.setattr(engine_verify, "verify_statute_citation", lambda law, art, timeout: {
            "status": "verification_failed", "reason": "<urlopen error timed out>"})
        r = self._verify(client, ["民法第197條"])[0]
        assert r["status"] == "local_cache_only" and r["verified_via"] == "local_statute_cache"
        assert r["gate"] == "blocked" and r["persisted"] is False
        assert r["live_attempt"] == {"tried": True, "outcome": "timeout", "error": "<urlopen error timed out>"}
        assert r["local_cache"]["file"] == "corpus/statutes/民法.txt" and r["local_cache"]["fetched_at"]
        from database.schema import CitationVerification
        assert make_session_factory(db_url)().query(CitationVerification).filter_by(
            citation_text="民法第197條").count() == 0

    def test_live_exception_is_reported_not_raised(self, client, monkeypatch):
        def raise_reset(*a, **k):
            raise ConnectionResetError("連線被重設")
        monkeypatch.setattr(engine_verify, "verify_statute_citation", raise_reset)
        r = self._verify(client, ["民法第197條"])[0]
        assert r["status"] == "local_cache_only" and r["live_attempt"]["outcome"] == "network_error"
        assert "ConnectionResetError" in r["live_attempt"]["error"]

    def test_statute_without_local_cache_fails_honestly(self, client, monkeypatch):
        monkeypatch.setattr(engine_verify, "verify_statute_citation", lambda law, art, timeout: {
            "status": "verification_failed", "reason": "offline"})
        r = self._verify(client, ["民事訴訟法第277條"])[0]  # 無本地快取
        assert r["status"] == "verification_failed" and r["gate"] == "blocked" and "verified_via" in r

    def test_nonexistent_statute_is_not_found(self, client, monkeypatch):
        monkeypatch.setattr(engine_verify, "verify_statute_citation", lambda law, art, timeout: {
            "status": "not_found", "law_name": law, "article_no": art, "note": "官網查無此條"})
        r = self._verify(client, ["民法第99999條"])[0]
        assert r["status"] == "not_found" and r["gate"] == "blocked"

    def test_fabricated_judgment_online_is_not_found(self, client, monkeypatch):
        monkeypatch.setattr(engine_verify, "verify_judgment_citation", lambda y, c, n, timeout: {
            "status": "not_found", "fjud_query": "105年度台簡上字第33號", "fjud_raw_hits": ["TNDV,110,重訴,215"] * 3})
        r = self._verify(client, [FABRICATED])[0]
        assert r["status"] == "not_found" and r["verified_via"] == "fjud_live"
        assert r["fjud_hit_count"] == 3 and r["gate"] == "blocked"

    def test_fabricated_judgment_offline_is_unverifiable_not_not_found(self, client, monkeypatch):
        """離線時不得宣稱「查無」(沒查到 ≠ 查證過不存在)，也絕不可放行。"""
        monkeypatch.setattr(engine_verify, "verify_judgment_citation", lambda y, c, n, timeout: {
            "status": "verification_failed", "reason": "<urlopen error [Errno 11001] getaddrinfo failed>"})
        r = self._verify(client, [FABRICATED])[0]
        assert r["status"] == "verification_failed" and r["gate"] == "blocked"
        assert r["live_attempt"]["outcome"] == "network_error"

    def test_offline_mode_never_touches_network(self, client, no_network):
        rs = self._verify(client, ["民法第197條", FABRICATED, "最高法院115年度台簡上字第8號"], mode="offline")
        by = {r["citation_text"]: r for r in rs}
        assert by["民法第197條"]["status"] == "local_cache_only"
        assert by["民法第197條"]["live_attempt"]["outcome"] == "skipped_offline_mode"
        assert by[FABRICATED]["status"] == "verification_failed"
        assert by["最高法院115年度台簡上字第8號"]["status"] == "published"

    def test_skip_live_after_prior_failure(self, client, no_network):
        r = self._verify(client, ["民法第197條"], skip_live=True)[0]
        assert r["live_attempt"]["outcome"] == "skipped_after_failure" and r["status"] == "local_cache_only"

    def test_unparseable_and_unknown_law(self, client):
        rs = self._verify(client, ["被告顯係推諉卸責之詞", "民事訴訟法第0條"], mode="offline")
        assert rs[0]["status"] == "unparseable" and rs[0]["gate"] == "blocked"

    def test_previous_record_is_reported_separately_from_this_run(self, client, no_network):
        r = self._verify(client, ["民法第474條"], mode="offline")[0]
        assert r["status"] == "local_cache_only"  # 本次沒有官方比對
        assert r["previous_record"]["status"] == "published"  # 先前紀錄另列，不混為本次結果

    def test_validation(self, client):
        assert client.post("/api/verify", json={"citations": []}).status_code == 422
        assert client.post("/api/verify", json={"citations": ["x"], "timeout_sec": 999}).status_code == 422


class TestRecordedChecks:
    def test_recorded_check_attached_to_matching_citation(self, db_url, tmp_path):
        path = tmp_path / "checks.json"
        path.write_text(json.dumps({
            "_meta": {"recorded_at": "2026-09-22T00:00:00Z"},
            "checks": [{"citation_text": FABRICATED, "status": "not_found", "checked_at": "2026-09-22T00:00:00Z",
                        "verified_via": "fjud_live", "fjud_hit_count": 20}]}, ensure_ascii=False), encoding="utf-8")
        client = TestClient(create_app(db_url=db_url, live_checks_path=str(path), seed_on_empty=False))
        cites = {c["citation_text"]: c for c in client.get("/api/cases/c1").json()["citations"]}
        assert cites[FABRICATED]["recorded_check"]["status"] == "not_found"
        assert cites["民法第474條"]["recorded_check"] is None


class TestSeed:
    def test_export_then_seed_roundtrip_preserves_timestamps(self, db_url, tmp_path):
        src = get_session(db_url)
        path = tmp_path / "fixture.json"
        counts = seed.write_fixture(src, str(path))
        assert counts["cases"] == 1 and counts["debate_arguments"] == 6 and counts["court_questions"] == 1
        dst = get_session(f"sqlite:///{tmp_path / 'fresh.db'}")
        assert seed.seed_if_empty(dst, str(path))["debate_arguments"] == 6
        from database.schema import DebateArgument
        assert ({a.created_at for a in dst.query(DebateArgument).all()}
                == {a.created_at for a in src.query(DebateArgument).all()})

    def test_seed_skips_nonempty_db(self, db_url, tmp_path):
        s = get_session(db_url)
        path = tmp_path / "fixture.json"
        seed.write_fixture(s, str(path))
        assert seed.seed_if_empty(s, str(path)) is None

    def test_app_seeds_empty_db_on_startup(self, db_url, tmp_path):
        path = tmp_path / "fixture.json"
        seed.write_fixture(get_session(db_url), str(path))
        app = create_app(db_url=f"sqlite:///{tmp_path / 'empty.db'}", fixture_path=str(path),
                         live_checks_path=str(tmp_path / "none.json"))
        assert app.state.seeded["cases"] == 1
        assert len(TestClient(app).get("/api/cases").json()["cases"]) >= 1

    def test_shipped_fixture_contains_demo_case(self):
        with open(seed.FIXTURE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        assert "test-2026-08-09-e2e-001" in {c["case_id"] for c in data["cases"]}


class TestStaticAndHealth:
    def test_health_reports_live_generation_disabled(self, client):
        h = client.get("/api/health").json()
        assert h["status"] == "ok" and h["live_generation"]["enabled"] is False
        assert h["corpus"]["judgments"] > 1000 and h["corpus"]["statutes"] == 5

    def test_root_serves_ui_without_redirect_and_assets(self, client):
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 200 and "LegalDebate" in r.text
        assert client.get("/app.js").status_code == 200 and client.get("/app.css").status_code == 200
        assert client.get("/api/health").status_code == 200  # 靜態掛載不得蓋掉 API 路由
