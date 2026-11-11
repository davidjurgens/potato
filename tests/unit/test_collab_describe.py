"""The Activity panel's lines: what one edit to a team's answer did.

Each line is read by a teammate deciding whether to look, so it names the
kind and label of what changed, not the stored JSON.
"""

import json

from potato.collab.describe import describe_ops
from potato.collab.state import label_key

CONFIG = {"annotation_schemes": [
    {"annotation_type": "radio", "name": "stance", "labels": ["pro", "con"]},
    {"annotation_type": "text", "name": "note"},
    {"annotation_type": "image_annotation", "name": "objects"},
    {"annotation_type": "tiered_annotation", "name": "tiers"},
    {"annotation_type": "video_annotation", "name": "clip"},
    {"annotation_type": "trajectory_eval", "name": "steps"},
]}


def op(schema, label, before, after):
    dump = lambda v: v if v is None or isinstance(v, str) else json.dumps(v)
    return {"key": label_key(schema, label), "before": dump(before), "after": dump(after)}


def lines(*ops):
    return describe_ops(list(ops), CONFIG)


def test_a_box_added_and_one_removed():
    before = [{"id": "a", "type": "bbox", "label": "car"}]
    after = [{"id": "b", "type": "bbox", "label": "dog"}]
    assert lines(op("objects", "_data", before, after)) == [
        "added bbox dog (objects)", "removed bbox car (objects)"]


def test_a_moved_box_is_a_change():
    before = [{"id": "a", "type": "bbox", "label": "car", "coordinates": [0, 0, 1, 1]}]
    after = [{"id": "a", "type": "bbox", "label": "car", "coordinates": [2, 2, 3, 3]}]
    assert lines(op("objects", "_data", before, after)) == ["changed bbox car (objects)"]


def test_annotations_inside_tiers_are_named_by_their_tier():
    before = {"annotations": {"words": [{"id": "w1", "value": "hi", "label": "hi"}]}}
    after = {"annotations": {"words": [{"id": "w1", "value": "hi", "label": "hi"},
                                       {"id": "w2", "label": "there"}]},
             "time_slots": {"ts0": 0}}
    assert lines(op("tiers", "_data", before, after)) == ["added word there (tiers)"]


def test_frame_annotations_kept_by_frame_are_elements():
    before = {"frame_annotations": {}}
    after = {"frame_annotations": {"12": {"frame": 12, "label": "goal"}}}
    assert lines(op("clip", "_data", before, after)) == ["added frame_annotation goal (clip)"]


def test_a_widgets_json_under_a_plain_label_is_described_not_quoted():
    before = {"steps": [{"step_index": 0, "verdict": "ok"}]}
    after = {"steps": [{"step_index": 0, "verdict": "bad"}]}
    out = lines(op("steps", "steps", before, after))
    assert out == ["changed step (steps)"]
    assert not any("{" in line for line in out)


def test_plain_values_still_read_as_before():
    assert lines(op("note", "text_box", None, "hello")) == ["note: set to 'hello'"]
    assert lines(op("stance", "pro", "pro", None), op("stance", "con", None, "con")) == [
        "stance: pro → con"]
