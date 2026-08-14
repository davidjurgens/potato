"""
Phase pages must load the same frontend assets as the annotation page.

Potato has two render paths: annotation pages go through
``render_page_with_annotations``, every other phase (consent, instructions,
training, surveys) through ``get_current_page_html``. Both render the SAME
template, so anything conditional in that template has to be wired into both.

It was not. ``get_current_page_html`` never set ``frontend_assets``, so the
template's ``| default({})`` kicked in and every gated asset was skipped. The
visible consequence was severe: on a TRAINING page an image-annotation schema
rendered its container, its canvas, and its toolbar — but neither fabric.js nor
image-annotation.js was loaded, so nothing ever initialized the canvas. A
trainee saw a drawing interface that could not draw, and therefore could never
pass a practice question no matter what they did.

Audio, video, span-link, and tracking practice questions had the same problem.
"""

import re

import pytest


TEMPLATE = "potato/templates/base_template_v2.html"


def _gated_assets():
    """{asset_key: [filenames]} for every frontend_assets-gated script/link."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    text = (root / TEMPLATE).read_text(encoding="utf-8")

    gated = {}
    current = None
    for line in text.splitlines():
        gate = re.search(r"frontend_assets\.(\w+)", line)
        if gate:
            current = gate.group(1)
            continue
        if current:
            found = re.search(r"filename='([^']+)'", line)
            if found:
                gated.setdefault(current, []).append(found.group(1))
            if "{% endif %}" in line:
                current = None
    return gated


class TestBothRenderPathsSetFrontendAssets:
    def test_the_phase_path_sets_frontend_assets(self):
        """
        The specific regression. Without this the template falls back to
        `frontend_assets | default({})` and silently loads nothing.
        """
        import inspect
        from potato import flask_server

        source = inspect.getsource(flask_server.get_current_page_html)
        assert "frontend_assets" in source, (
            "get_current_page_html does not set frontend_assets, so every gated "
            "asset is skipped on consent, instructions, training and survey "
            "pages — including the JS that makes an annotation canvas work.")

    def test_the_phase_path_sets_has_image_annotation(self):
        import inspect
        from potato import flask_server

        source = inspect.getsource(flask_server.get_current_page_html)
        assert "has_image_annotation" in source, (
            "get_current_page_html does not set has_image_annotation, so the "
            "template never stashes the image URL for the canvas to find.")

    def test_the_annotation_path_still_sets_them(self):
        import inspect
        from potato import flask_server

        source = inspect.getsource(flask_server.render_page_with_annotations)
        assert "frontend_assets" in source
        assert "has_image_annotation" in source


class TestImageAnnotationAssetsAreGated:
    def test_fabric_and_the_manager_are_gated_on_image_annotation(self):
        """
        Both are required for a working canvas, so both must be behind the same
        gate — and that gate must be set on every render path.
        """
        gated = _gated_assets()
        image_assets = " ".join(gated.get("image_annotation", []))
        assert "fabric" in image_assets, "fabric.js is not gated on image_annotation"
        assert "image-annotation.js" in image_assets


class TestTrainingUsesTheConfiguredTextKey:
    def test_training_context_reads_text_key(self):
        """
        Training hardcoded `displayed_text`/`text`. An image project sets
        `text_key: image_url`, so its training question came through EMPTY and
        the canvas had no image to load even once its assets were fixed.
        """
        import inspect
        from potato import flask_server

        source = inspect.getsource(flask_server._training_page_context)
        assert "text_key" in source, (
            "_training_page_context ignores item_properties.text_key, so image "
            "and media training questions render with no content")
