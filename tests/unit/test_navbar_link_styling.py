"""Every link in the annotation navbar must set its own colour.

The Codebook button (rendered when `annotation_codebook_url` is set) carried
`class="codebook-btn"` and the stylesheet had no rule for that class at all. An
`<a>` with no colour of its own falls back to the default anchor colour, so the
button rendered link-blue on the purple navbar — legible only if you already
knew it was there.

This is a whole class of bug rather than one typo: the navbar paints a dark
background, so any control added to it *must* bring a light foreground with it,
and a missing rule fails silently at exactly the moment the feature is turned
on. The test enumerates the anchors in the navbar straight from the template and
insists each one is actually styled.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "potato" / "templates" / "base_template_v2.html"
CSS = ROOT / "potato" / "static" / "styles.css"


@pytest.fixture(scope="module")
def navbar_link_classes():
    """Class names of every <a> inside the annotation navbar."""
    html = TEMPLATE.read_text(encoding="utf-8")
    start = html.find('<nav')
    end = html.find('</nav>', start)
    assert start != -1 and end != -1, "annotation navbar not found in template"
    nav = html[start:end]

    classes = set()
    for tag in re.findall(r"<a\b[^>]*>", nav):
        m = re.search(r'class="([^"{}]+)"', tag)  # skip Jinja-computed classes
        if m:
            classes.update(m.group(1).split())
    assert classes, "no classed anchors found in the navbar"
    return classes


@pytest.fixture(scope="module")
def css():
    return CSS.read_text(encoding="utf-8")


def _selectors_setting_color(css_text, class_name):
    """Rules scoped to .potato-navbar that name this class and set a color."""
    hits = []
    for m in re.finditer(r"\.potato-navbar[^{}]*\." + re.escape(class_name)
                         + r"(?![\w-])[^{}]*\{([^}]*)\}", css_text):
        if re.search(r"(^|;|\s)color\s*:", m.group(1)):
            hits.append(m.group(1))
    return hits


class TestNavbarLinksAreStyled:
    def test_every_navbar_link_class_has_a_scoped_rule(self, navbar_link_classes, css):
        unstyled = sorted(c for c in navbar_link_classes
                          if not _selectors_setting_color(css, c))
        assert not unstyled, (
            f"navbar link classes with no `.potato-navbar .{{class}}` colour rule: "
            f"{unstyled}. On the purple navbar these fall back to the default "
            f"anchor blue and are effectively unreadable.")

    def test_codebook_button_specifically(self, css):
        """The one that shipped broken; named so the regression is obvious."""
        bodies = _selectors_setting_color(css, "codebook-btn")
        assert bodies, ".potato-navbar .codebook-btn must set a colour"

    def test_codebook_matches_its_siblings(self, css):
        """It sits between the adjudicate and progress buttons; it should not
        look like a different kind of control."""
        codebook = _selectors_setting_color(css, "codebook-btn")
        adjudicate = _selectors_setting_color(css, "adjudicate-btn")
        assert codebook and adjudicate
        for body in (codebook[0], adjudicate[0]):
            assert "var(--light-color)" in body, (
                "navbar buttons should take their foreground from the light "
                "token, not a literal, so a theme change moves all of them")
