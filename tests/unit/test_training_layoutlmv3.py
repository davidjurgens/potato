"""layoutlmv3: words labelled by the regions drawn around them, and
predicted words merged back into region boxes.

The pages are synthetic forms: a title line at the top and a total line at
the bottom, so position alone separates the two labels. A tiny LayoutLMv3
built from a config (tests/helpers/tiny_hf.py) learns that.
"""

import os
import random

import pytest

from potato.training import registry
from potato.training.dataset import build_bundle
from potato.training.events import EXIT_OK
from potato.training.trainers.layoutlmv3 import page_words, regions_from_tags, word_tags
from tests.unit.test_training_detection_audio_dpo import _context, _predictions, _run, _spec

HAVE = __import__("importlib").util.find_spec
needs_torch = pytest.mark.skipif(not (HAVE("torch") and HAVE("transformers")),
                                 reason="torch/transformers absent")

TITLES = ["invoice", "receipt", "statement", "order"]
TOTALS = ["total", "amount", "due", "balance"]


def _box(x, y, w, h, label):
    return {"type": "bbox", "label": label,
            "coordinates": {"x": x, "y": y, "width": w, "height": h}}


def form_project(tmp, n=16):
    from PIL import Image
    rng = random.Random(0)
    os.makedirs(tmp / "pages", exist_ok=True)
    items, annotations = {}, []
    for i in range(n):
        path = tmp / "pages" / ("p%02d.png" % i)
        Image.new("RGB", (200, 260), (255, 255, 255)).save(path)
        title = [rng.choice(TITLES), rng.choice(TITLES)]
        total = [rng.choice(TOTALS), rng.choice(TOTALS)]
        words = ([{"text": t, "bbox": [20 + 60 * k, 20, 70 + 60 * k, 40]}
                  for k, t in enumerate(title)]
                 + [{"text": t, "bbox": [20 + 60 * k, 220, 70 + 60 * k, 240]}
                    for k, t in enumerate(total)])
        iid = "f%02d" % i
        items[iid] = {"id": iid, "image": "pages/p%02d.png" % i, "words": words}
        annotations.append({"instance_id": iid, "user_id": "a", "labels": {},
                            # Drawn around the words, 2 px out.
                            "image_annotations": {"layout": [
                                _box(18 / 200, 18 / 260, 114 / 200, 24 / 260, "title"),
                                _box(18 / 200, 218 / 260, 114 / 200, 24 / 260, "total")]}})
    scheme = {"annotation_type": "image_annotation", "name": "layout", "description": "",
              "labels": ["title", "total"], "tools": ["bbox"]}
    config, context = _context(tmp, [scheme], items, annotations)
    config["item_properties"]["text_key"] = "image"
    return config, context


def test_words_are_tagged_by_the_smallest_region_around_them():
    words = page_words({"words": [{"text": "a", "bbox": [10, 10, 20, 20]},
                                  {"text": "b", "bbox": [30, 10, 40, 20]},
                                  {"text": "c", "bbox": [10, 80, 20, 90]},
                                  {"text": "", "bbox": [0, 0, 1, 1]}]}, 100, 100)
    assert [w for w, _ in words] == ["a", "b", "c"]
    assert words[0][1] == pytest.approx((0.1, 0.1, 0.2, 0.2))
    page = _box(0, 0, 1, 1, "page")
    header = _box(0.05, 0.05, 0.4, 0.2, "header")
    assert word_tags(words, [page, header], ["page", "header"]) == [
        "B-header", "I-header", "B-page"]
    # Not a label of this scheme: as if not drawn.
    assert word_tags(words, [header], ["page"]) == ["O", "O", "O"]


def test_tags_merge_into_one_box_per_run():
    words = [("a", (0.1, 0.1, 0.2, 0.2)), ("b", (0.3, 0.1, 0.4, 0.25)),
             ("c", (0.1, 0.5, 0.2, 0.6)), ("d", (0.3, 0.5, 0.4, 0.6))]
    regions = regions_from_tags(words, ["B-x", "I-x", "B-x", "O"], [0.9, 0.7, 0.6, 0.9], "v")
    assert len(regions) == 2
    first = next(r for r in regions if r["confidence"] == 0.8)
    assert first["coordinates"] == pytest.approx(
        {"x": 0.1, "y": 0.1, "width": 0.3, "height": 0.15})
    assert first["label"] == "x" and first["source"] == "ai"


def test_it_asks_for_the_licence():
    listed = {r["name"]: r for r in registry.list_trainers()}
    assert listed["layoutlmv3"]["licence_ack"] is True
    assert listed["layoutlmv3"]["commercial_use"] is False


def test_bundle_rows_carry_the_words(tmp_path):
    config, context = form_project(tmp_path, n=4)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["layout"],
                                split_spec={"train": 1.0})
    row = next(bundle.read_split("train"))
    assert len(row["words"]) == 4 and row["words"][0]["bbox"] == [20, 20, 70, 40]


@needs_torch
def test_fit_predict_and_score(tmp_path):
    from tests.helpers.tiny_hf import tiny_layoutlmv3
    model_dir = tiny_layoutlmv3(str(tmp_path / "model"), TITLES + TOTALS)
    config, context = form_project(tmp_path)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["layout"], split_seed=2)
    spec = _spec(tmp_path, config, bundle, "layoutlmv3", "layout",
                 {"model_name": model_dir, "epochs": 30, "batch_size": 4,
                  "learning_rate": 3e-3, "min_instances": 4, "max_length": 32,
                  "patience": None})
    code, result, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    metrics = result["metrics"]
    assert metrics["heldout_metric"].endswith("map_50")
    records = _predictions(spec)
    assert records
    labels = {o["label"] for r in records for o in r["payload"]}
    assert labels <= {"title", "total"} and labels
    # Position decides the label here, and the boxes span the words: the
    # model gets both regions right on held-out pages.
    assert metrics["heldout_score"] > 0.5
