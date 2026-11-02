"""主 agent 的上下文每輪都重讀:範本、角色檔與分析由程式寫成檔,指令只印路徑,主 agent 不經手全文。"""
import json
import os
import subprocess
import sys

from database.db import DB_URL_ENV, get_session, record_argument, record_case

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASE_DIR = "database/live_runs/case-t"


def run_main(*args, db_url=None):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", **({DB_URL_ENV: db_url} if db_url else {})}
    return subprocess.run([sys.executable, "main.py", *args], cwd=ROOT, env=env, capture_output=True,
                          text=True, encoding="utf-8")


def landed(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'p.db'}"
    s = get_session(db_url)
    record_case(s, case_id="t", case_type="返還借款", facts_summary="原告匯款100萬元予被告。", claims="返還借款",
                protocol="v2", represented_side="plaintiff")
    record_argument(s, case_id="t", side="plaintiff", stage=1, position="請求返還",
                    reasoning="公開論證。【內部檢討】弱點哨兵【內部檢討結束】")
    s.close()
    return db_url


class TestPrompt:
    def test_fills_the_template_and_prints_only_the_path(self, tmp_path):
        out = tmp_path / "prompts" / "p1_analysis.txt"
        r = run_main("prompt", "stage1_prompt", "--out", str(out), "--phase", "p1", "--side", "plaintiff",
                     "--case-dir", CASE_DIR, "--set", "CASE_ID=t", "--set", "ROLE_VIEW_PATH=run/plaintiff_view.json",
                     "--set", "OUTPUT_PATH=run/p1_analysis.json")
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == str(out)
        text = out.read_text(encoding="utf-8")
        assert "{" + "RETRIEVAL_RULES}" not in text and "檢索規則：P1 起訴狀" in text
        assert f"--snapshot {CASE_DIR}/retrieval_cache/plaintiff" in text
        assert "run/p1_analysis.json" in text and "run/plaintiff_view.json" in text

    def test_phase_fills_only_what_the_template_uses(self, tmp_path):
        out = tmp_path / "p1_complaint.txt"
        r = run_main("prompt", "complaint_prompt", "--out", str(out), "--phase", "p1", "--side", "plaintiff",
                     "--case-dir", CASE_DIR, "--set", "CASE_ID=t", "--set", "ROLE_VIEW_PATH=v.json",
                     "--set", "ANALYSIS_PATH=a.json", "--set", "OUTPUT_PATH=run/complaint.json")
        assert r.returncode == 0, r.stderr
        assert f"--log {CASE_DIR}/search_logs/plaintiff_p1.jsonl" in out.read_text(encoding="utf-8")

    def test_unfilled_or_unknown_placeholder_is_refused(self, tmp_path):
        out = tmp_path / "x.txt"
        r = run_main("prompt", "complaint_prompt", "--out", str(out), "--set", "CASE_ID=t")
        assert r.returncode == 2 and "ROLE_VIEW_PATH" in r.stderr and not out.exists()
        r = run_main("prompt", "complaint_prompt", "--out", str(out), "--set", "CASE_ID=t", "--set", "TYPO=x")
        assert r.returncode == 2 and "TYPO" in r.stderr and not out.exists()


class TestOut:
    def test_role_view_and_public_args_write_files(self, tmp_path):
        db_url = landed(tmp_path)
        view, analysis = tmp_path / "plaintiff_view.json", tmp_path / "plaintiff_analysis.json"
        r = run_main("role-view", "--case-id", "t", "--role", "plaintiff", "--out", str(view), db_url=db_url)
        assert r.returncode == 0 and r.stdout.strip() == str(view)
        assert json.loads(view.read_text(encoding="utf-8"))["case"]["case_id"] == "t"
        r = run_main("public-args", "--case-id", "t", "--through-stage", "1", "--out", str(analysis), db_url=db_url)
        assert r.returncode == 0 and r.stdout.strip() == str(analysis)
        args = json.loads(analysis.read_text(encoding="utf-8"))["arguments"]
        assert args[0]["argument"] == "公開論證。" and "弱點哨兵" not in analysis.read_text(encoding="utf-8")
