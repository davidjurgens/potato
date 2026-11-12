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
by this factor; 2.0), ``modality`` (auto, text or image) and
``image_field``. ``features.distill`` turns it on.

On an image study (``modality: image``, or ``auto`` when the items' text
names image files) the trainer gets each image's file and CLIP embeddings
instead of the text, which there is only the image's URL. Images that are
not stored locally (remote URLs) are left out of training, and the trained
tier abstains on them.
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


def modality_of(engine, items, opts: Optional[Dict[str, Any]] = None) -> str:
    """``image`` or ``text``: the configured modality, or with ``auto``,
    image when most items name an image file."""
    from .sources.base import image_reference, looks_like_image
    opts = opts if opts is not None else (engine.cfg.distill or {})
    mode = opts.get("modality", "auto")
    if mode in ("text", "image"):
        return mode
    items = list(items)[:200]
    field = opts.get("image_field")
    hits = sum(1 for i in items if looks_like_image(image_reference(i, field)))
    return "image" if items and hits >= 0.8 * len(items) else "text"


def training_rows(engine, scheme, items_by_id: Dict[str, Any],
                  include_silver: bool = True, modality: str = "text",
                  image_field: Optional[str] = None) -> List[Dict[str, Any]]:
    from .sources.base import image_reference, local_image_file
    excluded = _excluded_items(engine, scheme.name)
    rows = []
    for lab in engine.store.resolved(schema=scheme.name, status=["accepted"]):
        if lab.item_id in excluded or lab.item_id not in items_by_id:
            continue
        if lab.origin == "auto" and not include_silver:
            continue
        if not isinstance(lab.value, str) or lab.value not in scheme.labels:
            continue
        item = items_by_id[lab.item_id]
        row = {"instance_id": lab.item_id, "text": item.text,
               "targets": {scheme.name: lab.value}, "silver": lab.origin == "auto"}
        if modality == "image":
            path = local_image_file(engine.app_config, image_reference(item, image_field))
            if path is None:
                continue
            row["media"] = path
        rows.append(row)
    return rows


def _write_bundle(rows, scheme, root: str, modality: str = "text") -> str:
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "train.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()[:16]
    with open(os.path.join(root, "manifest.json"), "w") as f:
        json.dump({"splits": {"train": {"path": "train.jsonl", "n": len(rows),
                                        "format": "jsonl"}},
                   "labels": {scheme.name: list(scheme.labels)}, "modality": modality,
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
    modality = modality_of(engine, items, opts)
    rows = training_rows(engine, scheme, by_id, bool(opts.get("include_silver", True)),
                         modality, opts.get("image_field"))
    if len(rows) < int(opts.get("min_labels", 200)) or len({r["targets"][scheme.name]
                                                          for r in rows}) < 2:
        return None
    excluded = _excluded_items(engine, scheme.name)
    assert not ({r["instance_id"] for r in rows} & excluded), \
        "distillation training set contains cert or audit items"
    run_id = f"{scheme.name}-{int(time.time())}"
    root = os.path.join(engine.task_dir, "engine_models", run_id)
    digest = _write_bundle(rows, scheme, root, modality)
    trainer = get_trainer(trainer_name)
    spec = TrainingSpec(run_id=run_id, trainer=trainer_name,
                        schemas=(TSchema(name=scheme.name,
                                         annotation_type=scheme.annotation_type,
                                         kind="nominal", labels=tuple(scheme.labels)),),
                        bundle_dir=root, workdir=root,
                        params={"calibrate": True,
                                **({"vectorizer": "clip"} if modality == "image" else {})})

    class _Log:
        def status(self, *a, **k): pass
        def progress(self, *a, **k): pass
        def log(self, level, msg): logger.info("distill %s: %s", run_id, msg)
        def metric(self, *a, **k): pass
        def should_stop(self): return False

    from potato.training.base import MissingDependency
    try:
        fit = trainer.fit(spec, BundleRef.load(root), _Log())
    except MissingDependency as e:
        # Image embeddings need sentence-transformers and pillow; say so
        # once per attempt rather than failing the planner pass.
        logger.warning("distill %s: %s (%s)", run_id, e,
                       getattr(e, "install_hint", "") or "")
        return None
    entry = {"id": f"distilled-{scheme.name}", "kind": "trained", "schemas": [scheme.name],
             "options": {"artifact_dir": root, "trainer": trainer_name, "run_id": run_id,
                         "scheme": scheme.name, "bundle_digest": digest,
                         "modality": modality,
                         **({"image_field": opts["image_field"]}
                            if opts.get("image_field") else {})},
             "n_train": len(rows), "n_silver": sum(r["silver"] for r in rows),
             "n_accepted": _n_accepted(engine, scheme),
             "metrics": fit.metrics, "created_at": time.time()}
    registry = engine.store.kv_get(KV_KEY, {}) or {}
    registry[scheme.name] = entry
    engine.store.kv_set(KV_KEY, registry)
    engine.reload_distilled()
    return entry


def _n_accepted(engine, scheme) -> int:
    return len(engine.store.resolved(schema=scheme.name, status=["accepted"]))


def due(engine, scheme) -> bool:
    """Whether a (re)distillation is due for this scheme."""
    if not engine.cfg.feature("distill"):
        return False
    opts = engine.cfg.distill or {}
    n = _n_accepted(engine, scheme)
    if n < int(opts.get("min_labels", 200)):
        return False
    prev = (engine.store.kv_get(KV_KEY, {}) or {}).get(scheme.name)
    if prev is None:
        return True
    # Growth is measured in accepted labels at both ends. The training set
    # leaves out cert, audit and unreadable-image rows, so comparing the
    # accepted count with it was always "doubled", and an image study
    # retrained on every planner pass.
    base = prev.get("n_accepted") or prev.get("n_train") or 1
    return n >= float(opts.get("every", 2.0)) * base
