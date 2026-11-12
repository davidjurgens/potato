"""A widget whose script never loads is a widget that does nothing.

`FRONTEND_ASSET_MARKERS` decides which bundles a page gets by looking for
markers in the rendered HTML. Two gaps, both found by opening the page:

1. `conversation_tree` was keyed on `conv-tree` -- a marker the *display* emits.
   The `tree_annotation` *scheme* emits `tree-ann-container`, so a project that
   used the scheme with any other display loaded no script at all: no node
   selection, no path building, nothing, and no error.

2. `segment-questions.js` was gated on audio or video. `tree_annotation`'s
   `node_scheme` renders through the same template, so the template was emitted
   and `window.SegmentQuestions` was undefined -- the node panel stayed empty,
   which is the symptom the audit reported as "the panel body is never filled".
"""

import re
from pathlib import Path

import pytest

import potato
from potato.flask_server import FRONTEND_ASSET_MARKERS, _detect_frontend_assets_for_page
from potato.server_utils.schemas.registry import schema_registry


TEMPLATE = (Path(potato.__file__).parent / "templates" / "base_template_v2.html").read_text(
    encoding="utf-8")

TREE_SCHEME = {
    "annotation_type": "tree_annotation", "name": "thread", "description": "d",
    "node_scheme": {"annotation_type": "likert", "name": "q",
                    "description": "How helpful?", "size": 5},
    "path_selection": {"enabled": True},
}


@pytest.fixture(scope="module")
def tree_html():
    html, _ = schema_registry.generate(TREE_SCHEME)
    return html


class TestTheSchemeIsEnoughToLoadItsScript:
    def test_the_scheme_emits_the_marker(self, tree_html):
        assert "tree-ann-container" in tree_html

    def test_the_marker_is_registered(self):
        assert "tree-ann-container" in FRONTEND_ASSET_MARKERS["conversation_tree"]

    def test_the_display_marker_is_still_there(self):
        """Keeping both, because either one on its own needs the script."""
        assert "conv-tree" in FRONTEND_ASSET_MARKERS["conversation_tree"]

    def test_the_template_gates_the_script_on_it(self):
        assert re.search(
            r"frontend_assets\.conversation_tree[^%]*%\}\s*<script[^>]*conversation-tree\.js",
            TEMPLATE, re.S)


class TestTheNodeSchemeFormLoadsItsHelper:
    def test_the_scheme_emits_the_template(self, tree_html):
        assert 'class="segment-questions-template"' in tree_html

    def test_the_template_is_a_registered_marker(self):
        assert "segment-questions-template" in FRONTEND_ASSET_MARKERS["segment_questions"]

    def test_the_script_is_gated_on_it_as_well_as_audio_and_video(self):
        block = TEMPLATE[TEMPLATE.index("segment-questions.js") - 400:
                         TEMPLATE.index("segment-questions.js")]
        for flag in ("audio_annotation", "video_annotation", "segment_questions"):
            assert flag in block, f"{flag} no longer gates segment-questions.js"


class TestDetectionOnRealMarkup:
    """The detector reads generated template text, so give it some."""

    def _detect(self, monkeypatch, html):
        monkeypatch.setattr(
            "potato.flask_server._read_cached_template_text", lambda _path: html)
        monkeypatch.setattr(
            "potato.flask_server._resolve_generated_template_path", lambda name: name)
        return _detect_frontend_assets_for_page("page.html")

    def test_a_tree_annotation_page_gets_both_scripts(self, monkeypatch, tree_html):
        detected = self._detect(monkeypatch, tree_html)

        assert detected["conversation_tree"] is True
        assert detected["segment_questions"] is True

    def test_a_tree_without_a_node_scheme_does_not_pull_in_the_helper(self, monkeypatch):
        scheme = dict(TREE_SCHEME)
        del scheme["node_scheme"]
        html, _ = schema_registry.generate(scheme)
        detected = self._detect(monkeypatch, html)

        assert detected["conversation_tree"] is True
        assert detected["segment_questions"] is False

    def test_an_unrelated_page_gets_neither(self, monkeypatch):
        html, _ = schema_registry.generate({
            "annotation_type": "radio", "name": "r", "description": "d",
            "labels": ["a", "b"]})
        detected = self._detect(monkeypatch, html)

        assert detected["conversation_tree"] is False
        assert detected["segment_questions"] is False
