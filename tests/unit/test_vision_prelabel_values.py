"""Vision predictions as prelabel input values, with what a widget cannot
show left out (audit 102). A widget handed a box of width -3, a ROI on a
plane the stack does not have, or a verdict it does not offer repaired it as
it drew, the repair changed its input, and the page saved the repaired
prediction as the annotator's answer the moment it opened."""

import json
import os

import pytest

from potato.server_utils.prelabel_values import client_shapes, prelabel_values, valid_shape

BOX = {"type": "bbox", "label": "damaged",
       "coordinates": {"x": 0.1, "y": 0.1, "width": 0.3, "height": 0.3}}


def test_valid_shapes():
    assert valid_shape(BOX)
    assert not valid_shape(dict(BOX, coordinates=dict(BOX["coordinates"], width=-3)))
    assert not valid_shape(dict(BOX, coordinates=dict(BOX["coordinates"], x=float("nan"))))
    assert not valid_shape(dict(BOX, coordinates=dict(BOX["coordinates"], x=0.9)))  # off the edge
    assert not valid_shape(dict(BOX, type="hexagon"))
    assert valid_shape(BOX, ["damaged"]) and not valid_shape(BOX, ["debris"])
    triangle = {"type": "polygon", "coordinates": [{"x": 0, "y": 0}, {"x": 1, "y": 0},
                                                   {"x": 0.5, "y": 1}]}
    assert valid_shape(triangle) and not valid_shape(dict(triangle, coordinates=triangle[
        "coordinates"][:2]))


def test_microscopy_rois_are_checked_against_labels_and_planes(tmp_path):
    scheme = {"annotation_type": "microscopy", "name": "cells", "labels": [{"name": "damaged"}]}
    payload = {"rois": [dict(BOX, z=0, t=1),
                        dict(BOX, z=0, t=7),                       # past the stack
                        dict(BOX, label="Nope", z=0, t=0),
                        dict(BOX, z=-1, t=0),
                        dict(BOX, coordinates=dict(BOX["coordinates"], width=-3))]}
    # Without the image, planes cannot be checked, the rest can.
    (value,) = prelabel_values(scheme, payload).values()
    assert [(r["z"], r["t"]) for r in json.loads(value)["rois"]] == [(0, 1), (0, 7)]

    tifffile = pytest.importorskip("tifffile")
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "mic_gen", os.path.join(os.path.dirname(__file__), "..", "..", "examples",
                                "image", "multichannel-microscopy", "generate_data.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    os.makedirs(tmp_path / "media")
    module.write_tiff(str(tmp_path / "media" / "s.ome.tif"),
                      str(tmp_path / "media" / "s_cells.tif"), size=32, timepoints=2)
    config = {"task_dir": str(tmp_path), "media_directory": "media"}
    (value,) = prelabel_values(scheme, payload, {"image": "s.ome.tif"}, config).values()
    assert [(r["z"], r["t"]) for r in json.loads(value)["rois"]] == [(0, 1)]


def test_gui_verdicts_must_be_offered_and_on_a_step():
    scheme = {"annotation_type": "gui_trajectory", "name": "gui"}
    item = {"steps": [{"action": "a"}, {"action": "b"}]}
    (value,) = prelabel_values(scheme, [
        {"index": 0, "verdict": "correct"}, {"index": 1, "verdict": "maybe"},
        {"index": 5, "verdict": "wrong_element"}], item).values()
    assert json.loads(value) == [{"index": 0, "step": 0, "verdict": "correct", "notes": ""}]


def test_grounding_and_caption_regions_are_checked():
    ground = {"annotation_type": "grounding_eval", "name": "g"}
    bad = dict(BOX, coordinates=dict(BOX["coordinates"], height=0))
    value = json.loads(prelabel_values(ground, {"regions": {"0": [BOX], "1": [bad]},
                                                "absent": ["2"]})["_data"])
    assert value["regions"] == {"0": [BOX]} and value["absent"] == ["2"]
    assert prelabel_values(ground, {"regions": {"1": [bad]}}) is None
    caption = {"annotation_type": "region_caption", "name": "c"}
    value = json.loads(prelabel_values(caption, {"captions": [
        {"region": BOX, "caption": "a mug"}, {"region": bad, "caption": "nothing"},
        {"region": BOX, "caption": None}]})["_data"])
    assert value == {"captions": [{"region": BOX, "caption": "a mug"}]}


def test_canvas_shapes_are_converted_or_left_out():
    """A normalized points-form polygon passed through and the canvas
    dropped it at load, so the next edit saved the item without it."""
    shapes, dropped = client_shapes([
        {"type": "polygon", "label": "object", "points": [[0.5, 0.5], [0.8, 0.5], [0.7, 0.8]]},
        {"type": "bbox", "label": "object", "bbox": [0.1, 0.1, 0.2, 0.2]},
        {"type": "polygon", "label": "object", "points": "x"},
        {"type": "bbox"},
        dict(BOX, label="object"),
        {"type": "keypoint_set", "label": "object", "coordinates": [{"x": 0.1, "y": 0.1, "v": 2}]},
    ], ["object"])
    assert dropped == 2
    assert shapes[0]["coordinates"] == [{"x": 0.5, "y": 0.5}, {"x": 0.8, "y": 0.5},
                                        {"x": 0.7, "y": 0.8}]
    assert shapes[1]["coordinates"] == {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2}
    assert [s["type"] for s in shapes] == ["polygon", "bbox", "bbox", "keypoint_set"]


def test_absent_ids_keep_strings_and_numbers_only():
    value = json.loads(prelabel_values({"annotation_type": "grounding_eval", "name": "g"},
                                       {"regions": {"0": [BOX]}, "absent": [1, None, "2", True]})
                       ["_data"])
    assert value["absent"] == ["1", "2"]
