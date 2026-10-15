"""
Distillation: train a cheap model on this study's labels and put it first.

The training set is every human label the engine has (calibration, verify,
resolve, adjudicated) plus, when ``distill.include_silver`` is on (default),
the machine labels a contract certified, which are marked silver in the
bundle. Two kinds of item never go in:

- items in the ``cert`` split: they are what the new tier will be tested on,
  and a model trained on its own test set would pass a test it should fail;
- items in the ``audit`` split: they measure drift in what is accepted.

``distill_scheme`` asserts both before training. The model is fitted with a
trainer from ``potato/training`` (``sklearn-text`` by default), saved under
``<task_dir>/engine_models/<run>``, and registered as a ``trained`` source
ahead of the configured cascade. Its arrival changes the cascade, so every
contract on the scheme goes stale and is recertified on the same human
labels with the new tier included.

Config (``labeling_engine.distill``): ``trainer``, ``min_labels`` (200),
``include_silver`` (true), ``every`` (retrain when the label count has grown
by this factor; 2.0). ``features.distill`` turns it on.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

KV_KEY = "distilled_sources"


def _excluded_items(engine, scheme: str) -> set:
    return {r.item_id for r in engine.store.requests(schema=scheme)
            if r.split in ("cert", "audit") or r.purpose == "audit"}


def training_rows(engine, scheme, items_by_id: Dict[str, Any],
                  include_silver: bool = True) -> List[Dict[str, Any]]:
    excluded = _excluded_items(engine, scheme.name)
    rows = []
    for lab in engine.store.resolved(schema=scheme.name, status=["accepted"]):
        if lab.item_id in excluded or lab.item_id not in items_by_id:
            continue
        if lab.origin == "auto" and not include_silver:
            continue
        if not isinstance(lab.value, str) or lab.value not in scheme.labels:
            continue
        rows.append({"instance_id": lab.item_id, "text": items_by_id[lab.item_id].text,
                     "targets": {scheme.name: lab.value},
                     "silver": lab.origin == "auto"})
    return rows


def _write_bundle(rows, scheme, root: str) -> str:
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "train.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()[:16]
    with open(os.path.join(root, "manifest.json"), "w") as f:
        json.dump({"splits": {"train": {"path": "train.jsonl", "n": len(rows),
                                        "format": "jsonl"}},
                   "labels": {scheme.name: list(scheme.labels)}, "modality": "text",
                   "digest": digest}, f)
    return digest


def distill_scheme(engine, scheme, items, trainer_name: Optional[str] = None
                   ) -> Optional[Dict[str, Any]]:
    """Train and register a distilled tier. Returns its source entry, or None."""
    from potato.training.base import BundleRef, SchemaSpec as TSchema, TrainingSpec
    from potato.training.registry import get_trainer
    opts = engine.cfg.distill or {}
    trainer_name = trainer_name or opts.get("trainer", "sklearn-text")
    by_id = {i.item_id: i for i in items}
    rows = training_rows(engine, scheme, by_id, bool(opts.get("include_silver", True)))
    if len(rows) < int(opts.get("min_labels", 200)) or len({r["targets"][scheme.name]
                                                          for r in rows}) < 2:
        return None
    excluded = _excluded_items(engine, scheme.name)
    assert not ({r["instance_id"] for r in rows} & excluded), \
        "distillation training set contains cert or audit items"
    run_id = f"{scheme.name}-{int(time.time())}"
    root = os.path.join(engine.task_dir, "engine_models", run_id)
    digest = _write_bundle(rows, scheme, root)
    trainer = get_trainer(trainer_name)
    spec = TrainingSpec(run_id=run_id, trainer=trainer_name,
                        schemas=(TSchema(name=scheme.name,
                                         annotation_type=scheme.annotation_type,
                                         kind="nominal", labels=tuple(scheme.labels)),),
                        bundle_dir=root, workdir=root,
                        params={"calibrate": True})

    class _Log:
        def status(self, *a, **k): pass
        def progress(self, *a, **k): pass
        def log(self, level, msg): logger.info("distill %s: %s", run_id, msg)
        def metric(self, *a, **k): pass
        def should_stop(self): return False

    fit = trainer.fit(spec, BundleRef.load(root), _Log())
    entry = {"id": f"distilled-{scheme.name}", "kind": "trained", "schemas": [scheme.name],
             "options": {"artifact_dir": root, "trainer": trainer_name, "run_id": run_id,
                         "scheme": scheme.name, "bundle_digest": digest},
             "n_train": len(rows), "n_silver": sum(r["silver"] for r in rows),
             "metrics": fit.metrics, "created_at": time.time()}
    registry = engine.store.kv_get(KV_KEY, {}) or {}
    registry[scheme.name] = entry
    engine.store.kv_set(KV_KEY, registry)
    engine.reload_distilled()
    return entry


def due(engine, scheme) -> bool:
    """Whether a (re)distillation is due for this scheme."""
    if not engine.cfg.feature("distill"):
        return False
    opts = engine.cfg.distill or {}
    n = len(engine.store.resolved(schema=scheme.name, status=["accepted"]))
    if n < int(opts.get("min_labels", 200)):
        return False
    prev = (engine.store.kv_get(KV_KEY, {}) or {}).get(scheme.name)
    if prev is None:
        return True
    return n >= float(opts.get("every", 2.0)) * (prev.get("n_train") or 1)
