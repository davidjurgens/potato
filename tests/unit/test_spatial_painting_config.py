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


def test_h_is_published_and_a_class_bound_to_it_warns(caplog):
    labels = [{"name": "road", "color": "#808080", "key_value": "h"}]
    with caplog.at_level("WARNING"):
        keys = {b["key"] for b in _keybindings(labels, ["cuboid_3d"], "scan")}
    assert "h / Shift+H" in keys
    assert "uses key 'h', which is already a viewer shortcut" in caplog.text


def warnings_for(caplog, key, tools=("cuboid_3d",), labels=None):
    labels = labels or [{"name": "road", "color": "#808080", "key_value": key}]
    caplog.clear()
    with caplog.at_level("WARNING"):
        _keybindings(labels, list(tools), "scan")
    return [r.getMessage() for r in caplog.records]


# What the viewer's _bindKeys takes before the class keys, written out here
# rather than read from VIEWER_KEYS so dropping an entry there fails a test.
ALWAYS = [",", ".", "h", "H"]
SELECTED = "an annotation is selected"
WHEN = {**dict.fromkeys(["q", "Q", "e", "E", "Delete", "Backspace", "Escape"], SELECTED),
        "[": "the scan is a sequence", "]": "the scan is a sequence",
        "f": "an annotation in a sequence is selected",
        "F": "an annotation in a sequence is selected"}
PAINTING = ["-", "_", "=", "+"]


@pytest.mark.parametrize("key", ALWAYS)
def test_a_class_on_a_key_the_viewer_always_takes_warns(caplog, key):
    [message] = warnings_for(caplog, key)
    assert message.endswith(f"uses key '{key}', which is already a viewer shortcut. "
                            "The viewer keeps the key; click the class button instead.")


@pytest.mark.parametrize("key, when", sorted(WHEN.items()))
def test_a_class_on_a_conditional_viewer_key_warns_with_the_condition(caplog, key, when):
    [message] = warnings_for(caplog, key)
    assert f"The viewer keeps the key while {when};" in message


@pytest.mark.parametrize("key", PAINTING)
def test_brush_keys_are_taken_only_when_painting(caplog, key):
    assert warnings_for(caplog, key, tools=["cuboid_3d"]) == []
    [message] = warnings_for(caplog, key, tools=["segment_3d"])
    assert "while the paint tool is armed" in message


def test_two_classes_on_one_key_name_both(caplog):
    labels = [{"name": "car", "color": "#f00", "key_value": "1"},
              {"name": "road", "color": "#00f", "key_value": 1}]
    [message] = warnings_for(caplog, None, labels=labels)
    assert "labels 'car' and 'road' both use key '1'. The first keeps it" in message


def test_a_free_key_does_not_warn(caplog):
    assert warnings_for(caplog, "1") == []


def test_the_0_key_is_a_key():
    labels = [{"name": "road", "color": "#808080", "key_value": 0}]
    bindings = _keybindings(labels, ["cuboid_3d"], "scan")
    assert {"key": "0", "description": "Select road"} in bindings
