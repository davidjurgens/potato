"""
Light and dark themes: ui.theme, the dark token values, and the stylesheets.

Browser behaviour (the toggle, persistence, what an annotator sees) is in
tests/playwright/test_dark_mode.py; the pages that carry the theme are in
tests/server/test_ui_theme_pages.py.
"""

import re
from pathlib import Path

import pytest

from potato.server_utils.config_module import ConfigValidationError
from potato.server_utils.theme import resolve_ui_theme, validate_ui_theme

STATIC = Path("potato/static")


class TestConfig:
    @pytest.mark.parametrize("ui,expected", [
        (None, "auto"),
        ({}, "auto"),
        ({"theme": "dark"}, "dark"),
        ({"theme": " Light "}, "light"),
        ({"theme": "midnight"}, "auto"),
    ])
    def test_resolve(self, ui, expected):
        config = {} if ui is None else {"ui": ui}
        assert resolve_ui_theme(config) == expected

    def test_an_unknown_theme_is_refused_at_load(self):
        with pytest.raises(ConfigValidationError, match="ui.theme"):
            validate_ui_theme({"ui": {"theme": "midnight"}})
        with pytest.raises(ConfigValidationError):
            validate_ui_theme({"ui": {"theme": True}})
        validate_ui_theme({"ui": {"theme": "auto"}})
        validate_ui_theme({"ui": {}})


def _block(css, selector):
    start = css.index(selector + " {")
    return css[start:css.index("}", start)]


def _tokens(block):
    return dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})\s*;", block))


def _lum(hexcolour):
    r, g, b = (int(hexcolour[i:i + 2], 16) / 255 for i in (1, 3, 5))

    def f(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _contrast(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.fixture(scope="module")
def css():
    return (STATIC / "styles.css").read_text()


class TestTokens:
    @pytest.fixture(scope="class")
    def dark(self, css):
        return _tokens(_block(css, ':root[data-theme="dark"]'))

    @pytest.mark.parametrize("fg,bg,floor", [
        ("--foreground", "--background", 7),
        ("--card-foreground", "--card", 7),
        ("--text-color", "--card", 7),
        ("--muted-foreground", "--card", 4.5),
        ("--muted-foreground", "--muted", 4.5),
        ("--primary", "--background", 4.5),
        ("--primary", "--card", 4.5),
        ("--primary-foreground", "--primary", 4.5),
        ("--input", "--card", 3),            # control edges
        ("--destructive-text", "--destructive-tint", 7),
        ("--warning-text", "--warning-tint", 7),
        ("--success-text", "--success-tint", 7),
        ("--foreground", "--primary-tint", 7),
    ])
    def test_dark_pairs_meet_their_floor(self, dark, fg, bg, floor):
        assert _contrast(dark[fg], dark[bg]) >= floor, (fg, bg)

    def test_every_neutral_scale_step_is_redefined_for_dark(self, css, dark):
        light = _tokens(_block(css, ":root"))
        scale = {k for k in light if re.fullmatch(r"--(zinc|gray|slate)-\d+", k)}
        assert len(scale) == 30
        assert scale <= set(dark)
        assert "--surface" in dark

    def test_the_scale_tokens_are_the_literals_they_replaced(self, css):
        # The light theme stays as it was because each token's light value is
        # exactly the colour the rule used to hard-code.
        light = _tokens(_block(css, ":root"))
        assert light["--gray-200"] == "#e5e7eb"
        assert light["--zinc-500"] == "#71717a"
        assert light["--slate-400"] == "#94a3b8"


@pytest.mark.parametrize("sheet", [
    "styles.css", "span-styles.css", "span-link-styles.css",
    "css/triage.css", "css/entity-linking.css",
])
def test_no_stylesheet_turns_dark_on_its_own(sheet):
    # A prefers-color-scheme block colours one component dark on a page that
    # is light (the toggle, or ui.theme: light). Dark rules key off data-theme.
    assert "prefers-color-scheme" not in re.sub(r"/\*.*?\*/", "", (STATIC / sheet).read_text(),
                                                flags=re.S)


class TestThemedBackground:
    def test_a_light_tint_gets_a_dark_twin_of_the_same_hue(self):
        import colorsys
        from potato.server_utils.theme import themed_background
        value = themed_background("#e8f5e9")
        light, dark = value[len("light-dark("):-1].split(", ")
        assert light == "#e8f5e9"
        r, g, b = (int(dark[i:i + 2], 16) / 255 for i in (1, 3, 5))
        hue, lightness, _ = colorsys.rgb_to_hls(r, g, b)
        assert lightness < 0.2
        assert abs(hue - colorsys.rgb_to_hls(0xe8 / 255, 0xf5 / 255, 0xe9 / 255)[0]) < 0.02
        # Page text in the dark theme reads on it.
        assert _contrast("#fafafa", dark) >= 7

    @pytest.mark.parametrize("colour", ["#4CAF50", "#1a1a1a", "var(--muted)",
                                        "linear-gradient(red, blue)", "", None])
    def test_everything_else_is_left_alone(self, colour):
        from potato.server_utils.theme import themed_background
        assert themed_background(colour) == colour

    def test_trace_step_colours_follow_the_theme(self):
        from potato.server_utils.displays.agent_trace_display import AgentTraceDisplay
        html = AgentTraceDisplay().render(
            {"key": "trace", "display_options": {}},
            [{"role": "assistant", "content": "x"}])
        assert "light-dark(#e8f5e9" in html          # observation steps
