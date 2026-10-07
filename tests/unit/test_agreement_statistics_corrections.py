"""
Corrections to the agreement statistics, found by checking Potato's numbers
against independent implementations.

* MACE counted every answer matching the true label as "knowing", so a pure
  spammer earned competence from its lucky guesses.
* "Ordinal" alpha used |a - b|, which is neither Krippendorff's ordinal metric
  nor the interval one.
* The KS statistic compared CDFs in the middle of a run of tied values.
* The geometry, rollout and span-gamma chance baselines followed dict order,
  which follows per-process string hashing, so the same data and seed gave a
  different number after a restart.
* The geometry bootstrap paired two copies of one item as "different items".
* BWS Bradley-Terry counted best-over-worst twice per judgment.

Expected values come from the ``krippendorff`` package and
``scipy.stats.ks_2samp``, not from the code under test.
"""

from __future__ import annotations

import random
import sys
import types

import numpy as np
import pytest

from potato.mace import MACEAlgorithm
from potato.server_utils.iaa import rollouts
from potato.server_utils.iaa import span
from potato.server_utils.iaa.alpha import krippendorff_alpha
from potato.server_utils.iaa.geometry_agreement import (
    _between_item_distances,
    _ks_statistic,
    geometry_agreement,
)


class TestMaceSpammers:
    def test_pure_spammers_get_near_zero_competence(self):
        rng = np.random.RandomState(0)
        n_items, n_labels = 300, 3
        true_competence = [0.9, 0.85, 0.6, 0.0, 0.0]
        truth = rng.randint(n_labels, size=n_items)
        annotations = np.zeros((n_items, len(true_competence)), int)
        for j, c in enumerate(true_competence):
            for i in range(n_items):
                annotations[i, j] = (truth[i] if rng.rand() < c
                                     else rng.randint(n_labels))

        mace = MACEAlgorithm(len(true_competence), n_labels, n_items, seed=1)
        _, competence, _, _ = mace.fit(annotations)

        # Before the fix: 0.35 and 0.35.
        assert competence[3] < 0.1
        assert competence[4] < 0.1
        for estimated, actual in zip(competence[:3], true_competence[:3]):
            assert estimated == pytest.approx(actual, abs=0.1)


# 3 annotators x 6 units on a 1-4 scale, one value missing. Reference values
# from krippendorff 0.8.2 (level_of_measurement=...).
_RELIABILITY = [[1, 2, 3, 3, 2, 1],
                [1, 2, 4, 3, 2, 2],
                [None, 3, 4, 3, 1, 1]]
_ROWS = [(f"a{a}", f"u{u}", v)
         for a, row in enumerate(_RELIABILITY)
         for u, v in enumerate(row) if v is not None]


class TestOrdinalAlpha:
    def test_matches_krippendorffs_ordinal_metric(self):
        assert krippendorff_alpha(_ROWS, "ordinal") == pytest.approx(
            0.7824698091156993, abs=1e-9)

    def test_interval_and_nominal_are_unchanged(self):
        assert krippendorff_alpha(_ROWS, "interval") == pytest.approx(
            0.7793103448275862, abs=1e-9)
        assert krippendorff_alpha(_ROWS, "nominal") == pytest.approx(
            0.3904761904761904, abs=1e-9)

    def test_matches_the_reference_package_on_random_data(self):
        krippendorff = pytest.importorskip("krippendorff")
        rnd = random.Random(3)
        for _ in range(5):
            n_ann, n_items = rnd.randint(2, 5), rnd.randint(5, 30)
            matrix = np.full((n_ann, n_items), np.nan)
            rows = []
            for i in range(n_items):
                base = rnd.choice([1, 2, 3, 4, 5])
                for a in range(n_ann):
                    if rnd.random() < 0.8:
                        v = max(1, min(5, base + rnd.choice([-2, -1, 0, 0, 1])))
                        matrix[a, i] = v
                        rows.append((f"u{a}", f"i{i}", v))
            expected = krippendorff.alpha(reliability_data=matrix,
                                          level_of_measurement="ordinal")
            assert krippendorff_alpha(rows, "ordinal") == pytest.approx(
                expected, abs=1e-9)


@pytest.mark.parametrize("ks", [_ks_statistic, rollouts._ks_statistic],
                         ids=["geometry", "rollouts"])
class TestKsTies:
    def test_identical_tied_samples_score_zero(self, ks):
        assert ks([0.5] * 10, [0.5] * 10) == 0.0

    def test_matches_scipy_with_ties(self, ks):
        ks_2samp = pytest.importorskip("scipy.stats").ks_2samp
        rnd = random.Random(1)
        for _ in range(200):
            a = [rnd.choice([0, 0.1, 0.25, 0.5, 1])
                 for _ in range(rnd.randint(1, 30))]
            b = [round(rnd.random(), 1) for _ in range(rnd.randint(1, 30))]
            assert ks(a, b) == pytest.approx(ks_2samp(a, b).statistic, abs=1e-12)


def _box(x, y):
    return {"type": "bbox", "label": "cat",
            "coordinates": {"x": x, "y": y, "width": 0.2, "height": 0.2}}


def _geometry_items(n=12):
    rnd = random.Random(7)
    items = {}
    for i in range(n):
        x, y = rnd.uniform(0, 0.7), rnd.uniform(0, 0.7)
        items[f"item_{i}"] = {
            "ann_a": [_box(x, y)],
            "ann_b": [_box(x + rnd.uniform(-0.05, 0.05), y)],
            "ann_c": [_box(x, y + rnd.uniform(-0.05, 0.05))],
        }
    return items


def _reordered(items):
    """Same data, every dict in reverse insertion order."""
    return {item: {ann: objs for ann, objs in reversed(list(by_ann.items()))}
            for item, by_ann in reversed(list(items.items()))}


class TestChanceBaselineIgnoresInputOrder:
    @pytest.mark.parametrize("chance_samples", [2000, 50],
                             ids=["exact", "sampled"])
    def test_geometry(self, chance_samples):
        items = _geometry_items()
        first = geometry_agreement(items, chance_samples=chance_samples,
                                   bootstrap=20)
        second = geometry_agreement(_reordered(items),
                                    chance_samples=chance_samples, bootstrap=20)
        assert first["localization"] == second["localization"]
        assert first["confidence"] == second["confidence"]

    def test_small_corpus_uses_every_between_item_pair(self):
        items = _geometry_items(n=4)  # 12 objects, 3 per item: 66 - 4 * 3
        report = geometry_agreement(items)
        assert report["n_chance_pairs"] == 54

    @pytest.mark.parametrize("chance_samples", [2000, 30],
                             ids=["exact", "sampled"])
    def test_rollouts(self, chance_samples):
        rnd = random.Random(2)
        items = {}
        for i in range(10):
            t = rnd.uniform(0, 10)
            items[f"clip_{i}"] = {
                ann: {"violations": [{"stream": "s", "t": t + rnd.uniform(-0.2, 0.2)}]}
                for ann in ("ann_a", "ann_b", "ann_c")}
        first = rollouts.localization(items, tolerance=1.0,
                                      chance_samples=chance_samples)
        second = rollouts.localization(_reordered(items), tolerance=1.0,
                                       chance_samples=chance_samples)
        assert first == second

    def test_span_gamma(self):
        spans = {"u1": [(0, 3, "X"), (5, 8, "Y")],
                 "u2": [(1, 3, "X"), (6, 9, "Y")],
                 "u3": [(0, 4, "X")]}
        reordered = {u: list(reversed(spans[u])) for u in reversed(list(spans))}
        assert span.gamma(spans, length=10) == span.gamma(reordered, length=10)


class TestBootstrapCopiesAreOneItem:
    def test_copies_of_one_item_never_form_a_between_pair(self):
        objects = {"ann_a": [_box(0.1, 0.1)], "ann_b": [_box(0.5, 0.5)]}
        sample = {"item_0~0": objects, "item_0~1": objects}
        source = {"item_0~0": "item_0", "item_0~1": "item_0"}
        assert _between_item_distances(
            sample, lambda a, b: 1.0, 2000, random.Random(0), source) == []


class TestBwsBradleyTerryPairs:
    def test_a_judgment_over_k_items_gives_2k_minus_3_pairs(self, monkeypatch):
        from potato.bws_scoring import BwsScorer

        captured = []
        fake = types.ModuleType("choix")

        def ilsr_pairwise(n_items, comparisons, alpha=0.0):
            captured.extend(comparisons)
            return np.zeros(n_items)

        fake.ilsr_pairwise = ilsr_pairwise
        monkeypatch.setitem(sys.modules, "choix", fake)

        ids = ["s1", "s2", "s3", "s4"]
        items = [{"source_id": sid, "text": sid, "position": pos}
                 for sid, pos in zip(ids, "ABCD")]
        annotation = {"instance_id": "t1", "bws_items": items,
                      "best": "A", "worst": "D", "annotator": "u1"}
        pool = [{"id": sid, "text": sid} for sid in ids]
        BwsScorer([annotation], pool, id_key="id").bradley_terry()

        assert len(captured) == 2 * 4 - 3
        assert len(set(captured)) == len(captured)
