"""
The engine end to end on a fixture source: predict, sample, humans answer,
certify, resolve, then change the cascade and watch the certificate go stale.
"""

import random

import pytest

from potato.labeling_engine.items import ItemView
from potato.labeling_engine.service import Engine
from potato.persistence import clear_db_cache

LABELS = ["positive", "negative", "neutral"]
SCHEME = {"name": "sentiment", "annotation_type": "radio", "labels": LABELS}


def _config(tmp_path, error_rate=0.15, contracts=None, **block):
    return {
        "task_dir": str(tmp_path), "annotation_task_name": f"e-{tmp_path.name}",
        "annotation_schemes": [SCHEME],
        "labeling_engine": {
            "enabled": True,
            "sources": [{"id": "fx", "kind": "fixture", "error_rate": error_rate,
                         "options": {"separability": 0.8}}],
            "cascade": ["fx"],
            "contracts": contracts or [
                {"id": "acc", "kind": "selective_risk", "schema": "sentiment",
                 "error": 0.1, "confidence": 0.9},
                {"id": "prev", "kind": "ppi", "schema": "sentiment"}],
            **block,
        },
    }


def _items(n, seed=0):
    rng = random.Random(seed)
    return [ItemView(f"i{k}", f"text {k}",
                     data={"gold": rng.choices(LABELS, [0.5, 0.3, 0.2])[0]})
            for k in range(n)]


@pytest.fixture(autouse=True)
def _fresh_db():
    clear_db_cache()
    yield
    clear_db_cache()


def _answer_all(engine, items, purposes=("calibration",)):
    gold = {i.item_id: i.data["gold"] for i in items}
    for r in engine.store.requests(status=["open"], purpose=list(purposes)):
        engine.record_human_label(r.item_id, r.schema, gold[r.item_id], "ann1",
                                  request_id=r.id)


def test_full_lifecycle(tmp_path):
    items = _items(3000)
    eng = Engine(_config(tmp_path))
    scheme = eng.scheme("sentiment")
    eng.register_items(items)
    eng.predict(scheme, items)
    assert eng.store.prediction_count() == 3000

    _, reqs = eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.12)
    opened = eng.store.requests(purpose=["calibration"])
    assert len(opened) == len(reqs) > 250
    assert all(r.visibility == "blind" and r.inclusion_prob == pytest.approx(0.12)
               for r in opened)
    assert {r.split for r in opened} == {"dev", "cert"}

    _answer_all(eng, items)
    results = eng.certify(scheme)
    assert results["acc"]["status"] == "met", results["acc"]
    assert results["prev"]["status"] == "met"

    counts = eng.resolve(scheme)
    assert counts["auto"] > 0 and counts["human"] == len(reqs)
    gold = {i.item_id: i.data["gold"] for i in items}
    auto = [r for r in eng.store.resolved(schema="sentiment") if r.origin == "auto"]
    wrong = sum(r.value != gold[r.item_id] for r in auto)
    assert wrong / len(auto) <= 0.1
    # Everything not accepted or human-labeled became a human request.
    verify = eng.store.requests(purpose=["verify", "resolve"])
    assert len(verify) == counts["pending"]
    assert all(r.inclusion_prob is None for r in verify)

    # Prevalence interval covers the truth.
    est = results["prev"]["metrics"]["estimates"]["all"]["positive"]
    true_pos = sum(g == "positive" for g in gold.values()) / len(gold)
    assert est["lo"] <= true_pos <= est["hi"]


def test_recertifying_the_same_data_is_not_a_new_look(tmp_path):
    items = _items(1500)
    eng = Engine(_config(tmp_path))
    scheme = eng.scheme("sentiment")
    eng.register_items(items)
    eng.predict(scheme, items)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.2)
    _answer_all(eng, items)
    first = eng.certify(scheme)["acc"]
    again = eng.certify(scheme)["acc"]
    assert first["look"] == again["look"] == 1


def test_more_labels_is_a_new_look_at_a_smaller_alpha(tmp_path):
    items = _items(1500)
    eng = Engine(_config(tmp_path))
    scheme = eng.scheme("sentiment")
    eng.register_items(items)
    eng.predict(scheme, items)
    ids = [i.item_id for i in items]
    eng.draw_calibration(scheme, ids, rate=0.1, seed=1)
    _answer_all(eng, items)
    a = eng.certify(scheme)["acc"]
    eng.draw_calibration(scheme, ids, rate=0.1, seed=2)
    _answer_all(eng, items)
    b = eng.certify(scheme)["acc"]
    assert b["look"] == 2 and b["alpha"] < a["alpha"]
    # The second wave raised every item's inclusion probability.
    meta = eng.store.get_items_meta(ids[:5], "pi")
    assert all(m["sentiment"] == pytest.approx(1 - 0.9 * 0.9) for m in meta.values())


def test_a_changed_source_stales_the_certificate(tmp_path):
    items = _items(2000)
    eng = Engine(_config(tmp_path))
    scheme = eng.scheme("sentiment")
    eng.register_items(items)
    eng.predict(scheme, items)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.15)
    _answer_all(eng, items)
    eng.certify(scheme)
    n_auto = eng.resolve(scheme)["auto"]
    assert n_auto > 0

    # Same study, new source parameters: a new source version.
    eng2 = Engine(_config(tmp_path, error_rate=0.2))
    assert eng2.contract_status(scheme)["acc"]["status"] == "stale"
    counts = eng2.resolve(scheme, open_requests=False)
    assert counts.get("pending_recert") == n_auto
    assert counts.get("auto", 0) == 0
    # The human calibration labels survive the change.
    assert len(eng2.view(scheme).cal) == len(eng.view(scheme).cal)


def test_organic_labels_never_reach_the_estimators(tmp_path):
    items = _items(300)
    eng = Engine(_config(tmp_path))
    scheme = eng.scheme("sentiment")
    eng.register_items(items)
    eng.predict(scheme, items)
    eng.record_human_label("i1", "sentiment", "positive", "someone")
    [r] = eng.store.requests(purpose=["organic"])
    assert r.inclusion_prob is None and r.status == "done"
    assert eng.view(scheme).cal == []


def test_human_label_budget_caps_new_requests(tmp_path):
    items = _items(1500)
    eng = Engine(_config(tmp_path))
    scheme = eng.scheme("sentiment")
    eng.register_items(items)
    eng.predict(scheme, items)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.2)
    _answer_all(eng, items)
    n0 = sum(sum(v.values()) for v in eng.store.request_counts().values())
    capped = Engine(_config(tmp_path, budgets={"human_labels": n0 + 5}))
    capped.certify(scheme)
    counts = capped.resolve(scheme)
    total = sum(sum(v.values()) for v in capped.store.request_counts().values())
    assert counts["requests_opened"] == 5 and total == n0 + 5
    assert counts.get("over_budget", 0) == counts["pending"] - 5


def test_status_summary(tmp_path):
    items = _items(200)
    eng = Engine(_config(tmp_path, budgets={"model_usd": 5}))
    scheme = eng.scheme("sentiment")
    eng.register_items(items)
    eng.predict(scheme, items)
    st = eng.status()
    assert st["items"] == 200 and st["predictions"] == 200
    assert st["budgets"]["model_usd"]["limit"] == 5
    assert st["schemes"]["sentiment"]["contracts"]["acc"]["status"] == "insufficient"


def _two_tier_config(tmp_path, **contract):
    cfg = _config(tmp_path)
    cfg["labeling_engine"]["sources"] = [
        {"id": "cheap", "kind": "fixture", "error_rate": 0.35, "seed": 1,
         "options": {"separability": 0.5}},
        {"id": "strong", "kind": "fixture", "error_rate": 0.05, "seed": 2,
         "options": {"separability": 0.8}},
    ]
    cfg["labeling_engine"]["cascade"] = ["cheap", "strong"]
    cfg["labeling_engine"]["contracts"] = [
        {"id": "acc", "kind": "selective_risk", "schema": "sentiment", "error": 0.1},
        {"id": "prev", "kind": "ppi", "schema": "sentiment", **contract}]
    return cfg


def test_ppi_is_unbiased_when_later_tiers_label_only_the_sample(tmp_path):
    """Live S1 run: the last tier labels the sample and some escalations, so
    'has a last-tier prediction' depended on being sampled and PPI came out
    at 17% for a class at 33%. The estimator must use an f that is the same
    function of an item whether it was sampled or not."""
    items = _items(2000, seed=3)
    eng = Engine(_two_tier_config(tmp_path))
    scheme = eng.scheme("sentiment")
    eng.register_items(items)
    eng.predict(scheme, items)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.1)
    eng.predict(scheme, items)          # the strong tier labels the sample
    _answer_all(eng, items)
    res = eng.certify(scheme)["prev"]
    gold = {i.item_id: i.data["gold"] for i in items}
    for label in LABELS:
        truth = sum(g == label for g in gold.values()) / len(gold)
        e = res["metrics"]["estimates"]["all"][label]
        assert e["lo"] <= truth <= e["hi"], (label, truth, e)
    assert res["metrics"]["tier"] in ("cheap", "cascade output")


def test_pointing_ppi_at_an_incomplete_tier_is_biased(tmp_path):
    """The guard: the same study with f forced to the last tier misses."""
    items = _items(2000, seed=3)
    eng = Engine(_two_tier_config(tmp_path, tier="strong"))
    scheme = eng.scheme("sentiment")
    eng.register_items(items)
    eng.predict(scheme, items)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.1)
    eng.predict(scheme, items)
    _answer_all(eng, items)
    res = eng.certify(scheme)["prev"]
    gold = {i.item_id: i.data["gold"] for i in items}
    truth = sum(g == "positive" for g in gold.values()) / len(gold)
    e = res["metrics"]["estimates"]["all"]["positive"]
    assert not (e["lo"] <= truth <= e["hi"]), (truth, e)


def test_schemes_share_one_calibration_sample(tmp_path):
    """A person answering an item answers every scheme's random request on
    it; independent per-scheme draws turned half of those into organic
    labels that no estimate could use."""
    cfg = _config(tmp_path)
    cfg["annotation_schemes"] = [SCHEME, {"name": "topic", "annotation_type": "radio",
                                          "labels": ["a", "b"]}]
    eng = Engine(cfg)
    items = _items(500)
    ids = [i.item_id for i in items]
    eng.register_items(items)
    eng.draw_calibration(eng.scheme("sentiment"), ids, rate=0.2)
    eng.draw_calibration(eng.scheme("topic"), ids, rate=0.2)
    a = {r.item_id: r.split for r in eng.store.requests(schema="sentiment")}
    b = {r.item_id: r.split for r in eng.store.requests(schema="topic")}
    assert a == b and len(a) > 50


def test_an_evaluation_that_tests_nothing_spends_no_look(tmp_path):
    items = _items(1500)
    eng = Engine(_config(tmp_path, contracts=[
        {"id": "acc", "kind": "selective_risk", "schema": "sentiment", "error": 0.1}]))
    scheme = eng.scheme("sentiment")
    eng.register_items(items)
    eng.predict(scheme, items)
    ids = [i.item_id for i in items]
    eng.draw_calibration(scheme, ids, rate=0.005, seed=1)   # far too few to test
    _answer_all(eng, items)
    first = eng.certify(scheme)["acc"]
    assert first["metrics"]["tested_cells"] == 0 and first["looks_spent"] == 0
    eng.draw_calibration(scheme, ids, rate=0.2, seed=2)
    _answer_all(eng, items)
    second = eng.certify(scheme)["acc"]
    assert second["metrics"]["tested_cells"] >= 1 and second["looks_spent"] == 1
    assert second["alpha"] == pytest.approx(0.1 * 6 / 3.141592653589793 ** 2)


def test_widen_overlap_sends_labeled_items_to_more_people(tmp_path):
    eng = Engine(_config(tmp_path, humans={"overlap_k": 3}))
    scheme = eng.scheme("sentiment")
    items = _items(400)
    eng.register_items(items)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.2)
    before = len(eng.store.requests(purpose=["calibration"]))
    added = eng.widen_overlap(scheme, 10)
    assert len(added) == 20
    per = {}
    for r in eng.store.requests(purpose=["calibration"]):
        per.setdefault(r.item_id, []).append(r)
    widened = [rs for rs in per.values() if len(rs) == 3]
    assert len(widened) == 10
    # Copies keep the original's design and inclusion probability.
    assert all(len({(r.inclusion_prob, r.split, r.design_id) for r in rs}) == 1
               for rs in widened)


def test_audits_catch_drift_and_stop_auto_acceptance(tmp_path):
    items = _items(2500, seed=5)
    cfg = _config(tmp_path, humans={"audit_rate": 0.5}, features={"drift": True})
    eng = Engine(cfg)
    scheme = eng.scheme("sentiment")
    eng.register_items(items)
    eng.predict(scheme, items)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.12)
    _answer_all(eng, items)
    eng.certify(scheme)
    assert eng.resolve(scheme)["auto"] > 0
    assert eng.draw_audit(scheme, seed=1)
    assert eng.draw_audit(scheme, seed=1) == []      # nothing newly accepted
    # The world changes: audits find the accepted labels mostly wrong.
    flip = {"positive": "negative", "negative": "neutral", "neutral": "positive"}
    for r in eng.store.requests(purpose=["audit"], status=["open"]):
        p = eng.store.get_prediction(r.shown_prediction_id)
        eng.record_human_label(r.item_id, "sentiment", flip[p.value], "auditor",
                               request_id=r.id)
    assert eng.drift_breached(scheme)
    counts = eng.resolve(scheme, open_requests=False)
    assert counts.get("auto", 0) == 0 and counts.get("pending_recert", 0) > 0


def test_steady_audits_do_not_breach(tmp_path):
    items = _items(2500, seed=6)
    eng = Engine(_config(tmp_path, humans={"audit_rate": 0.3}, features={"drift": True}))
    scheme = eng.scheme("sentiment")
    eng.register_items(items)
    eng.predict(scheme, items)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.12)
    _answer_all(eng, items)
    eng.certify(scheme)
    eng.resolve(scheme)
    eng.draw_audit(scheme)
    _answer_all(eng, items, purposes=("audit",))
    assert not eng.drift_breached(scheme)
    assert eng.resolve(scheme, open_requests=False).get("auto", 0) > 0


def test_status_reports_the_human_label_cap_as_the_planner_charges_it(tmp_path):
    """The planner charges ``human_labels`` per request opened. The status
    used to report ``budget.spent``, which nothing increments: 0 of 400 while
    171 requests were out."""
    items = _items(200)
    eng = Engine(_config(tmp_path, budgets={"human_labels": 400}))
    scheme = eng.scheme("sentiment")
    eng.register_items(items)
    eng.predict(scheme, items)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.2)
    opened = len(eng.store.requests(schema="sentiment"))
    assert opened > 0
    st = eng.status()
    assert st["budgets"]["human_labels"] == {"limit": 400, "spent": float(opened)}


def test_work_items_are_the_requests_not_the_corpus(tmp_path):
    items = _items(200)
    eng = Engine(_config(tmp_path))
    scheme = eng.scheme("sentiment")
    eng.register_items(items)
    eng.predict(scheme, items)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.1)
    open_ids = {r.item_id for r in eng.store.requests(status=["open"])}
    assert 0 < len(open_ids) < 200
    assert set(eng.work_item_ids_for("ann")) == open_ids
    [held] = eng.claim_requests("ann", n=1)
    eng.record_human_label(held.item_id, held.schema, "positive", "ann", request_id=held.id)
    # What this person answered is no longer their work; nobody else's view changes.
    assert set(eng.work_item_ids_for("ann")) == open_ids - {held.item_id}
    assert set(eng.work_item_ids_for("other")) == open_ids - {held.item_id}
