"""主 agent 的上下文每輪都重讀:範本、角色檔與分析由程式寫成檔,指令只印路徑,主 agent 不經手全文。"""
import json
import os
import re
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


# v2 範本(docs/zh/live-run-v2.md 第 3 節):每份都能由 main.py prompt 填完，而且寫了審查列出非寫不可的規則
V2_TEMPLATES = {
    "defense_stage1_prompt": (("--phase", "p2", "--side", "defendant"), ("ROLE_VIEW_PATH", "OUTPUT_PATH"),
                              ('"side": "defendant"', '"cited_precedents": []', "只讀這一份角色檔", "【內部檢討】",
                               "若被告能提出 X")),
    "answer_prompt": (("--phase", "p2", "--side", "defendant"), ("ROLE_VIEW_PATH", "ANALYSIS_PATH", "OUTPUT_PATH"),
                      ("一律不能 admit", "`deny` 或 `to_confirm`", "precedent_notes", "legal_basis", "hypothetical",
                       "不得在正文提到")),
    # W5-2、W5-3、W5-4:硬擋規則逐條、準備題格式、第零步看起訴狀程序事項、禁用自承
    "issue_sheet_prompt": (("--phase", "p3"), ("ROLE_VIEW_PATH", "OUTPUT_PATH"),
                           ("準備清單:I1:…", "「官方事實層(<id>):", "四、程序事項", "`admit`", "不得出現「自承」",
                            "`hypothetical` 是 true 或 false", "只讀這一份角色檔")),
    # W6-2、W6-3、W6-7、T11
    "round2_prompt": (("--phase", "p4", "--side", "plaintiff"),
                      ("SIDE", "SIDE_LABEL", "OWN_VIEW_PATH", "EXCHANGE_VIEW_PATH", "OWN_ANALYSIS_PATH", "OUTPUT_PATH"),
                      ('"case_id"', '"stage": 2', '"basis"', "【爭點 I1】", "第一個爭點段落的最後", "受挫評估", "內部檢討段落",
                       "--issue <爭點id>", "falsifier")),
    "opponent_summary_prompt": ((), ("OPPONENT", "OPPONENT_LABEL", "OPPONENT_ARGS_PATH", "OUTPUT_PATH"),
                                ("逐字複製", "strongest_point", "no_clear_claim", '"stage": 2')),
    "round3_prompt": (("--phase", "p5", "--side", "defendant"),
                      ("SIDE", "SIDE_LABEL", "OWN_VIEW_PATH", "EXCHANGE_VIEW_PATH", "OWN_PREVIOUS_PATH", "OWN_ANALYSIS_PATH",
                       "OPPONENT_SUMMARY_PATH", "OUTPUT_PATH"),
                      ('"stage": 3', '"basis"', "【爭點 I1】", "最強論點", "內部檢討段落", "不新增")),
    # W7-1:risk_map 新鍵
    "diagnosis_prompt": (("--phase", "p6"), ("JUDGE_VIEW_PATH", "BRIEF_ARGS_PATH", "CLOSING_ARGS_PATH", "ANCHOR_PATH", "OUTPUT_PATH"),
                         ("issue_assessment", "evidence_todo", "complaint_revisions", "fact_gaps", "opponent_hypotheticals",
                          "不給勝訴機率", "不得放在同一個括號")),
    # W7-5:律師段落
    "revision_prompt": ((), ("ROLE_VIEW_PATH", "ANALYSIS_PATH", "RETRIEVAL_CACHE_DIR", "OUTPUT_PATH"),
                        ("complaint_revisions", "律師在確認版新增", "被告推測的內容不得寫進 v2", "statement_quote", "precedent_notes")),
}


def test_v2_templates_fill_and_carry_the_required_rules(tmp_path):
    for name, (phase, keys, rules) in V2_TEMPLATES.items():
        out = tmp_path / f"{name}.txt"
        sets = [a for k in ("CASE_ID", *keys) for a in ("--set", f"{k}=x/{k.lower()}")]
        case_dir = ("--case-dir", CASE_DIR) if "--side" in phase else ()
        r = run_main("prompt", name, "--out", str(out), *phase, *case_dir, *sets)
        assert r.returncode == 0, (name, r.stderr)
        text = out.read_text(encoding="utf-8")
        assert not re.search(r"\{[A-Z_]+\}", text), name
        missing = [rule for rule in rules if rule not in text]
        assert not missing, (name, missing)


def test_every_v2_template_in_the_run_table_exists():
    """docs/zh/live-run-v2.md 第 3 節的 8 份範本都要有(審查 W4-1、W5-1、W6-2、W7-1、W7-2)。"""
    folder = os.path.join(ROOT, ".claude", "skills", "legal-debate", "templates")
    assert set(V2_TEMPLATES) == {"defense_stage1_prompt", "answer_prompt", "issue_sheet_prompt", "round2_prompt",
                                 "opponent_summary_prompt", "round3_prompt", "diagnosis_prompt", "revision_prompt"}
    assert all(os.path.exists(os.path.join(folder, f"{name}.txt")) for name in V2_TEMPLATES)


def test_skill_steps_match_the_run_table_and_name_existing_templates():
    """server/live_run.py 的步驟表指到的 SKILL.md Step 都要有標題;SKILL 用 `prompt <範本>` 點名的範本都要存在。"""
    from server.live_run import RUN_STEPS_V2
    skill = open(os.path.join(ROOT, ".claude", "skills", "legal-debate", "SKILL.md"), encoding="utf-8").read()
    steps = {step for _, _, doc, step in RUN_STEPS_V2 if doc == "SKILL.md"} | {"Step 10", "Step 11", "Step 13"}
    assert not [s for s in steps if f"### {s} —" not in skill]
    assert "Step 6 以後" not in skill and "Step 4 以後" not in skill  # 過渡段已拿掉
    folder = os.path.join(ROOT, ".claude", "skills", "legal-debate", "templates")
    named = set(re.findall(r"python main\.py prompt (\w+)", skill))
    assert set(V2_TEMPLATES) <= named
    assert not [n for n in named if not os.path.exists(os.path.join(folder, f"{n}.txt"))]
