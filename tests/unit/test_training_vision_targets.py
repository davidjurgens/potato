"""Training targets and held-out metrics for the vision answers stored as
one JSON blob: microscopy, geo, region captions, grounding, GUI verdicts.

Before group 3 these reached the bundle as an opaque string. A grounding
scheme was classified for training and its target was always empty, so a
run skipped every item; the rest had no kind a trainer could declare.
"""

import base64
import io
import json
import os
import types

import pytest

from potato.training import registry
from potato.training.dataset import build_bundle
from potato.training.evaluation import HEADLINE, score_split
from potato.training import vision, vision_metrics


def _context(tmp, schemes, items, annotations):
    config = {"task_dir": str(tmp),
              "item_properties": {"id_key": "id", "text_key": "text"},
              "annotation_schemes": schemes}
    return config, types.SimpleNamespace(
        config=config, annotations=annotations, items=items, schemas=schemes,
        output_dir=str(tmp), phase_responses={})


def _rows(bundle):
    return [row for split in ("train", "val", "test")
            for row in bundle.read_split(split)]


def _png(tmp, name, size=(40, 20)):
    from PIL import Image
    path = os.path.join(str(tmp), name)
    Image.new("RGB", size, (9, 9, 9)).save(path)
    return name


BOX = {"type": "bbox", "label": "cat",
       "coordinates": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}}


def test_the_new_kinds():
    assert registry.kind_of_schema({"annotation_type": "microscopy"}) == "geometry"
    assert registry.kind_of_schema({"annotation_type": "geo_annotation"}) == "geo"
    assert registry.kind_of_schema({"annotation_type": "gui_trajectory"}) == "gui_click"
    assert registry.kind_of_schema({"annotation_type": "region_caption"}) == "caption"
    assert registry.kind_of_schema({"annotation_type": "grounding_eval"}) == "grounding"
    for kind in ("geo", "caption", "grounding", "gui_click"):
        assert kind in HEADLINE


def test_blob_reads_each_storage_convention():
    answer = {"captions": [{"region": BOX, "caption": "a cat"}]}
    assert vision.blob({"_data": json.dumps(answer)}) == answer
    assert vision.blob({"scheme": json.dumps(answer)}) == answer
    assert vision.blob(json.dumps([{"index": 0}])) == [{"index": 0}]
    # A single-key answer that is already parsed is the answer, not a map.
    assert vision.blob(answer) == answer
    assert vision.blob({"_data": answer}) == answer
    assert vision.blob({"_data": "not json"}) is None


def test_grounding_target_reads_the_blob_with_expression_text(tmp_path):
    """A grounding answer used to train as ``_objects``, which a blob never
    has: every item came out with no target."""
    scheme = {"annotation_type": "grounding_eval", "name": "g", "description": "",
              "region_type": "box"}
    canvas = {"annotation_type": "image_annotation", "name": "canvas",
              "description": "", "labels": ["referent"], "tools": ["bbox"],
              "source_field": "picture"}
    items, annotations = {}, []
    for n in range(6):
        iid = "g%d" % n
        items[iid] = {"id": iid, "picture": _png(tmp_path, "p%d.png" % n),
                      "expressions": ["the cat", "the dog", "the unicorn"]}
        annotations.append({"instance_id": iid, "user_id": "a", "labels": {"g": {
            "_data": json.dumps({"regions": {"0": [BOX], "1": []},
                                 "absent": ["2"], "region_type": "box"})}}})
    config, context = _context(tmp_path, [canvas, scheme], items, annotations)
    bundle, stats, _ = build_bundle(context, str(tmp_path / "b"), ["g"])
    rows = _rows(bundle)
    assert len(rows) == 6 and not stats.n_skipped_no_label
    target = rows[0]["targets"]["g"]
    # "the dog" was not answered (no region, not absent): left out.
    assert [(e["id"], e["text"], e["absent"]) for e in target["expressions"]] == [
        ("0", "the cat", False), ("2", "the unicorn", True)]
    assert target["expressions"][0]["regions"] == [BOX]
    # The companion canvas's source_field names the image.
    assert all(r.get("media") for r in rows)


def test_caption_target_and_companion_media(tmp_path):
    scheme = {"annotation_type": "region_caption", "name": "cap", "description": ""}
    canvas = {"annotation_type": "image_annotation", "name": "canvas",
              "description": "", "labels": ["object"], "tools": ["bbox"]}
    items = {"c1": {"id": "c1", "image": _png(tmp_path, "c.png")}}
    annotations = [{"instance_id": "c1", "user_id": "a", "labels": {"cap": {
        "_data": json.dumps({"captions": [{"region": BOX, "caption": "a red mug"},
                                          {"region": BOX, "caption": "  "}]})}}}]
    config, context = _context(tmp_path, [canvas, scheme], items, annotations)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["cap"],
                                split_spec={"train": 1.0})
    row = _rows(bundle)[0]
    assert row["targets"]["cap"] == [{"region": BOX, "caption": "a red mug"}]
    assert row["media"].endswith("c.png")


def test_microscopy_rois_are_geometry_targets(tmp_path):
    scheme = {"annotation_type": "microscopy", "name": "m", "description": "",
              "labels": ["damaged"]}
    roi = {"type": "polygon", "label": "damaged", "z": 2, "t": 0,
           "coordinates": [{"x": 0.1, "y": 0.1}, {"x": 0.3, "y": 0.1}, {"x": 0.2, "y": 0.4}]}
    items = {"m1": {"id": "m1", "image": "tissue.ome.tif"}}
    annotations = [{"instance_id": "m1", "user_id": "a", "labels": {"m": {
        "m": json.dumps({"image": {"width": 64, "height": 64}, "rois": [roi],
                         "cells": [{"label_id": 3, "class": "positive"}]})}}}]
    config, context = _context(tmp_path, [scheme], items, annotations)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["m"],
                                split_spec={"train": 1.0}, include_media=False)
    row = _rows(bundle)[0]
    assert row["targets"]["m"] == [roi]
    assert bundle.manifest["labels"]["m"] == ["damaged"]
    assert bundle.manifest["modality"] == "image"


def test_geo_target_keeps_labelled_features():
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 2]},
         "properties": {"label": "Well", "tool": "point", "text": ""}},
        {"type": "Feature", "geometry": None,
         "properties": {"region": "r1", "label": "Dry"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [3, 4]},
         "properties": {"label": ""}}]}
    assert vision.geo_target({"geo": json.dumps(fc)}) == [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 2]},
         "properties": {"label": "Well"}}]


def test_gui_steps_link_inline_screenshots_and_normalize_pixel_clicks(tmp_path):
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (200, 100), (1, 2, 3)).save(buffer, format="PNG")
    inline = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
    scheme = {"annotation_type": "gui_trajectory", "name": "gui", "description": "",
              "coord_space": "pixels"}
    items = {"t1": {"id": "t1", "steps": [
        {"screenshot": inline, "action": "click Save", "x": 50, "y": 25},
        {"screenshot": inline, "action": "type hello"}]}}
    annotations = [{"instance_id": "t1", "user_id": "a", "labels": {"gui": {
        "gui": json.dumps([{"index": 1, "verdict": "wrong_action", "notes": ""},
                           {"index": 0, "verdict": "correct", "notes": ""}])}}}]
    config, context = _context(tmp_path, [scheme], items, annotations)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["gui"],
                                split_spec={"train": 1.0})
    row = _rows(bundle)[0]
    assert row["targets"]["gui"] == [{"index": 0, "verdict": "correct"},
                                     {"index": 1, "verdict": "wrong_action"}]
    first, second = row["steps"]
    assert first["point"] == {"x": 0.25, "y": 0.25}
    assert second["point"] is None and second["action"] == "type hello"
    # Both steps share one screenshot, written once.
    assert first["media"] == second["media"]
    assert os.path.isfile(os.path.join(bundle.root, "media", first["media"]))
    assert sorted(bundle.manifest["labels"]["gui"]) == ["correct", "wrong_action"]


# ---------------------------------------------------------------- metrics

def test_caption_scores():
    gold = [[{"region": BOX, "caption": "a red mug"},
             {"region": BOX, "caption": "the old dog sleeps"}]]
    perfect = vision_metrics.score_captions(gold, [{"captions": [
        {"caption": "a red mug"}, {"caption": "the old dog sleeps"}]}])
    assert perfect["token_f1"] == 1.0 and perfect["bleu4"] == pytest.approx(1.0)
    # "red mug" against "a red mug": P 1, R 2/3, F1 0.8; the second region
    # was not captioned: 0. Mean 0.4.
    half = vision_metrics.score_captions(gold, [{"captions": [{"caption": "red mug"}]}])
    assert half["token_f1"] == pytest.approx(0.4)
    assert vision_metrics.score_captions(gold, [None])["token_f1"] == 0.0


def test_grounding_scores():
    target = {"region_type": "box", "expressions": [
        {"id": "0", "text": "cat", "regions": [BOX], "absent": False},
        {"id": "2", "text": "unicorn", "regions": [], "absent": True}]}
    exact = vision_metrics.score_grounding(
        [target], [{"regions": {"0": [BOX]}, "absent": ["2"]}])
    assert exact["accuracy"] == 1.0 and exact["absent_accuracy"] == 1.0
    shifted = dict(BOX, coordinates={"x": 0.25, "y": 0.2, "width": 0.3, "height": 0.4})
    # Overlap 0.15 of width 0.3 at equal height: IoU 0.15/0.45 = 1/3.
    miss = vision_metrics.score_grounding(
        [target], [{"regions": {"0": [shifted], "2": [BOX]}, "absent": []}])
    assert miss["accuracy"] == 0.0 and miss["acc_25"] == 1.0
    assert miss["mean_iou"] == pytest.approx(1 / 3)
    assert miss["absent_accuracy"] == 0.0


def test_pointing_scores_use_point_in_region():
    target = {"region_type": "point", "expressions": [
        {"id": "0", "text": "cat", "regions": [BOX], "absent": False}]}
    inside = {"type": "landmark", "coordinates": {"x": 0.2, "y": 0.3}}
    outside = {"type": "landmark", "coordinates": {"x": 0.9, "y": 0.9}}
    assert vision_metrics.score_grounding(
        [target], [{"regions": {"0": [inside]}}])["accuracy"] == 1.0
    assert vision_metrics.score_grounding(
        [target], [{"regions": {"0": [outside]}}])["accuracy"] == 0.0


def test_gui_click_scores():
    steps = [{"index": 0, "point": {"x": 0.5, "y": 0.5}},
             {"index": 1, "point": {"x": 0.1, "y": 0.1}}]
    gold = [[{"index": 0, "verdict": "correct"}, {"index": 1, "verdict": "wrong_element"}]]
    near = [[{"index": 0, "verdict": "correct", "point": {"x": 0.53, "y": 0.5}},
             {"index": 1, "verdict": "correct", "point": {"x": 0.6, "y": 0.6}}]]
    scores = vision_metrics.score_gui_clicks(gold, near, [steps])
    # Step 1 was judged wrong: scored on its verdict, never on its click.
    assert scores["n_clicks"] == 1 and scores["click_accuracy"] == 1.0
    assert scores["verdict_accuracy"] == 0.5
    far = [[{"index": 0, "verdict": "correct", "point": {"x": 0.6, "y": 0.5}}]]
    assert vision_metrics.score_gui_clicks(gold, far, [steps])["click_accuracy"] == 0.0


def test_score_split_routes_the_vision_kinds():
    rows = [{"instance_id": "1", "targets": {"cap": [{"region": BOX, "caption": "a mug"}]}}]
    metrics, n = score_split(rows, {("1", "cap"): {"captions": [{"caption": "a mug"}]}},
                             "cap", "caption")
    assert n == 1 and metrics["token_f1"] == 1.0 and metrics["coverage"] == 1.0
    rows = [{"instance_id": "1", "targets": {"gui": [{"index": 0, "verdict": "correct"}]},
             "steps": [{"index": 0, "point": {"x": 0.5, "y": 0.5}}]}]
    metrics, _ = score_split(rows, {("1", "gui"): [
        {"index": 0, "verdict": "correct", "point": {"x": 0.5, "y": 0.5}}]},
        "gui", "gui_click")
    assert metrics["click_accuracy"] == 1.0 and metrics["verdict_macro_f1"] == 1.0


def _ome_tiff(tmp):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "mic_gen", os.path.join(os.path.dirname(__file__), "..", "..", "examples",
                                "image", "multichannel-microscopy", "generate_data.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.write_tiff(str(tmp / "stack.ome.tif"), str(tmp / "stack_cells.tif"),
                      size=64, timepoints=3)
    return "stack.ome.tif"


def test_microscopy_planes_are_rendered_and_folded_back(tmp_path):
    """Each annotated (z, t) becomes a rendered RGB row; predictions per
    plane come back as one microscopy answer with each ROI's plane."""
    pytest.importorskip("tifffile")
    from potato.training import rasters
    source = _ome_tiff(tmp_path)
    scheme = {"annotation_type": "microscopy", "name": "m", "description": "",
              "labels": ["damaged"]}
    roi = {"type": "bbox", "label": "damaged",
           "coordinates": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2}}
    items = {"m1": {"id": "m1", "image": source}, "m2": {"id": "m2", "image": source}}
    annotations = [{"instance_id": "m1", "user_id": "a", "labels": {"m": {"m": json.dumps(
        {"image": {"width": 64, "height": 64},
         "rois": [dict(roi, z=0, t=0), dict(roi, z=0, t=2)]})}}}]
    config, context = _context(tmp_path, [scheme], items, annotations)
    bundle, stats, split_ids = build_bundle(context, str(tmp_path / "b"), ["m"],
                                            split_spec={"train": 1.0},
                                            include_unlabeled=True)
    assert split_ids["train"] == ["m1"] and not stats.warnings
    rows = list(bundle.read_split("train"))
    assert sorted(r["instance_id"] for r in rows) == ["m1@z0t0", "m1@z0t2"]
    from PIL import Image
    for row in rows:
        assert row["plane_of"] == "m1" and row["targets"]["m"] == [roi]
        with Image.open(os.path.join(bundle.root, "media", row["media"])) as plane:
            assert plane.mode == "RGB" and plane.size == (64, 64)
    unlabeled = list(bundle.read_split("unlabeled"))
    assert [r["instance_id"] for r in unlabeled] == ["m2@z0t0"]
    # The link to the stack itself is gone: a remote run must not download it.
    linked = [f for d in os.listdir(os.path.join(bundle.root, "media"))
              if d != "planes" for f in os.listdir(os.path.join(bundle.root, "media", d))]
    assert linked == []

    path = str(tmp_path / "predictions.jsonl")
    with open(path, "w") as fh:
        for iid, conf in (("m1@z0t0", 0.8), ("m1@z0t2", 0.6), ("m2@z0t0", 0.9)):
            fh.write(json.dumps({"instance_id": iid, "schema_name": "m",
                                 "payload": [dict(roi, confidence=conf)],
                                 "confidence": conf}) + "\n")
    assert rasters.finalize_file(bundle, path) == 2
    with open(path) as fh:
        records = {r["instance_id"]: r for r in map(json.loads, fh)}
    answer = records["m1"]["payload"]
    assert answer["image"] == {"width": 64, "height": 64}
    assert sorted((r["z"], r["t"]) for r in answer["rois"]) == [(0, 0), (0, 2)]
    assert records["m1"]["confidence"] == pytest.approx(0.7)
    assert not records["m1"].get("heldout_only")

    # A plane predicted from an annotator's own answer (sam-finetune's
    # held-out prompts) keeps the item's answer out of write-back.
    with open(path, "w") as fh:
        for iid, flag in (("m1@z0t0", False), ("m1@z0t2", True)):
            fh.write(json.dumps({"instance_id": iid, "schema_name": "m",
                                 "payload": [dict(roi, confidence=0.5)], "confidence": 0.5,
                                 "heldout_only": flag}) + "\n")
    rasters.finalize_file(bundle, path)
    with open(path) as fh:
        (record,) = [json.loads(line) for line in fh]
    assert record["instance_id"] == "m1" and record["heldout_only"] is True
