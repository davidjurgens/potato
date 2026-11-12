"""
Regression test: the AI assistant panels must actually be visible.

Potato's AI assistant panels (hint, keyword, rationale) use the class name
`.tooltip` and are opened by adding `.active`. Bootstrap — loaded from the CDN
*before* styles.css in base_template_v2.html — ships its own rule for that same
class name:

    .tooltip { position:absolute; z-index:1080; display:block; ... opacity:0 }

Bootstrap fades its own tooltips in by adding `.show`, which Potato never uses.
Potato's `.tooltip.active` restored `display` but not `opacity`, so every AI
panel opened, took up layout, filled with real model output — and painted
nothing. The DOM said the feature worked; the screen showed an empty page.

This is why the class of bug is worth a test: nothing else catches it. Server
tests see a correct API response, the JS console is clean, `offsetParent` is
non-null and `getBoundingClientRect()` returns a full-size box. Only the
computed opacity gives it away.

The general rule this encodes: when Potato reuses a Bootstrap class name, any
property Bootstrap sets that would hide the element must be restored explicitly.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
STYLES = REPO_ROOT / "potato" / "static" / "styles.css"
TEMPLATE = REPO_ROOT / "potato" / "templates" / "base_template_v2.html"

#: Bootstrap class names Potato also uses, mapped to the properties Bootstrap
#: sets that would render the element invisible. Extend this when another
#: collision turns up.
COLLISIONS = {
    ".tooltip.active": ("opacity",),
}


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", " ", css, flags=re.DOTALL)


@pytest.fixture(scope="module")
def styles():
    # Stripped up front, not per-rule: a comment that quotes CSS can contain a
    # closing brace, which truncates any regex that scans for one.
    return _strip_comments(STYLES.read_text(encoding="utf-8"))


def _rule_body(css: str, selector: str) -> str:
    """Return the declaration block for an exact selector, or ''.

    Expects comment-free CSS (see `_strip_comments`).
    """
    pattern = re.compile(
        r"(?:^|[},])\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", re.MULTILINE)
    match = pattern.search(css)
    return match.group(1) if match else ""


class TestAiTooltipVisibility:
    def test_bootstrap_is_still_loaded_before_our_styles(self):
        """The premise. If this changes, the collision may no longer exist."""
        html = TEMPLATE.read_text(encoding="utf-8")
        bootstrap = html.find("bootstrap")
        ours = html.find("filename='styles.css'")
        assert bootstrap != -1, "Bootstrap is no longer loaded — re-check COLLISIONS"
        assert bootstrap < ours, (
            "styles.css now loads before Bootstrap; source order changed and the "
            "override reasoning in this test needs revisiting.")

    @pytest.mark.parametrize("selector,props", COLLISIONS.items())
    def test_collision_properties_are_restored(self, styles, selector, props):
        body = _rule_body(styles, selector)
        assert body, f"no `{selector}` rule in styles.css"
        missing = [p for p in props if not re.search(rf"\b{p}\s*:", body)]
        assert not missing, (
            f"`{selector}` does not set {missing}. Bootstrap sets those on the "
            f"bare class, so the element stays invisible even when Potato marks "
            f"it open. Rule body was:\n{body.strip()}")

    def test_active_tooltip_is_fully_opaque(self, styles):
        """Specifically: a panel that is open must not be see-through."""
        body = _rule_body(styles, ".tooltip.active")
        match = re.search(r"\bopacity\s*:\s*([\d.]+)", body)
        assert match, ".tooltip.active must set an explicit opacity"
        assert float(match.group(1)) == 1.0, (
            f"an open AI panel should be fully opaque, got {match.group(1)}")

    def test_active_tooltip_is_displayed(self, styles):
        body = _rule_body(styles, ".tooltip.active")
        assert re.search(r"\bdisplay\s*:\s*block", body), (
            ".tooltip.active must set display:block — the base .tooltip rule "
            "hides it with display:none")
