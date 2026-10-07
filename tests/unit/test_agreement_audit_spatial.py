"""
Spatial and temporal agreement, on the inputs the earlier tests never used:
sub-threshold pairs that outscore a valid match, self-intersecting polygons,
asymmetric sizes, competing partial overlaps, tied detector scores, one region
near two, and a misplaced span among correct ones.

Expected values come from hand computation, scipy's assignment, shapely's
make_valid and pygamma-agreement's best alignment, not from the code under
test.
"""

from __future__ import annotations

import math

import pytest

from potato.server_utils.iaa import captions, geometry, grounding, rollouts, span
from potato.server_utils.iaa.detection_ap import mean_average_precision
from potato.server_utils.iaa.geometry_agreement import (
    canonical_object, geometry_agreement,
)


def _bbox(x, y, w, h):
    return {"type": "bbox", "bbox": [x, y, w, h]}


class TestThresholdInsideTheAssignment:
    def test_a_valid_match_is_not_traded_for_two_invalid_ones(self):
        # Similarities [[.55, .40], [.438, .083]] at threshold 0.5: the raw
        # optimum is .40 + .438, both below threshold, which kept nothing.
        a = [_bbox(7, 0, 15, 10), _bbox(8, 0, 7, 10)]
        b = [_bbox(2, 0, 16, 10), _bbox(14, 0, 6, 10)]
        matches, _, _ = geometry.match_instances(a, b, threshold=0.5)
        assert [(i, j) for i, j, _ in matches] == [(0, 0)]

    def test_rollout_marks_keep_every_pair_inside_the_window(self):
        mark = lambda t: {"t": t}
        matches, _, _ = rollouts.match_breakpoints(
            [mark(0), mark(0.47)], [mark(0.45), mark(0.9)], 0.5)
        assert len(matches) == 2


class TestPolygonRepair:
    BOWTIE = [(0, 0), (2, 2), (2, 0), (0, 2)]

    def test_both_lobes_of_a_figure_eight_count(self):
        pytest.importorskip("shapely")
        left = geometry.iou_polygon(self.BOWTIE, [(0, 0), (1, 1), (0, 2)])
        right = geometry.iou_polygon(self.BOWTIE, [(2, 0), (1, 1), (2, 2)])
        assert left == pytest.approx(0.5)
        assert right == pytest.approx(0.5)


class TestSizeScaledSimilarityIsSymmetric:
    A = {"type": "keypoint_set", "points": [[20, 20], [30, 30]],
         "bbox": [10, 10, 40, 40]}
    B = {"type": "keypoint_set", "points": [[22, 21], [33, 31]],
         "bbox": [12, 10, 68, 70]}

    def test_keypoints(self):
        assert geometry.similarity(self.A, self.B) == pytest.approx(
            geometry.similarity(self.B, self.A))

    def test_landmarks(self):
        a = {"type": "landmark", "points": [[10, 10]], "bbox": [0, 0, 20, 20]}
        b = {"type": "landmark", "points": [[14, 10]], "bbox": [0, 0, 60, 80]}
        assert geometry.similarity(a, b) == pytest.approx(geometry.similarity(b, a))

    def test_ground_truth_reference_uses_the_truth_size(self):
        """COCO scales OKS by the ground truth's area."""
        reversed_truth = dict(self.A, bbox=self.B["bbox"])
        assert geometry.similarity(self.A, self.B, reference="b") == pytest.approx(
            geometry.similarity(reversed_truth, self.B, reference="b"))


class TestOptimalOneToOne:
    def test_grounding_set_similarity_does_not_depend_on_who_is_first(self):
        box = lambda x, w: {"type": "bbox", "coordinates": {
            "x": x, "y": 0, "width": w, "height": 0.5}}
        a = [box(0.12, 0.49), box(0.40, 0.28)]
        b = [box(0.04, 0.23), box(0.25, 0.47)]
        assert grounding.set_similarity(a, b) == pytest.approx(
            grounding.set_similarity(b, a))

    def test_partial_span_f1_finds_the_maximum_matching(self):
        _, _, f1 = span.span_f1_partial([(0, 10, "X"), (0, 4, "X")],
                                        [(0, 4, "X"), (5, 10, "X")])
        assert f1 == 1.0


class TestTiedDetectorScores:
    def test_ap_does_not_depend_on_dict_order(self):
        truth = {"i1": [{"type": "bbox", "label": "c", "bbox": [0, 0, 10, 10]}],
                 "i2": [{"type": "bbox", "label": "c", "bbox": [0, 0, 10, 10]}]}
        hit = {"type": "bbox", "label": "c", "bbox": [0, 0, 10, 10]}
        miss = {"type": "bbox", "label": "c", "bbox": [50, 50, 10, 10]}
        forward = {"i1": [hit], "i2": [miss]}
        backward = {"i2": [miss], "i1": [hit]}
        assert mean_average_precision(forward, truth)["mAP_50"] == pytest.approx(
            mean_average_precision(backward, truth)["mAP_50"])


class TestRegionCaptionsMatchOneToOne:
    def test_one_region_cannot_caption_two_units(self):
        box = lambda x: {"type": "bbox", "label": "r", "coordinates": {
            "x": x, "y": 0.2, "width": 0.3, "height": 0.3}}
        items = {"img": {
            "a": [{"region": box(0.10), "caption": "red car"},
                  {"region": box(0.15), "caption": "blue truck"}],
            "b": [{"region": box(0.12), "caption": "red car"},
                  {"region": box(0.60), "caption": "a tree"}],
        }}
        rows, matching = captions.region_caption_rows(items)
        assert sum(1 for who, _, _ in rows if who == "b") == 1
        assert matching["n_unmatched_regions"] == 2


class TestBootstrapHonoursTheBudget:
    def test_items_the_point_estimate_drops_are_not_bootstrapped(self):
        items = {f"i{n}": {u: [{"type": "bbox", "label": "c", "coordinates": {
            "x": 0.1 * n, "y": 0.1, "width": 0.2, "height": 0.2}}]
            for u in ("a", "b", "c")} for n in range(6)}
        report = geometry_agreement(items, max_pairs=1, bootstrap=20)
        assert report.get("truncated")
        assert "sigma_lower" not in report["confidence"]


class TestShapesThatHadNoGeometry:
    @pytest.mark.parametrize("obj", [
        {"type": "keypoint_set", "label": "p", "coordinates": [
            {"x": .1, "y": .1, "v": 2}, {"x": .3, "y": .4, "v": 2},
            {"x": .5, "y": .2, "v": 2}]},
        {"type": "cuboid_2d", "label": "c", "coordinates": {
            "front": [{"x": .1, "y": .1}, {"x": .3, "y": .1},
                      {"x": .3, "y": .3}, {"x": .1, "y": .3}],
            "back": [{"x": .15, "y": .15}, {"x": .35, "y": .15},
                     {"x": .35, "y": .35}, {"x": .15, "y": .35}]}},
        {"type": "freeform", "label": "f", "coordinates": [
            {"x": .1, "y": .1}, {"x": .2, "y": .15}, {"x": .3, "y": .3}]},
    ], ids=["keypoint_set", "cuboid_2d", "freeform"])
    def test_an_identical_copy_scores_one(self, obj):
        canonical = canonical_object(obj)
        assert geometry.similarity(canonical, canonical) == pytest.approx(1.0)
        report = mean_average_precision({"i": [dict(obj, score=0.9)]}, {"i": [obj]})
        assert report["mAP_50"] == pytest.approx(1.0)


class TestGammaFollowsMathet:
    def test_best_alignment_matches_pygamma(self):
        """pygamma-agreement's best-alignment disorder for both examples."""
        a = [(0, 10, "X"), (20, 30, "X"), (40, 50, "Y")]
        b = [(0, 10, "X"), (20, 30, "X"), (900, 910, "Y")]
        assert span._pairwise_disorder(a, b, 1, 1, 1) == pytest.approx(2 / 3)
        a = [(0, 10, "X"), (20, 30, "Y")]
        b = [(2, 10, "X"), (20, 35, "Y")]
        assert span._pairwise_disorder(a, b, 1, 1, 1) == pytest.approx(0.0261728, abs=1e-6)

    def test_one_misplaced_span_is_not_chance(self):
        a = [(0, 10, "X"), (20, 30, "X"), (40, 50, "Y")]
        b = [(0, 10, "X"), (20, 30, "X"), (900, 910, "Y")]
        assert span.gamma({"u1": a, "u2": b}, length=1000) > 0.4

    def test_nothing_marked_is_undefined(self):
        assert math.isnan(span.gamma({"u1": [], "u2": []}, length=10))
