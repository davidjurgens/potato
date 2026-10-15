"""Prelabelling unlabelled items (model_training.writeback.include_unlabeled),
and the startup replay keeping the write-back rules.

A run predicted only on its held-out val/test items, which are already
labelled, so write-back never prelabelled the items nobody had labelled.
Separately, every prediction is stored (its run's training items included),
and the replay at boot applied none of the rules ingest applies.
"""

import os
import tempfile
import types

import pytest

from potato.training import store, writeback
from potato.training.dataset import build_bundle
from potato.training.worker import _predict_items


def _context(tmp, n_labeled=8, n_unlabeled=5):
    config = {"task_dir": tmp, "annotation_task_name": "wb",
              "item_properties": {"id_key": "id", "text_key": "text"},
              "annotation_schemes": [{"annotation_type": "radio", "name": "s",
                                      "labels": ["a", "b"]}]}
    items, annotations = {}, []
    for n in range(n_labeled + n_unlabeled):
        iid = "i%02d" % n
        items[iid] = {"id": iid, "text": "item %d" % n}
        if n < n_labeled:
            annotations.append({"instance_id": iid, "user_id": "u",
                                "labels": {"s": {"a" if n % 2 else "b": True}}})
    return config, types.SimpleNamespace(config=config, annotations=annotations,
                                         items=items, schemas=config["annotation_schemes"],
                                         output_dir=tmp, phase_responses={})


def test_unlabelled_items_become_a_predict_only_split_when_asked():
    with tempfile.TemporaryDirectory() as tmp:
        config, ctx = _context(tmp)
        bundle, stats, split_ids = build_bundle(ctx, os.path.join(tmp, "b"), ["s"],
                                                split_seed=1, include_unlabeled=True)
        unlabeled = [r["instance_id"] for r in bundle.read_split("unlabeled")]
        assert unlabeled == ["i08", "i09", "i10", "i11", "i12"]
        assert "unlabeled" not in split_ids and "unlabeled" not in stats.splits
        predicted = {i.instance_id for i in _predict_items(bundle, ["val", "test", "unlabeled"])}
        assert set(unlabeled) <= predicted
        assert not predicted & set(split_ids.get("train", []))


def test_without_the_option_nothing_unlabelled_is_written():
    with tempfile.TemporaryDirectory() as tmp:
        config, ctx = _context(tmp)
        bundle, _, _ = build_bundle(ctx, os.path.join(tmp, "b"), ["s"], split_seed=1)
        assert list(bundle.read_split("unlabeled")) == []


class _Items:
    def __init__(self):
        self.set = []

    def set_prediction(self, iid, schema, payload, field="predictions"):
        self.set.append(iid)
        return True


def test_the_startup_replay_applies_the_write_back_rules(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        config = {"task_dir": tmp, "annotation_task_name": "wb",
                  "model_training": {"writeback": {"schemas": ["s"],
                                                   "min_confidence": 0.5}}}
        run_id = store.new_run_id()
        store.record_run(config, store.TrainingRun(run_id=run_id, trainer="sklearn-text",
                                                   schema_names=["s"], status="success"))
        store.record_run_items(config, run_id, {"train": ["trained"], "val": ["held"]})
        store.record_predictions(config, run_id, [
            ("trained", "s", {"label": "a"}, 0.99),     # leak guard
            ("held", "s", {"label": "a"}, 0.9),         # kept
            ("new", "s", {"label": "b"}, 0.8),          # unlabelled item: kept
            ("unsure", "s", {"label": "b"}, 0.2),       # below the floor
            ("refused", "s", {"label": "b"}, 0.9)])     # reviewer rejected
        monkeypatch.setattr(writeback, "_rejected_keys", lambda c: {("refused", "s")})
        items = _Items()
        assert writeback.rehydrate_predictions(config, items) == 2
        assert sorted(items.set) == ["held", "new"]


def test_stored_prelabels_are_back_after_a_restart(monkeypatch):
    """The replay ran from load_annotation_schematic_data, before any item was
    loaded: the first prediction raised KeyError ('Could not restore model
    predictions') and no prelabel ever survived a restart."""
    import json as _json
    import yaml
    from potato import flask_server
    from potato.item_state_management import (
        clear_item_state_manager, get_item_state_manager)
    from potato.server_utils import config_module
    from potato.user_state_management import clear_user_state_manager
    from pathlib import Path
    from tests.helpers.test_utils import cleanup_test_directory, create_test_directory
    monkeypatch.delenv("POTATO_SKIP_CONFIG_PATH_VALIDATION", raising=False)
    tmp_path = Path(create_test_directory("training_replay"))
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "items.jsonl").write_text("".join(
        _json.dumps({"id": f"i{k}", "text": f"item {k}"}) + "\n" for k in range(4)))
    cfg = {"annotation_task_name": "replay", "task_dir": str(tmp_path),
           "output_annotation_dir": "annotation_output",
           "data_files": ["data/items.jsonl"],
           "item_properties": {"id_key": "id", "text_key": "text"},
           "user_config": {"allow_all_users": True, "users": []},
           "annotation_schemes": [{"annotation_type": "radio", "name": "s",
                                   "description": "?", "labels": ["a", "b"]}],
           "model_training": {"enabled": True, "writeback": {"schemas": ["s"]}}}
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg))
    run_id = store.new_run_id()
    store.record_run(cfg, store.TrainingRun(run_id=run_id, trainer="sklearn-text",
                                            schema_names=["s"], status="success"))
    store.record_run_items(cfg, run_id, {"train": ["i0"], "val": ["i1"]})
    store.record_predictions(cfg, run_id, [("i0", "s", {"label": "a"}, 0.9),
                                           ("i1", "s", {"label": "b"}, 0.9),
                                           ("i3", "s", {"label": "a"}, 0.9)])
    saved = dict(config_module.config)
    clear_item_state_manager()
    clear_user_state_manager()
    try:
        flask_server.create_app(str(tmp_path / "config.yaml"))
        ism = get_item_state_manager()
        preds = {i: (ism.get_item(i).item_data or {}).get("predictions")
                 for i in ("i0", "i1", "i3")}
        assert preds["i1"] == {"s": {"label": "b"}} and preds["i3"] == {"s": {"label": "a"}}
        assert not preds["i0"]                     # a training item stays off
    finally:
        clear_item_state_manager()
        clear_user_state_manager()
        config_module.config.clear()
        config_module.config.update(saved)
        cleanup_test_directory(str(tmp_path))
