"""main.py 子指令的行為(以子程序執行，與即時執行時 Claude Code 呼叫的方式相同)。"""
import json
import os
import subprocess
import sys

from database.db import DB_URL_ENV, get_session, record_case

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_main(*args, db_url):
    env = {**os.environ, DB_URL_ENV: db_url, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, "main.py", *args], cwd=ROOT, env=env, capture_output=True,
                          encoding="utf-8", timeout=60)


def test_record_accepts_renamed_argument_field(tmp_path):
    # 範本輸出欄位由 reasoning 改名為 argument(避開 reasoning_extraction 分類器);資料庫欄位不變
    db_url = f"sqlite:///{tmp_path / 'cli.db'}"
    s = get_session(db_url)
    record_case(s, case_id="c1", case_type="買賣價金", facts_summary="事實", claims="請求")
    s.close()
    arg = tmp_path / "s1.json"
    arg.write_text(json.dumps({"case_id": "c1", "side": "defendant", "stage": 1, "position": "p", "argument": "論證理由"},
                              ensure_ascii=False), encoding="utf-8")
    r = run_main("record", "--json", str(arg), db_url=db_url)
    assert r.returncode == 0, r.stderr
    from database.schema import DebateArgument
    s = get_session(db_url)
    assert s.query(DebateArgument).filter_by(case_id="c1").one().reasoning == "論證理由"
    s.close()


def test_verdict_refuses_mixed_dismissal_citation(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'cli.db'}"
    s = get_session(db_url)
    record_case(s, case_id="c1", case_type="撤銷詐害債權", facts_summary="事實", claims="請求")
    s.close()
    v = tmp_path / "verdict.json"
    v.write_text(json.dumps({"verdict_main_text": "原告尚未補正，逾期有被裁定駁回的風險(民事訴訟法第249條第1項;參最高法院115年度台抗字第105號)。",
                             "verdict_analysis": "分析", "risk_map": {}, "mechanical_anchor_json": {}, "citations_used": []},
                            ensure_ascii=False), encoding="utf-8")
    r = run_main("verdict", "--case-id", "c1", "--json", str(v), db_url=db_url)
    assert r.returncode == 1 and r.stderr.startswith("拒絕落地:") and "同一個括號" in r.stderr
    from database.schema import Verdict
    s = get_session(db_url)
    assert s.query(Verdict).count() == 0
    s.close()


def test_duplicate_record_is_refused_without_traceback(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'cli.db'}"
    s = get_session(db_url)
    record_case(s, case_id="c1", case_type="買賣價金", facts_summary="事實", claims="請求")
    s.close()
    arg = tmp_path / "s1.json"
    arg.write_text(json.dumps({"case_id": "c1", "side": "plaintiff", "stage": 1, "position": "p", "reasoning": "r"},
                              ensure_ascii=False), encoding="utf-8")
    first = run_main("record", "--json", str(arg), db_url=db_url)
    assert first.returncode == 0 and first.stdout.startswith("已落地論證 c1 plaintiff stage1")
    # 實測:主 agent 誤把同一階段重跑一次時，原本印出 Python traceback
    again = run_main("record", "--json", str(arg), db_url=db_url)
    assert again.returncode == 1
    assert again.stderr.startswith("拒絕落地:") and "不可覆寫" in again.stderr and "Traceback" not in again.stderr
