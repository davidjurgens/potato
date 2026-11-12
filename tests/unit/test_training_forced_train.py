"""Corrections and pinned items train; they are never held out.

A reviewer correcting a model's prelabel is the most useful label a project
produces, and it is not a random sample of the corpus: it is drawn from the
items the model was worst at. In val or test it scores the model on its own
mistakes. So a ``correct`` verdict sends the item to train whatever its hash
split, and so does pinning it from the catalog ("train on these next run").
"""

import logging
import os
import tempfile
import types

import pytest

from potato import model_review
from potato.training import store
from potato.training.dataset import build_bundle
from potato.training.manager import TrainingManager
from tests.unit.test_training_bundle import _config, _context


@pytest.fixture
def project():
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        yield tmp, config, _context(tmp, config)


def _held_out(split_ids):
    return set(split_ids.get("val", [])) | set(split_ids.get("test", []))


def test_a_forced_item_moves_from_held_out_to_train(project):
    tmp, _, ctx = project
    _, _, plain = build_bundle(ctx, os.path.join(tmp, "a"), ["sentiment"])
    held = sorted(_held_out(plain))
    assert held, "the fixture needs at least one held-out item"

    bundle, stats, forced = build_bundle(
        ctx, os.path.join(tmp, "b"), ["sentiment"],
        force_train={"corrected": [held[0]]})

    assert held[0] in forced["train"]
    assert held[0] not in _held_out(forced)
    # Nothing else moved: the other held-out items keep their hash split.
    assert _held_out(forced) == set(held[1:])
    assert stats.forced_train["corrected"] == {
        "n": 1, "moved": 1, "waiting_for_label": 0}
    assert bundle.manifest["stats"]["forced_train"]["corrected"]["moved"] == 1
    assert any("moved to train" in w for w in stats.warnings)


def test_a_forced_item_already_in_train_moves_nothing(project):
    tmp, _, ctx = project
    _, _, plain = build_bundle(ctx, os.path.join(tmp, "a"), ["sentiment"])
    in_train = plain["train"][0]
    _, stats, forced = build_bundle(
        ctx, os.path.join(tmp, "b"), ["sentiment"],
        force_train={"corrected": [in_train]})
    assert forced == plain
    assert stats.forced_train["corrected"]["moved"] == 0
    assert not any("moved to train" in w for w in stats.warnings)


def test_an_unlabelled_forced_item_waits_and_is_not_invented(project):
    tmp, _, ctx = project
    _, stats, forced = build_bundle(
        ctx, os.path.join(tmp, "b"), ["sentiment"],
        force_train={"pinned_hard_example": ["nobody-labelled-this"]})
    assert "nobody-labelled-this" not in forced["train"]
    assert stats.forced_train["pinned_hard_example"] == {
        "n": 0, "moved": 0, "waiting_for_label": 1}


def _manager_like(config):
    return types.SimpleNamespace(config=config,
                                 logger=logging.getLogger("test"))


def test_correct_verdicts_and_pins_become_forced_ids(project):
    tmp, config, _ = project
    for iid, verdict, schema in [("i01", "correct", "sentiment"),
                                 ("i02", "correct", ""),
                                 ("i03", "correct", "other_scheme"),
                                 ("i04", "accept", "sentiment"),
                                 ("i05", "reject", "sentiment")]:
        model_review.record_verdict(config, model_review.ReviewVerdict(
            instance_id=iid, reviewer="r", verdict=verdict,
            schema_name=schema))
    store.pin_items(config, ["i07", "i08", "i07"], source="model-found-nothing")

    forced = TrainingManager._forced_train_ids(_manager_like(config),
                                               ["sentiment"])
    # Only corrections for this run's scheme (or none) count; accept and
    # reject do not change a split.
    assert forced == {"corrected": ["i01", "i02"],
                      "pinned_hard_example": ["i07", "i08"]}


def test_pins_are_idempotent_and_can_be_cleared(project):
    _, config, _ = project
    assert store.pin_items(config, ["a", "b"]) == 2
    assert store.pin_items(config, ["b", "c"]) == 1
    assert store.pinned_items(config) == {"hard_example": ["a", "b", "c"]}
    assert store.unpin_items(config, ["a"]) == 1
    assert store.unpin_items(config) == 2
    assert store.pinned_items(config) == {}
    with pytest.raises(ValueError):
        store.pin_items(config, ["a"], reason="typo")


def test_forcing_every_labelled_item_says_there_is_no_held_out_score(project):
    tmp, _, ctx = project
    _, _, plain = build_bundle(ctx, os.path.join(tmp, "a"), ["sentiment"])
    everything = [i for ids in plain.values() for i in ids]
    _, stats, forced = build_bundle(
        ctx, os.path.join(tmp, "b"), ["sentiment"],
        force_train={"pinned_hard_example": everything})
    assert not _held_out(forced)
    assert any("no held-out score" in w for w in stats.warnings), stats.warnings


def test_an_item_with_two_reasons_is_counted_once(project):
    tmp, _, ctx = project
    _, _, plain = build_bundle(ctx, os.path.join(tmp, "a"), ["sentiment"])
    item = sorted(_held_out(plain))[0]
    _, stats, _ = build_bundle(
        ctx, os.path.join(tmp, "b"), ["sentiment"],
        force_train={"corrected": [item], "pinned_hard_example": [item]})
    assert stats.forced_train["corrected"]["n"] == 1
    assert stats.forced_train["pinned_hard_example"]["n"] == 0
    assert sum(c["moved"] for c in stats.forced_train.values()) == 1


def test_items_earlier_runs_held_out_are_found(project):
    _, config, _ = project
    store.record_run_items(config, "run-1", {"train": ["a"], "val": ["b"],
                                             "test": ["c"]})
    store.record_run_items(config, "run-2", {"train": ["a", "b"], "val": ["c"]})
    assert store.heldout_in_other_runs(config, ["a", "b", "c"], "run-2") == {
        "run-1": ["b", "c"]}
    assert store.heldout_in_other_runs(config, ["a"], "run-3") == {}


def test_a_run_says_when_it_trains_on_what_an_earlier_run_held_out(project):
    tmp, config, ctx = project
    _, _, plain = build_bundle(ctx, os.path.join(tmp, "a"), ["sentiment"])
    item = sorted(_held_out(plain))[0]
    store.record_run_items(config, "run-1", {"val": [item]})
    store.pin_items(config, [item])

    manager = TrainingManager(config)
    manager._context_from_live_state = lambda: ctx
    run = store.TrainingRun(run_id="run-2", trainer="sklearn-text",
                            schema_names=["sentiment"], status="running",
                            created_at=1.0)
    store.record_run(config, run)
    os.makedirs(manager.run_dir("run-2"), exist_ok=True)
    try:
        manager._build(run, os.path.join(tmp, "b"), os.path.join(tmp, "w"))
        warnings = manager.status().get("warnings") or []
    finally:
        manager.shutdown()
    assert any("held out by earlier runs (run-1: 1)" in w for w in warnings), warnings
