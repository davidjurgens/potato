"""
The spatial generator's painting options: the paint controls, ``brush_size``,
and the level-of-detail default for a scheme that paints points.
"""

import json
import re

import pytest

from potato.server_utils.schemas.spatial_annotation import (
    _generate_internal, _keybindings)


def scheme(**overrides):
    base = {"annotation_type": "spatial_annotation", "name": "scan",
            "description": "Label the points", "tools": ["segment_3d"],
            "labels": [{"name": "road", "color": "#808080"}]}
    base.update(overrides)
    return base


def viewer_config(html):
    """The JSON object the inline bootstrap hands PointCloudAnnotationManager."""
    match = re.search(r"'input-scan',\s*(\{.*?\})\);", html, re.S)
    return json.loads(match.group(1))


def test_paint_controls_render_only_for_a_painting_scheme():
    html, _ = _generate_internal(scheme())
    assert 'class="pc-paint"' in html
    assert 'data-paint-mode="lasso"' in html
    html, _ = _generate_internal(scheme(tools=["cuboid_3d"]))
    assert 'class="pc-paint"' not in html


def test_brush_size_reaches_the_viewer_and_the_slider():
    html, _ = _generate_internal(scheme(brush_size=24))
    assert viewer_config(html)["brushSize"] == 24
    assert 'class="pc-brush-slider" min="2" max="80"' in html
    assert 'step="1" value="24"' in html
    assert viewer_config(_generate_internal(scheme())[0])["brushSize"] == 10


def test_brush_size_out_of_range_is_clamped_with_a_warning(caplog):
    with caplog.at_level("WARNING"):
        html, _ = _generate_internal(scheme(brush_size=500))
    assert viewer_config(html)["brushSize"] == 80
    assert "brush_size 500 is outside 2-80 px" in caplog.text


@pytest.mark.parametrize("bad", ["big", True, [10], float("inf"), float("nan")])
def test_brush_size_must_be_a_number(bad):
    with pytest.raises(ValueError, match="brush_size must be a number"):
        _generate_internal(scheme(brush_size=bad))


@pytest.mark.parametrize("tools, lod, expected", [
    (["segment_3d"], None, False),               # paint every point
    (["segment_3d", "cuboid_3d"], None, False),
    (["segment_3d"], True, True),                # asked for: honoured
    (["cuboid_3d"], None, True),                 # unchanged for boxes
    (["cuboid_3d"], False, False),
])
def test_lod_defaults_off_for_a_painting_scheme(tools, lod, expected):
    overrides = {"tools": tools}
    if lod is not None:
        overrides["lod"] = lod
    html, _ = _generate_internal(scheme(**overrides))
    assert viewer_config(html)["lod"] is expected


def test_painting_keys_are_published_only_when_painting():
    labels = [{"name": "road", "color": "#808080"}]
    keys = {b["key"] for b in _keybindings(labels, ["segment_3d"], "scan")}
    assert {"Shift + drag", "Alt + drag", "- / ="} <= keys
    keys = {b["key"] for b in _keybindings(labels, ["cuboid_3d"], "scan")}
    assert "Shift + drag" not in keys
