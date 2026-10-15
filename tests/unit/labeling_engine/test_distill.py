"""Distillation: train on human + certified labels, never on cert or audit
items, and put the new tier first, where it is recertified like any tier."""

import random

import pytest

from potato.labeling_engine import distill
from potato.labeling_engine.items import ItemView
from potato.labeling_engine.service import Engine
from potato.persistence import clear_db_cache

LABELS = ["positive", "negative"]
WORDS = {"positive": ["great", "love", "excellent", "happy"],
         "negative": ["awful", "hate", "broken", "refund"]}


@pytest.fixture(autouse=True)
def _db():
    clear_db_cache()
    yield
    clear_db_cache()


def _items(n=1200, seed=0):
    rng = random.Random(seed)
    out = []
    for k in range(n):
        g = rng.choice(LABELS)
        text = f"{rng.choice(WORDS[g])} {rng.choice(WORDS[g])} item {k}"
        out.append(ItemView(f"i{k}", text, data={"gold": g}))
    return out


def _engine(tmp_path, **features):
    cfg = {"task_dir": str(tmp_path), "annotation_task_name": "d",
           "annotation_schemes": [{"name": "s", "annotation_type": "radio", "labels": LABELS}],
           "labeling_engine": {
               "enabled": True,
               "sources": [{"id": "fx", "kind": "fixture", "error_rate": 0.1,
                            "options": {"separability": 0.8}}],
               "contracts": [{"id": "acc", "kind": "selective_risk", "schema": "s",
                              "error": 0.15}],
               "features": {"distill": True, **features},
               "distill": {"min_labels": 100}}}
    return Engine(cfg)


def _prepare(eng, items):
    scheme = eng.scheme("s")
    eng.register_items(items)
    eng.predict(scheme, items)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.2)
    gold = {i.item_id: i.data["gold"] for i in items}
    for r in eng.store.requests(status=["open"]):
        eng.record_human_label(r.item_id, "s", gold[r.item_id], "ann", request_id=r.id)
    eng.certify(scheme)
    eng.resolve(scheme, open_requests=False)
    return scheme


def test_training_set_excludes_cert_and_audit_items(tmp_path):
    eng = _engine(tmp_path)
    items = _items()
    scheme = _prepare(eng, items)
    rows = distill.training_rows(eng, scheme, {i.item_id: i for i in items})
    cert = {r.item_id for r in eng.store.requests(split="cert")}
    assert cert and rows
    assert not ({r["instance_id"] for r in rows} & cert)
    assert any(r["silver"] for r in rows) and any(not r["silver"] for r in rows)


def test_distilled_tier_goes_first_and_stales_the_contract(tmp_path):
    eng = _engine(tmp_path)
    items = _items()
    scheme = _prepare(eng, items)
    before = eng.cascade_hash(scheme)
    assert distill.due(eng, scheme)
    entry = distill.distill_scheme(eng, scheme, items)
    assert entry and entry["n_train"] >= 100
    assert eng.tiers(scheme)[0] == "distilled-s"
    assert eng.cascade_hash(scheme) != before
    assert eng.contract_status(scheme)["acc"]["status"] == "stale"
    eng.predict(scheme, items)
    preds = eng.store.current_predictions("s", eng.tier_versions(scheme)[0])
    gold = {i.item_id: i.data["gold"] for i in items}
    acc = sum(p.value == gold[i] for i, p in preds.items()) / len(preds)
    assert acc > 0.9                         # the text is learnable
    res = eng.certify(scheme)["acc"]
    assert res["status"] in ("met", "insufficient", "infeasible")
    assert "distilled-s" in res["metrics"]["route"]
    # A restart finds the distilled tier again.
    clear_db_cache()
    again = Engine(eng.app_config)
    assert again.tiers(again.scheme("s"))[0] == "distilled-s"


def test_turning_distillation_off_restores_the_configured_cascade(tmp_path):
    eng = _engine(tmp_path)
    items = _items()
    scheme = _prepare(eng, items)
    distill.distill_scheme(eng, scheme, items)
    cfg = dict(eng.app_config)
    cfg["labeling_engine"] = {**cfg["labeling_engine"], "features": {}}
    off = Engine(cfg)
    assert off.tiers(off.scheme("s")) == ["fx"]


def test_too_few_labels_trains_nothing(tmp_path):
    eng = _engine(tmp_path)
    items = _items(200)
    scheme = eng.scheme("s")
    eng.register_items(items)
    assert distill.distill_scheme(eng, scheme, items) is None
    assert not distill.due(eng, scheme)
