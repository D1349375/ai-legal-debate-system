"""T9:對手摘要檢查(check-summary)。只警告;摘要檔讀不到或格式錯誤才有結束碼 2。"""
import json
import os
import subprocess
import sys

import pytest

from database.db import DB_URL_ENV, get_session, record_argument, record_case
from engine.internal_review import END, START
from engine.summary_check import summary_warnings, validate_summary

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# W0 實跑被選為被告「最強論點」的句子:條件句,也是舉證責任的讓步句
W0_SENTENCE = "被告若主張更早知悉,則由被告就更早知悉負反證責任。"
CLAIM = "原告於民國112年3月已知悉受損害事實,其侵權行為損害賠償請求權已逾二年時效。"
STATUTE = "民法第197條第1項"
PRECEDENT = "最高法院112年度台上字第100號判決"
INTERNAL_SENTENCE = "這是我方內部檢討哨兵句。"


def _summary(**over):
    base = {"side": "defendant", "stage": 2, "position": "被告否認原告請求並主張時效消滅。",
            "strongest_point": CLAIM, "cited_statutes": [STATUTE], "cited_precedents": [PRECEDENT]}
    base.update(over)
    return base


def _arguments(stage=2, side="defendant"):
    return [{"side": side, "stage": stage, "position": "被告否認原告請求並主張時效消滅。",
             "argument": f"{CLAIM}{W0_SENTENCE}", "cited_statutes": [STATUTE, "民法第125條"],
             "cited_precedents": [PRECEDENT]}]


def _warnings(summary, arguments=None, protocol=None):
    return summary_warnings(validate_summary(summary), _arguments() if arguments is None else arguments, protocol)


def _joined(warnings):
    return "\n".join(warnings)


class TestStrongestPoint:
    def test_w0_sentence_is_a_conditional_concession(self):
        warnings = _warnings(_summary(strongest_point=W0_SENTENCE))
        text = _joined(warnings)
        assert "若" in text and "負反證責任" in text  # 條件字樣與舉證責任分配,各自指出
        assert "正面主張" in text
        assert "不是原句" not in text  # 這句確實逐字在論證裡,問題是選錯句

    def test_verbatim_positive_claim_has_no_warning(self):
        assert _warnings(_summary()) == []

    def test_verbatim_match_ignores_whitespace_and_punctuation(self):
        sentence = CLAIM.replace(",", "，").replace("。", " 。")
        assert _warnings(_summary(strongest_point=sentence)) == []

    def test_paraphrase_warns_not_verbatim(self):
        warnings = _warnings(_summary(strongest_point="原告早就知道損害，請求權已經過了時效。"))
        assert any("不是原句" in w for w in warnings)

    def test_half_a_sentence_is_not_verbatim(self):  # 去掉限定語的半句也要警告
        arguments = _arguments()
        arguments[0]["argument"] += "原告之請求已罹於時效,惟起算日資料未載,待確認。"
        warnings = _warnings(_summary(strongest_point="原告之請求已罹於時效"), arguments)
        assert any("不是原句" in w for w in warnings)
        # 連續兩句算原句(W0 那句另有條件句警告)
        assert not any("不是原句" in w for w in _warnings(_summary(strongest_point=CLAIM + W0_SENTENCE), arguments))

    def test_sentence_only_in_position_counts_as_verbatim(self):
        warnings = _warnings(_summary(strongest_point="被告否認原告請求並主張時效消滅。"))
        assert warnings == []

    @pytest.mark.parametrize("sentence", [
        "倘原告能證明其未曾知悉，則時效不起算。",
        "即使原告主張更晚知悉，其請求權亦已逾十年。",
        "縱使原告所述屬實，亦不得請求。",
        "如果原告不能舉證，其請求即無理由。",
        "原告就知悉時點負舉證責任。",
        "就更早知悉之事實，應由被告負反證責任。",
        "被告就此並無舉證之責。",
        "此部分的風險在於原告可能提出新證據。",
    ])
    def test_conditional_concession_and_burden_wordings_warn(self, sentence):
        arguments = _arguments()
        arguments[0]["argument"] += sentence
        warnings = _warnings(_summary(strongest_point=sentence), arguments)
        assert any("正面主張" in w for w in warnings), sentence

    def test_internal_review_cannot_be_the_strongest_point(self):
        # public_arguments 已濾掉內部檢討;摘要選到那句就是「不是原句」
        warnings = _warnings(_summary(strongest_point=INTERNAL_SENTENCE))
        assert any("不是原句" in w for w in warnings)

    def test_marked_no_clear_claim_skips_wording_check_but_stays_visible(self):
        warnings = _warnings(_summary(strongest_point=W0_SENTENCE, no_clear_claim=True))
        text = _joined(warnings)
        assert "無明確主張句" in text
        assert "負反證責任" not in text
        # 標了也還是要逐字
        paraphrased = _warnings(_summary(strongest_point="改寫過的句子。", no_clear_claim=True))
        assert any("不是原句" in w for w in paraphrased)


class TestProtocol:
    @pytest.mark.parametrize("stage", [1, 3])
    def test_v2_case_summarising_other_than_stage_two_warns(self, stage):
        warnings = _warnings(_summary(stage=stage), _arguments(stage=stage), protocol="v2")
        assert any("stage 2" in w and "5.6" in w for w in warnings)

    def test_v2_case_summarising_stage_two_is_fine(self):
        assert _warnings(_summary(), protocol="v2") == []

    def test_old_flow_may_summarise_stage_one(self):
        assert _warnings(_summary(stage=1), _arguments(stage=1), protocol=None) == []


class TestCitations:
    def test_citation_not_in_that_sides_list_warns(self):
        warnings = _warnings(_summary(cited_statutes=[STATUTE, "民法第184條"], cited_precedents=["最高法院99年度台上字第1號判決"]))
        text = _joined(warnings)
        assert "「民法第184條」" in text and "「最高法院99年度台上字第1號判決」" in text
        assert f"「{STATUTE}」" not in text and f"「{PRECEDENT}」" not in text  # 清單裡有的不警告

    def test_citation_in_the_other_stage_does_not_count(self):
        arguments = _arguments(stage=2) + [{"side": "defendant", "stage": 3, "position": "p", "argument": "a",
                                            "cited_statutes": ["民法第184條"], "cited_precedents": []}]
        warnings = _warnings(_summary(cited_statutes=["民法第184條"]), arguments)
        assert any("民法第184條" in w for w in warnings)

    def test_other_sides_citations_do_not_count(self):
        arguments = _arguments() + [{"side": "plaintiff", "stage": 2, "position": "p", "argument": "a",
                                     "cited_statutes": ["民法第184條"], "cited_precedents": []}]
        warnings = _warnings(_summary(cited_statutes=["民法第184條"]), arguments)
        assert any("民法第184條" in w for w in warnings)

    def test_no_public_argument_for_that_side_and_stage_warns_once(self):
        warnings = _warnings(_summary(stage=2), _arguments(stage=3))
        assert len(warnings) == 1 and "沒有" in warnings[0]


class TestValidate:
    @pytest.mark.parametrize("bad", [
        [], "text", {"side": "defendant"},
        _summary(side="judge"), _summary(stage=4), _summary(stage="2"), _summary(stage=True),
        _summary(strongest_point=""), _summary(strongest_point=5), _summary(position=None),
        _summary(cited_statutes="民法第197條"), _summary(cited_precedents=[1]),
        _summary(no_clear_claim="yes"),
    ])
    def test_malformed_summary_is_refused(self, bad):
        with pytest.raises(ValueError):
            validate_summary(bad)

    def test_missing_optional_fields_are_fine(self):
        data = {"side": "plaintiff", "stage": 1, "position": "p", "strongest_point": "s"}
        assert validate_summary(data)["cited_statutes"] == []


def _run(*args, db_url):
    env = {**os.environ, DB_URL_ENV: db_url, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, "main.py", *args], cwd=ROOT, env=env, capture_output=True,
                          encoding="utf-8", timeout=60)


def _landed(tmp_path, protocol=None):
    db_url = f"sqlite:///{tmp_path / 't9.db'}"
    s = get_session(db_url)
    extra = {"protocol": "v2", "represented_side": "plaintiff"} if protocol == "v2" else {}
    record_case(s, case_id="c1", case_type="侵權損害賠償", facts_summary="事實", claims="請求", **extra)
    for stage in (1, 2, 3):
        record_argument(s, case_id="c1", side="defendant", stage=stage, position="被告否認原告請求並主張時效消滅。",
                        reasoning=f"{CLAIM}{W0_SENTENCE}{START}{INTERNAL_SENTENCE}{END}",
                        cited_statutes=[STATUTE], cited_precedents=[PRECEDENT],
                        falsifier=None if stage == 1 else "讓步條件哨兵")
    s.close()
    return db_url


def _write(tmp_path, data, name="s.json"):
    path = tmp_path / name
    path.write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


class TestCli:
    def test_clean_summary_exits_zero_without_warnings(self, tmp_path):
        r = _run("check-summary", "--case-id", "c1", "--json", _write(tmp_path, _summary()), db_url=_landed(tmp_path))
        assert r.returncode == 0, r.stderr
        assert "警告" not in r.stderr and "0 則警告" in r.stdout

    def test_w0_sentence_warns_on_stderr_but_still_exits_zero(self, tmp_path):
        path = _write(tmp_path, _summary(strongest_point=W0_SENTENCE))
        r = _run("check-summary", "--case-id", "c1", "--json", path, db_url=_landed(tmp_path))
        assert r.returncode == 0, r.stderr
        assert "警告" in r.stderr and "負反證責任" in r.stderr
        assert "則警告" in r.stdout and "0 則警告" not in r.stdout

    def test_v2_case_with_stage_one_warns_and_exits_zero(self, tmp_path):
        path = _write(tmp_path, _summary(stage=1))
        r = _run("check-summary", "--case-id", "c1", "--json", path, db_url=_landed(tmp_path, protocol="v2"))
        assert r.returncode == 0, r.stderr
        assert "stage 2" in r.stderr

    def test_internal_review_is_not_readable_by_the_check(self, tmp_path):
        path = _write(tmp_path, _summary(strongest_point=INTERNAL_SENTENCE))
        r = _run("check-summary", "--case-id", "c1", "--json", path, db_url=_landed(tmp_path))
        assert r.returncode == 0 and "不是原句" in r.stderr

    @pytest.mark.parametrize("content", ["不是 JSON{", json.dumps(_summary(side="judge")), "[]"])
    def test_unreadable_or_malformed_summary_exits_two(self, tmp_path, content):
        r = _run("check-summary", "--case-id", "c1", "--json", _write(tmp_path, content), db_url=_landed(tmp_path))
        assert r.returncode == 2
        assert r.stderr.strip()  # 印出原因

    def test_missing_file_exits_two(self, tmp_path):
        r = _run("check-summary", "--case-id", "c1", "--json", str(tmp_path / "nope.json"), db_url=_landed(tmp_path))
        assert r.returncode == 2 and r.stderr.strip()

    def test_unknown_case_exits_two(self, tmp_path):
        r = _run("check-summary", "--case-id", "nope", "--json", _write(tmp_path, _summary()), db_url=_landed(tmp_path))
        assert r.returncode == 2 and "nope" in r.stderr
