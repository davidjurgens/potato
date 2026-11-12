"""Optimizer reports: cheaper cascades and prompt variants, scored on dev only."""

import json
import random

import pytest

from potato.labeling_engine import optimize
from potato.labeling_engine.items import ItemView
from potato.labeling_engine.model import ModelCall
from potato.labeling_engine.service import Engine
from potato.persistence import clear_db_cache

LABELS = ["positive", "negative"]


@pytest.fixture(autouse=True)
def _db():
    clear_db_cache()
    yield
    clear_db_cache()


def _study(tmp_path, sources, cascade):
    cfg = {"task_dir": str(tmp_path), "annotation_task_name": "o",
           "annotation_schemes": [{"name": "s", "annotation_type": "radio",
                                   "labels": LABELS, "description": "sentiment"}],
           "labeling_engine": {"enabled": True, "sources": sources, "cascade": cascade,
                               "contracts": [{"id": "acc", "kind": "selective_risk",
                                              "schema": "s", "error": 0.15}]}}
    eng = Engine(cfg)
    rng = random.Random(1)
    items = [ItemView(f"i{k}", f"text {k}", data={"gold": rng.choice(LABELS)})
             for k in range(1500)]
    scheme = eng.scheme("s")
    eng.register_items(items)
    eng.predict(scheme, items)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.25)
    eng.predict(scheme, items)
    gold = {i.item_id: i.data["gold"] for i in items}
    for r in eng.store.requests(status=["open"]):
        eng.record_human_label(r.item_id, "s", gold[r.item_id], "ann", request_id=r.id)
    return eng, scheme, items


def test_cascade_report_prefers_the_cheap_good_tier(tmp_path):
    eng, scheme, _ = _study(tmp_path, [
        {"id": "cheap", "kind": "fixture", "error_rate": 0.05, "seed": 1,
         "options": {"separability": 0.9}},
        {"id": "dear", "kind": "fixture", "error_rate": 0.05, "seed": 2,
         "options": {"separability": 0.9}}], ["cheap", "dear"])
    # Make "dear" expensive in the call log.
    vid = eng.tier_versions(scheme)[1]
    eng.store.add_calls([ModelCall(vid, "fixture", "dear", "p", f"x{k}", cost_usd=0.01,
                                   estimated=False) for k in range(20)])
    rep = optimize.cascade_report(eng, scheme)
    assert rep["recommended"]["tiers"] == ["cheap"]
    assert {tuple(c["tiers"]) for c in rep["candidates"]} == {
        ("cheap",), ("dear",), ("cheap", "dear")}
    # It spent no look at the cert labels.
    assert eng.store.looks_used("acc", eng.cascade_hash(scheme)) == 0


def test_prompt_search_scores_variants_on_dev(tmp_path, monkeypatch):
    from potato.labeling_engine.sources.llm import LLMSource
    truth = {}

    class Fake:
        def query_with_usage(self, prompt, fmt=None):
            # The paraphrase (it says "carefully") is always right; the
            # current prompt is right on about half the items.
            iid = "i" + prompt.split("text ")[-1].split()[0].strip('"\n')
            g = truth.get(iid, "positive")
            right = "carefully" in prompt or int(iid[1:]) % 2 == 0
            label = g if right else ("negative" if g == "positive" else "positive")
            return {"label": label, "confidence": 80}, None
    monkeypatch.setattr(LLMSource, "_endpoint", lambda self, temperature=None: Fake())
    rng = random.Random(1)
    for k in range(1500):
        truth[f"i{k}"] = rng.choice(LABELS)
    eng, scheme, items = _study(tmp_path, [
        {"id": "llm", "kind": "llm", "endpoint_type": "openai", "model": "m"}], ["llm"])
    para = json.dumps(["Read the review carefully. {instructions}\nLabels:\n{labels}\n"
                       "Item: {text}\nAnswer with JSON: label, confidence, reasoning. "
                       "positive negative"])
    n_calls = eng.store.conn.execute("SELECT COUNT(*) FROM model_call").fetchone()[0]
    rep = optimize.prompt_search(eng, scheme, items, n_variants=1, generate=lambda r: para)
    assert len(rep["results"]) == 2, rep
    assert rep["results"][0]["is_current"] is False
    assert rep["results"][0]["accuracy"] > rep["results"][1]["accuracy"]
    # The current prompt is scored from the tier's own predictions: the only
    # new calls are the paraphrase's, one per dev item.
    n_dev = rep["n_dev"]
    new = eng.store.conn.execute("SELECT COUNT(*) FROM model_call").fetchone()[0] - n_calls
    assert new == n_dev


def test_prompt_search_says_so_when_there_are_no_paraphrases(tmp_path, monkeypatch):
    from potato.labeling_engine.sources.llm import LLMSource

    class Fake:
        def query_with_usage(self, prompt, fmt=None):
            return {"label": "positive", "confidence": 80}, None
    monkeypatch.setattr(LLMSource, "_endpoint", lambda self, temperature=None: Fake())
    eng, scheme, items = _study(tmp_path, [
        {"id": "llm", "kind": "llm", "endpoint_type": "openai", "model": "m"}], ["llm"])
    n_calls = eng.store.conn.execute("SELECT COUNT(*) FROM model_call").fetchone()[0]
    rep = optimize.prompt_search(eng, scheme, items, n_variants=2, generate=lambda r: "[]")
    assert "no usable paraphrases" in rep["error"]
    assert eng.store.conn.execute("SELECT COUNT(*) FROM model_call").fetchone()[0] == n_calls


def test_no_cascade_is_recommended_when_none_keeps_coverage(tmp_path):
    """Every candidate accepts nothing: naming the cheapest would recommend a
    tier the contract rejected."""
    eng, scheme, _ = _study(tmp_path, [
        {"id": "a", "kind": "fixture", "error_rate": 0.5, "seed": 1,
         "options": {"separability": 0.0}},
        {"id": "b", "kind": "fixture", "error_rate": 0.5, "seed": 2,
         "options": {"separability": 0.0}}], ["a", "b"])
    rep = optimize.cascade_report(eng, scheme)
    assert all(c["contracts"]["acc"]["coverage"] == 0 for c in rep["candidates"])
    assert rep["recommended"] is None
    assert rep["note"].startswith("No candidate cascade keeps any coverage")


def test_features_optimize_puts_a_report_in_each_planner_pass(tmp_path):
    """The flag was declared and read by nothing."""
    from potato.labeling_engine.allocation.planner import Planner
    srcs = [{"id": "cheap", "kind": "fixture", "error_rate": 0.05, "seed": 1,
             "options": {"separability": 0.9}},
            {"id": "dear", "kind": "fixture", "error_rate": 0.05, "seed": 2,
             "options": {"separability": 0.9}}]
    eng, scheme, items = _study(tmp_path, srcs, ["cheap", "dear"])
    off = Planner(eng, item_source=lambda _engine: items).tick()
    assert "optimize" not in off["schemes"]["s"]
    eng.cfg.features["optimize"] = True
    planner = Planner(eng, item_source=lambda _engine: items)
    on = planner.tick()
    assert on["schemes"]["s"]["optimize"]["current"] == ["cheap", "dear"]
    assert on["schemes"]["s"]["optimize"]["recommended"]
    assert planner.last_optimize["s"]["note"].startswith("Scored on dev labels only")
