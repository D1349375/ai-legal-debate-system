"""W3 關卡 1 與續跑(書狀交換流程 protocol v2)。

以 tests/fake_claude.py 的 v2 流程模擬 Claude Code(不呼叫模型)。T3.6 舊案續跑行為不變由 tests/test_live_run.py 涵蓋。
"""
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from database.db import (
    get_session, record_argument, record_case, record_gate, record_pleading, record_question, plaintiff_view,
)
from database.schema import Case, DebateArgument, PleadingDraft
from server import live_run
from server.app import create_app

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAKE = os.path.join(ROOT, "tests", "fake_claude.py")
LOCAL = "http://127.0.0.1:8000"
CASE = {"case_type": "撤銷詐害債權", "facts_summary": "原告公司於民國104年4月間解散。被告甲將房地贈與被告乙。",
        "claims": "撤銷贈與及移轉登記", "plaintiff": {"name": "甲公司", "ban": "22099131"}, "defendant": {"name": "甲、乙"}}


@pytest.fixture
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path / 'gate.db'}"
    get_session(url).close()
    return url


@pytest.fixture
def client(db_url, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "full")
    monkeypatch.setenv("FAKE_CLAUDE_EXPECT_DB_URL", db_url)  # T7:假 Claude 確認拿到的是同一顆資料庫
    for name in ("FAKE_CLAUDE_STOP_AFTER_P1", "FAKE_CLAUDE_FORCE_RELAND"):
        monkeypatch.delenv(name, raising=False)
    opts = {"enabled": True, "command": [sys.executable, FAKE], "runs_dir": str(tmp_path / "runs")}
    app = create_app(db_url=db_url, cases_dir=str(tmp_path / "none"), seed_on_empty=False,
                     local_clients=("testclient",), live=opts)
    return TestClient(app, base_url=LOCAL)


def create_v2(client):
    r = client.post("/api/cases", json=CASE)
    assert r.status_code == 201, r.text
    return r.json()["case_id"]


def start(client, case_id, *, stop_after=None, resume=False):
    body = {"stop_after": stop_after} if stop_after else {}
    return client.post(f"/api/cases/{case_id}/runs" + ("?resume=true" if resume else ""), json=body)


def run(client, case_id, **kw):
    r = start(client, case_id, **kw)
    assert r.status_code == 201, r.text
    run_id = r.json()["run"]["id"]
    client.app.state.live.wait(run_id, timeout=60)
    return client.get(f"/api/runs/{run_id}").json()


def run_dir(tmp_path, run):
    return tmp_path / "runs" / f"run-{run['run']['id']}"


def gate(client, case_id, version_id, action="continue"):
    return client.post(f"/api/cases/{case_id}/gates/complaint", json={"version_id": version_id, "action": action})


def complaint_id(db_url, case_id):
    with get_session(db_url) as s:
        rows = [r for r in s.query(PleadingDraft).filter_by(case_id=case_id, pleading_type="complaint").all()
                if r.source is None]
        assert len(rows) == 1
        return rows[0].id


def stored_gates(db_url, case_id):
    with get_session(db_url) as s:
        raw = s.query(Case).filter_by(case_id=case_id).one().gates_json
        return json.loads(raw) if raw else None


def edit(client, case_id, parent_id, text):
    r = client.post(f"/api/cases/{case_id}/pleadings", json={"parent_id": parent_id, "draft_text": text, "mode": "offline"})
    assert r.status_code == 201, r.text
    return r.json()


class TestStopAfter:
    def test_stop_after_complaint_succeeds_without_later_steps(self, client, db_url, tmp_path):  # T3.1
        case_id = create_v2(client)
        done = run(client, case_id, stop_after="complaint")
        assert done["run"]["status"] == "succeeded", done["run"]["error"]
        assert done["run"]["error"] is None and done["run"]["stop_after"] == "complaint"
        assert "只產起訴狀" in done["events"][0]["text"]
        assert done["events"][-1]["text"].startswith("執行完成，起訴狀 v1 已落地")
        prompt = (run_dir(tmp_path, done) / "prompt.txt").read_text(encoding="utf-8")
        assert "只跑到起訴狀" in prompt and "Step 1–3" in prompt and "本次要產生的書狀" not in prompt
        with get_session(db_url) as s:
            assert {(a.side, a.stage) for a in s.query(DebateArgument).filter_by(case_id=case_id)} == {("plaintiff", 1)}
        complaint_id(db_url, case_id)
        assert stored_gates(db_url, case_id) is None  # 停在關卡前，沒有自動通過
        d = client.get(f"/api/cases/{case_id}").json()
        assert d["gates"]["complaint"] is None and d["gates"]["pending"] == "complaint"
        assert d["resume"]["possible"] is False and "關卡 1" in d["resume"]["reason"]
        assert d["resume"]["gate_pending"] is True

    def test_missing_complaint_is_incomplete(self, client, db_url, monkeypatch):
        case_id = create_v2(client)
        monkeypatch.setenv("FAKE_CLAUDE_MODE", "partial")  # v2:只落地原告分析就回報完成
        done = run(client, case_id, stop_after="complaint")
        assert done["run"]["status"] == "incomplete"
        assert done["run"]["error"] == "Claude Code 回報完成，但資料庫仍缺:起訴狀 v1"
        plan = client.get(f"/api/cases/{case_id}").json()["resume"]
        assert plan["possible"] and plan["from_key"] == "complaint" and plan["stop_after_allowed"] is True
        monkeypatch.setenv("FAKE_CLAUDE_MODE", "full")
        again = run(client, case_id, stop_after="complaint", resume=True)
        assert again["run"]["status"] == "succeeded", again["run"]["error"]
        complaint_id(db_url, case_id)

    def test_stop_after_only_for_v2_cases(self, client, db_url):
        with get_session(db_url) as s:
            record_case(s, case_id="old", case_type="t", facts_summary="舊流程案件事實", claims="c", created_via="ui")
        r = start(client, "old", stop_after="complaint")
        assert r.status_code == 409 and "書狀交換流程" in r.json()["detail"]
        assert start(client, "old", stop_after="answer").status_code == 409  # 第 3 批:answer 是 v2 的停止點
        assert start(client, "old", stop_after="closing").status_code == 422

    def test_v2_has_no_document_choice_or_step_9c(self, client):
        case_id = create_v2(client)
        r = client.post(f"/api/cases/{case_id}/runs", json={"documents": ["defendant"]})
        assert r.status_code == 409 and "不選書狀" in r.json()["detail"]
        r = client.post(f"/api/cases/{case_id}/runs", json={"kind": "pleadings", "documents": ["defendant"]})
        assert r.status_code == 409 and "補產" in r.json()["detail"]


class TestGate:
    def stopped_case(self, client, db_url):
        case_id = create_v2(client)
        assert run(client, case_id, stop_after="complaint")["run"]["status"] == "succeeded"
        return case_id, complaint_id(db_url, case_id)

    def test_cannot_resume_until_confirmed_then_starts_from_defense(self, client, db_url, tmp_path):  # T3.2
        case_id, cid = self.stopped_case(client, db_url)
        r = start(client, case_id, resume=True)
        assert r.status_code == 409 and "關卡 1" in r.json()["detail"]
        r = gate(client, case_id, cid)
        assert r.status_code == 200, r.text
        g = stored_gates(db_url, case_id)["complaint"]
        assert (g["action"], g["version_id"], g["source"], g["by"]) == ("continue", cid, "system", "ui")
        assert g["recorded_at"]
        d = client.get(f"/api/cases/{case_id}").json()
        assert d["gates"]["complaint"]["version_id"] == cid and d["gates"]["pending"] is None
        plan = d["resume"]
        assert plan["possible"] and plan["from_key"] == "defense" and plan["from_label"] == "被告防禦分析"
        assert plan["stop_after_allowed"] is False
        assert start(client, case_id, resume=True, stop_after="complaint").status_code == 409
        done = run(client, case_id, resume=True)
        assert done["run"]["status"] == "succeeded", done["run"]["error"]
        assert done["run"]["resume_from"] == "被告防禦分析"
        prompt = (run_dir(tmp_path, done) / "prompt.txt").read_text(encoding="utf-8")
        # 第 3 批:關卡 1 之後照新流程從 SKILL.md Step 4 往下,不再借舊流程(審查 A1)
        assert "本次是續跑" in prompt and f"#{cid}" in prompt and "從 SKILL.md Step 4" in prompt
        assert "legacy-v1.md" not in prompt
        landed = json.loads((run_dir(tmp_path, done) / "landed.json").read_text(encoding="utf-8"))
        assert landed["confirmed_complaint"]["version_id"] == cid
        with get_session(db_url) as s:
            assert {(a.side, a.stage) for a in s.query(DebateArgument).filter_by(case_id=case_id)} == {
                (side, n) for side in ("plaintiff", "defendant") for n in (1, 2, 3)}
            assert s.query(PleadingDraft).filter_by(case_id=case_id, side="defendant", pleading_type="answer").count() == 1
        assert complaint_id(db_url, case_id) == cid  # 起訴狀沒有重新落地
        assert stored_gates(db_url, case_id)["complaint"]["by"] == "ui"  # 續跑不會把律師確認改成自動
        assert client.get(f"/api/cases/{case_id}").json()["resume"]["possible"] is False

    def test_gate_is_written_once(self, client, db_url):
        case_id, cid = self.stopped_case(client, db_url)
        assert gate(client, case_id, cid).status_code == 200
        before = stored_gates(db_url, case_id)
        r = gate(client, case_id, cid, "finish")
        assert r.status_code == 409 and "不可覆寫" in r.json()["detail"]
        assert stored_gates(db_url, case_id) == before

    def test_finish_ends_the_case(self, client, db_url):
        case_id, cid = self.stopped_case(client, db_url)
        assert gate(client, case_id, cid, "finish").status_code == 200
        plan = client.get(f"/api/cases/{case_id}").json()["resume"]
        assert plan["possible"] is False and "到此結束" in plan["reason"]
        assert start(client, case_id, resume=True).status_code == 409

    def test_gate_input_is_checked(self, client, db_url):
        case_id, cid = self.stopped_case(client, db_url)
        assert client.post(f"/api/cases/{case_id}/gates/complaint", json={"version_id": cid, "action": "skip"}).status_code == 422
        assert gate(client, "nope", cid).status_code == 404
        assert gate(client, case_id, 99999).status_code == 404
        other = create_v2(client)
        assert gate(client, other, cid).status_code == 404  # 別的案件的版本
        r = gate(client, other, cid + 1000)
        assert r.status_code == 404
        with get_session(db_url) as s:
            ans = record_pleading(s, case_id=case_id, draft_text="民事答辯狀", citations_used=[], side="defendant").id
            record_case(s, case_id="old", case_type="t", facts_summary="舊流程案件事實", claims="c", created_via="ui")
            old = record_pleading(s, case_id="old", draft_text="民事起訴狀", citations_used=[]).id
        r = gate(client, case_id, ans)
        assert r.status_code == 409 and "起訴狀" in r.json()["detail"]
        r = gate(client, "old", old)
        assert r.status_code == 409 and "書狀交換流程" in r.json()["detail"]
        assert stored_gates(db_url, case_id) is None

    def test_no_gate_while_this_case_is_running(self, client, db_url, monkeypatch):
        case_id, cid = self.stopped_case(client, db_url)
        runner = client.app.state.live
        monkeypatch.setattr(runner, "_active", SimpleNamespace(case_id=case_id, run_id=99))
        r = gate(client, case_id, cid)
        assert r.status_code == 409 and "執行中" in r.json()["detail"]
        monkeypatch.setattr(runner, "_active", SimpleNamespace(case_id="other", run_id=99))
        assert gate(client, case_id, cid).status_code == 200  # 別的案件在跑不影響

    def test_blocked_lawyer_version_cannot_be_confirmed(self, client, db_url):  # T3.3
        case_id, cid = self.stopped_case(client, db_url)
        system_text = client.get(f"/api/cases/{case_id}").json()["pleadings"]["plaintiff"]["draft_text"]
        bad = edit(client, case_id, cid, system_text + "\n參照最高法院999年度台上字第1號判決。")
        assert bad["exportable"] is False and bad["blocked_count"] == 1
        for action in ("continue", "finish"):
            r = gate(client, case_id, bad["id"], action)
            assert r.status_code == 409 and "未通過" in r.json()["detail"]
        assert stored_gates(db_url, case_id) is None
        good = edit(client, case_id, bad["id"], system_text + "\n新增的律師補充段落。")
        assert good["exportable"] is True
        assert good["new_paragraphs_without_cf"] == ["新增的律師補充段落。"]  # 只提示，不阻擋
        assert gate(client, case_id, good["id"]).status_code == 200
        g = stored_gates(db_url, case_id)["complaint"]
        assert (g["version_id"], g["source"]) == (good["id"], "lawyer_edit")

    def test_full_run_without_stop_passes_gate_automatically(self, client, db_url, tmp_path):  # T3.4
        case_id = create_v2(client)
        done = run(client, case_id)
        assert done["run"]["status"] == "succeeded", done["run"]["error"]
        assert done["run"]["stop_after"] is None
        prompt = (run_dir(tmp_path, done) / "prompt.txt").read_text(encoding="utf-8")
        assert "跑完全程" in prompt and "未經律師確認" in prompt
        g = stored_gates(db_url, case_id)["complaint"]
        assert (g["action"], g["by"], g["version_id"], g["source"]) == ("continue", "auto", complaint_id(db_url, case_id), "system")
        assert g["run_id"] == done["run"]["id"] and "未經律師確認" in g["note"]
        assert any("關卡 1 自動通過" in e["text"] for e in done["events"])
        with get_session(db_url) as s:
            assert s.query(PleadingDraft).filter_by(case_id=case_id, side="defendant", pleading_type="answer").count() == 1
        d = client.get(f"/api/cases/{case_id}").json()
        assert d["gates"]["complaint"]["by"] == "auto" and d["resume"]["possible"] is False

    def test_no_auto_gate_when_run_stopped_at_p1(self, client, db_url, monkeypatch):
        case_id = create_v2(client)
        monkeypatch.setenv("FAKE_CLAUDE_STOP_AFTER_P1", "1")  # 沒指定停止點，但起訴狀落地後就結束
        done = run(client, case_id)
        assert done["run"]["status"] == "incomplete" and "被告防禦分析" in done["run"]["error"]
        assert stored_gates(db_url, case_id) is None  # 流程沒有越過關卡，律師仍可確認
        assert client.get(f"/api/cases/{case_id}").json()["resume"]["gate_pending"] is True

    def test_role_view_reads_confirmed_lawyer_version(self, client, db_url, tmp_path):  # T3.5
        case_id, cid = self.stopped_case(client, db_url)
        with get_session(db_url) as s:
            before = plaintiff_view(s, case_id)["complaint"]
        assert before["version_id"] == cid and before["confirmed"] is False and before["gate"] is None
        system_text = client.get(f"/api/cases/{case_id}").json()["pleadings"]["plaintiff"]["draft_text"]
        lawyer_text = system_text.replace("民事起訴狀", "民事起訴狀(律師修訂)", 1)
        v = edit(client, case_id, cid, lawyer_text)
        assert gate(client, case_id, v["id"]).status_code == 200
        env = {**os.environ, "LEGALDEBATE_DB_URL": db_url, "PYTHONUTF8": "1"}
        p = subprocess.run([sys.executable, "main.py", "role-view", "--case-id", case_id, "--role", "plaintiff"],
                           cwd=ROOT, env=env, capture_output=True, encoding="utf-8")
        assert p.returncode == 0, p.stderr
        view = json.loads(p.stdout)["complaint"]
        assert view["version_id"] == v["id"] and view["source"] == "lawyer_edit" and view["confirmed"] is True
        assert view["draft_text"] == lawyer_text and view["gate"]["by"] == "ui"
        done = run(client, case_id, resume=True)
        assert done["run"]["status"] == "succeeded", done["run"]["error"]
        prompt = (run_dir(tmp_path, done) / "prompt.txt").read_text(encoding="utf-8")
        assert f"律師編輯版 #{v['id']}" in prompt
        landed = json.loads((run_dir(tmp_path, done) / "landed.json").read_text(encoding="utf-8"))
        assert landed["confirmed_complaint"]["draft_text"] == lawyer_text
        assert landed["confirmed_complaint"]["source"] == "lawyer_edit"
        # 假 Claude 回報它讀到的起訴狀版本(續跑用的就是律師版)
        assert (run_dir(tmp_path, done) / "complaint_read.txt").read_text(encoding="utf-8") == str(v["id"])


class TestPlanV2:
    def case(self, s, case_id="v"):
        record_case(s, case_id=case_id, case_type="t", facts_summary="事實經過", claims="c", created_via="ui",
                    protocol="v2", represented_side="plaintiff")
        return case_id

    def complaint(self, s, case_id="v"):
        return record_pleading(s, case_id=case_id, draft_text="民事起訴狀〔CF1〕", citations_used=[],
                               pleading_type="complaint", round=1, is_simulated=0).id

    def test_resume_plan_v2(self, tmp_path):
        with get_session(f"sqlite:///{tmp_path / 'p.db'}") as s:
            self.case(s)
            plan = live_run.resume_plan(s, "v")
            assert plan["possible"] is False and plan["reason"].startswith("此案件沒有落地紀錄")
            record_argument(s, case_id="v", side="plaintiff", stage=1, position="p", reasoning="r")
            plan = live_run.resume_plan(s, "v")
            assert plan["possible"] and plan["from_key"] == "complaint" and plan["from_step"] == "Step 3"
            assert plan["from_doc"] == "SKILL.md" and plan["landed"] == ["原告請求權基礎檢驗"]
            assert plan["stop_after_allowed"] is True and plan["missing_sides"] == []
            cid = self.complaint(s)
            plan = live_run.resume_plan(s, "v")
            assert plan["possible"] is False and plan["gate_pending"] is True
            record_gate(s, case_id="v", gate="complaint", version_id=cid, action="continue", by="ui")
            plan = live_run.resume_plan(s, "v")
            assert plan["from_key"] == "defense" and plan["from_doc"] == "SKILL.md" and plan["from_step"] == "Step 4"
            assert plan["landed"] == ["原告請求權基礎檢驗", "起訴狀 v1", "關卡 1(確認起訴狀 #%d)" % cid]
            record_argument(s, case_id="v", side="defendant", stage=1, position="p", reasoning="r")
            assert live_run.resume_plan(s, "v")["from_key"] == "answer"
            record_argument(s, case_id="v", side="plaintiff", stage=2, position="p", reasoning="r", falsifier="x")
            plan = live_run.resume_plan(s, "v")  # 答辯狀、爭點整理表沒落地，第 2 輪卻有：不猜
            assert plan["possible"] is False and "不連續" in plan["reason"]

    def test_complaint_without_analysis_is_a_gap(self, tmp_path):
        with get_session(f"sqlite:///{tmp_path / 'p.db'}") as s:
            self.case(s)
            self.complaint(s)
            plan = live_run.resume_plan(s, "v")
            assert plan["possible"] is False and "不連續" in plan["reason"]

    def test_pipeline_missing_v2(self, tmp_path):
        with get_session(f"sqlite:///{tmp_path / 'p.db'}") as s:
            self.case(s)
            assert live_run.pipeline_missing(s, "v", stop_after="complaint") == ["原告請求權基礎檢驗", "起訴狀 v1"]
            record_argument(s, case_id="v", side="plaintiff", stage=1, position="p", reasoning="r")
            self.complaint(s)
            assert live_run.pipeline_missing(s, "v", stop_after="complaint") == []
            full = live_run.pipeline_missing(s, "v")
            assert full[0] == "被告防禦分析" and full[1] == "被告答辯狀" and full[-1] == "起訴狀 v2"
            assert "原告 Stage 1" not in full and "原告起訴狀骨架" not in full
            # 第 3 批:完成判定看爭點整理表,不看 CourtQuestion(審查 A1)
            assert "法官訊問" not in full and "爭點整理表" in full
            record_question(s, case_id="v", question_text="q", target_side="defendant", based_on="b")
            assert "爭點整理表" in live_run.pipeline_missing(s, "v")

    def test_gate_rules_in_db(self, tmp_path):
        with get_session(f"sqlite:///{tmp_path / 'p.db'}") as s:
            self.case(s)
            cid = self.complaint(s)
            with pytest.raises(ValueError, match="action"):
                record_gate(s, case_id="v", gate="complaint", version_id=cid, action="maybe", by="ui")
            with pytest.raises(ValueError, match="關卡"):
                record_gate(s, case_id="v", gate="answer", version_id=cid, action="continue", by="ui")
            record_gate(s, case_id="v", gate="complaint", version_id=cid, action="continue", by="auto", run_id=3,
                        note="未經律師確認")
            with pytest.raises(ValueError, match="不可覆寫"):
                record_gate(s, case_id="v", gate="complaint", version_id=cid, action="continue", by="ui")

    def test_prompt_v1_resume_points_to_legacy_doc(self):
        plan = {"possible": True, "landed": ["Stage 1 爭點整理"], "landed_keys": ["stage1"], "from_key": "questions",
                "from_label": "法官訊問", "from_step": "Step 3", "from_doc": "references/legacy-v1.md", "missing_sides": []}
        p = live_run.build_prompt("c1", "database/live_runs/run-9", plan)
        assert "從 references/legacy-v1.md Step 3(法官訊問)開始" in p and "SKILL.md Step 3" not in p


class TestV2ReadAllowlist:
    """v2 讀檔白名單(防污染):別的執行、別的案件、docs/、舊輸入檔都擋,本次執行、本案件、skill 不擋。"""

    def test_read_denials_block_siblings_on_each_level(self, tmp_path):
        for folder in ("docs/zh", "data/cases", "video", ".claude/worktrees/x", ".claude/skills/legal-debate/references",
                       ".claude/skills/other", "database/live_runs/run-1", "database/live_runs/run-2",
                       "database/live_runs/case-a", "database/live_runs/case-b"):
            os.makedirs(tmp_path / folder)
        for f in ("main.py", "database/db.py", ".claude/launch.json"):
            (tmp_path / f).write_text("x", encoding="utf-8")
        keep = ["database/live_runs/run-2", "database/live_runs/case-b", live_run.SKILL_DIR_REL]
        rules = set(live_run.read_denials(str(tmp_path), keep))
        assert {"Read(/docs/**)", "Read(/data/**)", "Read(/video/**)", "Read(/main.py)", "Read(/database/db.py)",
                "Read(/.claude/launch.json)", "Read(/.claude/worktrees/**)", "Read(/.claude/skills/other/**)",
                "Read(/database/live_runs/run-1/**)", "Read(/database/live_runs/case-a/**)"} == rules
        assert not any(k in r for r in rules for k in ("run-2", "case-b", "legal-debate"))

    def test_v2_runs_carry_the_denials_and_v1_runs_do_not(self, client, db_url, tmp_path, monkeypatch):
        seen = []
        real = live_run.build_args
        monkeypatch.setattr(live_run, "build_args", lambda *a, **kw: seen.append(kw.get("read_denied", ())) or real(*a, **kw))
        run(client, create_v2(client), stop_after="complaint")
        denied = seen[-1]
        assert "Read(/docs/**)" in denied and "Read(/data/**)" in denied and denied[-1] == live_run.V2_DENIED_READS[0]
        assert "legacy-v1.md" in live_run.V2_DENIED_READS[0]
        assert not any("legal-debate/**" in r or r == "Read(/.claude/skills/**)" for r in denied)
        args = real(["claude"], "x", model="m", budget_usd=1, read_denied=denied)
        assert args[args.index("--disallowedTools") + 1:][-len(denied):] == list(denied)
        # 不限路徑的 Read／Grep／Glob 放行會放行專案外，v2 拿掉(專案內不靠它也放行)
        allowed = args[args.index("--allowedTools") + 1:args.index("--disallowedTools")]
        assert not {"Read", "Grep", "Glob"} & set(allowed) and "Agent" in allowed
        # 舊流程(protocol 為 NULL)照舊，不加白名單
        with get_session(db_url) as s:
            record_case(s, case_id="old1", case_type="t", facts_summary="f", claims="c", created_via="ui")
        r = client.post("/api/cases/old1/runs")
        assert r.status_code == 201, r.text
        client.app.state.live.wait(r.json()["run"]["id"], timeout=60)
        assert seen[-1] == ()
