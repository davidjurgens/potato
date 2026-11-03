"""Learning from disagreement: soft targets in hf-text-classification, and
soft-label schemes trained as distributions.

The behaviour that matters is the one a hard label cannot produce: on items
the annotators split evenly, a model trained on their vote split should be
unsure, where one trained on the voted label is confidently whichever label
the vote happened to keep.
"""

import json
import os
import types
from pathlib import Path

import pytest

from potato.training import worker
from potato.training.base import ResourceLimits, TrainingSpec
from potato.training.dataset import build_bundle, schema_specs_from_config
from potato.training.events import EXIT_OK, CollectingReporter
from tests.helpers.test_utils import create_test_directory

HAVE_HF = all(__import__("importlib").util.find_spec(m) for m in
              ("torch", "transformers", "tokenizers"))
needs_hf = pytest.mark.skipif(not HAVE_HF, reason="torch/transformers absent")

POS = ["great movie loved it", "wonderful film excellent", "so good enjoyed",
       "great charming work", "loved excellent film", "a delight"]
NEG = ["terrible movie hated it", "awful film poor", "so bad disliked",
       "poor tedious work", "hated dreadful film", "a chore"]
MEH = ["an ordinary film", "a middling movie", "average work", "plain film",
       "a so so movie", "unremarkable work"]
TRAIN = {"epochs": 30, "batch_size": 8, "learning_rate": 3e-3,
         "min_instances": 4, "patience": None}


@pytest.fixture
def work(request):
    return Path(create_test_directory("soft_" + request.node.name))


def _context(work, scheme, items, annotations):
    config = {"task_dir": str(work),
              "item_properties": {"id_key": "id", "text_key": "text"},
              "annotation_schemes": [scheme]}
    return config, types.SimpleNamespace(
        config=config, annotations=annotations, items=items, schemas=[scheme],
        output_dir=str(work), phase_responses={})


def _fit(work, config, context, name, **extra):
    from tests.helpers.tiny_hf import tiny_encoder
    bundle, _, _ = build_bundle(context, str(work / "bundle"), [name], split_seed=1)
    params = dict(TRAIN, model_name=tiny_encoder(str(work / "m"), POS + NEG + MEH),
                  **extra)
    spec = TrainingSpec(
        run_id="r1", trainer="hf-text-classification",
        schemas=schema_specs_from_config(config, [name], bundle.manifest["labels"]),
        bundle_dir=bundle.root, workdir=str(work / "artifacts"), params=params,
        seed=3, limits=ResourceLimits(device="cpu"))
    report = CollectingReporter()
    assert worker.run(spec, report) == EXIT_OK, report.of_type("log")[-3:]
    result = report.of_type("result")[0]
    with open(os.path.join(spec.workdir, "predictions.jsonl")) as fh:
        predictions = [json.loads(line) for line in fh if line.strip()]
    return result, predictions


def _split_project(work):
    """Clear items, which three annotators agree on, and MEH items, which
    they always split 2:1 for positive: the vote keeps "positive", and a
    third of them said otherwise every time."""
    scheme = {"annotation_type": "radio", "name": "s", "labels": ["positive", "negative"]}
    items, annotations = {}, []
    for rep in range(4):
        for group, texts in (("positive", POS), ("negative", NEG), ("meh", MEH)):
            for n, text in enumerate(texts):
                iid = "%s%d_%d" % (group, rep, n)
                items[iid] = {"id": iid, "text": "%s %d" % (text, rep)}
                if group == "meh":
                    votes = ["positive", "positive", "negative"]
                else:
                    votes = [group] * 3
                for user, label in zip("abc", votes):
                    annotations.append({"instance_id": iid, "user_id": user,
                                        "labels": {"s": {label: True}}})
    return scheme, items, annotations


def _meh_certainty(predictions):
    meh = [p for p in predictions if p["instance_id"].startswith("meh")]
    assert meh
    return sum(max(p["payload"]["probabilities"].values()) for p in meh) / len(meh)


@needs_hf
def test_soft_targets_leave_the_model_unsure_where_annotators_were(work):
    scheme, items, annotations = _split_project(work)
    config, context = _context(work, scheme, items, annotations)
    hard_result, hard = _fit(work / "hard", config, context, "s")
    soft_result, soft = _fit(work / "soft", config, context, "s", soft_targets=True)
    # A 2:1 split: the soft model should sit near 0.67, the hard one near 1.
    # (The hard model's checkpoint is chosen early, on val macro-F1, so it
    # stops short of 1; seeded on a CPU, these runs measured 0.76 and 0.62.)
    assert _meh_certainty(soft) < _meh_certainty(hard) - 0.1
    assert 0.55 < _meh_certainty(soft) < 0.8
    # The held-out score reports distance from the vote split and calibration.
    metrics = soft_result["metrics"]
    assert "test_soft_jsd" in metrics and "test_ece" in metrics
    assert 0 <= metrics["test_ece"] <= 1 and 0 <= metrics["test_soft_jsd"] <= 1


@needs_hf
def test_a_soft_label_scheme_trains_and_predicts_a_distribution(work):
    scheme = {"annotation_type": "soft_label", "name": "d",
              "labels": ["pos", "neg"], "total": 100}
    items, annotations = {}, []
    for rep in range(4):
        for group, texts, mass in (("p", POS, "90"), ("n", NEG, "10"), ("m", MEH, "50")):
            for n, text in enumerate(texts):
                iid = "%s%d_%d" % (group, rep, n)
                items[iid] = {"id": iid, "text": "%s %d" % (text, rep)}
                annotations.append({"instance_id": iid, "user_id": "a", "labels": {
                    "d": {"pos": mass, "neg": str(100 - int(mass))}}})
    config, context = _context(work, scheme, items, annotations)
    result, predictions = _fit(work, config, context, "d")
    assert result["metrics"]["heldout_metric"] == "test distribution_agreement"
    assert result["metrics"]["heldout_score"] >= 0.9
    payload = next(p for p in predictions if p["instance_id"].startswith("m"))["payload"]
    assert set(payload["distribution"]) == {"pos", "neg"}
    assert 0.3 <= payload["distribution"]["pos"] <= 0.7
