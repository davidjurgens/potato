"""The annotation-status pills must be readable against the navbar.

All three were translucent white text on a translucent white scrim over the
purple navbar. Composited, "Not labeled" — the state an annotator sees on every
fresh item — came out at 2.98:1, "In progress" at 3.3 and "Labeled" at 3.6,
against a WCAG AA floor of 4.5:1 for 12px text. Found by measuring the live
page, not by reading the stylesheet: the failure only exists once the alpha
layers are composited, so neither colour looks wrong on its own.
"""

import re
from pathlib import Path

import pytest

STYLES = Path(__file__).resolve().parents[2] / "potato" / "static" / "styles.css"

# --primary, the navbar background the pills sit on.
NAVBAR_RGB = (0x6E, 0x56, 0xCF)

# AA for normal text; the pills are 12px (--text-xs).
AA_NORMAL = 4.5

BADGE_STATES = ["labeled", "unlabeled", "in_progress"]


def _relative_luminance(rgb):
    def channel(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(fg, bg):
    a, b = _relative_luminance(fg), _relative_luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def _composite(rgba, backdrop):
    """Flatten `rgba` over an opaque backdrop, the way the browser paints it."""
    r, g, b, a = rgba
    return tuple(round(c * a + bc * (1 - a)) for c, bc in zip((r, g, b), backdrop))


def _parse_color(value):
    value = value.strip()
    m = re.fullmatch(r"#([0-9a-fA-F]{6})", value)
    if m:
        h = m.group(1)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0)
    m = re.fullmatch(r"#([0-9a-fA-F]{3})", value)
    if m:
        h = m.group(1)
        return tuple(int(c * 2, 16) for c in h) + (1.0,)
    m = re.fullmatch(r"rgba?\(([^)]*)\)", value)
    if m:
        parts = [p.strip() for p in re.split(r"[,\s/]+", m.group(1)) if p.strip()]
        nums = [float(p) for p in parts]
        if len(nums) == 3:
            nums.append(1.0)
        return tuple(nums)
    raise AssertionError(f"unhandled colour syntax in styles.css: {value!r}")


@pytest.fixture(scope="module")
def badge_rules():
    """{state: {"color": rgba, "background-color": rgba}} from styles.css."""
    css = STYLES.read_text(encoding="utf-8")
    rules = {state: {} for state in BADGE_STATES}

    for selector, body in re.findall(r"([^{}]+)\{([^}]*)\}", css):
        classes = {
            m.group(1)
            for m in re.finditer(r"\.status-badge\.([A-Za-z_]+)(?![\w-])", selector)
        }
        # ::before is the state dot, decorative — the word carries the state.
        if not classes or "::before" in selector:
            continue
        for prop in ("color", "background-color"):
            m = re.search(rf"(?<![\w-]){prop}\s*:\s*([^;]+);", body)
            if not m:
                continue
            for state in classes & set(BADGE_STATES):
                rules[state][prop] = _parse_color(m.group(1))

    return rules


@pytest.mark.parametrize("state", BADGE_STATES)
def test_badge_text_meets_aa_against_the_navbar(state, badge_rules):
    rule = badge_rules[state]
    assert rule.get("color") and rule.get("background-color"), (
        f".status-badge.{state} must set both a colour and a background"
    )

    backdrop = _composite(rule["background-color"], NAVBAR_RGB)
    text = _composite(rule["color"], backdrop)
    ratio = _contrast(text, backdrop)

    assert ratio >= AA_NORMAL, (
        f".status-badge.{state} composites to {ratio:.2f}:1 over the navbar, "
        f"below the {AA_NORMAL}:1 WCAG AA floor for 12px text"
    )
