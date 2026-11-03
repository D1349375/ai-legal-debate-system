"""ui/app.js 的 delabelJargon:英文欄位名換成中文後,不能和原本並列的中文重複。

例:評估理由原文「對於 falsifier 與讓步條件的逐條回應」,原本顯示成「對於 讓步條件 與讓步條件的逐條回應」。
直接用 node 執行 app.js 裡 TEXT_JARGON 到 delabelJargon 那一段;沒有 node 就略過。
"""
import json
import os
import re
import shutil
import subprocess

import pytest

APP_JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui", "app.js")
NODE = shutil.which("node")


def delabel(texts):
    source = open(APP_JS, encoding="utf-8").read()
    block = re.search(r"var TEXT_JARGON = \[.*?\n  function delabelJargon\(raw\) \{.*?\n  \}", source, re.S).group(0)
    script = block + "\nprocess.stdout.write(JSON.stringify(" + json.dumps(texts, ensure_ascii=False) + ".map(delabelJargon)));"
    out = subprocess.run([NODE, "-e", script], capture_output=True, timeout=30, check=True)
    return json.loads(out.stdout.decode("utf-8"))


pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")


def test_field_name_next_to_its_chinese_name_is_not_repeated():
    assert delabel(["對於 falsifier 與讓步條件的逐條回應"]) == ["對於讓步條件的逐條回應"]


@pytest.mark.parametrize("raw", ["讓步條件(falsifier)已列明", "falsifier(讓步條件)已列明", "讓步條件、falsifier已列明"])
def test_other_side_by_side_forms(raw):
    assert delabel([raw]) == ["讓步條件已列明"]


def test_plain_replacements_are_unchanged():
    assert delabel(["原告falsifier(6)自承", "weak_points中被告falsifier(5)", "原告讓步條件與被告讓步條件"]) == [
        "原告讓步條件(6)自承", "雙方讓步條件中被告讓步條件(5)", "原告讓步條件與被告讓步條件"]
