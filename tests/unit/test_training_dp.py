"""DP-SGD (``dp``) on the transformer classifiers: refused when it cannot be
private, and when opacus is installed, a run that spends no more than the
budget it was given and says what it spent."""

import json
import os

import pytest

from potato.training import registry
from potato.training.dataset import build_bundle
from potato.training.events import EXIT_OK
from potato.training.trainers import _dp
from tests.unit.test_training_trainers import (NEG, POS, _context, _predictions, _run,
                                               _spec, sentiment_project)

HAVE = __import__("importlib").util.find_spec
needs_opacus = pytest.mark.skipif(
    not all(HAVE(m) for m in ("opacus", "torch", "transformers")),
    reason="opacus/torch/transformers absent")


@pytest.mark.parametrize("dp,needle", [
    ({"epsilon": 0}, "epsilon must be a finite number above 0"),
    ({"epsilon": 3, "delta": 0.5}, "at least 1 / 100 train items"),
    ({"epsilon": 3, "delta": 2}, "between 0 and 1"),
    ({"epsilon": 3, "max_grad_norm": -1}, "max_grad_norm must be a finite number above 0"),
    ({"epsilon": 3, "noise": 1.0}, "does not take noise"),
    ("yes", "must be a mapping"),
])
def test_dp_settings_that_cannot_be_private_are_refused(dp, needle):
    assert any(needle in p for p in _dp.problems({"dp": dp}, 100)), _dp.problems({"dp": dp}, 100)


def test_dp_refuses_a_quantized_model_and_accumulated_batches():
    problems = _dp.problems({"dp": {"epsilon": 3}, "lora": {"quantize": "4bit"},
                             "gradient_accumulation": 4}, 100)
    assert any("quantized" in p for p in problems)
    assert any("gradient_accumulation" in p for p in problems)
    assert _dp.problems({"dp": None}, 100) == []


def test_dp_defaults_delta_below_one_over_n():
    assert _dp.settings({"dp": {"epsilon": 2}}, 40) == {
        "epsilon": 2.0, "delta": 1.0 / 400, "max_grad_norm": 1.0}
    assert _dp.settings({}, 40) is None


@pytest.mark.skipif(HAVE("opacus") is not None, reason="opacus is installed")
def test_without_opacus_a_dp_run_is_refused_at_validation(tmp_path):
    config, context = sentiment_project(tmp_path)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["s"], split_seed=1)
    for name in ("hf-text-classification", "hf-image-classification"):
        spec = _spec(tmp_path, config, bundle, name, "s", {"dp": {"epsilon": 3}})
        problems = registry.get_trainer_class(name)().validate(spec, bundle)
        assert any("pip install opacus" in p for p in problems), (name, problems)


def test_the_dp_parameter_is_declared_on_both_classifiers():
    for name in ("hf-text-classification", "hf-image-classification"):
        assert registry.param_problems(name, {"dp": {"epsilon": 3}}) == []
        assert registry.param_problems(name, {"dp": None}) == []
        assert registry.param_problems(name, {"dp": 3})


@needs_opacus
def test_a_private_text_classifier_spends_at_most_its_budget(tmp_path):
    from tests.helpers.tiny_hf import tiny_encoder
    config, context = sentiment_project(tmp_path)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["s"], split_seed=1)
    params = {"epochs": 8, "batch_size": 8, "learning_rate": 3e-3, "min_instances": 4,
              "patience": None, "model_name": tiny_encoder(str(tmp_path / "m"), POS + NEG),
              "dp": {"epsilon": 8.0, "max_grad_norm": 1.0}}
    spec = _spec(tmp_path, config, bundle, "hf-text-classification", "s", params)
    code, result, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    metrics = result["metrics"]
    assert 0 < metrics["dp_epsilon"] <= 8.0 + 1e-6, metrics
    with open(os.path.join(spec.workdir, "model_card.json")) as fh:
        card = json.load(fh)
    assert card["dp"]["epsilon_target"] == 8.0
    assert card["dp"]["epsilon_spent"] == metrics["dp_epsilon"]
    assert card["dp"]["noise_multiplier"] > 0 and card["dp"]["covers"] == "train split"
    spent = [e["value"] for e in report.of_type("metric") if e["name"] == "dp_epsilon"]
    assert spent == sorted(spent) and len(spent) == 8
    # The model it released predicts like any other.
    assert _predictions(spec)[0]["payload"]["label"] in ("positive", "negative")


@needs_opacus
def test_a_private_image_classifier_runs_and_reports_epsilon(tmp_path):
    from tests.helpers.tiny_hf import colour_images, tiny_vit
    images = colour_images(str(tmp_path / "img"), 24)
    items, annotations = {}, []
    for n, (path, label) in enumerate(images):
        iid = "i%02d" % n
        items[iid] = {"id": iid, "image": os.path.relpath(path, tmp_path)}
        annotations.append({"instance_id": iid, "user_id": "a",
                            "labels": {"c": {label: True}}})
    scheme = {"annotation_type": "radio", "name": "c", "description": "",
              "labels": ["red", "blue"]}
    config, context = _context(tmp_path, [scheme], items, annotations)
    config["item_properties"]["text_key"] = "image"
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["c"], split_seed=1)
    spec = _spec(tmp_path, config, bundle, "hf-image-classification", "c",
                 {"epochs": 3, "batch_size": 8, "learning_rate": 3e-3, "min_instances": 4,
                  "patience": None, "model_name": tiny_vit(str(tmp_path / "m")),
                  "dp": {"epsilon": 5.0}})
    code, result, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    assert 0 < result["metrics"]["dp_epsilon"] <= 5.0 + 1e-6, result["metrics"]
