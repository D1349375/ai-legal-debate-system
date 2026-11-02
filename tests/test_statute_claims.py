"""T8:找出附有內容描述的條文引用(只抽取，不判斷)。"""
import json
import os
import subprocess
import sys

from engine.statute_claims import statute_claims

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# W0 訊問 2 的引用與描述(該項實為歸入權規定，描述不符;判斷交給查證 subagent)
W0_QUESTION = "被告主張本件應由監察人代表公司，依公司法第23條第3項(公司對負責人訴訟之代表人),請被告說明依據。"


def _one(text):
    claims = statute_claims(text)
    assert len(claims) == 1, claims
    return claims[0]


def test_w0_question_two_parenthetical_description():
    claims = statute_claims({"questions": [{"question_text": "請原告說明匯款日期。"},
                                           {"question_text": W0_QUESTION}]})
    assert claims == [{"citation": "公司法第23條第3項", "law_name": "公司法", "articles": ["23"],
                       "description": "公司對負責人訴訟之代表人", "form": "括號說明",
                       "where": ["questions[1].question_text"]}]


def test_citations_without_description_are_not_listed():
    text = ("原告依民法第179條請求返還。民法第184條(原證3)。"
            "被告違反公司法第8條(下稱系爭規定)。民法第767條(最高法院某判決參照)。")
    assert statute_claims(text) == []


def test_description_after_the_word_rule():
    claim = _one("依民法第184條第1項前段規定，因故意或過失，不法侵害他人之權利者，負損害賠償責任。故被告應賠償。")
    assert claim["citation"] == "民法第184條第1項前段"
    assert claim["description"] == "因故意或過失，不法侵害他人之權利者，負損害賠償責任"
    assert claim["form"] == "依條文規定轉述"


def test_quoted_rule_after_colon():
    claim = _one("民法第125條規定：「請求權，因十五年間不行使而消滅。」")
    assert claim["description"] == "「請求權，因十五年間不行使而消滅。」"


def test_description_before_stated_explicitly_with_chained_articles():
    claim = _one("按當事人主張有利於己之事實者，就其事實有舉證之責任，民事訴訟法第277條前段、第278條第1項分別定有明文。")
    assert claim["citation"] == "民事訴訟法第277條前段、第278條第1項"
    assert claim["articles"] == ["277", "278"]
    assert claim["description"] == "當事人主張有利於己之事實者，就其事實有舉證之責任"
    assert claim["form"] == "前文轉述後稱定有明文"


def test_description_before_a_citation_in_parentheses():
    claim = _one("縱認被告受有利益，被告得主張損益相抵(民法第216條之1)。")
    assert claim["citation"] == "民法第216條之1"
    assert claim["description"] == "被告得主張損益相抵"
    assert claim["form"] == "括號引用前的說明"
    claim = _one("依誠信原則（民法第148條第2項、第219條），不得任令被告阻卻請求。")
    assert claim["articles"] == ["148", "219"] and claim["description"] == "誠信原則"


def test_quotation_right_after_the_citation():
    claim = _one("此正是民法第356條第2項但書『依通常之檢查不能發見之瑕疵』之典型情形。")
    assert claim["citation"] == "民法第356條第2項但書"
    assert claim["description"] == "『依通常之檢查不能發見之瑕疵』"
    assert claim["form"] == "條文後引號"
    assert _one("罰鍰不是公司法第23條第1項所稱「損害」。")["description"] == "「損害」"


def test_lists_of_citations_are_not_descriptions():
    assert statute_claims("本件引用之法條及裁判（均經查證引擎確認存在）：民法第244條、民法第245條、公司法第8條。") == []


def test_sub_article_number_kept():
    claim = _one("依民法第191條之2規定，汽車在使用中加損害於他人者，駕駛人應賠償因此所生之損害。")
    assert claim["citation"] == "民法第191條之2" and claim["articles"] == ["191-2"]


def test_same_claim_in_two_places_is_listed_once():
    claims = statute_claims({"a": W0_QUESTION, "b": [W0_QUESTION]})
    assert len(claims) == 1 and claims[0]["where"] == ["a", "b[0]"]


def test_cli_reads_json_and_plain_text(tmp_path):
    def run(path):
        r = subprocess.run([sys.executable, "main.py", "statute-claims", "--json", str(path)], cwd=ROOT,
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"}, capture_output=True,
                           encoding="utf-8", timeout=60)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)

    as_json = tmp_path / "questions.json"
    as_json.write_text(json.dumps({"questions": [{"question_text": W0_QUESTION}]}, ensure_ascii=False),
                       encoding="utf-8")
    assert [c["citation"] for c in run(as_json)["claims"]] == ["公司法第23條第3項"]
    as_text = tmp_path / "draft.md"
    as_text.write_text("一、" + W0_QUESTION + "\n二、原告依民法第179條請求返還。\n", encoding="utf-8")
    result = run(as_text)
    assert result["claims"][0]["where"] == ["全文"]
    assert len(result["claims"]) == 1
