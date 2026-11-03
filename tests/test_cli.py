"""main.py 子指令的行為(以子程序執行，與即時執行時 Claude Code 呼叫的方式相同)。"""
import json
import os
import subprocess
import sys

from database.db import DB_URL_ENV, finalize_case, get_session, record_argument, record_case
from database.schema import CourtQuestion, Verdict

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
                             "verdict_analysis": "分析", "risk_map": {}, "citations_used": []},
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


class TestVerdictMechanicalAnchor:
    def _ready_case(self, tmp_path):
        db_url = f"sqlite:///{tmp_path / 'cli.db'}"
        s = get_session(db_url)
        record_case(s, case_id="c1", case_type="買賣價金", facts_summary="事實", claims="請求")
        for side in ("plaintiff", "defendant"):
            record_argument(s, case_id="c1", side=side, stage=1, position="立場", reasoning="第一階段論證")
            record_argument(s, case_id="c1", side=side, stage=3, position="立場", reasoning=f"{side} 第三階段完整論證",
                            falsifier="若有新證據則讓步")
        anchor = finalize_case(s, case_id="c1")
        s.close()
        return db_url, anchor

    def _verdict(self, tmp_path, db_url, extra=None):
        payload = {"verdict_main_text": "主文", "verdict_analysis": "理由", "risk_map": {}, "citations_used": []}
        if extra is not None:
            payload["mechanical_anchor_json"] = extra
        path = tmp_path / "verdict.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return run_main("verdict", "--case-id", "c1", "--json", str(path), db_url=db_url)

    def _stored(self, db_url):
        s = get_session(db_url)
        row = s.query(Verdict).filter_by(case_id="c1").one()
        anchor = json.loads(row.mechanical_anchor_json)
        s.close()
        return anchor

    def test_payload_without_anchor_stores_recomputed_value(self, tmp_path):
        db_url, expected = self._ready_case(tmp_path)
        result = self._verdict(tmp_path, db_url)
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""
        assert self._stored(db_url) == expected

    def test_attribution_warnings_do_not_block_record_or_verdict(self, tmp_path):
        db_url, _ = self._ready_case(tmp_path)
        question = tmp_path / "question.json"
        question.write_text(json.dumps({"case_id": "c1", "target_side": "defendant",
            "question_text": "被告承認沒有原句。", "based_on": "被告 Stage 1 主張"}, ensure_ascii=False), encoding="utf-8")
        recorded = run_main("record", "--json", str(question), db_url=db_url)
        assert recorded.returncode == 0 and "轉述警告" in recorded.stderr
        verdict = tmp_path / "verdict-warning.json"
        verdict.write_text(json.dumps({"verdict_main_text": "主文", "verdict_analysis":
            "原告民法第184條降為純備位,並承認受民法第197條時效風險壓制。",
            "risk_map": {}, "citations_used": []}, ensure_ascii=False), encoding="utf-8")
        landed = run_main("verdict", "--case-id", "c1", "--json", str(verdict), db_url=db_url)
        assert landed.returncode == 0 and "轉述警告" in landed.stderr
        assert self._stored(db_url)

    def test_changed_payload_anchor_warns_and_stores_recomputed_value(self, tmp_path):
        db_url, expected = self._ready_case(tmp_path)
        altered = json.loads(json.dumps(expected))
        altered["weak_points"][0]["response_excerpt"] = "從略"
        result = self._verdict(tmp_path, db_url, altered)
        assert result.returncode == 0, result.stderr
        assert "警告:" in result.stderr and "機械彙整" in result.stderr
        assert self._stored(db_url) == expected

    def test_matching_payload_anchor_does_not_warn(self, tmp_path):
        db_url, expected = self._ready_case(tmp_path)
        result = self._verdict(tmp_path, db_url, expected)
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""
        assert self._stored(db_url) == expected

    def test_incomplete_stage3_is_refused(self, tmp_path):
        db_url = _case_with_stage1(tmp_path)
        result = self._verdict(tmp_path, db_url)
        assert result.returncode == 1 and "拒絕落地:" in result.stderr and "stage3" in result.stderr
        s = get_session(db_url)
        assert s.query(Verdict).count() == 0
        s.close()


def _case_with_stage1(tmp_path, facts="事實"):
    db_url = f"sqlite:///{tmp_path / 'cli.db'}"
    s = get_session(db_url)
    record_case(s, case_id="c1", case_type="買賣價金", facts_summary=facts, claims="請求")
    for side, text in (("plaintiff", "原告已交付全部貨物。"), ("defendant", "被告未在送貨單記載異議。這是本案最大弱點。")):
        record_argument(s, case_id="c1", side=side, stage=1, position="立場", reasoning=text)
    s.close()
    return db_url


def _question_rows(db_url):
    s = get_session(db_url)
    rows = s.query(CourtQuestion).filter_by(case_id="c1").all()
    s.close()
    return rows


def _record_question(tmp_path, db_url, text, target="defendant", based_on="被告 Stage1 主張"):
    q = tmp_path / "q.json"
    q.write_text(json.dumps({"case_id": "c1", "question_text": text, "target_side": target, "based_on": based_on},
                            ensure_ascii=False), encoding="utf-8")
    return run_main("record", "--json", str(q), db_url=db_url)


class TestAdmissionGate:
    def test_question_without_quote_is_refused(self, tmp_path):
        db_url = _case_with_stage1(tmp_path)
        r = _record_question(tmp_path, db_url, "被告已自認沒有行車紀錄器,請說明。")
        assert r.returncode == 1 and r.stderr.startswith("拒絕落地:") and "沒有緊接引述" in r.stderr
        assert _question_rows(db_url) == []

    def test_question_quoting_self_assessment_is_refused(self, tmp_path):
        db_url = _case_with_stage1(tmp_path)
        assert _record_question(tmp_path, db_url, "被告自承「這是本案最大弱點」,請說明。").returncode == 1

    def test_question_quoting_a_real_statement_lands(self, tmp_path):
        db_url = _case_with_stage1(tmp_path)
        r = _record_question(tmp_path, db_url, "被告自承「未在送貨單記載異議」,此是否構成通知?")
        assert r.returncode == 0, r.stderr
        assert len(_question_rows(db_url)) == 1

    def test_official_issue_follow_up_still_lands(self, tmp_path):
        # 商業組示範主軸:補正追問帶 plaintiff:dissolved 這種事項 id,不能被擋
        db_url = _case_with_stage1(tmp_path)
        r = _record_question(tmp_path, db_url, "程序補正(plaintiff:dissolved)僅列清算人待查明,請補提清算人就任聲報。",
                             target="plaintiff", based_on="官方事實層(plaintiff:dissolved):原告補正不足")
        assert r.returncode == 0, r.stderr
        assert _question_rows(db_url)[0].based_on.startswith("官方事實層(plaintiff:dissolved)")

    def test_verdict_with_admission_in_risk_map_is_refused(self, tmp_path):
        db_url = _case_with_stage1(tmp_path)
        v = tmp_path / "verdict.json"
        v.write_text(json.dumps({"verdict_main_text": "結論", "verdict_analysis": "分析",
                                 "risk_map": {"對被告不利之處": ["被告已自認欠缺客觀證據"]},
                                 "citations_used": []}, ensure_ascii=False), encoding="utf-8")
        r = run_main("verdict", "--case-id", "c1", "--json", str(v), db_url=db_url)
        assert r.returncode == 1 and "沒有緊接引述" in r.stderr


class TestFactualQuestionWarning:
    def test_factual_question_to_defendant_warns_but_lands(self, tmp_path):
        db_url = _case_with_stage1(tmp_path)
        r = _record_question(tmp_path, db_url, "被告是否持有行車紀錄器?")
        assert r.returncode == 0 and "準備題" in r.stderr
        assert len(_question_rows(db_url)) == 1

    def test_legal_question_and_prep_question_do_not_warn(self, tmp_path):
        db_url = _case_with_stage1(tmp_path)
        assert _record_question(tmp_path, db_url, "依案件所載的 email,是否已足以特定瑕疵?").stderr == ""
        r = _record_question(tmp_path, db_url, "對方可能提出行車紀錄器(假設,尚未發生),你方要如何準備?",
                             target="plaintiff", based_on="準備清單:原告主張完全停等")
        assert r.returncode == 0 and r.stderr == ""


class TestCheckJudge:
    def _check(self, tmp_path, db_url, payload):
        f = tmp_path / "judge.json"
        f.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return run_main("check-judge", "--case-id", "c1", "--json", str(f), db_url=db_url)

    def test_any_bad_question_fails_the_batch_and_lands_nothing(self, tmp_path):
        db_url = _case_with_stage1(tmp_path)
        r = self._check(tmp_path, db_url, {"uncontested_points": [], "questions": [
            {"question_text": "依案件所載,此要件應由誰舉證?", "target_side": "defendant", "based_on": "被告主張"},
            {"question_text": "被告已自認沒有證據,請說明。", "target_side": "defendant", "based_on": "被告主張"}]})
        assert r.returncode == 1 and "第 2 則" in r.stderr and "第 1 則" not in r.stderr
        assert _question_rows(db_url) == []

    def test_clean_questions_and_verdict_pass(self, tmp_path):
        db_url = _case_with_stage1(tmp_path)
        assert self._check(tmp_path, db_url, {"questions": [
            {"question_text": "依案件所載,此要件應由誰舉證?", "target_side": "defendant", "based_on": "被告主張"}]}).returncode == 0
        assert self._check(tmp_path, db_url, {"verdict_main_text": "結論", "verdict_analysis": "分析", "risk_map": {}}).returncode == 0

    def test_bad_verdict_fails(self, tmp_path):
        db_url = _case_with_stage1(tmp_path)
        r = self._check(tmp_path, db_url, {"verdict_main_text": "結論", "verdict_analysis": "被告坦承欠缺證據。", "risk_map": {}})
        assert r.returncode == 1 and "沒有緊接引述" in r.stderr

    def test_attribution_warning_does_not_fail_check(self, tmp_path):
        db_url = _case_with_stage1(tmp_path)
        r = self._check(tmp_path, db_url, {"verdict_main_text": "結論", "verdict_analysis":
            "原告民法第184條降為純備位,並承認受民法第197條時效風險壓制。", "risk_map": {}})
        assert r.returncode == 0
        assert "轉述警告" in r.stderr and "不要退回" in r.stderr

    def test_missing_based_on_is_left_to_record(self, tmp_path):
        # 缺 based_on 由 record 原本的檢查處理;轉述核對不能因此讓 check-judge 當掉
        db_url = _case_with_stage1(tmp_path)
        r = self._check(tmp_path, db_url, {"questions": [
            {"question_text": "依案件所載,此要件應由誰舉證?", "target_side": "defendant"}]})
        assert r.returncode == 0 and "Traceback" not in r.stderr


def test_argument_with_unquoted_admission_warns_but_lands(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'cli.db'}"
    s = get_session(db_url)
    record_case(s, case_id="c1", case_type="買賣價金", facts_summary="事實", claims="請求")
    s.close()
    arg = tmp_path / "s1.json"
    arg.write_text(json.dumps({"case_id": "c1", "side": "plaintiff", "stage": 1, "position": "p",
                               "argument": "被告已自認沒有證據。"}, ensure_ascii=False), encoding="utf-8")
    r = run_main("record", "--json", str(arg), db_url=db_url)
    assert r.returncode == 0 and "警告" in r.stderr


def test_finalize_for_judge_leaves_out_drift_and_excerpts(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'cli.db'}"
    s = get_session(db_url)
    record_case(s, case_id="c1", case_type="買賣價金", facts_summary="事實", claims="請求")
    for side in ("plaintiff", "defendant"):
        record_argument(s, case_id="c1", side=side, stage=1, position="p", reasoning="r")
        record_argument(s, case_id="c1", side=side, stage=3, position="p", reasoning="論證全文", falsifier=f"{side} 的條件")
    s.close()
    r = run_main("finalize", "--for-judge", "--case-id", "c1", db_url=db_url)
    assert r.returncode == 0, r.stderr
    view = json.loads(r.stdout)
    assert set(view) == {"concession_conditions", "procedural_issues"}
    assert {"side": "plaintiff", "condition": "plaintiff 的條件"} in view["concession_conditions"]
    assert "論證全文" not in r.stdout
    # 完整輸出照舊,評估落地與 UI 重算比對都靠它
    assert {"weak_points", "position_drift", "procedural_issues"} <= set(json.loads(run_main("finalize", "--case-id", "c1", db_url=db_url).stdout))
