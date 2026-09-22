"""深/淺色主題的 WCAG AA 對比度與「不得硬編碼顏色」檢查，直接解析 ui/app.css，不需瀏覽器。"""
import os
import re

import pytest

UI_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui")
CSS_PATH = os.path.join(UI_DIR, "app.css")

THEME_BLOCKS = {
    "dark": re.compile(r':root,\s*:root\[data-theme="dark"\]\s*\{(.*?)\n\}', re.S),
    "light": re.compile(r':root\[data-theme="light"\]\s*\{(.*?)\n\}', re.S),
}
BACKGROUNDS = ["bg-base", "bg-sidebar", "bg-panel", "bg-card", "bg-card-hover", "bg-input", "bg-active"]
STATUS_SETS = ["ok", "bad", "warn", "rec", "plaintiff", "defendant", "judge"]


def _css():
    with open(CSS_PATH, encoding="utf-8") as f:
        return f.read()


def _tokens(theme):
    body = THEME_BLOCKS[theme].search(_css()).group(1)
    return dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;", body))


def _luminance(hex_color):
    channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(fg, bg):
    a, b = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def _text_pairs():
    pairs = []
    for t in ("text-primary", "text-secondary", "text-muted", "text-accent"):
        pairs += [(t, b) for b in BACKGROUNDS]
    pairs.append(("on-accent", "accent"))
    pairs += [("focus", b) for b in ("bg-card", "bg-panel", "bg-input")]
    for s in STATUS_SETS:
        pairs += [(f"{s}-fg", f"{s}-bg"), (f"{s}-fg", "bg-card"), (f"{s}-fg", "bg-input"), (f"{s}-fg", "bg-sidebar")]
        pairs.append(("text-primary", f"{s}-bg"))
        pairs.append(("text-secondary", f"{s}-bg"))
    pairs += [("paper-fg", "paper-bg"), ("paper-muted", "paper-bg"),
              ("paper-fg", "paper-note-bg"), ("paper-muted", "paper-note-bg")]
    return pairs


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_all_text_pairs_meet_wcag_aa(theme):
    tokens = _tokens(theme)
    failures = []
    for fg, bg in _text_pairs():
        assert fg in tokens and bg in tokens, f"{theme}:缺少色票 {fg} 或 {bg}"
        ratio = contrast(tokens[fg], tokens[bg])
        if ratio < 4.5:
            failures.append(f"{fg} {tokens[fg]} on {bg} {tokens[bg]} = {ratio:.2f}")
    assert not failures, f"{theme} 主題對比不足 4.5:1:\n" + "\n".join(failures)


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_graphic_fills_meet_3_to_1(theme):
    """位移長條等圖形填色(非文字)至少 3:1(WCAG 1.4.11)。"""
    tokens = _tokens(theme)
    for fg in ("plaintiff-fg", "defendant-fg"):
        assert contrast(tokens[fg], tokens["bg-input"]) >= 3.0


def test_both_themes_define_the_same_tokens():
    assert set(_tokens("dark")) == set(_tokens("light"))


def test_status_colors_are_distinguishable_within_each_theme():
    """通過/查無/警示三種狀態色在兩種主題下不可近似(另外 UI 仍以圖示+文字標示，不單靠顏色)。"""
    for theme in ("dark", "light"):
        t = _tokens(theme)
        for a, b in (("ok-fg", "bad-fg"), ("ok-fg", "warn-fg"), ("bad-fg", "warn-fg")):
            fa, fb = t[a], t[b]
            dist = sum(abs(int(fa[i:i + 2], 16) - int(fb[i:i + 2], 16)) for i in (1, 3, 5))
            assert dist > 120, f"{theme}: {a} 與 {b} 色差過小"


def test_no_hardcoded_colors_outside_theme_blocks():
    css = _css()
    for pattern in THEME_BLOCKS.values():
        css = pattern.sub("", css)
    assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", css), "主題區塊以外出現寫死的 hex 顏色"
    assert not re.findall(r"\b(?:rgb|rgba|hsl|hsla)\(", css), "主題區塊以外出現寫死的 rgb/hsl 顏色"


def test_no_hardcoded_colors_in_html_or_js():
    for name in os.listdir(UI_DIR):
        if not name.endswith((".html", ".js")):
            continue
        with open(os.path.join(UI_DIR, name), encoding="utf-8") as f:
            content = f.read()
        assert not re.findall(r"#[0-9a-fA-F]{6}\b", content), f"{name} 出現寫死的 hex 顏色"
        assert not re.findall(r"\b(?:rgb|rgba|hsl|hsla)\(", content), f"{name} 出現寫死的 rgb/hsl 顏色"
