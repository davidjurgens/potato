"""sam-finetune: SAM's mask decoder fitted on the study's outlines, then
used to turn boxes into outlines.

A tiny SAM built from a config (tests/helpers/tiny_hf.py), so nothing
downloads. The data are discs on a dark ground; a box around each disc
should come back as an outline of the disc.
"""

import json
import os

import numpy
import pytest

from potato.training.dataset import build_bundle
from potato.training.events import EXIT_OK
from potato.training.writeback import ingest_predictions
from tests.unit.test_training_cellpose import cells
from tests.unit.test_training_detection_audio_dpo import _context, _predictions, _run, _spec

HAVE = __import__("importlib").util.find_spec
needs_torch = pytest.mark.skipif(not (HAVE("torch") and HAVE("transformers")),
                                 reason="torch/transformers absent")


def disc_project(tmp, n=10, prior_for=()):
    images = cells(str(tmp / "img"), n)
    items, annotations = {}, []
    for i, (path, objects) in enumerate(images):
        iid = "d%02d" % i
        items[iid] = {"id": iid, "image": os.path.relpath(path, tmp)}
        if iid in prior_for:
            # A detector's box around each disc, already written back.
            items[iid]["predictions"] = {"discs": [
                {"type": "bbox", "label": "nucleus", "source": "ai", "confidence": 0.8,
                 "coordinates": {"x": min(p["x"] for p in o["coordinates"]),
                                 "y": min(p["y"] for p in o["coordinates"]),
                                 "width": 16 / 64, "height": 16 / 64}} for o in objects]}
            continue
        annotations.append({"instance_id": iid, "user_id": "a", "labels": {},
                            "image_annotations": {"discs": objects}})
    scheme = {"annotation_type": "image_annotation", "name": "discs",
              "description": "", "labels": ["nucleus"], "tools": ["polygon"]}
    config, context = _context(tmp, [scheme], items, annotations)
    config["item_properties"]["text_key"] = "image"
    return config, context


def test_prior_boxes_ride_along_and_are_clipped_per_tile(tmp_path):
    config, context = disc_project(tmp_path, n=6, prior_for=("d05",))
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["discs"],
                                split_spec={"train": 1.0}, include_unlabeled=True)
    unlabeled = list(bundle.read_split("unlabeled"))
    assert [r["instance_id"] for r in unlabeled] == ["d05"]
    assert len(unlabeled[0]["prior"]) == 2 and unlabeled[0]["prior"][0]["type"] == "bbox"
    config["model_training"] = {"tiling": {"enabled": True, "tile_size": 32, "overlap": 8}}
    bundle, _, _ = build_bundle(context, str(tmp_path / "t"), ["discs"],
                                split_spec={"train": 1.0}, include_unlabeled=True)
    tiles = list(bundle.read_split("unlabeled"))
    with_prior = [t for t in tiles if t.get("prior")]
    assert with_prior and all(0 <= b["coordinates"]["x"] <= 1
                              for t in with_prior for b in t["prior"])


@needs_torch
def test_fit_refines_boxes_and_keeps_answer_prompted_predictions_private(tmp_path):
    from tests.helpers.tiny_hf import tiny_sam
    model_dir = tiny_sam(str(tmp_path / "sam"))
    config, context = disc_project(tmp_path, n=12, prior_for=("d11",))
    bundle, _, split_ids = build_bundle(context, str(tmp_path / "b"), ["discs"],
                                        split_seed=4, include_unlabeled=True)
    # A tiny SAM predicts a 16x16 mask for a 64-pixel image, so it learns
    # slowly: 60 epochs reach a val mask IoU near 0.3 alone, 0.14 inside the
    # whole unit run (0 after 3).
    spec = _spec(tmp_path, config, bundle, "sam-finetune", "discs",
                 {"model_name": model_dir, "epochs": 60, "min_instances": 4,
                  "learning_rate": 3e-3, "patience": None})
    code, result, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    assert result["metrics"]["val_mask_iou"] > 0.1
    assert result["metrics"]["heldout_metric"].endswith("map_50")
    records = {r["instance_id"]: r for r in _predictions(spec)}
    # The unlabelled item was prompted with its prior boxes: publishable.
    assert "d11" in records and not records["d11"].get("heldout_only")
    shape = records["d11"]["payload"][0]
    assert shape["type"] == "polygon" and shape["source"] == "ai"
    # Held-out items were prompted with an annotator's boxes: scored only.
    heldout = [i for s in ("val", "test") for i in split_ids.get(s, [])]
    assert heldout and all(records[i]["heldout_only"] for i in heldout if i in records)

    from unittest.mock import MagicMock, patch
    config["model_training"] = {"writeback": {"schemas": ["discs"]}}
    items = MagicMock()
    items.set_prediction.return_value = True
    with patch("potato.training.writeback.store") as store:
        store.training_split_ids.return_value = set(split_ids["train"])
        store.all_training_split_ids.return_value = set()
        writeback = ingest_predictions(
            type("Run", (), {"run_id": "r1"})(),
            os.path.join(spec.workdir, "predictions.jsonl"), config, items)
        stored = [row[0] for call in store.record_predictions.call_args_list
                  for row in call.args[2]]
    assert writeback.n_skipped_heldout_only == len([i for i in heldout if i in records])
    assert stored == ["d11"]
    assert [c.args[0] for c in items.set_prediction.call_args_list] == ["d11"]
