"""
Frontend Asset Detection Tests (PR #142 follow-up)

Verifies that:
1. _detect_frontend_assets_for_page correctly detects markers in HTML
2. FRONTEND_ASSET_MARKERS stays in sync with actual schema/display generators
3. Every asset key referenced in base_template_v2.html has a marker entry
4. Edge cases (empty HTML, missing files, mtime caching) work correctly
"""

import os
import re
import importlib
import inspect

import pytest

from potato.flask_server import (
    _detect_frontend_assets_for_page,
    _read_cached_template_text,
    FRONTEND_ASSET_MARKERS,
    _FRONTEND_TEMPLATE_TEXT_CACHE,
)


# ---------------------------------------------------------------------------
# Basic detection tests (carried over from PR #142 with additions)
# ---------------------------------------------------------------------------

class TestDetectFrontendAssets:

    def test_triage_page_only_loads_triage(self, tmp_path):
        html_file = tmp_path / "triage_only.html"
        html_file.write_text(
            '<form class="annotation-form triage" data-annotation-type="triage">'
            '<div class="triage-container"></div></form>',
            encoding="utf-8",
        )
        assets = _detect_frontend_assets_for_page(str(html_file))

        assert assets["triage"] is True
        # Everything else should be off
        for key in ("web_agent_viewer", "web_agent_playback", "pdf_bbox",
                     "tiered_annotation", "image_annotation", "audio_annotation",
                     "video_annotation", "coreference", "tracking"):
            assert assets[key] is False, f"{key} should be False for triage-only page"

    def test_display_html_markers_detected(self, tmp_path):
        html_file = tmp_path / "blank.html"
        html_file.write_text("<html><body></body></html>", encoding="utf-8")

        display_html = (
            '<div class="web-agent-viewer" data-auto-playback="true"></div>'
            '<div class="pdf-display pdf-viewer-paginated pdf-bbox-mode">'
            '<canvas class="pdf-bbox-canvas"></canvas></div>'
        )
        assets = _detect_frontend_assets_for_page(str(html_file), display_html=display_html)

        assert assets["web_agent_viewer"] is True
        assert assets["web_agent_playback"] is True
        assert assets["pdf_bbox"] is True

    def test_empty_html_returns_all_false(self, tmp_path):
        html_file = tmp_path / "empty.html"
        html_file.write_text("", encoding="utf-8")

        assets = _detect_frontend_assets_for_page(str(html_file))
        for key, val in assets.items():
            assert val is False, f"{key} should be False for empty HTML"

    def test_missing_file_returns_all_false(self):
        assets = _detect_frontend_assets_for_page("/nonexistent/path.html")
        for key, val in assets.items():
            assert val is False, f"{key} should be False for missing file"

    def test_empty_path_returns_all_false(self):
        assets = _detect_frontend_assets_for_page("")
        for key, val in assets.items():
            assert val is False, f"{key} should be False for empty path"

    def test_no_segmentation_tools_alias(self, tmp_path):
        """
        segmentation_tools is gone.

        It existed only to load segmentation-tools.js, whose
        SegmentationToolManager was never instantiated anywhere, and
        css/segmentation.css, whose only live rules overrode the accessible
        .tool-btn.active styling for two tools. Both were deleted; the alias
        would now gate nothing.
        """
        html_file = tmp_path / "img.html"
        html_file.write_text(
            '<div class="image-annotation-container"></div>',
            encoding="utf-8",
        )
        assets = _detect_frontend_assets_for_page(str(html_file))
        assert assets["image_annotation"] is True
        assert "segmentation_tools" not in assets

    def test_coreference_also_enables_span_link(self, tmp_path):
        """span_link should be True when coreference is detected."""
        html_file = tmp_path / "coref.html"
        html_file.write_text(
            '<div data-annotation-type="coreference"></div>',
            encoding="utf-8",
        )
        assets = _detect_frontend_assets_for_page(str(html_file))
        assert assets["coreference"] is True
        assert assets["span_link"] is True

    def test_conversation_tree_uses_correct_marker(self, tmp_path):
        """Regression: the marker must be 'conv-tree', not 'conversation-tree'."""
        html_file = tmp_path / "tree.html"
        html_file.write_text(
            '<div class="conv-tree" data-tree-config="{}"></div>',
            encoding="utf-8",
        )
        assets = _detect_frontend_assets_for_page(str(html_file))
        assert assets["conversation_tree"] is True

    def test_conversation_tree_wrong_marker_not_detected(self, tmp_path):
        """Ensure the old wrong marker doesn't accidentally match."""
        html_file = tmp_path / "tree2.html"
        html_file.write_text(
            '<div class="conversation-tree"></div>',
            encoding="utf-8",
        )
        assets = _detect_frontend_assets_for_page(str(html_file))
        assert assets["conversation_tree"] is False

    def test_each_asset_detectable_individually(self, tmp_path):
        """Each asset key should be independently detectable via its markers."""
        for asset_key, markers in FRONTEND_ASSET_MARKERS.items():
            # Use first marker for each asset
            html_file = tmp_path / f"{asset_key}.html"
            html_file.write_text(f"<div>{markers[0]}</div>", encoding="utf-8")
            assets = _detect_frontend_assets_for_page(str(html_file))
            assert assets[asset_key] is True, (
                f"Asset '{asset_key}' not detected with marker '{markers[0]}'"
            )


# ---------------------------------------------------------------------------
# Mtime cache tests
# ---------------------------------------------------------------------------

class TestReadCachedTemplateText:

    def test_caches_by_mtime(self, tmp_path):
        html_file = tmp_path / "cached.html"
        html_file.write_text("original content", encoding="utf-8")

        # Clear cache
        _FRONTEND_TEMPLATE_TEXT_CACHE.clear()

        result1 = _read_cached_template_text(str(html_file))
        assert result1 == "original content"

        # Same mtime → should return cached
        result2 = _read_cached_template_text(str(html_file))
        assert result2 == "original content"
        assert str(html_file) in _FRONTEND_TEMPLATE_TEXT_CACHE

    def test_invalidates_on_mtime_change(self, tmp_path):
        import time
        html_file = tmp_path / "changing.html"
        html_file.write_text("version 1", encoding="utf-8")

        _FRONTEND_TEMPLATE_TEXT_CACHE.clear()
        result1 = _read_cached_template_text(str(html_file))
        assert result1 == "version 1"

        # Force a different mtime
        time.sleep(0.05)
        html_file.write_text("version 2", encoding="utf-8")

        result2 = _read_cached_template_text(str(html_file))
        assert result2 == "version 2"

    def test_returns_empty_for_missing_file(self):
        _FRONTEND_TEMPLATE_TEXT_CACHE.clear()
        result = _read_cached_template_text("/nonexistent/file.html")
        assert result == ""

    def test_returns_empty_for_empty_path(self):
        assert _read_cached_template_text("") == ""
        assert _read_cached_template_text(None) == ""


# ---------------------------------------------------------------------------
# Marker-generator sync tests — catches silent asset-loading failures
# ---------------------------------------------------------------------------

# Maps asset keys to the generator modules/functions that produce their HTML
# and at least one marker substring that MUST appear in the output.
# This is the authoritative list — if a generator changes its class names,
# these tests will fail.
# Maps asset keys to the module that generates their HTML and the marker
# substrings that MUST appear in the module source.  The "symbol" is a
# function or class name that must exist in the module (sanity check that
# the module hasn't been gutted or reorganised).
_GENERATOR_MARKER_EXPECTATIONS = {
    "image_annotation": {
        "module": "potato.server_utils.schemas.image_annotation",
        "symbol": "generate_image_annotation_layout",
        "markers": ["image-annotation-container"],
    },
    "audio_annotation": {
        "module": "potato.server_utils.schemas.audio_annotation",
        "symbol": "generate_audio_annotation_layout",
        "markers": ["audio-annotation-container"],
    },
    "video_annotation": {
        "module": "potato.server_utils.schemas.video_annotation",
        "symbol": "generate_video_annotation_layout",
        "markers": ["video-annotation-container"],
    },
    "span_link": {
        "module": "potato.server_utils.schemas.span_link",
        "symbol": "generate_span_link_layout",
        "markers": ["span-link-container"],
    },
    "event_annotation": {
        "module": "potato.server_utils.schemas.event_annotation",
        "symbol": "generate_event_annotation_layout",
        "markers": ["event-annotation-container"],
    },
    "coreference": {
        "module": "potato.server_utils.schemas.coreference",
        "symbol": "generate_coreference_layout",
        "markers": ["coreference", "coref-chain-panel"],
    },
    "triage": {
        "module": "potato.server_utils.schemas.triage",
        "symbol": "generate_triage_layout",
        "markers": ["triage-container"],
    },
    "tiered_annotation": {
        "module": "potato.server_utils.schemas.tiered_annotation",
        "symbol": "generate_tiered_annotation_layout",
        "markers": ["tiered-annotation-container"],
    },
    "conversation_tree": {
        "module": "potato.server_utils.displays.conversation_tree_display",
        "symbol": "ConversationTreeDisplay",
        "markers": ["conv-tree"],
    },
    "document_bbox": {
        "module": "potato.server_utils.displays.document_display",
        "symbol": "DocumentDisplay",
        "markers": ["document-bbox-container"],
    },
    "pdf_bbox": {
        "module": "potato.server_utils.displays.pdf_display",
        "symbol": "PDFDisplay",
        "markers": ["pdf-bbox-container"],
    },
    "web_agent_viewer": {
        "module": "potato.server_utils.displays.web_agent_trace_display",
        "symbol": "WebAgentTraceDisplay",
        "markers": ["web-agent-viewer"],
    },
    "live_coding_agent": {
        "module": "potato.server_utils.displays.live_coding_agent_display",
        "symbol": "LiveCodingAgentDisplay",
        "markers": ["live-coding-agent-viewer"],
    },
    "turn_annotations": {
        "module": "potato.server_utils.turn_annotations",
        "symbol": "get_turn_level_schemes",
        "markers": ["turn-anno-hidden", "turn-anno-slot"],
    },
    "multi_agent_discussion": {
        "module": "potato.server_utils.displays.multi_agent_discussion_display",
        "symbol": "MultiAgentDiscussionDisplay",
        "markers": ["mad-legend-chip"],
    },
    "audio_dialogue": {
        "module": "potato.server_utils.displays.audio_dialogue_display",
        "symbol": "AudioDialogueDisplay",
        "markers": ['class="audio-dialogue"'],
    },
    "run_tree": {
        "module": "potato.server_utils.displays.agent_trace_display",
        "symbol": "AgentTraceDisplay",
        "markers": ['class="run-tree"'],
    },
    "entity_linking": {
        "module": "potato.server_utils.schemas.span",
        "symbol": "generate_span_layout",
        "markers": ["data-entity-linking"],
    },
}


class TestMarkerGeneratorSync:
    """Verify that FRONTEND_ASSET_MARKERS stays in sync with actual generators.

    If a generator renames a CSS class, the corresponding test here will fail,
    preventing a silent asset-loading miss in production.
    """

    @pytest.mark.parametrize(
        "asset_key",
        list(_GENERATOR_MARKER_EXPECTATIONS.keys()),
    )
    def test_generator_output_contains_expected_markers(self, asset_key):
        """Each generator must produce HTML containing at least one of its markers."""
        spec = _GENERATOR_MARKER_EXPECTATIONS[asset_key]

        try:
            mod = importlib.import_module(spec["module"])
        except ImportError:
            pytest.skip(f"Module {spec['module']} not importable")

        symbol = getattr(mod, spec["symbol"], None)
        if symbol is None:
            pytest.fail(
                f"Symbol {spec['symbol']} not found in {spec['module']}. "
                f"Was it renamed? Update _GENERATOR_MARKER_EXPECTATIONS."
            )

        # Check the full module source for marker strings. We use module source
        # rather than just the public function because many generators delegate
        # to an internal function via safe_generate_layout().
        try:
            source = inspect.getsource(mod)
        except (OSError, TypeError):
            pytest.skip(f"Cannot get source for {spec['module']}")

        for marker in spec["markers"]:
            assert marker in source, (
                f"Marker '{marker}' not found in module {spec['module']}. "
                f"Was the CSS class renamed? Update both the generator and "
                f"FRONTEND_ASSET_MARKERS in flask_server.py."
            )

    @pytest.mark.parametrize(
        "asset_key",
        list(_GENERATOR_MARKER_EXPECTATIONS.keys()),
    )
    def test_markers_registered_in_frontend_asset_markers(self, asset_key):
        """Every generator's markers must appear in FRONTEND_ASSET_MARKERS."""
        assert asset_key in FRONTEND_ASSET_MARKERS, (
            f"Asset key '{asset_key}' has a generator but no entry in FRONTEND_ASSET_MARKERS"
        )
        spec = _GENERATOR_MARKER_EXPECTATIONS[asset_key]
        registered_markers = FRONTEND_ASSET_MARKERS[asset_key]
        for marker in spec["markers"]:
            assert any(marker in rm for rm in registered_markers), (
                f"Marker '{marker}' from generator {spec['module']}.{spec['function']} "
                f"not found in FRONTEND_ASSET_MARKERS['{asset_key}'] = {registered_markers}"
            )


# ---------------------------------------------------------------------------
# Template sync test — ensures base_template_v2.html references match registry
# ---------------------------------------------------------------------------

class TestTemplateAssetSync:
    """Verify that base_template_v2.html asset conditionals match the registry."""

    @pytest.fixture(scope="class")
    def template_text(self):
        template_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "potato", "templates", "base_template_v2.html"
        )
        with open(template_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_all_template_asset_keys_in_registry(self, template_text):
        """Every frontend_assets.X in the template must exist in FRONTEND_ASSET_MARKERS."""
        # Match patterns like frontend_assets.image_annotation or frontend_assets.pdf_bbox
        used_keys = set(re.findall(r"frontend_assets\.(\w+)", template_text))
        # Remove 'default' which is a Jinja2 filter, not an asset key
        used_keys.discard("default")

        all_asset_keys = set(FRONTEND_ASSET_MARKERS.keys())

        missing = used_keys - all_asset_keys
        assert not missing, (
            f"Template references asset keys not in FRONTEND_ASSET_MARKERS: {missing}. "
            f"Add entries for these keys to FRONTEND_ASSET_MARKERS in flask_server.py."
        )

    def test_all_registry_keys_used_in_template(self, template_text):
        """Every FRONTEND_ASSET_MARKERS key should be referenced in the template.

        If a key exists in the registry but isn't used in the template, either
        the template conditional is missing or the registry entry is stale.
        """
        used_keys = set(re.findall(r"frontend_assets\.(\w+)", template_text))
        for key in FRONTEND_ASSET_MARKERS:
            assert key in used_keys, (
                f"FRONTEND_ASSET_MARKERS has key '{key}' but base_template_v2.html "
                f"never references frontend_assets.{key}. Is the template conditional missing?"
            )


# ---------------------------------------------------------------------------
# The page template must not trip markers by itself
# ---------------------------------------------------------------------------

class TestTemplateDoesNotSelfTrigger:
    """The scan reads the generated page template, which contains every gated
    `<script src=...>` include inside its own `{% if %}` block. Markers that are
    also file names (`pdf-link-mode`, `web-agent-recorder`,
    `live-coding-agent-viewer`) matched those includes, and `label-btn` matched
    a template comment, so four bundles loaded on every page of every task.
    """

    @pytest.fixture(scope="class")
    def base_template(self):
        path = os.path.join(os.path.dirname(__file__), "..", "..", "potato",
                            "templates", "base_template_v2.html")
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_the_bare_base_template_loads_no_gated_bundle(self, tmp_path, base_template):
        page = tmp_path / "plain.html"
        page.write_text(base_template, encoding="utf-8")
        assets = _detect_frontend_assets_for_page(str(page))
        on = sorted(k for k, v in assets.items() if v)
        assert on == [], f"a page with no schemes or displays turned on: {on}"

    def test_a_plain_radio_page_loads_no_gated_bundle(self, tmp_path, base_template):
        from potato.server_utils.schemas.radio import generate_radio_layout
        radio_html, _ = generate_radio_layout({
            "annotation_type": "radio", "name": "sentiment",
            "description": "Sentiment?", "labels": ["pos", "neg"],
            "annotation_id": 0})
        page = tmp_path / "radio.html"
        page.write_text(base_template.replace("</body>", radio_html + "</body>"),
                        encoding="utf-8")
        assets = _detect_frontend_assets_for_page(str(page))
        assert sorted(k for k, v in assets.items() if v) == []

    def test_markers_still_found_in_real_markup(self, tmp_path, base_template):
        page = tmp_path / "pdf.html"
        page.write_text(base_template, encoding="utf-8")
        display = ('<div class="pdf-display pdf-link-mode pdf-viewer-paginated"></div>'
                   '<div class="live-coding-agent-viewer" id="lca-viewer-x"></div>'
                   '<nav class="run-tree" aria-label="Sub-agent run tree"></nav>')
        assets = _detect_frontend_assets_for_page(str(page), display_html=display)
        assert assets["pdf_link"] and assets["live_coding_agent"] and assets["run_tree"]
        assert not assets["web_agent_recorder"]

    def test_a_process_reward_page_does_not_load_the_coding_agent_viewer(self, tmp_path, base_template):
        # process_reward's inline script looks the viewer up with
        # querySelector('.live-coding-agent-viewer'); the page has no viewer.
        from potato.server_utils.schemas.process_reward import generate_process_reward_layout
        html, _ = generate_process_reward_layout({
            "annotation_type": "process_reward", "name": "step_rewards",
            "description": "Rate each step", "mode": "per_step",
            "annotation_id": 0})
        assert "live-coding-agent-viewer" in html, "the probe no longer exercises the case"
        page = tmp_path / "prm.html"
        page.write_text(base_template.replace("</body>", html + "</body>"), encoding="utf-8")
        assert not _detect_frontend_assets_for_page(str(page))["live_coding_agent"]

    def test_markers_in_inline_scripts_do_not_count(self, tmp_path):
        page = tmp_path / "inline.html"
        page.write_text("<script>\n  container.querySelectorAll('.label-btn');\n"
                        "  document.querySelector('.live-coding-agent-viewer');\n</script>",
                        encoding="utf-8")
        assets = _detect_frontend_assets_for_page(str(page))
        assert not assets["label_visibility"]
        assert not assets["live_coding_agent"]

    def test_markup_beside_an_inline_script_still_counts(self, tmp_path):
        # Only the script element is dropped, including when markup sits
        # inside a <template> the page clones later.
        page = tmp_path / "beside.html"
        page.write_text('<script>var a = 1;</script>'
                        '<template><button class="label-btn"></button></template>'
                        '<script>var b = 2;</script>'
                        '<div class="run-tree"></div>',
                        encoding="utf-8")
        assets = _detect_frontend_assets_for_page(str(page))
        assert assets["label_visibility"]
        assert assets["run_tree"]

    def test_markers_in_comments_do_not_count(self, tmp_path):
        page = tmp_path / "comment.html"
        page.write_text('<!-- a .label-btn toolbar -->{# label-btn #}'
                        '<link rel="stylesheet" href="/static/pdf-link-mode.css">'
                        '<script src="/static/web-agent-recorder.js?v=1"></script>',
                        encoding="utf-8")
        assets = _detect_frontend_assets_for_page(str(page))
        assert not assets["label_visibility"]
        assert not assets["pdf_link"]
        assert not assets["web_agent_recorder"]
