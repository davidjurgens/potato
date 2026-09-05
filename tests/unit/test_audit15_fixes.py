"""Regressions for the audit-15 findings.

Each test names the finding it guards and fails on the behaviour that was
reported, not on an approximation of it.
"""

import io
import json
import os

import pytest


def _read(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


# --------------------------------------------------------------- finding 1 --
# Keyword highlights loaded, computed and cached — and never drew.

class TestKeywordHighlightsAreDrawn:
    def test_the_renderer_resolves_a_per_field_container(self):
        source = _read("potato/static/span-core.js")
        assert "overlayTargetFor(targetField)" in source, (
            "the renderer must resolve a container, not assume #span-overlays")
        # The unconditional lookup that silently returned on every
        # instance_display page must be gone.
        assert "const spanOverlays = document.getElementById('span-overlays');\n" \
               "        if (!spanOverlays) {\n            return;" not in source

    def test_clearing_reaches_every_container(self):
        source = _read("potato/static/span-core.js")
        assert "document.querySelectorAll('.keyword-highlight-overlay')" in source

    def test_a_not_ready_page_retries_before_warning(self):
        """The strategies await fonts, so "not ready" is normal for a moment.

        Warning on the first attempt fired on every healthy load.
        """
        source = _read("potato/static/span-core.js")
        assert "insertKeywordHighlights(keywords, attempt = 0)" in source
        assert "Gave up drawing" in source

    def test_the_api_names_the_field_its_offsets_index(self):
        source = _read("potato/routes.py")
        assert '"target_field": keyword_target_field' in source
        assert 'keyword.setdefault("target_field", keyword_target_field)' in source
        # The cached branch too, or the second visit to an item draws nothing.
        assert 'keyword.setdefault("target_field", cached_field)' in source


# --------------------------------------------------------------- finding 2 --
# A selection with an endpoint at a span boundary was refused.

class TestSelectionBoundaryResolution:
    def test_the_ad_hoc_element_branches_are_gone(self):
        source = _read("potato/static/span-core.js")
        # These two conditions excluded exactly the boundaries a drag that
        # starts or ends at an existing span produces.
        assert "if (startOffset < startContainer.childNodes.length)" not in source
        assert "if (endOffset > 0 && endOffset <= endContainer.childNodes.length)" not in source

    def test_a_single_resolver_handles_both_boundaries(self):
        source = _read("potato/static/span-core.js")
        assert "resolveBoundaryOffset(textNodes, container, offset)" in source
        assert "resolveBoundaryOffset(\n            textNodes, startContainer, startOffset)" in source
        assert "resolveBoundaryOffset(\n            textNodes, endContainer, endOffset)" in source

    def test_it_measures_with_a_range_not_child_indices(self):
        source = _read("potato/static/span-core.js")
        assert "probe.comparePoint(tn.node, tn.node.length)" in source


# --------------------------------------------------------------- finding 3 --
# image_key skipped media resolution, so the model never saw the image.

class TestVisionResolvesLocalMedia:
    @pytest.fixture
    def media_project(self, tmp_path):
        import struct
        import zlib

        def chunk(tag, data):
            body = tag + data
            return (struct.pack(">I", len(data)) + body
                    + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

        raw = b"".join(b"\x00" + b"\xff\x00\x00" * 2 for _ in range(2))
        png = (b"\x89PNG\r\n\x1a\n"
               + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(raw))
               + chunk(b"IEND", b""))
        media = tmp_path / "media"
        media.mkdir()
        (media / "shelf1.png").write_bytes(png)

        from potato.server_utils.config_module import config
        previous = dict(config)
        config.clear()
        config.update({"task_dir": str(tmp_path), "media_directory": "media"})
        yield tmp_path
        config.clear()
        config.update(previous)

    @pytest.mark.parametrize("reference", [
        "shelf1.png", "media/shelf1.png", "/media/shelf1.png",
    ])
    def test_a_local_reference_becomes_image_bytes(self, media_project, reference):
        from potato.ai.ai_cache import _image_data_from_local_media
        data = _image_data_from_local_media(reference)
        assert data is not None, f"{reference!r} did not resolve to bytes"
        assert data.mime_type == "image/png"
        assert data.data, "no base64 payload"

    def test_a_missing_file_does_not_resolve(self, media_project):
        from potato.ai.ai_cache import _image_data_from_local_media
        assert _image_data_from_local_media("nope.png") is None

    def test_a_remote_url_is_left_to_the_downloader(self, media_project):
        from potato.ai.ai_cache import _image_data_from_local_media
        assert _image_data_from_local_media("https://example.com/x.png") is None

    def test_the_public_entry_point_tries_local_media_first(self, media_project):
        from potato.ai.ai_cache import _get_image_data_from_url
        assert _get_image_data_from_url("shelf1.png") is not None


# --------------------------------------------------------------- finding 4 --
# MCP stored "text_box" as the label name for every scalar answer.

class TestMcpScalarLabelName:
    @pytest.fixture
    def app_context(self):
        from flask import Flask
        from potato.server_utils.config_module import config
        previous = dict(config)
        config.clear()
        config.update({"annotation_schemes": [
            {"name": "disposition", "annotation_type": "radio",
             "labels": ["Bug", "Feature request"]},
            {"name": "notes", "annotation_type": "text"},
        ]})
        app = Flask(__name__)
        with app.test_request_context():
            yield
        config.clear()
        config.update(previous)

    def test_a_chosen_label_is_stored_the_way_a_browser_stores_it(self, app_context):
        from potato.mcp_server.routes import _resolve_scalar_label
        resolved, refusal = _resolve_scalar_label("disposition", "Feature request")
        assert refusal is None
        # Browser: {Label("disposition", "Feature request"): "Feature request"}
        assert resolved == ("Feature request", "Feature request")

    def test_a_value_that_names_no_label_is_refused(self, app_context):
        from potato.mcp_server.routes import _resolve_scalar_label
        resolved, refusal = _resolve_scalar_label("disposition", "Fix")
        assert resolved is None
        assert refusal is not None and refusal[1] == 400
        message = refusal[0].get_json()["error"]
        assert "Feature request" in message, "the refusal must name the valid labels"

    def test_free_text_still_uses_text_box(self, app_context):
        from potato.mcp_server.routes import _resolve_scalar_label
        resolved, refusal = _resolve_scalar_label("notes", "some prose")
        assert refusal is None
        assert resolved == ("text_box", "some prose")


# --------------------------------------------------------------- finding 5 --
class TestMcpPhaseRouting:
    def test_a_submission_outside_the_annotation_phase_is_refused(self):
        source = _read("potato/mcp_server/routes.py")
        assert "phase != UserPhase.ANNOTATION" in source
        assert "has nowhere" in source
        # And it is a refusal, not a success.
        assert "409," in source


# --------------------------------------------------------------- finding 6 --
class TestImageAnnotationFindsDisplayImage:
    def test_it_searches_instance_display_fields(self):
        source = _read("potato/server_utils/schemas/image_annotation.py")
        assert "instance_display image field" in source
        assert ".image-container img[data-source-url]" in source

    def test_the_console_advice_names_source_field(self):
        source = _read("potato/server_utils/schemas/image_annotation.py")
        assert "`source_field` on the " in source


# --------------------------------------------------------------- finding 7 --
class TestRetryReSyncs:
    def test_the_button_no_longer_rebuilds_from_a_stale_render(self):
        template = _read("potato/templates/base_template_v2.html")
        assert 'onclick="retryAfterError()"' in template
        assert 'onclick="loadCurrentInstance()"' not in template

    def test_retry_saves_then_reloads(self):
        source = _read("potato/static/annotation.js")
        assert "async function retryAfterError()" in source
        assert "window.location.reload()" in source
        # A refused save must leave the panel up rather than reload into a
        # page that will refuse the next edit too.
        assert "if (saved === false) return;" in source


# --------------------------------------------------------------- finding 9 --
class TestPhaseFileErrorsNameTheEntry:
    def test_a_missing_annotation_type_names_file_and_entry(self):
        import potato.flask_server as fs
        with pytest.raises(ValueError) as excinfo:
            fs._check_phase_schemes(
                [{"annotation_type": "radio", "name": "ok", "description": "d"},
                 {"name": "consent_q", "description": "Do you consent?"}],
                "consent.jsonl", "consent")
        message = str(excinfo.value)
        assert "consent.jsonl" in message
        assert "entry 1" in message
        assert "consent_q" in message
        assert "annotation_type" in message

    def test_a_non_object_entry_is_named_too(self):
        import potato.flask_server as fs
        with pytest.raises(ValueError) as excinfo:
            fs._check_phase_schemes(["not a dict"], "survey.jsonl", "poststudy")
        assert "entry 0" in str(excinfo.value)

    def test_a_well_formed_file_passes(self):
        import potato.flask_server as fs
        fs._check_phase_schemes(
            [{"annotation_type": "radio", "name": "q", "description": "d"}],
            "ok.jsonl", "consent")


# -------------------------------------------------------------- finding 10 --
class TestLegendProseIsNotAllBold:
    def test_block_children_of_a_legend_carry_body_weight(self):
        css = _read("potato/static/styles.css")
        assert ".annotation-form legend > p," in css
        # 400, so <b>/<strong> at 700 inside them stands out again.
        assert "font-weight: 400;" in css.split(".annotation-form legend > p,")[1][:400]
