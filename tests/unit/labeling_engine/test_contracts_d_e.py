"""
Budget-first projections, the distributional contract, and the legacy
uncertified threshold.
"""

import hashlib

import numpy as np
import pytest

from potato.labeling_engine.config.schema import ContractConfig
from potato.labeling_engine.contracts import CalItem, CalibrationView, TierPred
from potato.labeling_engine.contracts.budget_first import BudgetFirst
from potato.labeling_engine.contracts.distributional import Distributional, jsd
from potato.labeling_engine.contracts.threshold_legacy import ThresholdLegacy

LABELS = ["pos", "neg"]


def _u(*parts):
    return int.from_bytes(hashlib.blake2b(":".join(map(str, parts)).encode(),
                                          digest_size=8).digest(), "big") / 2 ** 64


def _view(n=300, err=lambda c: 0.3 * (1 - c), cert_share=0.5):
    cal = []
    for i in range(n):
        truth = LABELS[int(_u("t", i) < 0.4)]
        conf = _u("c", i)
        wrong = _u("w", i) < err(conf)
        pred = LABELS[1 - LABELS.index(truth)] if wrong else truth
        out = TierPred(pred, conf)
        split = "cert" if _u("s", i) < cert_share else "dev"
        cal.append(CalItem(f"i{i}", truth, split, 0.2, tiers=[out], output=out))
    return CalibrationView("s", LABELS, ["t0"], cal=cal, output_complete=True)


class TestBudgetFirst:

    def test_more_budget_buys_more_coverage_at_a_strict_target(self):
        view = _view()
        small = BudgetFirst(ContractConfig(id="b", kind="budget_first", schema="s",
                                           human_labels=0)).evaluate(view)
        big = BudgetFirst(ContractConfig(id="b", kind="budget_first", schema="s",
                                         human_labels=2000)).evaluate(view)
        cov = lambda r, e: next(f["coverage"] for f in r.metrics["frontier"] if f["error"] == e)
        assert small.status == big.status == "met"
        assert cov(big, 0.05) >= cov(small, 0.05)
        assert cov(big, 0.05) > 0
        # Looser targets never cover less.
        covs = [f["coverage"] for f in big.metrics["frontier"]]
        assert covs == sorted(covs)

    def test_dollars_through_the_reward(self):
        cfg = ContractConfig(id="b", kind="budget_first", schema="s", human_usd=50,
                             raw={"reward_per_label_usd": 0.25})
        assert BudgetFirst(cfg)._labels() == 200

    def test_too_few_dev_labels(self):
        res = BudgetFirst(ContractConfig(id="b", kind="budget_first", schema="s",
                                         human_labels=100)).evaluate(_view(n=10))
        assert res.status == "insufficient"


def _people_view(n=60, k=5, machine="match", seed=0):
    rng = np.random.default_rng(seed)
    cal = []
    for i in range(n):
        p_pos = rng.uniform(0.1, 0.9)       # how contested the item is
        people = {f"r{j}": ("pos" if rng.random() < p_pos else "neg") for j in range(k)}
        if machine == "match":
            dist = {"pos": p_pos, "neg": 1 - p_pos}
        else:                                 # always certain, always "pos"
            dist = {"pos": 1.0, "neg": 0.0}
        out = TierPred("pos" if dist["pos"] >= 0.5 else "neg", max(dist.values()),
                       dist=dist)
        cal.append(CalItem(f"i{i}", None, "dev", 0.5, tiers=[out], output=out,
                           humans=people))
    # groups_by names an annotator field: two cohorts of people.
    cohorts = {f"r{j}": {"cohort": "A" if j % 2 else "B"} for j in range(k)}
    return CalibrationView("s", LABELS, ["t0"], cal=cal, output_complete=True,
                           user_groups=cohorts)


class TestDistributional:

    def test_jsd_bounds(self):
        a, b = np.array([1.0, 0.0]), np.array([0.0, 1.0])
        assert jsd(a, a) == pytest.approx(0.0) and jsd(a, b) == pytest.approx(1.0)

    def test_a_calibrated_machine_beats_an_overconfident_one(self):
        cfg = ContractConfig(id="d", kind="distributional", schema="s", max_distance=0.35,
                             groups_by="cohort")
        good = Distributional(cfg).evaluate(_people_view(machine="match"))
        bad = Distributional(cfg).evaluate(_people_view(machine="sure"))
        assert good.status == "met" and bad.status == "infeasible"
        assert (good.metrics["overall"]["machine_distance"]
                < bad.metrics["overall"]["machine_distance"])
        assert set(good.metrics["groups"]) == {"A", "B"}

    def test_needs_several_people_per_item(self):
        cfg = ContractConfig(id="d", kind="distributional", schema="s")
        res = Distributional(cfg).evaluate(_people_view(k=2))
        assert res.status == "insufficient" and res.projection["more_overlap_items"] > 0


def test_legacy_threshold_is_uncertified_but_reports_its_error():
    cfg = ContractConfig(id="l", kind="threshold_legacy", schema="s", threshold=0.8)
    res = ThresholdLegacy(cfg).evaluate(_view())
    assert res.status == "met" and res.acceptance == {"t0": {"*": 0.8}}
    assert res.statement.startswith("Uncertified")
    assert res.metrics["measured_error"] is not None


def test_ppi_by_and_distributional_groups_by_produce_groups(tmp_path):
    """Found by potato-skill (B3): both keys were documented and did nothing."""
    import random as _r
    from potato.labeling_engine.items import ItemView
    from potato.labeling_engine.service import Engine
    from potato.persistence import clear_db_cache
    clear_db_cache()
    labels = ["positive", "negative"]
    cfg = {"task_dir": str(tmp_path), "annotation_task_name": "b3",
           "annotation_schemes": [{"name": "s", "annotation_type": "radio", "labels": labels}],
           "labeling_engine": {"enabled": True,
                               "sources": [{"id": "fx", "kind": "fixture", "error_rate": 0.1}],
                               "humans": {"overlap": 1.0, "overlap_k": 3},
                               "contracts": [
                                   {"id": "prev", "kind": "ppi", "schema": "s", "by": "lang"},
                                   {"id": "dist", "kind": "distributional", "schema": "s",
                                    "groups_by": "age"}]}}
    eng = Engine(cfg)
    rng = _r.Random(0)
    items = [ItemView(f"i{k}", "t", data={"gold": rng.choice(labels),
                                          "lang": "en" if k % 2 else "de"})
             for k in range(800)]
    scheme = eng.scheme("s")
    eng.register_items(items)
    eng.predict(scheme, items)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.25)
    gold = {i.item_id: i.data["gold"] for i in items}
    people = ["u1", "u2", "u3", "u4", "u5", "u6"]
    eng.user_attributes = lambda u: {"age": "young" if u in ("u1", "u2", "u3") else "old"}
    for k, r in enumerate(eng.store.requests(status=["open"])):
        eng.record_human_label(r.item_id, "s", gold[r.item_id], people[k % 6], request_id=r.id)
    res = eng.certify(scheme)
    assert {"all", "en", "de"} <= set(res["prev"]["metrics"]["estimates"])
    assert set(res["dist"]["metrics"]["groups"]) == {"young", "old"}
    clear_db_cache()


def test_a_distribution_clearly_off_target_is_infeasible_not_insufficient():
    """Found by potato-skill (B16)."""
    cfg = ContractConfig(id="d", kind="distributional", schema="s", max_distance=0.05)
    res = Distributional(cfg).evaluate(_people_view(n=200, machine="sure"))
    assert res.status == "infeasible" and "More items will not meet it" in res.notes[-1]
