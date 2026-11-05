"""W2 起訴狀 v1:事實對應檢查、程式組成正文、落地閘門、匯出移除 CF 標記、舊案回應不變(T2.1–T2.7)。不連網。"""
import json
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from database.db import (
    DB_URL_ENV, get_session, record_argument, record_case, record_party_check, record_pleading, upsert_citation,
)
from database.schema import PleadingDraft
from engine import fact_points, pleading_render
from engine.party_issues import procedural_issues
from server import pleading_export, services
from server.app import create_app

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL = "http://127.0.0.1:8000"
FACTS = ("原告公司於民國104年4月間解散。被告甲於104年7月15日將其所有之房地贈與其配偶即被告乙,"
         "並於同年7月27日完成所有權移轉登記。原告公司以丙為法定代理人提起本件訴訟;卷內資料未載明丙之身分。")
EVIDENCE = [{"id": "甲證1", "type": "書證", "date": "2023-10-12", "description": "系爭房地登記謄本", "proves": "贈與及移轉登記"}]


def dissolved_check():
    with open(os.path.join(ROOT, "demo", "recorded_party_checks.json"), encoding="utf-8") as f:
        return next(c for c in json.load(f)["checks"] if c["ban"] == "29112102")


def payload(**over):
    p = {
        "cause": "撤銷詐害債權",
        "prayers": ["被告甲、乙間就系爭房地於民國104年7月15日所為之贈與行為及同年7月27日所為之所有權移轉登記行為,均應撤銷。",
                    "被告乙應將系爭房地之所有權移轉登記塗銷。", "訴訟費用由被告負擔。"],
        "claim_basis": [{"seq": 1, "role": "primary", "basis": ["民法第244條"], "prayer": "訴之聲明第一、二項"}],
        "fact_points": [
            {"id": "CF1", "text": "被告甲將系爭房地贈與被告乙並完成移轉登記。", "evidence_ids": ["甲證1"], "statement_quote": None},
            {"id": "CF2", "text": "原告公司於104年4月間解散。", "evidence_ids": [], "statement_quote": "原告公司於民國104年4月間解散"},
        ],
        "legal_argument": "被告甲之無償行為有害及債權,原告得依民法第244條第1項聲請法院撤銷,並依同條第4項請求回復原狀。",
        "procedural_statements": [{"id": "plaintiff:dissolved", "text": "原告已解散,法定代理人應列清算人,清算人為何人待查明後補正。"}],
        "basis": ["民法第244條"],
        "citations": ["民法第244條"],
        "precedent_notes": [],
        "fact_gaps": ["被告甲贈與時有無其他財產,卷內未見證據"],
        "lawyer_notes": ["清算人姓名須調閱解散前變更登記表"],
    }
    p.update(over)
    return p


def setup_case(url, *, evidence=EVIDENCE, analysis="程序補正(plaintiff:dissolved):清算人待查明。依民法第244條請求。",
               published=("民法第244條",)):
    s = get_session(url)
    record_case(s, case_id="v2", case_type="撤銷詐害債權", facts_summary=FACTS, claims="撤銷贈與及移轉登記",
                parties={"plaintiff": {"name": "順昌導線工業有限公司", "ban": "29112102"},
                         "defendant": {"name": "甲、乙", "ban": None}},
                created_via="ui", protocol="v2", represented_side="plaintiff", evidence=evidence)
    rec = dissolved_check()
    record_party_check(s, case_id="v2", role="plaintiff", query_ban="29112102", result=rec["result"], raw={},
                       via="recorded", fetched_at=rec["fetched_at"])
    if analysis is not None:
        record_argument(s, case_id="v2", side="plaintiff", stage=1, position="撤銷詐害行為", reasoning=analysis)
    for c in published:
        upsert_citation(s, citation_text=c, source_type="statute", status="published")
    s.close()


@pytest.fixture
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path / 'complaint.db'}"
    setup_case(url)
    return url


def run_main(*args, db_url):
    env = {**os.environ, DB_URL_ENV: db_url, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, "main.py", *args], cwd=ROOT, env=env, capture_output=True,
                          encoding="utf-8", timeout=60)


def write(tmp_path, obj, name="complaint.json"):
    path = tmp_path / name
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return str(path)


def problems(p, evidence=EVIDENCE, facts=FACTS):
    return fact_points.fact_point_problems(p["fact_points"], evidence_ids=[e["id"] for e in evidence], facts_summary=facts)


class TestFactPoints:
    def test_fact_without_evidence_or_quote_is_refused_by_name(self):  # T2.1
        p = payload(fact_points=[payload()["fact_points"][0],
                                 {"id": "CF2", "text": "被告甲贈與時已無其他財產。", "evidence_ids": [], "statement_quote": None}])
        out = problems(p)
        assert len(out) == 1 and "CF2" in out[0] and "fact_gaps" in out[0]

    def test_quote_may_differ_only_in_whitespace(self):  # T2.2
        ok = payload(fact_points=[{"id": "CF1", "text": "原告解散。", "evidence_ids": [],
                                   "statement_quote": "原告公司於民國 104年4月間\n解散"}])
        assert problems(ok) == []
        changed = payload(fact_points=[{"id": "CF1", "text": "原告解散。", "evidence_ids": [],
                                        "statement_quote": "原告公司於民國105年4月間解散"}])
        out = problems(changed)
        assert len(out) == 1 and "CF1" in out[0] and "逐字" in out[0]

    def test_unknown_evidence_id_is_refused(self):  # T2.3
        p = payload(fact_points=[{"id": "CF1", "text": "贈與。", "evidence_ids": ["甲證9"], "statement_quote": None}])
        out = problems(p)
        assert len(out) == 1 and "CF1" in out[0] and "甲證9" in out[0]

    def test_ids_must_be_unique_and_well_formed(self):
        fp = payload()["fact_points"]
        assert any("重複" in m for m in problems(payload(fact_points=[fp[0], {**fp[1], "id": "CF1"}])))
        assert any("編號" in m for m in problems(payload(fact_points=[{**fp[0], "id": "F1"}])))
        assert problems(payload(fact_points=[])) == ["fact_points 不可為空"]

    def test_strip_cf_tags(self):
        text = "原告公司已解散。〔CF2〕\n被告甲贈與。 〔CF10〕"
        assert fact_points.strip_cf_tags(text) == "原告公司已解散。\n被告甲贈與。"
        assert fact_points.cf_ids(text) == ["CF2", "CF10"]


def render(p=None, *, checks=None, parties=None, evidence=EVIDENCE):
    checks = {"plaintiff": {**dissolved_check()["result"], "via": "recorded"}, "defendant": None} if checks is None else checks
    case = {"case_type": "撤銷詐害債權", "claim_amount": None, "evidence": evidence,
            "parties": parties or {"plaintiff": {"name": "順昌導線工業有限公司", "ban": "29112102"},
                                   "defendant": {"name": "甲、乙", "ban": None}}}
    return pleading_render.render_complaint(p or payload(), case=case, party_checks=checks,
                                            procedural=procedural_issues(checks))


class TestRender:
    def test_dissolved_party_lists_liquidator_to_be_confirmed_without_names(self):  # T2.4
        text = render()
        plaintiff, defendant = text.split("被告")[0], text.split("為請求")[0].split("被告", 1)[1]
        assert "法定代理人" in plaintiff and "清算人(待查明" in plaintiff
        assert "順昌導線工業有限公司" in plaintiff and "29112102" in plaintiff
        assert "丙" not in text  # 案件事實寫的起訴代表人身分不明,不得帶入
        assert "甲、乙" in defendant and "(待填" in defendant and "未查核" in defendant

    def test_dissolved_party_never_uses_a_registered_name(self):  # T2.4:登記仍帶人名時也不照列原負責人
        check = {**dissolved_check()["result"], "legal_representative": {"title": "董事", "name": "王大明"},
                 "registered_responsible_name": "王大明", "via": "recorded"}
        text = render(checks={"plaintiff": check, "defendant": None})
        assert "王大明" not in text and "清算人(待查明" in text

    def test_normal_company_takes_registered_representative(self):
        check = {**dissolved_check()["result"], "status_text": "核准設立", "status_level": "ok",
                 "legal_representative": {"title": "董事", "name": "王大明"}, "warnings": [], "via": "recorded"}
        text = render(checks={"plaintiff": check, "defendant": None})
        assert "法定代理人　董事 王大明" in text and "待查明" not in text.split("為請求")[0]

    def test_body_structure(self):
        text = render()
        assert text.startswith("民事起訴狀\n")
        for part in ("訴訟標的金額或價額:(待填", "為請求撤銷詐害債權提起訴訟事:", "訴之聲明", "一、被告甲、乙間",
                     "事實及理由", "〔CF1〕", "〔CF2〕", "先位:民法第244條", "證物名稱及件數:", "甲證1:系爭房地登記謄本",
                     "此　致", "(待填:受理法院)", "【本稿產出說明】", "被告甲贈與時有無其他財產"):
            assert part in text, part
        body, note = pleading_export.split_draft_note(text)
        assert "被告甲贈與時有無其他財產" not in body and note  # 事實缺口與律師附註不進正文
        assert "plaintiff:dissolved" not in body and "原告已解散" in body
        assert pleading_export.lint_pleading(text) == []

    def test_cf_tags_do_not_change_citation_extraction(self):
        text = "被告依民法第244條第1項〔CF1〕。參最高法院105年度台簡上字第33號〔CF2〕"
        tagged = [c["citation_text"] for c in services.extract_citations(text)]
        assert tagged == [c["citation_text"] for c in services.extract_citations(fact_points.strip_cf_tags(text))]
        assert tagged == ["民法第244條", "最高法院105年度台簡上字第33號"]


class TestComplaintCommand:
    def test_lands_with_structure(self, db_url, tmp_path):
        r = run_main("complaint", "--case-id", "v2", "--json", write(tmp_path, payload()), db_url=db_url)
        assert r.returncode == 0, r.stderr
        with get_session(db_url) as s:
            row = s.query(PleadingDraft).one()
            assert (row.side, row.pleading_type, row.round, row.is_simulated, row.source) == ("plaintiff", "complaint", 1, 0, None)
            assert "〔CF1〕" in row.draft_text and "清算人(待查明" in row.draft_text
            stored = json.loads(row.structured_json)
            assert stored["basis"] == ["民法第244條"] and stored["fact_points"][1]["statement_quote"]
        again = run_main("complaint", "--case-id", "v2", "--json", write(tmp_path, payload()), db_url=db_url)
        assert again.returncode == 1 and "不可覆寫" in again.stderr

    def test_check_only_does_not_land(self, db_url, tmp_path):
        r = run_main("complaint", "--case-id", "v2", "--json", write(tmp_path, payload()), "--check", db_url=db_url)
        assert r.returncode == 0, r.stderr
        assert "民事起訴狀" in r.stdout and "檢查通過" in r.stdout
        with get_session(db_url) as s:
            assert s.query(PleadingDraft).count() == 0

    def test_unmapped_fact_is_refused(self, db_url, tmp_path):  # T2.1 經 CLI
        bad = payload(fact_points=[{"id": "CF7", "text": "被告甲惡意脫產。", "evidence_ids": [], "statement_quote": None}])
        r = run_main("complaint", "--case-id", "v2", "--json", write(tmp_path, bad), db_url=db_url)
        assert r.returncode == 1 and "CF7" in r.stderr
        with get_session(db_url) as s:
            assert s.query(PleadingDraft).count() == 0

    def test_unpublished_citation_is_refused_and_nothing_lands(self, db_url, tmp_path):  # T2.5
        p = payload(legal_argument="依民法第244條第1項及民法第245條請求。", citations=["民法第244條", "民法第245條"])
        r = run_main("complaint", "--case-id", "v2", "--json", write(tmp_path, p), db_url=db_url)
        assert r.returncode == 1 and "拒絕落地" in r.stderr and "民法第245條" in r.stderr
        with get_session(db_url) as s:
            assert s.query(PleadingDraft).count() == 0

    def test_citation_only_in_body_is_gated_too(self, db_url, tmp_path):
        p = payload(legal_argument="依民法第244條及民法第184條請求。")
        r = run_main("complaint", "--case-id", "v2", "--json", write(tmp_path, p), db_url=db_url)
        assert r.returncode == 1 and "民法第184條" in r.stderr

    def test_judgment_only_in_body_must_be_listed(self, db_url, tmp_path):
        # W2 實跑 #1 後補:判決只寫在正文、沒列進 citations,會繞過摘句與實質核對
        p = payload(legal_argument="依民法第244條請求,參最高法院105年度台簡上字第33號。")
        with get_session(db_url) as s:
            upsert_citation(s, citation_text="最高法院105年度台簡上字第33號", source_type="judgment", status="published")
        r = run_main("complaint", "--case-id", "v2", "--json", write(tmp_path, p), "--check", db_url=db_url)
        assert r.returncode == 1 and "最高法院105年度台簡上字第33號" in r.stderr and "citations" in r.stderr

    def test_unparseable_citation_is_refused_with_a_rewrite_hint(self, db_url, tmp_path):
        # 2026-11-04 實跑 W8 工程案:匯出時會是 unparseable 的寫法,落地(含 --check)時就退回,原因寫明怎麼改
        p = payload(legal_argument="其請求權時效適用同法第245條。")
        r = run_main("complaint", "--case-id", "v2", "--json", write(tmp_path, p), "--check", db_url=db_url)
        assert r.returncode == 1 and "同法第245條" in r.stderr and "法規名第N條" in r.stderr

    def test_paraphrased_fact_only_warns(self, db_url, tmp_path):
        fp = payload()["fact_points"]
        p = payload(fact_points=[fp[0], {**fp[1], "text": "原告公司於104年4月間解散,並已清算完結。"}])
        r = run_main("complaint", "--case-id", "v2", "--json", write(tmp_path, p), "--check", db_url=db_url)
        assert r.returncode == 0 and "警告:CF2 的事實內容不是事實經過的原文" in r.stdout
        assert "CF1" not in r.stdout.split("結構檢查通過")[1]  # 有證據編號的不比對文字

    def test_structure_errors(self, db_url, tmp_path):
        cases = [
            (payload(procedural_statements=[]), "plaintiff:dissolved"),
            (payload(basis=["民法第244條", "民法第179條"]), "basis"),
            (payload(claim_basis=[{"seq": 1, "role": "main", "basis": ["民法第244條"], "prayer": "一"}]), "role"),
            (payload(citations=["民法第244條", "最高法院105年度台簡上字第33號"]), "precedent_notes"),
            (payload(prayers=[]), "prayers"),
        ]
        for bad, word in cases:
            r = run_main("complaint", "--case-id", "v2", "--json", write(tmp_path, bad), "--check", db_url=db_url)
            assert r.returncode == 1 and word in r.stderr, (word, r.stderr)

    def test_analysis_must_answer_ex_officio_issue(self, tmp_path):
        url = f"sqlite:///{tmp_path / 'no-cure.db'}"
        setup_case(url, analysis="依民法第244條請求。")
        r = run_main("complaint", "--case-id", "v2", "--json", write(tmp_path, payload()), "--check", db_url=url)
        assert r.returncode == 1 and "程序補正(plaintiff:dissolved)" in r.stderr

    def test_requires_v2_case_and_landed_analysis(self, tmp_path):
        url = f"sqlite:///{tmp_path / 'other.db'}"
        setup_case(url, analysis=None)
        r = run_main("complaint", "--case-id", "v2", "--json", write(tmp_path, payload()), "--check", db_url=url)
        assert r.returncode == 1 and "分析" in r.stderr
        with get_session(url) as s:
            record_case(s, case_id="old", case_type="消費借貸", facts_summary="借款未還", claims="返還借款")
        r = run_main("complaint", "--case-id", "old", "--json", write(tmp_path, payload()), "--check", db_url=url)
        assert r.returncode == 1 and "v2" in r.stderr

    def test_judgment_needs_substantive_review_before_landing(self, db_url, tmp_path, monkeypatch):
        note = {"citation": "最高法院105年度台簡上字第33號", "doc_date": "20161026", "doc_type": "判決",
                "case_cause": "撤銷詐害債權", "quote": "原句", "proposition": "命題"}
        p = payload(citations=["民法第244條", note["citation"]], precedent_notes=[note])
        with get_session(db_url) as s:
            upsert_citation(s, citation_text=note["citation"], source_type="judgment", status="published")
        r = run_main("complaint", "--case-id", "v2", "--json", write(tmp_path, p), db_url=db_url)
        assert r.returncode == 1 and "實質核對" in r.stderr
        review = write(tmp_path, [{"citation": note["citation"], "supports": False, "reason": "案由不同"}], "review.json")
        r = run_main("complaint", "--case-id", "v2", "--json", write(tmp_path, p), "--review-json", review, db_url=db_url)
        assert r.returncode == 1 and "案由不同" in r.stderr
        with get_session(db_url) as s:
            assert s.query(PleadingDraft).count() == 0


class TestReadByPlaintiff:
    """起訴狀引用的判決要原告方在本案用 judgment 讀過全文(docs/zh/retrieval-interface.md 第十三節第 4 項)。
    落地在同一個程序裡跑,判決全文由假的 fjud 提供,不連網。"""
    JID = "TPSV,111,台上,1069,20250716,1"
    TEXT = "最高法院民事判決\n111年度台上字第1069號\n主文\n原判決廢棄。\n理由\n按締約上過失責任，以契約未成立為前提。"
    NOTE = {"citation": "最高法院111年度台上字第1069號", "doc_date": "20250716", "doc_type": "判決",
            "case_cause": "請求損害賠償", "quote": "按締約上過失責任，以契約未成立為前提。", "proposition": "締約上過失以契約未成立為前提"}

    def land(self, db_url, tmp_path, monkeypatch, *, read, snapshot=True):
        import argparse
        import main
        from engine import fjud, retrieval_cache
        monkeypatch.setattr(fjud, "fetch_document", lambda jid, timeout=None, session=None: {
            "jid": jid, "url": fjud.document_url(jid), "full_text": self.TEXT, "case_cause": "請求損害賠償"})
        monkeypatch.setattr(fjud, "advanced_search", lambda citation=None, **kw: {
            "rows": [{"jid": self.JID}] if citation == ("111", "台上", "1069") else []})
        monkeypatch.setenv(DB_URL_ENV, db_url)
        root = tmp_path / "case-snap"
        if read:  # 原告用 judgment 讀過全文
            assert main.cmd_judgment(argparse.Namespace(target=self.JID, doc_date=None, json=True, log=None, issue=None,
                                                        snapshot=str(root / "plaintiff"))) == 0
        else:  # 全文只是被 search-judgments --fetch 存進快照,不算讀過
            retrieval_cache.get_judgment(self.JID, snapshot=str(root / "plaintiff"))
        with get_session(db_url) as s:
            upsert_citation(s, citation_text=self.NOTE["citation"], source_type="judgment", status="published")
        p = payload(citations=["民法第244條", self.NOTE["citation"]], precedent_notes=[self.NOTE])
        review = write(tmp_path, [{"citation": self.NOTE["citation"], "supports": True, "reason": "理由欄第一段"}], "review.json")
        return main.cmd_complaint(argparse.Namespace(case_id="v2", json=write(tmp_path, p), check=False, review_json=review,
                                                     snapshot=str(root) if snapshot else None))

    def test_judgment_the_plaintiff_did_not_read_is_refused(self, db_url, tmp_path, monkeypatch, capsys):
        assert self.land(db_url, tmp_path, monkeypatch, read=False) == 1
        assert "not_read_by_side" in capsys.readouterr().err
        with get_session(db_url) as s:
            assert s.query(PleadingDraft).count() == 0

    def test_judgment_needs_the_case_snapshot(self, db_url, tmp_path, monkeypatch, capsys):
        assert self.land(db_url, tmp_path, monkeypatch, read=True, snapshot=False) == 1
        assert "快照根目錄" in capsys.readouterr().err

    def test_judgment_the_plaintiff_read_lands(self, db_url, tmp_path, monkeypatch, capsys):
        assert self.land(db_url, tmp_path, monkeypatch, read=True) == 0, capsys.readouterr().err
        with get_session(db_url) as s:
            assert s.query(PleadingDraft).count() == 1


@pytest.fixture
def client(db_url, tmp_path):
    app = create_app(db_url=db_url, cases_dir=str(tmp_path / "none"), live_checks_path=str(tmp_path / "none.json"),
                     seed_on_empty=False, local_clients=("testclient",))
    return TestClient(app, base_url=LOCAL)


class TestDisplayAndExport:
    def test_export_drops_cf_tags_but_screen_keeps_them(self, db_url, tmp_path, client):  # T2.6
        assert run_main("complaint", "--case-id", "v2", "--json", write(tmp_path, payload()), db_url=db_url).returncode == 0
        d = client.get("/api/cases/v2").json()
        assert "〔CF1〕" in d["pleading"]["draft_text"] and d["pleading"]["pleading_type"] == "complaint"
        assert d["pleading"]["structured"]["fact_gaps"] == payload()["fact_gaps"]
        [v] = d["pleading_versions"]
        r = client.get(f"/api/cases/v2/pleadings/{v['id']}/export")
        assert r.status_code == 200
        text = r.content.decode("utf-8")
        assert "〔CF" not in text and "被告甲將系爭房地贈與被告乙並完成移轉登記。" in text
        # 律師編輯版保留 CF 標記(逐點表態要用),匯出一樣移除
        edited = v["draft_text"].replace("系爭房地贈與", "系爭房地無償贈與")
        saved = client.post("/api/cases/v2/pleadings", json={"parent_id": v["id"], "draft_text": edited, "mode": "offline"})
        assert saved.status_code == 201, saved.text
        text = client.get(f"/api/cases/v2/pleadings/{saved.json()['id']}/export").content.decode("utf-8")
        assert "〔CF" not in text and "無償贈與" in text

    def test_latest_main_document_is_picked_by_type(self, db_url, tmp_path, client):
        assert run_main("complaint", "--case-id", "v2", "--json", write(tmp_path, payload()), db_url=db_url).returncode == 0
        with get_session(db_url) as s:  # 之後的模擬準備書狀不能蓋掉起訴狀
            record_pleading(s, case_id="v2", draft_text="民事準備書狀", citations_used=[], pleading_type="brief", round=2,
                            is_simulated=1)
        d = client.get("/api/cases/v2").json()
        assert d["pleading"]["draft_text"].startswith("民事起訴狀") and d["pleading"]["draft_count"] == 1

    def test_old_case_pleadings_response_is_unchanged(self, tmp_path):  # T2.7
        url = f"sqlite:///{tmp_path / 'old.db'}"
        with get_session(url) as s:
            record_case(s, case_id="old", case_type="消費借貸", facts_summary="借款未還", claims="返還借款")
            upsert_citation(s, citation_text="民法第474條", source_type="statute", status="published")
            record_pleading(s, case_id="old", draft_text="民事起訴狀\n依民法第474條請求。", citations_used=["民法第474條"])
            record_pleading(s, case_id="old", draft_text="民事答辯狀\n否認。", citations_used=[], side="defendant")
            d = services.get_case_detail(s, "old")
        assert set(d["pleadings"]["plaintiff"]) == {"id", "side", "draft_text", "generated_at", "origin",
                                                    "citation_verification_status", "draft_count", "citation_check"}
        assert d["pleadings"]["plaintiff"]["draft_text"].startswith("民事起訴狀")
        assert d["pleadings"]["defendant"]["draft_text"] == "民事答辯狀\n否認。"
        assert d["pleading"] == d["pleadings"]["plaintiff"]
        assert set(d["pleading_versions"][0]) == {"id", "source", "parent_id", "side", "document", "label", "generated_at",
                                                  "draft_text", "origin", "status", "citation_check", "blocked_count",
                                                  "exportable", "lint_warnings"}
