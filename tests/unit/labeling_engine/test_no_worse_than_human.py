"""
Contract (c) on simulated studies: several people per item, a machine that is
as good as they are, and one that is clearly worse.
"""

import hashlib

import pytest

from potato.labeling_engine.config.schema import ContractConfig
from potato.labeling_engine.contracts import CalItem, CalibrationView, TierPred
from potato.labeling_engine.contracts.no_worse_than_human import NoWorseThanHuman

LABELS = ["success", "failure"]


def _u(*parts):
    return int.from_bytes(hashlib.blake2b(":".join(map(str, parts)).encode(),
                                          digest_size=8).digest(), "big") / 2 ** 64


def _view(machine_error, human_error=0.1, n_items=120, raters=4, per_item=3):
    cal = []
    for i in range(n_items):
        truth = LABELS[int(_u("t", i) < 0.4)]
        flip = {"success": "failure", "failure": "success"}
        m = flip[truth] if _u("m", i) < machine_error else truth
        who = [f"r{(i + k) % raters}" for k in range(per_item)]
        humans = {r: (flip[truth] if _u(r, i) < human_error else truth) for r in who}
        out = TierPred(m, 0.9)
        cal.append(CalItem(f"i{i}", truth, "dev", 0.5, tiers=[out], output=out,
                           humans=humans))
    return CalibrationView("s", LABELS, ["judge"], cal=cal, population=[],
                           output_complete=True)


def _cfg(eps=0.15):
    return ContractConfig(id="c", kind="no_worse_than_human", schema="s",
                          epsilon=eps, confidence=0.95)


def test_a_machine_as_good_as_people_passes():
    res = NoWorseThanHuman(_cfg()).evaluate(_view(machine_error=0.08))
    assert res.status == "met", res.metrics["alt_test"]


def test_a_clearly_worse_machine_is_violated():
    res = NoWorseThanHuman(_cfg(eps=0.05)).evaluate(_view(machine_error=0.45))
    assert res.status == "violated", res.metrics


def test_too_few_overlapping_labels_is_insufficient():
    res = NoWorseThanHuman(_cfg()).evaluate(_view(0.1, n_items=12))
    assert res.status == "insufficient"
    assert res.projection["more_overlap_items"] > 0


def test_single_rater_items_are_not_overlap():
    v = _view(0.1, per_item=1)
    res = NoWorseThanHuman(_cfg()).evaluate(v)
    assert res.metrics["overlap_items"] == 0 and res.status == "insufficient"
