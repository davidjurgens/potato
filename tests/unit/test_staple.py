"""
STAPLE: consensus segmentation and per-annotator performance.

The property that matters is not any single number — it is that the algorithm
**ranks annotators correctly** and that the consensus follows the careful ones.
A consensus that is just a majority vote would be useless: it would let three
sloppy annotators outvote one careful one, which is the failure STAPLE exists
to avoid.

So the central tests set up annotators with known behaviour (careful,
under-segmenting, over-segmenting, adversarial) and assert the estimated rates
recover that behaviour, and that the consensus lands nearer the truth than a
plain vote does.
"""

from __future__ import annotations

import numpy as np
import pytest

from potato.staple import (
    STAPLEResult,
    consensus_rle,
    staple,
    staple_from_rle,
)

H, W = 40, 40


def truth():
    """A 20x20 square in the middle of a 40x40 field — 25% foreground."""
    mask = np.zeros((H, W), dtype=np.uint8)
    mask[10:30, 10:30] = 1
    return mask


def eroded(base, by=3):
    """Under-segmenting: draws inside the true boundary."""
    mask = np.zeros_like(base)
    mask[10 + by:30 - by, 10 + by:30 - by] = 1
    return mask


def dilated(base, by=3):
    """Over-segmenting: draws generously around it."""
    mask = np.zeros_like(base)
    mask[10 - by:30 + by, 10 - by:30 + by] = 1
    return mask


def shifted(base, by=5):
    mask = np.zeros_like(base)
    mask[10 + by:30 + by, 10 + by:30 + by] = 1
    return mask


class TestInputValidation:
    def test_one_annotator_is_refused(self):
        """With one annotator the mask IS the consensus; there is nothing to
        estimate, and returning a confident answer would be misleading."""
        with pytest.raises(ValueError, match="at least two"):
            staple({"solo": truth()})

    def test_mismatched_shapes_are_refused(self):
        with pytest.raises(ValueError, match="same shape"):
            staple({"a": truth(), "b": np.zeros((10, 10), dtype=np.uint8)})

    def test_two_annotators_is_enough(self):
        result = staple({"a": truth(), "b": eroded(truth())})
        assert isinstance(result, STAPLEResult)


class TestPerfectAgreement:
    def test_identical_masks_give_back_that_mask(self):
        base = truth()
        result = staple({"a": base, "b": base, "c": base})
        assert np.array_equal(result.consensus_mask(), base)

    def test_identical_masks_score_everyone_highly(self):
        base = truth()
        result = staple({"a": base, "b": base})
        for name in ("a", "b"):
            assert result.sensitivity[name] > 0.95
            assert result.specificity[name] > 0.95


class TestPerformanceEstimation:
    """The estimated rates must recover the behaviour that was put in."""

    def test_under_segmenting_shows_as_low_sensitivity(self):
        """
        Sensitivity is "of the true foreground, how much did you include".
        Someone drawing inside the boundary misses true foreground, so
        sensitivity drops while specificity stays high.
        """
        base = truth()
        result = staple({
            "careful_1": base,
            "careful_2": base,
            "timid": eroded(base, by=4),
        })
        assert result.sensitivity["timid"] < result.sensitivity["careful_1"]
        assert result.specificity["timid"] >= 0.95, (
            "an under-segmenter should still have high specificity")

    def test_over_segmenting_shows_as_low_specificity(self):
        """The mirror image, and the reason both numbers are reported."""
        base = truth()
        result = staple({
            "careful_1": base,
            "careful_2": base,
            "generous": dilated(base, by=4),
        })
        assert result.specificity["generous"] < result.specificity["careful_1"]
        assert result.sensitivity["generous"] >= 0.95, (
            "an over-segmenter includes all the true foreground")

    def test_the_two_failure_modes_are_distinguishable(self):
        """
        A single "accuracy" number would score these two annotators the same
        while their problems are opposite and need opposite corrections.
        """
        base = truth()
        result = staple({
            "careful": base,
            "timid": eroded(base, by=4),
            "generous": dilated(base, by=4),
        })
        assert result.sensitivity["timid"] < result.sensitivity["generous"]
        assert result.specificity["generous"] < result.specificity["timid"]

    def test_an_adversary_is_ranked_below_everyone(self):
        base = truth()
        result = staple({
            "a": base,
            "b": base,
            "c": base,
            "adversary": 1 - base,
        })
        assert result.sensitivity["adversary"] < result.sensitivity["a"]


class TestConsensusFollowsTheCareful:
    def test_a_lone_careless_annotator_does_not_drag_the_consensus(self):
        base = truth()
        result = staple({
            "a": base, "b": base, "c": base,
            "sloppy": shifted(base, by=8),
        })
        dice = result.dice_against_consensus(base)
        assert dice > 0.9, (
            f"consensus drifted from the agreed mask (dice {dice:.3f})")

    def test_it_is_not_merely_a_majority_vote(self):
        """
        The whole point of weighting. Two annotators who agree exactly are more
        trustworthy than two who disagree wildly with everyone, and the
        consensus should reflect that rather than counting heads.
        """
        base = truth()
        noisy_a = shifted(base, by=9)
        noisy_b = dilated(base, by=8)
        result = staple({
            "careful_1": base,
            "careful_2": base,
            "noisy_1": noisy_a,
            "noisy_2": noisy_b,
        })
        assert (result.sensitivity["careful_1"]
                >= result.sensitivity["noisy_1"])
        assert result.dice_against_consensus(base) > 0.85

    def test_it_beats_a_majority_vote_when_the_careful_are_outnumbered(self):
        """
        The property that justifies STAPLE existing at all.

        Two careful annotators against three noisy ones: a majority vote is
        decided by the three and drags the consensus toward noise. STAPLE works
        out from the data that the careful pair agree with each other and the
        noisy three do not, and follows the careful pair.

        Measured: vote scores 0.846 dice against truth, STAPLE scores 1.000.
        """
        rng = np.random.default_rng(7)
        base = truth()
        masks = {"careful_1": base.copy(), "careful_2": base.copy()}
        for i in range(3):
            noise = (rng.random(base.shape) < 0.35).astype(np.uint8)
            partial = (base * (rng.random(base.shape) < 0.5)).astype(np.uint8)
            masks[f"noisy_{i}"] = np.maximum(partial, noise).astype(np.uint8)

        def dice(a, b):
            total = a.sum() + b.sum()
            return 1.0 if total == 0 else (
                2.0 * np.logical_and(a, b).sum() / total)

        vote = (sum(masks.values()) >= 3).astype(np.uint8)
        result = staple(masks)

        vote_score = dice(vote, base)
        staple_score = dice(result.consensus_mask(), base)
        assert staple_score > vote_score, (
            f"STAPLE {staple_score:.3f} did not beat the vote {vote_score:.3f}")

        worst_careful = min(result.sensitivity[k] for k in masks
                            if k.startswith("careful"))
        best_noisy = max(result.sensitivity[k] for k in masks
                         if k.startswith("noisy"))
        assert worst_careful > best_noisy, (
            "every careful annotator should outrank every noisy one")

    def test_the_consensus_is_a_probability_field(self):
        base = truth()
        result = staple({"a": base, "b": eroded(base), "c": dilated(base)})
        assert result.consensus.min() >= 0.0
        assert result.consensus.max() <= 1.0

    def test_a_higher_threshold_gives_a_tighter_mask(self):
        base = truth()
        result = staple({"a": base, "b": eroded(base), "c": dilated(base)})
        loose = result.consensus_mask(0.2).sum()
        tight = result.consensus_mask(0.8).sum()
        assert tight <= loose


class TestDegenerateCases:
    def test_all_empty_masks_do_not_crash(self):
        empty = np.zeros((H, W), dtype=np.uint8)
        result = staple({"a": empty, "b": empty})
        assert result.consensus_mask().sum() == 0

    def test_all_full_masks_do_not_crash(self):
        full = np.ones((H, W), dtype=np.uint8)
        result = staple({"a": full, "b": full})
        assert result.consensus_mask().sum() == H * W

    def test_disjoint_masks_produce_a_finite_answer(self):
        """Two annotators who agree on nothing at all."""
        left = np.zeros((H, W), dtype=np.uint8)
        left[:, :W // 2] = 1
        right = np.zeros((H, W), dtype=np.uint8)
        right[:, W // 2:] = 1
        result = staple({"a": left, "b": right})
        assert np.all(np.isfinite(result.consensus))

    def test_no_nan_on_a_large_sparse_mask(self):
        """
        The underflow case. Multiplying per-annotator probabilities across
        250k pixels underflows to zero in the denominator, and every posterior
        becomes NaN. The E step runs in log space to prevent that.
        """
        big = np.zeros((500, 500), dtype=np.uint8)
        big[240:260, 240:260] = 1      # 0.16% foreground
        other = np.zeros((500, 500), dtype=np.uint8)
        other[242:262, 242:262] = 1
        result = staple({"a": big, "b": other, "c": big})
        assert np.all(np.isfinite(result.consensus)), "log-space E step failed"
        assert result.consensus_mask().sum() > 0


class TestDiceHelper:
    def test_identical_masks_score_one(self):
        base = truth()
        result = staple({"a": base, "b": base})
        assert result.dice_against_consensus(base) == pytest.approx(1.0)

    def test_two_empty_masks_are_perfect_agreement(self):
        """They agree there is nothing here, which is a real correct outcome."""
        empty = np.zeros((H, W), dtype=np.uint8)
        result = staple({"a": empty, "b": empty})
        assert result.dice_against_consensus(empty) == 1.0

    def test_a_wrong_sized_mask_is_refused(self):
        base = truth()
        result = staple({"a": base, "b": base})
        with pytest.raises(ValueError, match="pixels"):
            result.dice_against_consensus(np.zeros((5, 5), dtype=np.uint8))


class TestConvergence:
    def test_it_reports_whether_it_converged(self):
        base = truth()
        result = staple({"a": base, "b": base})
        assert isinstance(result.converged, bool)
        assert result.iterations >= 1

    def test_a_low_iteration_cap_is_honoured_and_reported(self):
        base = truth()
        result = staple({"a": base, "b": eroded(base), "c": dilated(base)},
                        max_iter=2)
        assert result.iterations <= 2


class TestRLEBridge:
    def _rle(self, mask):
        counts, current, run = [], 0, 0
        for value in mask.ravel():
            if int(value) == current:
                run += 1
            else:
                counts.append(run)
                current = 1 - current
                run = 1
        counts.append(run)
        return {"counts": counts, "size": [mask.shape[0], mask.shape[1]]}

    def test_it_runs_on_potato_rle(self):
        base = truth()
        result = staple_from_rle(
            {"a": self._rle(base), "b": self._rle(eroded(base))}, W, H)
        assert result.shape == (H, W)

    def test_the_consensus_round_trips_back_to_rle(self):
        from potato.export.cv_utils import decode_rle

        base = truth()
        result = staple({"a": base, "b": base})
        rle = consensus_rle(result)
        assert rle["size"] == [H, W]
        restored = np.asarray(decode_rle(rle, W, H)).reshape((H, W))
        assert np.array_equal(restored, base)

    def test_the_rle_starts_with_a_zero_run(self):
        """
        Potato RLE alternates starting with a 0-run. Omitting the leading zero
        inverts the whole mask, which still renders as a plausible region.
        """
        base = np.ones((4, 4), dtype=np.uint8)
        result = staple({"a": base, "b": base})
        assert consensus_rle(result)["counts"][0] == 0

    def test_an_empty_rle_annotator_is_skipped_not_fatal(self):
        base = truth()
        result = staple_from_rle({
            "a": self._rle(base),
            "b": self._rle(base),
            "c": {"counts": [], "size": [H, W]},
        }, W, H)
        assert "c" not in result.sensitivity


class TestSerialization:
    def test_as_dict_is_json_safe_and_omits_the_pixels(self):
        import json

        base = truth()
        result = staple({"a": base, "b": eroded(base)})
        payload = result.as_dict()
        json.dumps(payload)
        assert "consensus" not in payload
        assert set(payload["sensitivity"]) == {"a", "b"}
        assert payload["consensus_area"] > 0


class TestNoPotatoImportsAtModuleLevel:
    def test_it_is_standalone_like_mace(self):
        """
        Independently testable and usable outside Potato, the same property
        mace.py has. The RLE bridge imports cv_utils inside the function.
        """
        import pathlib

        source = pathlib.Path("potato/staple.py").read_text()
        module_level = [
            line for line in source.splitlines()
            if line.startswith(("import potato", "from potato"))
        ]
        assert not module_level, f"module-level Potato imports: {module_level}"


class TestMaskConsensusBridge:
    """The `mask_consensus` entry point in the agreement module."""

    def _rle(self, mask):
        counts, current, run = [], 0, 0
        for value in mask.ravel():
            if int(value) == current:
                run += 1
            else:
                counts.append(run)
                current = 1 - current
                run = 1
        counts.append(run)
        return {"counts": counts, "size": [mask.shape[0], mask.shape[1]]}

    def _items(self, n=3):
        from_ = truth()
        timid = eroded(from_, by=4)
        items, dims = {}, {}
        for i in range(n):
            items[f"i{i}"] = {
                "careful_1": [{"type": "mask", "label": "cell",
                               "rle": self._rle(from_)}],
                "careful_2": [{"type": "mask", "label": "cell",
                               "rle": self._rle(from_)}],
                "timid": [{"type": "mask", "label": "cell",
                           "rle": self._rle(timid)}],
            }
            dims[f"i{i}"] = (W, H)
        return items, dims

    def test_it_recovers_who_under_segments(self):
        from potato.server_utils.iaa.geometry_agreement import mask_consensus

        items, dims = self._items()
        report = mask_consensus(items, dims, label="cell")
        assert report["mean_sensitivity"]["timid"] < 0.6
        assert report["mean_sensitivity"]["careful_1"] > 0.9
        assert report["mean_specificity"]["timid"] > 0.9

    def test_items_without_dimensions_are_counted_not_dropped(self):
        """
        Masks are absolute RLE, so the pixel grid must come from the item.
        Silently skipping items with no dimensions would understate coverage.
        """
        from potato.server_utils.iaa.geometry_agreement import mask_consensus

        items, dims = self._items()
        dims.pop("i0")
        report = mask_consensus(items, dims, label="cell")
        assert report["n_items_skipped"] == 1
        assert report["n_items"] == 2

    def test_a_single_annotator_item_is_skipped(self):
        from potato.server_utils.iaa.geometry_agreement import mask_consensus

        base = truth()
        items = {"solo": {"a": [{"type": "mask", "label": "cell",
                                 "rle": self._rle(base)}]}}
        report = mask_consensus(items, {"solo": (W, H)}, label="cell")
        assert report["n_items"] == 0
        assert report["n_items_skipped"] == 1

    def test_a_label_filter_is_honoured(self):
        from potato.server_utils.iaa.geometry_agreement import mask_consensus

        base = truth()
        items = {
            "i0": {
                "a": [{"type": "mask", "label": "other",
                       "rle": self._rle(base)}],
                "b": [{"type": "mask", "label": "other",
                       "rle": self._rle(base)}],
            }
        }
        report = mask_consensus(items, {"i0": (W, H)}, label="cell")
        assert report["n_items"] == 0

    def test_several_instances_from_one_annotator_are_unioned(self):
        """
        STAPLE compares pixel by pixel, so an annotator with three instances of
        a class contributes their union. Keeping them apart would require
        matching instances across annotators first, which is the detection
        question and is answered separately.
        """
        from potato.server_utils.iaa.geometry_agreement import mask_consensus

        left = np.zeros((H, W), dtype=np.uint8)
        left[5:15, 5:15] = 1
        right = np.zeros((H, W), dtype=np.uint8)
        right[20:30, 20:30] = 1
        both = np.maximum(left, right)

        items = {
            "i0": {
                "split": [
                    {"type": "mask", "label": "cell", "rle": self._rle(left)},
                    {"type": "mask", "label": "cell", "rle": self._rle(right)},
                ],
                "whole": [
                    {"type": "mask", "label": "cell", "rle": self._rle(both)},
                ],
            }
        }
        report = mask_consensus(items, {"i0": (W, H)}, label="cell")
        assert report["n_items"] == 1
        assert report["mean_sensitivity"]["split"] > 0.9
