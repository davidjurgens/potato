"""Acquisition scores, and the order llm_confidence serves items in when a
trainer writes them."""

import json
import os
import types
from pathlib import Path

import pytest

from potato.training import acquisition, worker
from potato.training.base import ResourceLimits, TrainingSpec
from potato.training.dataset import build_bundle, schema_specs_from_config
from potato.training.events import EXIT_OK, CollectingReporter
from tests.helpers.test_utils import create_test_directory

HAVE_HF = all(__import__("importlib").util.find_spec(m) for m in
              ("torch", "transformers", "tokenizers"))
needs_hf = pytest.mark.skipif(not HAVE_HF, reason="torch/transformers absent")


def test_uncertainty_scores():
    assert acquisition.uncertainty([0.9, 0.1], "least_confident") == pytest.approx(0.1)
    assert acquisition.uncertainty([0.5, 0.4, 0.1], "margin") == pytest.approx(0.9)
    assert acquisition.uncertainty([0.5, 0.5], "entropy") == pytest.approx(1.0)
    assert acquisition.uncertainty([1.0, 0.0], "entropy") == 0.0


def test_bald_separates_disagreeing_samples_from_an_ambiguous_item():
    # Every sample says 50/50: the item is ambiguous, more data will not help.
    assert acquisition.bald([[0.5, 0.5]] * 4) == pytest.approx(0.0)
    # Samples confidently disagree: the model does not know yet.
    assert acquisition.bald([[1.0, 0.0], [0.0, 1.0]] * 2) == pytest.approx(1.0)


def test_coreset_spreads_out_and_scores_fall_in_picking_order():
    labelled = [[0.0, 0.0]]
    candidates = [[0.1, 0.0], [0.11, 0.0], [5.0, 0.0], [2.5, 0.0]]
    scores = acquisition.coreset_scores(candidates, labelled)
    assert scores[2] == 1.0                    # farthest from the labelled point
    assert scores[3] > scores[1] > scores[0]   # then the middle, then the pair
    # Once one of two near-copies is picked, the other scores almost nothing.
    assert scores[0] < 0.01


def test_llm_confidence_orders_by_acquisition_when_present():
    from potato import model_review
    summaries = {
        "a": model_review.summarize_predictions(
            "a", {"predictions": {"s": {"label": "x", "confidence": 0.2}}}, "predictions"),
        "b": model_review.summarize_predictions(
            "b", {"predictions": {"s": {"label": "x", "confidence": 0.9,
                                        "acquisition": 0.8}}}, "predictions"),
        "c": model_review.summarize_predictions(
            "c", {"predictions": {"s": {"label": "x", "confidence": 0.6,
                                        "acquisition": 0.3}}}, "predictions"),
    }
    assert summaries["b"].max_acquisition == 0.8 and summaries["a"].max_acquisition is None

    from potato.item_state_management import ItemStateManager
    manager = ItemStateManager.__new__(ItemStateManager)
    manager.config = {"annotation_schemes": [{"name": "s"}]}
    manager.remaining_instance_ids = ["a", "b", "c"]
    items = {iid: types.SimpleNamespace(get_data=lambda iid=iid: {
        "predictions": {"s": {"a": {"label": "x", "confidence": 0.2},
                              "b": {"label": "x", "confidence": 0.9, "acquisition": 0.8},
                              "c": {"label": "x", "confidence": 0.6,
                                    "acquisition": 0.3}}[iid]}}) for iid in "abc"}
    manager._store = types.SimpleNamespace(get=items.get)
    manager._item_is_complete = lambda iid: False
    manager._item_is_saturated = lambda iid: False
    manager._already_with_user = lambda user, iid: False
    # Acquisition scores first, highest first; then confidence-only items.
    assert manager._llm_confidence_candidates(None) == ["b", "c", "a"]


@needs_hf
@pytest.mark.parametrize("method", ["margin", "bald", "coreset"])
def test_text_classifier_writes_acquisition_scores(method, request):
    from tests.helpers.tiny_hf import tiny_encoder
    from tests.unit.test_training_trainers import POS, NEG, sentiment_project
    work = Path(create_test_directory("acq_" + request.node.name))
    config, context = sentiment_project(work)
    bundle, _, _ = build_bundle(context, str(work / "bundle"), ["s"], split_seed=1)
    spec = TrainingSpec(
        run_id="r1", trainer="hf-text-classification",
        schemas=schema_specs_from_config(config, ["s"], bundle.manifest["labels"]),
        bundle_dir=bundle.root, workdir=str(work / "artifacts"),
        params={"epochs": 3, "batch_size": 8, "learning_rate": 3e-3, "min_instances": 4,
                "patience": None, "acquisition": method, "mc_samples": 3,
                # Digits in the vocabulary: the items differ by a number, and
                # as [UNK] every held-out item was a copy of a training one.
                "model_name": tiny_encoder(str(work / "m"),
                                           POS + NEG + [str(d) for d in range(10)])},
        seed=3, limits=ResourceLimits(device="cpu"))
    report = CollectingReporter()
    assert worker.run(spec, report) == EXIT_OK
    with open(os.path.join(spec.workdir, "predictions.jsonl")) as fh:
        payloads = [json.loads(line)["payload"] for line in fh if line.strip()]
    scores = [p["acquisition"] for p in payloads]
    assert all(0.0 <= s <= 1.0 for s in scores)
    assert len(set(scores)) > 1, "every item scored the same"


@needs_hf
@pytest.mark.parametrize("method", ["entropy", "bald", "coreset"])
def test_image_classifier_writes_acquisition_scores(method, request):
    pytest.importorskip("PIL")
    from tests.helpers.tiny_hf import colour_images, tiny_vit
    from tests.unit.test_training_trainers import _context
    work = Path(create_test_directory("acq_img_" + request.node.name))
    images = colour_images(str(work / "images"), 40)
    items, annotations = {}, []
    for n, (path, label) in enumerate(images):
        iid = "i%02d" % n
        items[iid] = {"id": iid, "image": os.path.relpath(path, work)}
        annotations.append({"instance_id": iid, "user_id": "a",
                            "labels": {"c": {label: True}}})
    scheme = {"annotation_type": "radio", "name": "c", "labels": ["red", "blue"]}
    config, context = _context(work, [scheme], items, annotations)
    config["item_properties"]["text_key"] = "image"
    bundle, _, _ = build_bundle(context, str(work / "bundle"), ["c"], split_seed=1)
    spec = TrainingSpec(
        run_id="r1", trainer="hf-image-classification",
        schemas=schema_specs_from_config(config, ["c"], bundle.manifest["labels"]),
        bundle_dir=bundle.root, workdir=str(work / "artifacts"),
        params={"epochs": 2, "batch_size": 8, "learning_rate": 3e-3, "min_instances": 4,
                "patience": None, "acquisition": method, "mc_samples": 3,
                "model_name": tiny_vit(str(work / "m"))},
        seed=3, limits=ResourceLimits(device="cpu"))
    report = CollectingReporter()
    assert worker.run(spec, report) == EXIT_OK, [e["msg"] for e in report.of_type("log")][-3:]
    with open(os.path.join(spec.workdir, "predictions.jsonl")) as fh:
        payloads = [json.loads(line)["payload"] for line in fh if line.strip()]
    scores = [p["acquisition"] for p in payloads]
    assert all(0.0 <= s <= 1.0 for s in scores) and len(set(scores)) > 1
    assert set(payloads[0]["probabilities"]) == {"red", "blue"}
    if method == "bald":
        # ViT has no dropout: every Monte Carlo pass agrees, so BALD would
        # score every image 0. The run says so and uses entropy.
        assert any("bald needs dropout" in e["msg"] for e in report.of_type("log"))


def test_coreset_in_numpy_matches_the_reference_and_scales():
    """Pure Python is O(n^2 d): 400 candidates took 4.4 s and 5,000 would
    take minutes. The numpy path must pick in the same order."""
    import random
    import time
    from potato.training import acquisition
    rng = random.Random(4)
    points = [[rng.gauss(0, 1) for _ in range(8)] for _ in range(60)]
    known = [[rng.gauss(0, 1) for _ in range(8)] for _ in range(5)]
    for labelled in (known, []):
        assert acquisition._coreset_numpy(points, labelled) == pytest.approx(
            acquisition._coreset_python(points, labelled), abs=1e-6)
    many = [[rng.gauss(0, 1) for _ in range(256)] for _ in range(1500)]
    started = time.time()
    scores = acquisition.coreset_scores(many, known and [[0.0] * 256])
    assert len(scores) == 1500 and max(scores) == 1.0
    assert time.time() - started < 5      # pure Python: about 20 s
