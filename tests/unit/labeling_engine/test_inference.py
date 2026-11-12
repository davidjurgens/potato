"""Truth inference: majority, Dawid-Skene, adjudication override."""

import random

import pytest

from potato.labeling_engine.inference import infer, majority


def test_majority_ties_go_to_the_first_label():
    assert majority({"a": "x", "b": "y"}) == ("x", 0.5)
    assert majority({"a": "x", "b": "y", "c": "y"})[0] == "y"


def test_majority_handles_structured_values():
    v, c = majority({"a": {"0": 1}, "b": {"0": 1}, "c": {"0": -1}})
    assert v == {"0": 1} and c == pytest.approx(2 / 3)


def test_dawid_skene_downweights_a_careless_rater():
    rng = random.Random(0)
    truth = {f"i{k}": rng.choice(["p", "n"]) for k in range(150)}
    flip = {"p": "n", "n": "p"}
    labels = {}
    for item, t in truth.items():
        labels[item] = {
            "good1": t if rng.random() > 0.05 else flip[t],
            "good2": t if rng.random() > 0.05 else flip[t],
            # Two raters who answer at random: majority ties them with the
            # good raters on every item where one good rater slips, and
            # Dawid-Skene learns to ignore them.
            "random1": rng.choice(["p", "n"]),
            "random2": rng.choice(["p", "n"]),
        }
    maj = infer(labels, "majority")
    ds = infer(labels, "dawid_skene")
    acc = lambda res: sum(res[i][0] == truth[i] for i in truth) / len(truth)
    assert acc(ds) >= acc(maj)
    assert acc(ds) > 0.9


def test_adjudication_wins():
    out = infer({"i1": {"a": "x", "b": "x"}}, "dawid_skene", adjudicated={"i1": "y"})
    assert out["i1"] == ("y", 1.0)


def test_unknown_method():
    with pytest.raises(ValueError):
        infer({}, "vibes")
