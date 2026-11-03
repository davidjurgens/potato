"""The reward-model trainer: comparisons from every comparative answer type,
a fit through the worker on a tiny model, and predictions in each scheme's
own shape.

The data is easy on purpose: positive sentences beat negative ones. A loop
that cannot learn that is broken, and one that can is what these tests need
before they check what it wrote.
"""

import json
import os
import random
import types
from pathlib import Path

import pytest

from potato.training import worker
from potato.training.base import ResourceLimits, TrainingSpec
from potato.training.dataset import build_bundle, schema_specs_from_config
from potato.training.events import EXIT_OK, CollectingReporter
from potato.training.trainers.reward_model import (answer_from_rewards,
                                                   comparisons)
from tests.helpers.test_utils import create_test_directory

HAVE_HF = all(__import__("importlib").util.find_spec(m) for m in
              ("torch", "transformers", "tokenizers"))
needs_hf = pytest.mark.skipif(not HAVE_HF, reason="torch/transformers absent")

POS = ["great movie loved it", "wonderful film excellent", "so good enjoyed",
       "great charming work", "loved excellent film", "a delight"]
NEG = ["terrible movie hated it", "awful film poor", "so bad disliked",
       "poor tedious work", "hated dreadful film", "a chore"]
MID = ["an ordinary film", "a middling movie", "average work", "plain film",
       "a so so movie", "unremarkable work"]
TRAIN = {"epochs": 25, "batch_size": 8, "learning_rate": 3e-3,
         "min_instances": 4, "patience": None}


@pytest.fixture
def work(request):
    return Path(create_test_directory("reward_" + request.node.name))


# ------------------------------------------------------------ comparisons

def test_each_answer_type_yields_comparisons():
    pair = {"candidates": ["x", "y"], "targets": {"p": "B"}}
    assert comparisons("preference", pair, "p", []) == [
        {"context": "", "order": ["y", "x"], "weight": 1.0}]
    assert comparisons("preference", {"candidates": ["x", "y"],
                                      "targets": {"p": "tie"}}, "p", []) == []

    scale = {"candidates": ["x", "y"], "targets": {"p": -1.5}}
    (unit,) = comparisons("preference_scale", scale, "p", [], scale_max=3)
    assert unit["order"] == ["x", "y"] and unit["weight"] == 0.5
    assert comparisons("preference_scale", {"candidates": ["x", "y"],
                                            "targets": {"p": 0}}, "p", []) == []

    ranked = {"text": "q", "targets": {"r": ["b", "c", "a"]}}
    (listwise,) = comparisons("ranking", ranked, "r", ["a", "b", "c"])
    assert listwise == {"context": "q", "order": ["b", "c", "a"], "weight": 1.0}
    pairs = comparisons("ranking", ranked, "r", ["a", "b", "c"], listwise=False)
    assert [u["order"] for u in pairs] == [["b", "c"], ["b", "a"], ["c", "a"]]

    tuple_ = {"candidates": ["p", "q", "s"], "targets": {"w": {"best": "B",
                                                               "worst": "C"}}}
    orders = [u["order"] for u in comparisons("bws", tuple_, "w", [])]
    # q beats p and s; p beats s.
    assert sorted(orders) == [["p", "s"], ["q", "p"], ["q", "s"]]


def test_a_tie_is_two_items_and_not_a_pair():
    """The ranking schema stores a tie as "fine=great". Split on "," alone
    it was an item of that name: a phantom label, and the tie was lost."""
    tied = {"text": "q", "targets": {"r": ["awful=fine", "great"]}}
    pairs = comparisons("ranking", tied, "r", ["awful", "fine", "great"])
    assert sorted(u["order"] for u in pairs) == [["awful", "great"], ["fine", "great"]]
    assert comparisons("ranking", {"text": "q", "targets": {"r": ["awful=fine"]}},
                       "r", ["awful", "fine"]) == []


def test_a_tied_ranking_bundles_the_scheme_labels(work):
    scheme = {"annotation_type": "ranking", "name": "rank", "allow_ties": True,
              "labels": ["Cost", "Speed", "Quality", "Support"]}
    rows = [("t%02d" % n, {"text": "item %d" % n}, {"rank_order": "Speed=Cost,Quality"})
            for n in range(8)]
    _, bundle = _project(work, scheme, rows)
    assert bundle.manifest["labels"]["rank"] == ["Cost", "Quality", "Speed", "Support"]
    first = json.loads(Path(bundle.root, "train.jsonl").read_text().splitlines()[0])
    assert first["targets"]["rank"] == ["Cost=Speed", "Quality"]


def test_answers_from_rewards():
    payload, confidence = answer_from_rewards("preference", [0.0, 2.0], ["x", "y"])
    assert payload["label"] == "B" and confidence == pytest.approx(0.8808, abs=1e-4)
    payload, _ = answer_from_rewards("preference_scale", [3.0, 0.0], ["x", "y"],
                                     scale=(-3, 3))
    assert payload["value"] == -3            # strongly prefers A
    payload, _ = answer_from_rewards("ranking", [0.1, 0.9, 0.5], ["a", "b", "c"])
    assert payload["order"] == ["b", "c", "a"]
    payload, _ = answer_from_rewards("bws", [0.1, 0.9, 0.5], ["p", "q", "s"])
    assert (payload["best"], payload["worst"]) == ("B", "A")


# --------------------------------------------------------- fit end to end

def _project(work, scheme, rows, unlabeled=()):
    items, annotations = {}, []
    for iid, data, value in rows:
        items[iid] = dict(data, id=iid)
        annotations.append({"instance_id": iid, "user_id": "a",
                            "labels": {scheme["name"]: value}})
    for iid, data in unlabeled:
        items[iid] = dict(data, id=iid)
    config = {"task_dir": str(work),
              "item_properties": {"id_key": "id", "text_key": "text"},
              "annotation_schemes": [scheme]}
    context = types.SimpleNamespace(config=config, annotations=annotations,
                                    items=items, schemas=[scheme],
                                    output_dir=str(work), phase_responses={})
    bundle, _, _ = build_bundle(context, str(work / "bundle"), [scheme["name"]],
                                split_seed=1, include_unlabeled=bool(unlabeled))
    return config, bundle


def _fit(work, config, bundle, scheme, **extra):
    from tests.helpers.tiny_hf import tiny_encoder
    params = dict(TRAIN, model_name=tiny_encoder(str(work / "m"), POS + NEG + MID
                                                 + ["great", "fine", "awful"]),
                  **extra)
    params.update(__import__("potato.training.trainers.reward_model",
                             fromlist=["x"]).RewardModelTrainer.server_params(
        config, [scheme["name"]], params))
    spec = TrainingSpec(
        run_id="r1", trainer="reward-model",
        schemas=schema_specs_from_config(config, [scheme["name"]],
                                         bundle.manifest["labels"]),
        bundle_dir=bundle.root, workdir=str(work / "artifacts"),
        params=params, seed=3, limits=ResourceLimits(device="cpu"))
    report = CollectingReporter()
    code = worker.run(spec, report)
    result = (report.of_type("result") or [None])[0]
    with open(os.path.join(spec.workdir, "predictions.jsonl")) as fh:
        predictions = [json.loads(line) for line in fh if line.strip()]
    return code, result, predictions


def _pairs(n_reps=5):
    rng = random.Random(0)
    rows = []
    for rep in range(n_reps):
        for n, (good, bad) in enumerate(zip(POS, NEG)):
            flip = rng.random() < 0.5
            candidates = [bad, good] if flip else [good, bad]
            rows.append(("p%d_%d" % (rep, n), {"text": candidates},
                         "B" if flip else "A"))
    return rows


@needs_hf
def test_pairwise_preferences_train_a_reward_model(work):
    scheme = {"annotation_type": "pairwise", "name": "pref", "mode": "binary"}
    rows = [(iid, data, {"selection": value}) for iid, data, value in _pairs()]
    config, bundle = _project(work, scheme, rows,
                              unlabeled=[("u1", {"text": [NEG[0], POS[0]]})])
    code, result, predictions = _fit(work, config, bundle, scheme)
    assert code == EXIT_OK
    assert result["metrics"]["heldout_metric"] == "test accuracy"
    assert result["metrics"]["heldout_score"] >= 0.9
    by_id = {p["instance_id"]: p for p in predictions}
    # The unlabelled item has its candidates, so it got a prediction.
    assert by_id["u1"]["payload"]["label"] == "B"
    assert len(by_id["u1"]["payload"]["rewards"]) == 2
    assert 0.5 <= by_id["u1"]["confidence"] <= 1


@needs_hf
def test_a_scale_preference_predicts_a_point_on_the_scale(work):
    scheme = {"annotation_type": "pairwise", "name": "pref", "mode": "scale",
              "scale": {"min": -2, "max": 2}}
    rows = [(iid, data, {"scale_value": "-2" if value == "A" else "2"})
            for iid, data, value in _pairs()]
    config, bundle = _project(work, scheme, rows)
    code, result, predictions = _fit(work, config, bundle, scheme)
    assert code == EXIT_OK
    assert result["metrics"]["heldout_metric"] == "test direction_accuracy"
    assert result["metrics"]["heldout_score"] >= 0.9
    assert {p["payload"]["value"] for p in predictions} <= {-2, -1, 0, 1, 2}


@needs_hf
def test_a_ranking_trains_listwise(work):
    scheme = {"annotation_type": "ranking", "name": "rank",
              "labels": ["great", "fine", "awful"]}
    rows = [("r%02d" % n, {"text": text}, {"rank_order": "great,fine,awful"})
            for n, text in enumerate((POS + NEG + MID) * 2)]
    config, bundle = _project(work, scheme, rows)
    code, result, predictions = _fit(work, config, bundle, scheme)
    assert code == EXIT_OK
    assert result["metrics"]["heldout_metric"] == "test kendall_tau"
    assert result["metrics"]["heldout_score"] >= 0.9
    assert predictions[0]["payload"]["order"] == ["great", "fine", "awful"]


@needs_hf
def test_bws_tuples_train_best_and_worst(work):
    scheme = {"annotation_type": "bws", "name": "bws"}
    rng = random.Random(1)
    rows = []
    for n in range(36):
        texts = [(POS[n % 6], "best"), (MID[n % 6], "mid"), (NEG[n % 6], "worst")]
        rng.shuffle(texts)
        letters = {role: "ABC"[i] for i, (_, role) in enumerate(texts)}
        rows.append(("bws_tuple_%04d" % n,
                     {"text": "", "_bws_items": [{"source_id": "s%d" % i,
                                                  "text": t, "position": i}
                                                 for i, (t, _) in enumerate(texts)]},
                     {"best": letters["best"], "worst": letters["worst"]}))
    config, bundle = _project(work, scheme, rows)
    code, result, predictions = _fit(work, config, bundle, scheme)
    assert code == EXIT_OK
    assert result["metrics"]["heldout_metric"] == "test best_worst_accuracy"
    assert result["metrics"]["heldout_score"] >= 0.8
    assert set(predictions[0]["payload"]) >= {"best", "worst", "rewards"}


def test_ties_alone_are_refused_before_the_fit(work):
    from potato.training.base import BundleRef
    from potato.training.trainers.reward_model import RewardModelTrainer
    scheme = {"annotation_type": "pairwise", "name": "pref"}
    rows = [(iid, data, {"selection": "tie"}) for iid, data, _ in _pairs(1)]
    config, bundle = _project(work, scheme, rows)
    spec = TrainingSpec(run_id="r", trainer="reward-model",
                        schemas=schema_specs_from_config(config, ["pref"]),
                        bundle_dir=bundle.root, workdir=str(work / "a"),
                        params={"min_instances": 1})
    problems = RewardModelTrainer().validate(spec, BundleRef.load(bundle.root))
    assert any("No usable comparisons" in p for p in problems)
