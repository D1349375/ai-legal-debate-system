"""即時執行(server/live_run.py)的測試。

不呼叫真的 Claude Code:以 tests/fake_claude.py 模擬 `claude -p --output-format stream-json` 的輸出，
並把內容寫進後端交給子程序的同一顆暫存資料庫。真實執行(2026-10-28 實測約 11 分鐘、估算 2.5 美元)不在自動測試範圍。
"""
import os
import sys

import pytest
from fastapi.testclient import TestClient

from database.db import get_session, make_session_factory, record_argument, record_case, record_pleading
from database.schema import LiveRun
from server import live_run
from server.app import create_app

FAKE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_claude.py")
LOCAL = "http://127.0.0.1:8000"
CASE = {"case_type": "買賣價金", "facts_summary": "原告於115年1月出賣貨物予被告，被告迄未給付價金。",
        "claims": "被告應給付原告新臺幣50萬元。",
        "plaintiff": {"name": "甲公司", "ban": "22099131"}, "defendant": {"name": "乙"}}


@pytest.fixture
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path / 'live.db'}"
    s = get_session(url)
    record_case(s, case_id="rec1", case_type="錄製", facts_summary="錄製案件事實", claims="請求")
    record_argument(s, case_id="rec1", side="plaintiff", stage=1, position="p", reasoning="r")
    s.close()
    return url


def make_client(db_url, tmp_path, monkeypatch, mode="full", enabled=True, **live):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    opts = {"enabled": enabled, "command": [sys.executable, FAKE], "runs_dir": str(tmp_path / "runs"), **live}
    app = create_app(db_url=db_url, cases_dir=str(tmp_path / "none"), seed_on_empty=False,
                     local_clients=("testclient",), live=opts)
    return TestClient(app, base_url=LOCAL)


def create(client, **over):
    r = client.post("/api/cases", json={**CASE, **over})
    assert r.status_code == 201, r.text
    return r.json()["case_id"]


def run_to_end(client, case_id):
    r = client.post(f"/api/cases/{case_id}/runs")
    assert r.status_code == 201, r.text
    run_id = r.json()["run"]["id"]
    client.app.state.live.wait(run_id, timeout=60)
    return client.get(f"/api/runs/{run_id}").json()


class TestLiveRun:
    def test_disabled_by_default_with_reason(self, db_url, tmp_path, monkeypatch):
        c = make_client(db_url, tmp_path, monkeypatch, enabled=False, reason="以 --host 0.0.0.0 啟動")
        h = c.get("/api/health").json()["live_generation"]
        assert h["enabled"] is False and "0.0.0.0" in h["reason"]
        case_id = create(c)
        r = c.post(f"/api/cases/{case_id}/runs")
        assert r.status_code == 403 and "0.0.0.0" in r.json()["detail"]

    def test_full_run_lands_everything_and_is_labelled_live(self, db_url, tmp_path, monkeypatch):
        c = make_client(db_url, tmp_path, monkeypatch)
        case_id = create(c)
        r = run_to_end(c, case_id)
        assert r["run"]["status"] == "succeeded" and r["run"]["error"] is None
        assert r["run"]["cost_usd"] == 3.21 and r["active"] is False
        kinds = [e["kind"] for e in r["events"]]
        assert "landed" in kinds and "result" in kinds
        texts = [e["text"] for e in r["events"]]
        # 讀到 main.py 原始碼不算落地;多筆 result 只摘要一次，權限拒絕跨輪加總
        assert not any("print(" in t for t in texts if t)
        assert sum(1 for e in r["events"] if e["text"].startswith("Claude Code 回報完成")) == 1
        assert any("共 2 輪" in t for t in texts) and any("1 次工具呼叫因權限不足被拒" in t for t in texts)
        assert "全部完成" in texts and "Stage 1 已派出，等待完成" not in texts
        d = c.get(f"/api/cases/{case_id}").json()
        assert d["provenance"]["kind"] == "live_generated"
        assert {a["origin"]["kind"] for a in d["arguments"]} == {"live"}
        assert d["verdict"]["origin"] == {"kind": "live", "run_id": r["run"]["id"], "run_status": "succeeded"}
        assert d["pleading"]["origin"]["kind"] == "live"
        assert d["pleadings"]["defendant"]["origin"]["kind"] == "live"  # 完整流程同時產出起訴狀與答辯狀
        assert d["arguments"][0]["model_id"] == "claude-sonnet-5-5"  # 子程序收到 CLAUDE_CODE_SUBAGENT_MODEL
        # 錄製案件不受影響
        assert c.get("/api/cases/rec1").json()["provenance"]["kind"] == "recorded_replay"
        listed = {x["case_id"]: x for x in c.get("/api/cases").json()["cases"]}
        assert listed[case_id]["last_run_status"] == "succeeded" and listed["rec1"]["last_run_status"] is None
        # 結束後的事件照原序號與時間，含啟動與結論兩則(stream-json 沒有)
        assert [e["seq"] for e in r["events"]] == list(range(1, r["event_count"] + 1))
        assert all(e["at"] for e in r["events"])
        assert r["events"][0]["text"].startswith("已啟動執行") and r["events"][-1]["text"].startswith("執行完成")
        # 執行紀錄存檔：重新啟動後仍看得到同樣的過程
        run_dir = tmp_path / "runs" / f"run-{r['run']['id']}"
        assert os.path.isfile(run_dir / "stream.jsonl")
        c2 = make_client(db_url, tmp_path, monkeypatch)
        again = c2.get(f"/api/runs/{r['run']['id']}").json()
        assert again["events"] == r["events"] and again["event_count"] == r["event_count"]
        assert c2.get(f"/api/runs/{r['run']['id']}?since=3").json()["events"][0]["seq"] == 4
        # 沒有事件摘要檔的舊執行：從 stream-json 重建(沒有時間),result 一樣只摘要一次
        os.remove(run_dir / "events.jsonl")
        old = c2.get(f"/api/runs/{r['run']['id']}").json()
        assert any(e["kind"] == "landed" for e in old["events"]) and old["events"][0]["at"] is None
        assert sum(1 for e in old["events"] if e["kind"] == "result") == 1
        assert any("1 次工具呼叫因權限不足被拒" in e["text"] for e in old["events"])

    def test_cannot_rerun_case_with_landed_records(self, db_url, tmp_path, monkeypatch):
        c = make_client(db_url, tmp_path, monkeypatch)
        r = c.post("/api/cases/rec1/runs")
        assert r.status_code == 409 and "不可覆寫" in r.json()["detail"]
        assert c.post("/api/cases/nope/runs").status_code == 409

    def test_incomplete_run_is_not_reported_as_success(self, db_url, tmp_path, monkeypatch):
        c = make_client(db_url, tmp_path, monkeypatch, mode="partial")
        r = run_to_end(c, create(c))
        assert r["run"]["status"] == "incomplete"
        assert "原告 Stage 2" in r["run"]["error"] and "起訴狀骨架" in r["run"]["error"] and "答辯狀骨架" in r["run"]["error"]

    def test_budget_stop_is_reported(self, db_url, tmp_path, monkeypatch):
        c = make_client(db_url, tmp_path, monkeypatch, mode="budget")
        r = run_to_end(c, create(c))
        assert r["run"]["status"] == "failed" and "花費上限" in r["run"]["error"]
        assert r["run"]["cost_usd"] == 15.02 and r["run"]["exit_code"] == 1

    def test_api_error_with_success_subtype_is_failure(self, db_url, tmp_path, monkeypatch):
        c = make_client(db_url, tmp_path, monkeypatch, mode="api_error")
        r = run_to_end(c, create(c))
        assert r["run"]["status"] == "failed" and "OAuth session expired" in r["run"]["error"]

    def test_not_logged_in_refuses_before_starting(self, db_url, tmp_path, monkeypatch):
        monkeypatch.setenv("FAKE_CLAUDE_AUTH", "0")
        c = make_client(db_url, tmp_path, monkeypatch)
        case_id = create(c)
        r = c.post(f"/api/cases/{case_id}/runs")
        assert r.status_code == 403 and "尚未登入" in r.json()["detail"]
        assert c.get(f"/api/cases/{case_id}").json()["live_runs"] == []  # 沒有留下假的執行紀錄
        auth = c.get("/api/health").json()["live_generation"]["auth"]
        assert auth["checked"] is True and auth["logged_in"] is False

    def test_crash_reports_exit_code_and_stderr(self, db_url, tmp_path, monkeypatch):
        c = make_client(db_url, tmp_path, monkeypatch, mode="crash")
        r = run_to_end(c, create(c))
        assert r["run"]["status"] == "failed"
        assert "結束碼 3" in r["run"]["error"] and "fake crash" in r["run"]["error"]

    def test_one_run_at_a_time_and_cancel(self, db_url, tmp_path, monkeypatch):
        c = make_client(db_url, tmp_path, monkeypatch, mode="hang")
        first, second = create(c), create(c)
        r = c.post(f"/api/cases/{first}/runs")
        run_id = r.json()["run"]["id"]
        assert r.json()["active"] is True
        busy = c.post(f"/api/cases/{second}/runs")
        assert busy.status_code == 409 and "進行中" in busy.json()["detail"]
        assert c.get("/api/health").json()["live_generation"]["active_run"]["id"] == run_id
        done = c.post(f"/api/runs/{run_id}/cancel").json()
        assert done["run"]["status"] == "cancelled" and "取消" in done["run"]["error"]
        assert c.post(f"/api/runs/{run_id}/cancel").status_code == 409
        assert c.get("/api/health").json()["live_generation"]["active_run"] is None

    def test_timeout_kills_run(self, db_url, tmp_path, monkeypatch):
        c = make_client(db_url, tmp_path, monkeypatch, mode="hang", max_minutes=0.02)
        r = run_to_end(c, create(c))
        assert r["run"]["status"] == "failed" and "超過" in r["run"]["error"]

    def test_safety_stop_and_quota_are_recorded(self, db_url, tmp_path, monkeypatch):
        monkeypatch.setenv("FAKE_CLAUDE_SAFETY", "1")
        monkeypatch.setenv("FAKE_CLAUDE_QUOTA", "1")
        c = make_client(db_url, tmp_path, monkeypatch)
        case_id = create(c)
        r = run_to_end(c, case_id)
        run = r["run"]
        assert run["status"] == "succeeded" and run["error"] is None  # 重派成功就算完成，但要記下被中止過
        assert [s["who"] for s in run["safety_stops"]] == ["subagent「被告 Stage 1」"]
        assert run["quota"]["seven_day"] == {"start": 0.93, "end": 0.95, "resets_at": "2026-11-01T16:00:00Z"}
        assert run["quota"]["five_hour"]["start"] == 0 and run["quota"]["five_hour"]["end"] == 0.27
        warns = [e["text"] for e in r["events"] if e["kind"] == "warn"]
        assert any("被告 Stage 1" in t and "安全分類器中止" in t for t in warns)
        assert any("1 次回覆被安全分類器中止" in t for t in warns)
        # 案件明細與開始前的額度提醒
        assert c.get(f"/api/cases/{case_id}").json()["live_runs"][0]["safety_stops"] == run["safety_stops"]
        q = c.get("/api/health").json()["live_generation"]["quota"]
        assert q["run_id"] == run["id"] and q["windows"]["seven_day"]["end"] == 0.95

    def test_incomplete_run_names_safety_stop_as_likely_cause(self, db_url, tmp_path, monkeypatch):
        monkeypatch.setenv("FAKE_CLAUDE_SAFETY", "1")
        c = make_client(db_url, tmp_path, monkeypatch, mode="partial")
        r = run_to_end(c, create(c))
        assert r["run"]["status"] == "incomplete"
        assert "安全分類器中止" in r["run"]["error"] and "被告 Stage 1" in r["run"]["error"]
        assert r["run"]["quota"] is None  # 沒有額度事件(例如 API 金鑰登入)時不臆測

    def test_failed_run_with_known_cause_only_notes_safety_stop(self, db_url, tmp_path, monkeypatch):
        monkeypatch.setenv("FAKE_CLAUDE_SAFETY", "1")
        monkeypatch.setenv("FAKE_CLAUDE_STOP_AFTER_S1", "budget")
        c = make_client(db_url, tmp_path, monkeypatch)
        r = run_to_end(c, create(c))
        err = r["run"]["error"]
        assert r["run"]["status"] == "failed" and "花費上限" in err
        assert "另外，執行期間有 1 次回覆被 Anthropic 安全分類器中止" in err and "很可能" not in err

    def test_old_runs_are_backfilled_from_stream_log(self, db_url, tmp_path, monkeypatch):
        monkeypatch.setenv("FAKE_CLAUDE_SAFETY", "1")
        c = make_client(db_url, tmp_path, monkeypatch)
        run_id = run_to_end(c, create(c))["run"]["id"]
        factory = make_session_factory(db_url)
        with factory() as s:  # 模擬 notes_json 欄位加入前結束的執行
            s.get(LiveRun, run_id).notes_json = None
            s.commit()
        c2 = make_client(db_url, tmp_path, monkeypatch)
        assert len(c2.get(f"/api/runs/{run_id}").json()["run"]["safety_stops"]) == 1

    def test_stale_running_rows_become_interrupted(self, db_url, tmp_path, monkeypatch):
        factory = make_session_factory(db_url)
        with factory() as s:
            s.add(LiveRun(case_id="rec1", status="running", started_at="2026-10-28T00:00:00Z"))
            s.commit()
        c = make_client(db_url, tmp_path, monkeypatch)
        runs = c.get("/api/cases/rec1").json()["live_runs"]
        assert runs[0]["status"] == "interrupted" and "重新啟動" in runs[0]["error"]


class TestCommandAndStream:
    def test_serve_enables_live_runs_only_on_loopback(self):
        assert live_run.options_for_host("127.0.0.1") == {"enabled": True, "model": "claude-sonnet-5-5", "budget_usd": 15.0}
        assert live_run.options_for_host("localhost", budget_usd=5)["budget_usd"] == 5
        off = live_run.options_for_host("0.0.0.0")
        assert off["enabled"] is False and "0.0.0.0" in off["reason"]

    def test_minimal_permissions(self):
        args = live_run.build_args(["claude"], "x", model="claude-sonnet-5-5", budget_usd=15)
        assert args[args.index("--permission-mode") + 1] == "dontAsk"
        assert "bypassPermissions" not in args and "--dangerously-skip-permissions" not in args
        allowed = args[args.index("--allowedTools") + 1:args.index("--disallowedTools")]
        assert allowed == list(live_run.ALLOWED_TOOLS)
        assert "Bash(python main.py *)" in allowed and not any(a == "Bash" or a == "Write" for a in allowed)
        assert args[args.index("--max-budget-usd") + 1] == "15"

    def test_answer_prompt_runs_only_step_9c(self):
        p = live_run.build_answer_prompt("test-2026-10-27-gcis-001", "database/live_runs/run-9")
        assert p.startswith("/legal-debate test-2026-10-27-gcis-001") and "Step 9C" in p
        assert "pleading-source --case-id test-2026-10-27-gcis-001 --side defendant" in p and "--side defendant" in p
        assert "不要執行 `python main.py case`、`record`、`finalize`、`verdict`" in p

    def test_prompt_pins_case_and_run_dir(self):
        p = live_run.build_prompt("ui-20261028-001", "database/live_runs/run-7")
        assert p.startswith("/legal-debate ui-20261028-001")
        assert "database/live_runs/run-7/case.json" in p and "不要再執行 `python main.py case`" in p

    def test_summarize_events(self):
        tool = {"type": "assistant", "parent_tool_use_id": "x", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "python main.py record --json a.json"}}]}}
        assert live_run.summarize_event(tool) == [
            {"kind": "tool", "text": "執行指令:python main.py record --json a.json", "subagent": True}]
        rejected = {"type": "user", "message": {"content": [
            {"type": "tool_result", "content": [{"type": "text", "text": "拒絕落地:以下引用尚未查證"}], "is_error": True}]}}
        assert live_run.summarize_event(rejected)[0]["kind"] == "error"
        # 實測:讀到 main.py 原始碼(含「拒絕落地」字樣)曾被誤判為錯誤
        read_source = {"type": "user", "message": {"content": [
            {"type": "tool_result", "content": [{"type": "text", "text": 'print(f"拒絕落地:{e}", file=sys.stderr)'}]}]}}
        assert live_run.summarize_event(read_source) == []
        read_landed_source = {"type": "user", "message": {"content": [
            {"type": "tool_result", "content": '    60\t    print(f"已落地論證 {row.case_id}")'}]}}
        assert live_run.summarize_event(read_landed_source) == []
        ok = {"type": "user", "message": {"content": [
            {"type": "tool_result", "content": "已落地論證 c1 plaintiff stage1\n已落地論證 c1 defendant stage1"}]}}
        assert live_run.summarize_event(ok)[0]["kind"] == "landed"
        res = live_run.summarize_event({"type": "result", "subtype": "error_max_turns", "is_error": True,
                                        "total_cost_usd": 2, "permission_denials": [{}, {}]})
        assert "回合上限" in res[0]["text"] and "2 次" in res[-1]["text"]
        assert live_run.summarize_event({"type": "stream_event"}) == []
        # 實測(2026-10-29 執行 #4):分類器中止只以合成 user 訊息出現在 stream-json
        stop = {"type": "user", "parent_tool_use_id": "t1", "task_description": "被告 Stage 1", "message": {"content": [
            {"type": "text", "text": "Your response above was stopped by a safety classifier — this is not a tool or API error."}]}}
        ev = live_run.summarize_event(stop)
        assert ev[0]["kind"] == "warn" and "subagent「被告 Stage 1」" in ev[0]["text"] and ev[0]["subagent"] is True
        assert live_run.safety_stop_task({**stop, "parent_tool_use_id": None}) == "主 agent"
        assert live_run.safety_stop_task({"type": "user", "message": {"content": [{"type": "text", "text": "hi"}]}}) is None
        assert live_run.safety_stop_task({"type": "user", "message": {"content": [{"type": "text", "text": None}]}}) is None

    def test_quota_windows_merge_and_bad_notes(self):
        obs = live_run.StreamObserver()
        both = {"five_hour": {"utilization": 0.1, "resetsAt": 1793269800}, "seven_day": {"utilization": 0.9, "resetsAt": 1793548800}}
        obs.feed({"type": "rate_limit_event", "rate_limit_info": {"unifiedWindows": both}})
        obs.feed({"type": "rate_limit_event", "rate_limit_info": {"unifiedWindows": {"five_hour": {"utilization": 0.3}}}})
        q = obs.to_dict()["quota"]
        assert q["five_hour"]["start"] == 0.1 and q["five_hour"]["end"] == 0.3
        assert q["seven_day"] == {"start": 0.9, "end": 0.9, "resets_at": "2026-11-01T16:00:00Z"}  # 少了的視窗保留舊值
        # 舊格式(2026-10-28 執行 #1:沒有 unifiedWindows)不臆測
        old = live_run.StreamObserver()
        old.feed({"type": "rate_limit_event", "rate_limit_info": {"rateLimitType": "five_hour", "utilization": 0.5}})
        assert old.to_dict()["quota"] is None
        # notes_json 是合法 JSON 但不是物件時不讓 API 掛掉
        row = LiveRun(id=1, case_id="c", status="succeeded", started_at="x", notes_json="[]")
        d = live_run.run_to_dict(row)
        assert d["safety_stops"] == [] and d["quota"] is None

    def test_usage_limit_is_explained(self):
        # 2026-10-28 Pro 訂閱實跑時的 result 事件(節錄)
        limit = {"type": "result", "subtype": "success", "is_error": True, "api_error_status": 429,
                 "terminal_reason": "api_error", "result": "You've hit your session limit · resets 7pm (Asia/Taipei)"}
        text = live_run.result_error(limit)
        assert "用量上限" in text and "resets 7pm" in text and "建立新案件" in text
        assert "用量上限" not in live_run.result_error({**limit, "api_error_status": 401, "result": "OAuth session expired"})

    def test_claude_cmd_wrapper_is_not_called_directly(self, tmp_path, monkeypatch):
        cmd = tmp_path / "claude.cmd"
        cmd.write_text("@echo off")
        monkeypatch.delenv("LEGALDEBATE_CLAUDE_BIN", raising=False)
        monkeypatch.setattr(live_run.shutil, "which", lambda name: str(cmd))
        prefix, reason = live_run.resolve_claude_command()
        assert prefix is None and "claude.exe" in reason
        exe = tmp_path / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        assert live_run.resolve_claude_command() == ([str(exe)], None)
        monkeypatch.setattr(live_run.shutil, "which", lambda name: None)
        assert live_run.resolve_claude_command()[0] is None


def land_debated_case(db_url, case_id="done1"):
    """已跑完攻防、只有原告起訴狀的既有案件(2026-10-29 前跑完的案件都是如此)。"""
    s = get_session(db_url)
    record_case(s, case_id=case_id, case_type="消費借貸", facts_summary="事實", claims="請求")
    for side in ("plaintiff", "defendant"):
        record_argument(s, case_id=case_id, side=side, stage=3, position=f"{side} s3", reasoning="r", falsifier="f")
    record_pleading(s, case_id=case_id, draft_text="民事起訴狀", citations_used=[])
    s.close()
    return case_id


class TestAnswerRun:
    def start(self, client, case_id):
        return client.post(f"/api/cases/{case_id}/runs", json={"kind": "answer"})

    def test_answer_run_lands_only_the_answer(self, db_url, tmp_path, monkeypatch):
        case_id = land_debated_case(db_url)
        c = make_client(db_url, tmp_path, monkeypatch)
        assert c.post(f"/api/cases/{case_id}/runs").status_code == 409  # 完整流程仍不能重跑
        r = self.start(c, case_id)
        assert r.status_code == 201, r.text
        run_id = r.json()["run"]["id"]
        assert r.json()["run"]["kind"] == "answer"
        c.app.state.live.wait(run_id, timeout=60)
        done = c.get(f"/api/runs/{run_id}").json()
        assert done["run"]["status"] == "succeeded", done["run"]["error"]
        assert done["events"][0]["text"].startswith("已啟動執行 #%d(只產答辯狀" % run_id)
        assert done["events"][-1]["text"] == "執行完成，答辯狀骨架已落地資料庫"
        d = c.get(f"/api/cases/{case_id}").json()
        assert d["pleadings"]["defendant"]["origin"] == {"kind": "live", "run_id": run_id, "run_status": "succeeded"}
        assert d["pleadings"]["plaintiff"]["origin"]["kind"] == "recorded"  # 既有起訴狀不動
        assert len(d["arguments"]) == 2
        again = self.start(c, case_id)
        assert again.status_code == 409 and "已有答辯狀骨架" in again.json()["detail"]

    def test_answer_run_requires_defendant_stage3(self, db_url, tmp_path, monkeypatch):
        c = make_client(db_url, tmp_path, monkeypatch)
        r = self.start(c, "rec1")
        assert r.status_code == 409 and "還沒有被告 Stage 3" in r.json()["detail"]
        assert self.start(c, "nope").status_code == 409
        assert c.post("/api/cases/rec1/runs", json={"kind": "other"}).status_code == 422

    def test_answer_run_without_landing_is_incomplete(self, db_url, tmp_path, monkeypatch):
        case_id = land_debated_case(db_url)
        c = make_client(db_url, tmp_path, monkeypatch, mode="partial")
        run_id = self.start(c, case_id).json()["run"]["id"]
        c.app.state.live.wait(run_id, timeout=60)
        run = c.get(f"/api/runs/{run_id}").json()["run"]
        assert run["status"] == "incomplete" and run["error"] == "Claude Code 回報完成，但資料庫仍缺:答辯狀骨架"
