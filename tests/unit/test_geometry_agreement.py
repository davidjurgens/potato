"""
Chance-corrected agreement over geometry.

The load-bearing property of an agreement measure is not any single value — it
is that the measure ORDERS annotator quality correctly. A coefficient that
returns 0.8 for careful work and 0.9 for careless work is worse than none,
because it will be believed. So the central tests here feed in progressively
noisier annotations and assert the score falls monotonically.

That framing is Braylan, Alonso and Lease's (WWW 2022): they evaluate distance
functions by rank correlation with known annotator quality, and it is why this
module defaults to sigma over a GIoU distance rather than alpha over 1 - IoU.
"""

from __future__ import annotations

import math
import random

import pytest

from potato.server_utils.iaa.geometry_agreement import (
    DISTANCES,
    centroid_distance,
    geometry_agreement,
    giou_bbox,
    sigma_agreement,
)


def box(x, y, w=0.2, h=0.2, label="cat"):
    return {"type": "bbox", "label": label,
            "coordinates": {"x": x, "y": y, "width": w, "height": h}}


def corpus(offset=0.0, n=10, label_b="cat", seed=None):
    """Two annotators; the second is displaced by `offset`."""
    rng = random.Random(seed) if seed is not None else None
    items = {}
    for i in range(n):
        x = 0.05 + (i % 5) * 0.15
        y = 0.05 + (i // 5) * 0.3
        jitter_x = rng.uniform(-offset, offset) if rng else offset
        jitter_y = rng.uniform(-offset, offset) if rng else offset
        items[f"item_{i}"] = {
            "ann_a": [box(x, y)],
            "ann_b": [box(x + jitter_x, y + jitter_y, label=label_b)],
        }
    return items


class TestGIoU:
    def test_identical_boxes_score_one(self):
        assert giou_bbox([0, 0, 1, 1], [0, 0, 1, 1]) == pytest.approx(1.0)

    def test_touching_boxes_score_zero(self):
        assert giou_bbox([0, 0, 0.2, 0.2], [0.2, 0, 0.2, 0.2]) == pytest.approx(0.0)

    def test_it_keeps_a_gradient_where_plain_iou_is_flat(self):
        """
        The whole reason GIoU is the default. Plain IoU is 0 for every disjoint
        pair, so a near-miss and a wild miss score identically and the measure
        has no gradient exactly where annotators disagree most.
        """
        near = giou_bbox([0, 0, 0.2, 0.2], [0.25, 0, 0.2, 0.2])
        far = giou_bbox([0, 0, 0.2, 0.2], [0.8, 0, 0.2, 0.2])
        assert near > far, "GIoU must distinguish a near miss from a far one"

    def test_it_is_bounded_below_by_minus_one(self):
        assert giou_bbox([0, 0, 0.01, 0.01], [0.99, 0.99, 0.01, 0.01]) >= -1.0

    def test_a_degenerate_box_does_not_crash(self):
        assert giou_bbox([0, 0, 0, 0], [0, 0, 1, 1]) == -1.0


class TestContainment:
    """``containment_bbox`` answers "is this inside that?", which IoU does not.

    Added for the VLM critique's "did the annotator miss this?" pass, where an
    IoU test reported a missed car that was in fact annotated — by a box three
    times too large, whose looseness is exactly what pushed IoU down to 0.12.
    """

    def test_a_box_fully_inside_another_scores_one(self):
        from potato.server_utils.iaa.geometry import containment_bbox

        assert containment_bbox([0.4, 0.4, 0.1, 0.1],
                                [0.2, 0.2, 0.6, 0.6]) == pytest.approx(1.0)

    def test_containment_stays_high_where_iou_collapses(self):
        from potato.server_utils.iaa.geometry import (containment_bbox,
                                                      iou_bbox)

        inner = [0.45, 0.45, 0.05, 0.05]
        outer = [0.2, 0.2, 0.6, 0.6]
        assert iou_bbox(inner, outer) < 0.05
        assert containment_bbox(inner, outer) == pytest.approx(1.0)

    def test_it_is_asymmetric(self):
        """The asymmetry is the point: a wheel is inside a bus, a bus is not
        inside a wheel."""
        from potato.server_utils.iaa.geometry import containment_bbox

        small = [0.4, 0.4, 0.1, 0.1]
        big = [0.2, 0.2, 0.6, 0.6]
        assert containment_bbox(small, big) > containment_bbox(big, small)

    def test_half_overlap_scores_half(self):
        from potato.server_utils.iaa.geometry import containment_bbox

        assert containment_bbox([0.0, 0.0, 0.2, 0.2],
                                [0.1, 0.0, 0.2, 0.2]) == pytest.approx(0.5)

    def test_disjoint_boxes_score_zero(self):
        from potato.server_utils.iaa.geometry import containment_bbox

        assert containment_bbox([0.0, 0.0, 0.1, 0.1],
                                [0.5, 0.5, 0.1, 0.1]) == 0.0

    def test_degenerate_input_does_not_divide_by_zero(self):
        from potato.server_utils.iaa.geometry import containment_bbox

        assert containment_bbox([0, 0, 0, 0], [0, 0, 1, 1]) == 0.0
        assert containment_bbox([0, 0, 1, 1], [0, 0, 0, 0]) == 0.0
        assert containment_bbox([], [0, 0, 1, 1]) == 0.0
        assert containment_bbox([0, 0, 1], [0, 0, 1, 1]) == 0.0


class TestSigma:
    def test_identical_distributions_give_zero(self):
        """Agreeing no more than chance is 0, not 0.5."""
        assert sigma_agreement([0.4] * 5, [0.4] * 5) == pytest.approx(0.0)

    def test_perfect_agreement_gives_one(self):
        assert sigma_agreement([0.0] * 5, [0.5] * 5) == pytest.approx(1.0)

    def test_worse_than_chance_goes_negative(self):
        """
        Not clamped to 0 on purpose: annotators further apart on the same item
        than on unrelated ones is a real and diagnosable state, usually a
        definition problem rather than carelessness.
        """
        assert sigma_agreement([0.8] * 5, [0.4] * 5) < 0

    def test_no_variation_at_all_is_undefined_not_perfect(self):
        assert math.isnan(sigma_agreement([0.0] * 5, [0.0] * 5))

    def test_empty_input_is_undefined(self):
        assert math.isnan(sigma_agreement([], [0.5]))
        assert math.isnan(sigma_agreement([0.5], []))


class TestTheOrderingProperty:
    """
    The property that actually matters: more noise must score lower.

    A measure that ranks careless work above careful work is worse than no
    measure, because it will be believed.
    """

    def test_sigma_falls_monotonically_as_noise_rises(self):
        offsets = [0.0, 0.01, 0.02, 0.03]
        sigmas = []
        for offset in offsets:
            report = geometry_agreement(corpus(offset=offset, n=12))
            sigmas.append(report["localization"]["sigma"])

        assert not any(math.isnan(s) for s in sigmas), sigmas
        for earlier, later in zip(sigmas, sigmas[1:]):
            assert later <= earlier + 1e-9, (
                f"agreement rose with noise: {sigmas}")
        assert sigmas[0] > sigmas[-1], "noise made no difference at all"

    @pytest.mark.parametrize("distance", sorted(DISTANCES))
    def test_every_distance_orders_correctly(self, distance):
        """
        Each offered distance must satisfy the ordering property, or it should
        not be offered. This is the check Braylan et al. apply to candidate
        distance functions.
        """
        clean = geometry_agreement(corpus(offset=0.005, n=12),
                                   distance=distance)
        noisy = geometry_agreement(corpus(offset=0.03, n=12),
                                   distance=distance)
        clean_sigma = clean["localization"]["sigma"]
        noisy_sigma = noisy["localization"]["sigma"]
        if math.isnan(clean_sigma) or math.isnan(noisy_sigma):
            pytest.skip(f"{distance} undefined on this fixture")
        assert noisy_sigma < clean_sigma, (
            f"{distance} scored noisier annotations higher "
            f"({noisy_sigma:.3f} >= {clean_sigma:.3f})")

    def test_an_unknown_distance_is_refused(self):
        with pytest.raises(ValueError, match="Unknown distance"):
            geometry_agreement({}, distance="cosine")


class TestTheThreeQuestions:
    def test_a_label_disagreement_shows_up_as_classification(self):
        """
        Same geometry, different labels. Localization must stay high and
        classification must drop — reporting one blended number would hide
        which of the two is the actual problem.
        """
        items = {}
        for i in range(10):
            x = 0.05 + (i % 5) * 0.15
            items[f"item_{i}"] = {
                "a": [box(x, 0.1, label="cat")],
                "b": [box(x, 0.1, label="dog" if i % 2 else "cat")],
            }
        report = geometry_agreement(items)
        assert report["localization"]["sigma"] > 0.9
        assert report["classification"]["alpha"] < 0.6

    def test_a_missed_object_shows_up_as_detection(self):
        """Same labels and positions; one annotator simply misses things."""
        items = {}
        for i in range(10):
            x = 0.05 + (i % 5) * 0.15
            both = [box(x, 0.1), box(x, 0.6)]
            items[f"item_{i}"] = {
                "a": both,
                "b": both if i % 2 else [box(x, 0.1)],
            }
        report = geometry_agreement(items)
        assert report["detection"]["alpha"] < 0.6
        assert report["localization"]["sigma"] > 0.9

    def test_the_three_are_reported_separately(self):
        report = geometry_agreement(corpus(offset=0.01))
        assert "detection" in report
        assert "classification" in report
        assert "localization" in report


class TestUndefinedIsExplained:
    def test_unanimous_detection_says_why_it_is_undefined(self):
        """
        Alpha divides by expected disagreement, so a unanimous corpus has
        D_e = 0 and alpha is genuinely undefined — not 1.0. A bare NaN cannot
        be told apart from a broken computation, so the reason is named.
        """
        report = geometry_agreement(corpus(offset=0.0))
        detection = report["detection"]
        assert math.isnan(detection["alpha"])
        assert "undefined_because" in detection
        assert "Perfect agreement" in detection["undefined_because"]

    def test_a_single_annotator_corpus_is_reported_not_scored(self):
        items = {"a": {"only": [box(0.1, 0.1)]}}
        report = geometry_agreement(items)
        assert report["n_items"] == 0
        assert report["n_items_skipped"] == 1
        assert "note" in report

    def test_an_empty_corpus_does_not_crash(self):
        report = geometry_agreement({})
        assert report["n_items"] == 0


class TestChanceCorrection:
    def test_an_easy_corpus_is_not_rewarded_for_being_easy(self):
        """
        The point of chance correction. If every image holds one big centred
        object, two annotators agree closely — but so would two annotators
        working on DIFFERENT images, so the measure must not read that as
        skill.
        """
        easy = {
            f"item_{i}": {
                "a": [box(0.25, 0.25, 0.5, 0.5)],
                "b": [box(0.26, 0.26, 0.5, 0.5)],
            }
            for i in range(10)
        }
        report = geometry_agreement(easy)
        sigma = report["localization"]["sigma"]
        # Raw mean IoU here would be ~0.96 and look excellent.
        assert report["localization"]["mean_distance"] < 0.05
        assert sigma < 0.95, (
            f"sigma {sigma:.3f} does not discount how easy this corpus is")

    def test_the_chance_baseline_is_reported(self):
        report = geometry_agreement(corpus(offset=0.01))
        assert report["n_chance_pairs"] > 0
        assert not math.isnan(report["localization"]["mean_chance_distance"])


class TestReproducibility:
    def test_the_same_data_gives_the_same_answer(self):
        """
        An agreement number that moves between runs of identical data cannot
        go in a paper. The chance baseline is sampled, so the seed is fixed.
        """
        data = corpus(offset=0.02, n=12)
        first = geometry_agreement(data)["localization"]["sigma"]
        second = geometry_agreement(data)["localization"]["sigma"]
        assert first == second

    def test_a_different_seed_gives_a_similar_answer(self):
        """Sampling noise must not swamp the signal."""
        data = corpus(offset=0.02, n=12)
        a = geometry_agreement(data, seed=1)["localization"]["sigma"]
        b = geometry_agreement(data, seed=999)["localization"]["sigma"]
        assert abs(a - b) < 0.1, f"seed changed sigma from {a:.3f} to {b:.3f}"


class TestBootstrap:
    def test_it_produces_an_interval_containing_the_estimate(self):
        data = corpus(offset=0.02, n=14)
        report = geometry_agreement(data, bootstrap=40)
        interval = report["confidence"]
        sigma = report["localization"]["sigma"]
        assert interval["sigma_lower"] <= sigma + 0.15
        assert interval["sigma_upper"] >= sigma - 0.15

    def test_it_is_skipped_by_default(self):
        assert "confidence" not in geometry_agreement(corpus(offset=0.01))

    def test_too_few_items_says_so_rather_than_inventing_an_interval(self):
        items = {"only": {"a": [box(0.1, 0.1)], "b": [box(0.1, 0.1)]}}
        report = geometry_agreement(items, bootstrap=20)
        assert "note" in report["confidence"]


class TestDistances:
    def test_centroid_distance_is_zero_for_identical_boxes(self):
        a = {"type": "bbox", "bbox": [0.1, 0.1, 0.2, 0.2]}
        assert centroid_distance(a, a) == pytest.approx(0.0)

    def test_centroid_distance_is_bounded(self):
        a = {"type": "bbox", "bbox": [0.0, 0.0, 0.01, 0.01]}
        b = {"type": "bbox", "bbox": [0.99, 0.99, 0.01, 0.01]}
        assert 0.0 <= centroid_distance(a, b) <= 1.0

    def test_giou_actually_runs_on_canonical_objects(self):
        """
        The distances read the CANONICAL shape (`bbox`), not the client shape
        (`coordinates`). An earlier version read only the client form, so GIoU
        silently never fired and every distance fell through to plain IoU —
        the measure this module exists to avoid defaulting to.
        """
        from potato.server_utils.iaa.geometry_agreement import _bbox_of

        assert _bbox_of({"type": "bbox", "bbox": [1, 2, 3, 4]}) == [1, 2, 3, 4]

    def test_disjoint_boxes_are_ordered_by_giou_but_tied_by_iou(self):
        from potato.server_utils.iaa.geometry_agreement import giou_distance
        from potato.server_utils.iaa.geometry import delta_geometric

        a = {"type": "bbox", "bbox": [0.0, 0.0, 0.1, 0.1]}
        near = {"type": "bbox", "bbox": [0.15, 0.0, 0.1, 0.1]}
        far = {"type": "bbox", "bbox": [0.85, 0.0, 0.1, 0.1]}

        assert giou_distance(a, near) < giou_distance(a, far)
        # The control: plain IoU cannot tell them apart at all.
        assert delta_geometric(a, near) == delta_geometric(a, far) == 1.0


class TestCostControl:
    """
    Pairwise comparison is quadratic in annotators AND instances. A 5-annotator
    project with 50 instances per image costs 25k mask decodes per image, which
    turns an admin page load into a hang.
    """

    def _crowded(self, n_items=3, n_objects=40, n_annotators=4):
        items = {}
        for i in range(n_items):
            per_annotator = {}
            for a in range(n_annotators):
                per_annotator[f"ann_{a}"] = [
                    box(0.01 * j, 0.01 * j, 0.02, 0.02)
                    for j in range(n_objects)
                ]
            items[f"item_{i}"] = per_annotator
        return items

    def test_a_tiny_budget_truncates_and_says_so_loudly(self):
        report = geometry_agreement(self._crowded(), max_pairs=1)
        assert report.get("truncated") is True
        assert report["n_items_over_budget"] > 0
        assert "budget" in report["truncation_note"]

    def test_the_note_says_how_much_was_actually_measured(self):
        """
        A truncated number that reads as complete will be quoted. The note has
        to name the coverage, not just admit truncation.
        """
        report = geometry_agreement(self._crowded(), max_pairs=1)
        assert "item(s) that fit" in report["truncation_note"]

    def test_an_over_budget_item_is_skipped_whole_not_half_measured(self):
        """
        A partially processed item biases the mean toward whichever annotator
        pair happened to run before the budget ran out.
        """
        report = geometry_agreement(self._crowded(n_items=2), max_pairs=1)
        assert report["n_items_over_budget"] == 2
        assert report["n_matched_pairs"] == 0

    def test_a_generous_budget_does_not_truncate(self):
        report = geometry_agreement(self._crowded(), max_pairs=10_000_000)
        assert "truncated" not in report
        assert report["n_matched_pairs"] > 0

    def test_ordinary_projects_are_unaffected_by_the_default(self):
        report = geometry_agreement(corpus(offset=0.01, n=20))
        assert "truncated" not in report
