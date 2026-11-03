"""第 3 批:server/live_run.py 的書狀交換流程(審查 A1–A6)與假 Claude 跑完 P0–P6。

- A1 步驟表照新流程:分析 → 起訴狀 → 關卡 1 → 被告分析 → 答辯狀 → 爭點整理表 → 第 2 輪論證 → 準備書狀
  → 第 3 輪論證 → 言詞辯論意旨狀 → 評估 → 起訴狀 v2;完成判定看 IssueSheet,不看 CourtQuestion。
- A2 停止點多 answer、issue_sheet。
- A3 執行 prompt 不再把 case.json 交給角色;被告只讀 role-view --role defendant。
- A4 續跑的 landed.json 不含論證全文(有原告內部檢討),另有爭點整理表;續跑指示不叫任何 subagent 讀它。
- A5 排除的來源裁判由伺服器設定帶入環境變數,檢索指令自己套用,不經過模型。
"""
import json
import os
import subprocess
import sys

import pytest

from database.db import (
    get_session, record_argument, record_case, record_gate, record_issue_sheet, record_pleading, record_verdict,
)
from database.schema import DebateArgument, IssueSheet, PleadingDraft, Verdict
from server import live_run
from tests.test_gate import client, complaint_id, create_v2, db_url, run, run_dir, start, stored_gates  # noqa: F401

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORDER = ["analysis", "complaint", "gate1", "defense", "answer", "issue_sheet", "stage2", "brief", "stage3", "closing",
         "verdict", "revision"]


class Steps:
    """在空資料庫裡一步一步落地 v2 各階段的最小紀錄(不經過檢查,只為了看步驟表怎麼判斷)。"""

    def __init__(self, s, case_id="v"):
        self.s, self.case_id = s, case_id
        record_case(s, case_id=case_id, case_type="t", facts_summary="事實經過", claims="c", created_via="ui",
                    protocol="v2", represented_side="plaintiff")

    def arg(self, side, stage):
        record_argument(self.s, case_id=self.case_id, side=side, stage=stage, position="p",
                        reasoning="【爭點 I1】r\n【內部檢討】哨兵內部檢討【內部檢討結束】",
                        falsifier="x" if stage > 1 else None)

    def pleading(self, side, kind, rnd):
        return record_pleading(self.s, case_id=self.case_id, draft_text=f"{side} {kind}", citations_used=[], side=side,
                               pleading_type=kind, round=rnd, is_simulated=0 if kind == "complaint" else 1).id

    def until(self, key):
        """落地到 key(含)為止。"""
        for step in ORDER[:ORDER.index(key) + 1]:
            if step == "analysis":
                self.arg("plaintiff", 1)
            elif step == "complaint":
                self.cid = self.pleading("plaintiff", "complaint", 1)
            elif step == "gate1":
                record_gate(self.s, case_id=self.case_id, gate="complaint", version_id=self.cid, action="continue", by="ui")
            elif step == "defense":
                self.arg("defendant", 1)
            elif step == "answer":
                self.aid = self.pleading("defendant", "answer", 1)
            elif step == "issue_sheet":
                record_issue_sheet(self.s, case_id=self.case_id, sheet={"issues": [{"id": "I1"}]}, complaint_id=self.cid,
                                   answer_id=self.aid)
            elif step in ("stage2", "stage3"):
                for side in ("plaintiff", "defendant"):
                    self.arg(side, int(step[-1]))
            elif step in ("brief", "closing"):
                for side in ("plaintiff", "defendant"):
                    self.pleading(side, step, 2 if step == "brief" else 3)
            elif step == "verdict":
                record_verdict(self.s, case_id=self.case_id, verdict_main_text="m", verdict_reasoning="r", risk_map={},
                               mechanical_anchor_json={}, protocol_version="v2-pleading-exchange", citations_used=[])
            elif step == "revision":
                from database.db import record_complaint_revision
                record_complaint_revision(self.s, case_id=self.case_id, parent_id=self.cid, draft_text="v2",
                                          citations_used=[], structured={})


@pytest.fixture
def steps(tmp_path):
    with get_session(f"sqlite:///{tmp_path / 'steps.db'}") as s:
        yield Steps(s)


class TestStepTable:  # A1
    def test_order(self):
        assert [key for key, *_ in live_run.RUN_STEPS_V2] == ORDER
        assert live_run.STOP_AFTER == ("complaint", "answer", "issue_sheet")  # A2

    @pytest.mark.parametrize("done,expected", [("gate1", "defense"), ("defense", "answer"), ("answer", "issue_sheet"),
                                               ("issue_sheet", "stage2"), ("stage2", "brief"), ("brief", "stage3"),
                                               ("stage3", "closing"), ("closing", "verdict"), ("verdict", "revision")])
    def test_resume_starts_at_the_next_new_step(self, steps, done, expected):
        steps.until(done)
        plan = live_run.resume_plan(steps.s, "v")
        assert plan["possible"] and plan["from_key"] == expected, plan
        assert plan["from_doc"] == "SKILL.md" and plan["from_step"].startswith("Step ")

    def test_everything_landed(self, steps):
        steps.until("revision")
        plan = live_run.resume_plan(steps.s, "v")
        assert plan["possible"] is False and "皆已落地" in plan["reason"]
        assert live_run.pipeline_missing(steps.s, "v") == []

    def test_answer_landing_is_not_a_gap(self, steps):  # 舊表把答辯狀排最後,一落地就被判不連續
        steps.until("answer")
        assert "不連續" not in (live_run.resume_plan(steps.s, "v")["reason"] or "")

    def test_issue_sheet_counts_not_court_questions(self, steps):
        steps.until("issue_sheet")
        missing = live_run.pipeline_missing(steps.s, "v")
        assert "爭點整理表" not in missing and "法官訊問" not in missing
        assert missing[0] == "原告第 2 輪論證" and missing[-1] == "起訴狀 v2"

    def test_one_side_of_a_round(self, steps):
        steps.until("issue_sheet")
        steps.arg("plaintiff", 2)
        plan = live_run.resume_plan(steps.s, "v")
        assert plan["from_key"] == "stage2" and plan["missing_sides"] == ["defendant"]

    def test_gap_is_refused(self, steps):
        steps.until("answer")
        steps.arg("plaintiff", 2)  # 爭點整理表沒落地,第 2 輪卻有
        plan = live_run.resume_plan(steps.s, "v")
        assert plan["possible"] is False and "不連續" in plan["reason"]

    @pytest.mark.parametrize("stop,last", [("complaint", "起訴狀 v1"), ("answer", "被告答辯狀"), ("issue_sheet", "爭點整理表")])
    def test_pipeline_missing_stops(self, steps, stop, last):
        assert live_run.pipeline_missing(steps.s, "v", stop_after=stop)[-1] == last

    def test_stop_options_follow_the_resume_point(self, steps):
        steps.until("complaint")
        record_gate(steps.s, case_id="v", gate="complaint", version_id=steps.cid, action="continue", by="ui")
        plan = live_run.resume_plan(steps.s, "v")
        assert plan["stop_after_options"] == ["answer", "issue_sheet"] and plan["stop_after_allowed"] is False
        steps.arg("defendant", 1)
        steps.aid = steps.pleading("defendant", "answer", 1)
        assert live_run.resume_plan(steps.s, "v")["stop_after_options"] == ["issue_sheet"]


class TestPrompt:
    def test_roles_do_not_get_case_json(self):  # A3
        p = live_run.build_prompt("c1", "database/live_runs/run-9", protocol="v2")
        assert "role-view --case-id c1 --role defendant" in p and "role-view --case-id c1 --role judge" in p
        assert "不得把這個檔案或它的路徑交給任何 subagent" in p
        assert "SKILL.md 提到案件輸入檔或 {CASE_FACTS_PATH} 時填這個檔案" not in p

    @pytest.mark.parametrize("stop,step", [("answer", "Step 5"), ("issue_sheet", "Step 6")])
    def test_stop_points(self, stop, step):
        p = live_run.build_prompt("c1", "database/live_runs/run-9", protocol="v2", stop_after=stop)
        assert step in p and "不要往下跑" in p and "關卡 1" in p

    def test_resume_never_hands_landed_json_to_subagents(self, steps):  # A4
        steps.until("issue_sheet")
        plan = live_run.resume_plan(steps.s, "v")
        p = live_run.build_prompt("v", "database/live_runs/run-9", plan, protocol="v2")
        assert "從 SKILL.md Step 7" in p and "legacy-v1.md" not in p
        assert "landed.json 只給你(主 agent)" in p and "不要交給任何 subagent" in p
        assert "role-view --case-id v --role defendant" in p

    def test_landed_json_has_no_argument_text_and_has_the_sheet(self, steps):  # A4
        steps.until("issue_sheet")
        landed = live_run.export_landed(steps.s, "v")
        dumped = json.dumps(landed, ensure_ascii=False)
        assert "哨兵內部檢討" not in dumped
        assert {(a["side"], a["stage"]) for a in landed["arguments"]} == {("plaintiff", 1), ("defendant", 1)}
        assert landed["issue_sheet"]["sheet"] == {"issues": [{"id": "I1"}]}
        assert landed["confirmed_complaint"]["version_id"] == steps.cid

    def test_legacy_landed_json_is_unchanged(self, tmp_path):
        with get_session(f"sqlite:///{tmp_path / 'old.db'}") as s:
            record_case(s, case_id="old", case_type="t", facts_summary="f", claims="c")
            record_argument(s, case_id="old", side="plaintiff", stage=1, position="p", reasoning="舊流程原文")
            landed = live_run.export_landed(s, "old")
        assert landed["arguments"][0]["argument"] == "舊流程原文" and "issue_sheet" not in landed


class TestExclude:  # A5
    def env(self, tmp_path, exclude):
        return {**os.environ, "LEGALDEBATE_DB_URL": f"sqlite:///{tmp_path / 'x.db'}", "PYTHONUTF8": "1",
                live_run.EXCLUDE_ENV: exclude}

    def test_judgment_command_applies_the_server_exclusion(self, tmp_path):
        p = subprocess.run([sys.executable, "main.py", "judgment", "114年度台上字第1987號"], cwd=ROOT,
                           env=self.env(tmp_path, "114年度台上字第1987號"), capture_output=True, encoding="utf-8", timeout=60)
        assert p.returncode != 0 and "excluded" in p.stderr

    def test_rules_text_does_not_reveal_it(self, tmp_path):
        p = subprocess.run([sys.executable, "main.py", "retrieval-rules", "--phase", "p1", "--side", "plaintiff"], cwd=ROOT,
                           env=self.env(tmp_path, "114年度台上字第1987號"), capture_output=True, encoding="utf-8", timeout=60)
        assert p.returncode == 0, p.stderr
        assert "1987" not in p.stdout

    def test_manager_passes_it_to_claude(self, db_url, tmp_path, monkeypatch):  # noqa: F811
        from fastapi.testclient import TestClient
        from server.app import create_app
        monkeypatch.setenv("FAKE_CLAUDE_MODE", "full")
        monkeypatch.setenv("FAKE_CLAUDE_EXPECT_DB_URL", db_url)
        opts = {"enabled": True, "command": [sys.executable, os.path.join(ROOT, "tests", "fake_claude.py")],
                "runs_dir": str(tmp_path / "runs"), "exclude": ["114年度台上字第1987號", "114年度台上字第1547號"]}
        app = create_app(db_url=db_url, cases_dir=str(tmp_path / "none"), seed_on_empty=False,
                         local_clients=("testclient",), live=opts)
        c = TestClient(app, base_url="http://127.0.0.1:8000")
        case_id = create_v2(c)
        done = run(c, case_id, stop_after="complaint")
        assert done["run"]["status"] == "succeeded", done["run"]["error"]
        seen = (run_dir(tmp_path, done) / "exclude_env.txt").read_text(encoding="utf-8")
        assert seen == "114年度台上字第1987號;114年度台上字第1547號"
        prompt = (run_dir(tmp_path, done) / "prompt.txt").read_text(encoding="utf-8")
        assert "1987" not in prompt and "1547" not in prompt  # 不在 prompt 提示模型

    def test_bad_exclusion_is_refused_at_startup(self, tmp_path):
        with pytest.raises(ValueError):
            live_run.LiveRunManager(None, root=ROOT, enabled=False, exclude=["不是字號"])


class TestFakeFullRun:  # 假 Claude 跑完 P0–P6
    def test_full_run_lands_every_step(self, client, db_url, tmp_path):  # noqa: F811
        case_id = create_v2(client)
        done = run(client, case_id)
        assert done["run"]["status"] == "succeeded", done["run"]["error"]
        with get_session(db_url) as s:
            assert {(a.side, a.stage) for a in s.query(DebateArgument).filter_by(case_id=case_id)} == {
                (side, n) for side in ("plaintiff", "defendant") for n in (1, 2, 3)}
            kinds = sorted((r.side, r.pleading_type, r.source or "system")
                           for r in s.query(PleadingDraft).filter_by(case_id=case_id))
            assert kinds == sorted([("plaintiff", "complaint", "system"), ("defendant", "answer", "system"),
                                    ("plaintiff", "brief", "system"), ("defendant", "brief", "system"),
                                    ("plaintiff", "closing", "system"), ("defendant", "closing", "system"),
                                    ("plaintiff", "complaint", "system_revision")])
            assert s.query(IssueSheet).filter_by(case_id=case_id).count() == 1
            assert s.query(Verdict).filter_by(case_id=case_id).one().protocol_version == "v2-pleading-exchange"
        assert stored_gates(db_url, case_id)["complaint"]["by"] == "auto"
        assert client.get(f"/api/cases/{case_id}").json()["resume"]["possible"] is False

    @pytest.mark.parametrize("stop,last_model", [("answer", PleadingDraft), ("issue_sheet", IssueSheet)])
    def test_stop_points_auto_pass_gate_and_stop(self, client, db_url, stop, last_model):  # noqa: F811
        case_id = create_v2(client)
        done = run(client, case_id, stop_after=stop)
        assert done["run"]["status"] == "succeeded", done["run"]["error"]
        assert done["run"]["stop_after"] == stop
        assert stored_gates(db_url, case_id)["complaint"]["by"] == "auto"  # 越過了關卡 1
        with get_session(db_url) as s:
            assert s.query(DebateArgument).filter_by(case_id=case_id, stage=2).count() == 0
            if stop == "answer":
                assert s.query(IssueSheet).filter_by(case_id=case_id).count() == 0
        plan = client.get(f"/api/cases/{case_id}").json()["resume"]
        assert plan["possible"] and plan["from_key"] == ("issue_sheet" if stop == "answer" else "stage2")

    def test_resume_after_answer_finishes(self, client, db_url, tmp_path):  # noqa: F811
        case_id = create_v2(client)
        run(client, case_id, stop_after="answer")
        done = run(client, case_id, resume=True)
        assert done["run"]["status"] == "succeeded", done["run"]["error"]
        assert done["run"]["resume_from"] == "爭點整理表"
        landed = json.loads((run_dir(tmp_path, done) / "landed.json").read_text(encoding="utf-8"))
        assert all("argument" not in a for a in landed["arguments"])
