"""
Regression tests for the server-side gating of the three universal sidebars.

Memos, search-and-claim and the codebook tray used to be self-gating: the
template shipped all three on every annotation page and each one probed its own
API to discover whether the feature was on. A task with none of them therefore
made nine failed requests per page view -- five 503s from the codebook
blueprint, two from memos, a 403 from search -- which is enough console noise to
hide the error an annotator actually needs to see.

The server decides now. These tests hold the two halves of that in place: the
predicate must agree with the blueprints that enforce the same rules, and both
render paths must supply the flags the template reads.

The browser half lives in tests/selenium/test_codebook_ui.py and
test_search_ui.py, which assert the markup is absent rather than merely hidden,
and in tests/unit/test_preview_render.py, which asserts a shipped example makes
no background requests at all.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FLASK_SERVER = REPO_ROOT / "potato" / "flask_server.py"
BASE_TEMPLATE = REPO_ROOT / "potato" / "templates" / "base_template_v2.html"

#: Both functions that render the annotation template. See CLAUDE.md: a
#: conditional added to one of them silently does nothing on the other half.
RENDER_PATHS = ["render_page_with_annotations", "get_current_page_html"]

#: Flag name -> the script tag it must gate.
GATED_SCRIPTS = {
    "memos_enabled": "filename='memos.js'",
    "search_claim_enabled": "filename='search.js'",
    "codebook_ui_enabled": "filename='codebook.js'",
}


@pytest.fixture(scope="module")
def server_source():
    return FLASK_SERVER.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def template_source():
    return BASE_TEMPLATE.read_text(encoding="utf-8")


def _function_body(source: str, name: str) -> str:
    match = re.search(rf"^def {re.escape(name)}\(", source, re.MULTILINE)
    assert match, f"{name}() not found in flask_server.py"
    start = match.start()
    nxt = re.search(r"^def \w+\(", source[start + 1:], re.MULTILINE)
    end = start + 1 + nxt.start() if nxt else len(source)
    return source[start:end]


def _flags(config):
    from potato.flask_server import _annotation_sidebar_flags
    return _annotation_sidebar_flags(config)


class TestTheGateAgreesWithTheBlueprints:
    """The client must not think a feature is on when the API says it is off.

    Each predicate is imported from the module that enforces it rather than
    reimplemented, so these tests are about the wiring rather than the rules.
    """

    def test_a_plain_task_gets_nothing(self):
        assert _flags({}) == {
            "memos_enabled": False,
            "codebook_ui_enabled": False,
            "search_claim_enabled": False,
        }

    def test_qda_mode_brings_memos_and_the_codebook(self):
        flags = _flags({"qda_mode": {"enabled": True}})
        assert flags["memos_enabled"]
        assert flags["codebook_ui_enabled"]
        assert not flags["search_claim_enabled"]

    def test_solo_mode_brings_memos_and_the_codebook(self):
        flags = _flags({"solo_mode": {"enabled": True}})
        assert flags["memos_enabled"]
        assert flags["codebook_ui_enabled"]

    def test_explicit_annotation_ui_memos_wins(self):
        assert _flags({"annotation_ui": {"memos": True}})["memos_enabled"]
        assert not _flags({
            "qda_mode": {"enabled": True},
            "annotation_ui": {"memos": False},
        })["memos_enabled"]

    def test_a_codebook_backed_scheme_brings_the_tray(self):
        flags = _flags({"annotation_schemes": [
            {"annotation_type": "radio", "name": "q", "codebook": True},
        ]})
        assert flags["codebook_ui_enabled"]

    def test_codebook_mode_brings_the_tray(self):
        assert _flags({"codebook_mode": "open"})["codebook_ui_enabled"]

    def test_annotator_claim_brings_the_search_panel(self):
        assert _flags({"search": {"annotator_claim": True}})["search_claim_enabled"]

    def test_search_enabled_alone_does_not(self):
        """`search.enabled` defaults on; the annotator panel is separate."""
        assert not _flags({"search": {"enabled": True}})["search_claim_enabled"]

    @pytest.mark.parametrize("name,predicate", [
        ("memos_enabled", "potato.memos.api:memos_enabled"),
        ("codebook_ui_enabled", "potato.codebook.api:codebook_enabled"),
    ])
    def test_matches_the_blueprints_own_predicate(self, name, predicate):
        import importlib

        module_path, attr = predicate.split(":")
        enabled = getattr(importlib.import_module(module_path), attr)
        for config in (
            {},
            {"qda_mode": {"enabled": True}},
            {"solo_mode": {"enabled": True}},
            {"annotation_ui": {"memos": True}},
            {"codebook_mode": "fixed"},
        ):
            assert _flags(config)[name] == bool(enabled(config)), (
                f"{name} disagrees with {predicate} for {config}; the panel "
                f"would render against an API that refuses it, or vice versa"
            )


class TestBothRenderPathsSupplyTheFlags:
    @pytest.mark.parametrize("func", RENDER_PATHS)
    def test_render_path_calls_the_shared_helper(self, server_source, func):
        body = _function_body(server_source, func)
        assert "_annotation_sidebar_flags" in body, (
            f"{func}() does not supply the sidebar flags, so every variable "
            f"the template reads falls through to `default(false)` and the "
            f"feature silently disappears on the pages it renders."
        )


class TestTheTemplateActuallyGates:
    @pytest.mark.parametrize("flag,script", sorted(GATED_SCRIPTS.items()))
    def test_script_is_inside_its_flag(self, template_source, flag, script):
        """The script tag must sit after the `{% if <flag> %}` that guards it.

        Gating only the markup would leave the client loading and probing --
        the exact cost this fix removes.
        """
        guard = template_source.find("{%% if %s | default(false) %%}" % flag)
        assert guard != -1, f"no guard for {flag} in base_template_v2.html"
        tag = template_source.find(script)
        assert tag != -1, f"{script} is not in base_template_v2.html"
        closing = template_source.find("{% endif %}", tag)
        assert guard < tag < closing, (
            f"{script} is not inside the {flag} guard, so it loads on every "
            f"annotation page and probes its API to find out it is off"
        )

    def test_every_gated_script_loads_once(self, template_source):
        for script in GATED_SCRIPTS.values():
            assert template_source.count(script) == 1, (
                f"{script} appears more than once; only one of them is gated"
            )
