"""
Scoring grounding and pointing.

Two things in here are load-bearing beyond the arithmetic:

- `region_similarity` must normalize before comparing. Passing raw client
  objects to `iaa.geometry.similarity` returns **0.0 for every pair** — a
  confident report of total disagreement — because it reads a `bbox` key the
  client shape does not have. That is the failure the coordinate contract at
  `cv_utils.py:729` exists to prevent, and it was reproduced here during
  development.
- An unanswered expression must be excluded, not scored. Counting it as a miss
  makes a model look worse the more expressions an annotator skipped.
"""

import math

import pytest

from potato.grounding import metrics as M


def box(x, y, w, h, label="referent"):
    return {"type": "bbox", "label": label, "color": "#f00",
            "coordinates": {"x": x, "y": y, "width": w, "height": h}}


def polygon(points, label="referent"):
    return {"type": "polygon", "label": label, "color": "#f00",
            "coordinates": [{"x": px, "y": py} for px, py in points]}


def point(x, y):
    return {"x": x, "y": y}


class TestRegionSimilarity:
    def test_identical_boxes_score_one(self):
        assert M.region_similarity(box(0.2, 0.2, 0.4, 0.4),
                                   box(0.2, 0.2, 0.4, 0.4)) == pytest.approx(1.0)

    def test_disjoint_boxes_score_zero(self):
        assert M.region_similarity(box(0.0, 0.0, 0.2, 0.2),
                                   box(0.7, 0.7, 0.2, 0.2)) == 0.0

    def test_overlapping_boxes_score_between(self):
        value = M.region_similarity(box(0.2, 0.2, 0.4, 0.4),
                                    box(0.25, 0.25, 0.4, 0.4))
        assert 0.4 < value < 0.9

    def test_the_client_shape_is_normalized_before_comparing(self):
        """
        The regression this module was written around. Without normalization
        `similarity` reads a `bbox` key the client never writes and returns
        0.0 for everything, which reads as total disagreement rather than as a
        broken comparison.
        """
        from potato.server_utils.iaa import geometry

        raw = box(0.2, 0.2, 0.4, 0.4)
        assert geometry.similarity(raw, raw) == 0.0    # the trap
        assert M.region_similarity(raw, raw) == pytest.approx(1.0)  # the fix

    def test_polygons_work_too(self):
        shape = polygon([(0.2, 0.2), (0.6, 0.2), (0.6, 0.6), (0.2, 0.6)])
        assert M.region_similarity(shape, shape) == pytest.approx(1.0)

    def test_different_types_never_match(self):
        """A mask and a box may cover the same pixels; conflating them would
        hide a real disagreement about how the object should be represented."""
        assert M.region_similarity(box(0.2, 0.2, 0.4, 0.4),
                                   polygon([(0.2, 0.2), (0.6, 0.2),
                                            (0.6, 0.6)])) == 0.0

    def test_junk_is_zero_not_an_exception(self):
        assert M.region_similarity(None, box(0, 0, 1, 1)) == 0.0
        assert M.region_similarity({}, {}) == 0.0


class TestRegionCenter:
    def test_box_center(self):
        assert M.region_center(box(0.2, 0.2, 0.4, 0.4)) == {"x": pytest.approx(0.4),
                                                            "y": pytest.approx(0.4)}

    def test_landmark_is_its_own_center(self):
        landmark = {"type": "landmark", "coordinates": {"x": 0.3, "y": 0.7}}
        assert M.region_center(landmark) == {"x": 0.3, "y": 0.7}

    def test_polygon_centroid(self):
        centre = M.region_center(
            polygon([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]))
        assert centre["x"] == pytest.approx(0.5)
        assert centre["y"] == pytest.approx(0.5)

    def test_unknown_shapes_return_none(self):
        assert M.region_center({"type": "nonsense"}) is None
        assert M.region_center(None) is None


class TestPointInRegion:
    def test_inside_and_outside_a_box(self):
        target = box(0.2, 0.2, 0.4, 0.4)
        assert M.point_in_region(point(0.4, 0.4), target)
        assert not M.point_in_region(point(0.9, 0.9), target)

    def test_the_boundary_counts_as_inside(self):
        assert M.point_in_region(point(0.2, 0.2), box(0.2, 0.2, 0.4, 0.4))

    def test_inside_and_outside_a_polygon(self):
        shape = polygon([(0.1, 0.1), (0.5, 0.1), (0.5, 0.5), (0.1, 0.5)])
        assert M.point_in_region(point(0.3, 0.3), shape)
        assert not M.point_in_region(point(0.8, 0.3), shape)

    def test_an_ellipse_is_an_ellipse_not_its_box(self):
        ellipse = {"type": "ellipse",
                   "coordinates": {"cx": 0.5, "cy": 0.5, "rx": 0.3, "ry": 0.1}}
        assert M.point_in_region(point(0.5, 0.55), ellipse)
        # A corner of the bounding box, well outside the ellipse itself.
        assert not M.point_in_region(point(0.78, 0.58), ellipse)

    def test_a_point_target_has_no_interior(self):
        """
        Two points a pixel apart are not "outside" each other — that is a
        distance question, and answering it with False would report a miss for
        a model pointing almost exactly right.
        """
        landmark = {"type": "landmark", "coordinates": {"x": 0.5, "y": 0.5}}
        assert not M.point_in_region(point(0.5, 0.5), landmark)

    def test_junk_is_false_not_an_exception(self):
        assert not M.point_in_region({}, box(0, 0, 1, 1))
        assert not M.point_in_region(point(0.5, 0.5), None)


class TestGroundingAccuracy:
    def test_thresholds_are_reported_separately(self):
        """One number cannot distinguish nearly-right from nowhere-near."""
        result = M.grounding_accuracy([
            {"truth": box(0.2, 0.2, 0.4, 0.4),
             "prediction": box(0.22, 0.22, 0.4, 0.4)},   # tight
            {"truth": box(0.2, 0.2, 0.4, 0.4),
             "prediction": box(0.4, 0.4, 0.4, 0.4)},     # loose
        ])
        assert result["acc@0.25"] > result["acc@0.9"]

    def test_an_unanswered_expression_is_excluded_not_scored(self):
        """
        Counting it as a miss makes a model look worse the more expressions the
        annotator skipped, which is a statement about the annotator.
        """
        result = M.grounding_accuracy([
            {"truth": box(0.2, 0.2, 0.4, 0.4),
             "prediction": box(0.2, 0.2, 0.4, 0.4)},
            {"truth": None, "prediction": box(0.1, 0.1, 0.2, 0.2)},
        ])
        assert result["n_scored"] == 1
        assert result["n_unanswered_excluded"] == 1
        assert result["acc@0.5"] == 1.0

    def test_declining_a_referent_that_is_not_there_is_correct(self):
        result = M.grounding_accuracy([
            {"truth": None, "truth_absent": True,
             "prediction": None, "prediction_absent": True},
        ])
        assert result["absent"]["correctly_declined"] == 1
        assert result["absent"]["hallucinated_a_location"] == 0

    def test_pointing_at_something_that_is_not_there_is_a_hallucination(self):
        result = M.grounding_accuracy([
            {"truth": None, "truth_absent": True,
             "prediction": box(0.2, 0.2, 0.3, 0.3)},
        ])
        assert result["absent"]["hallucinated_a_location"] == 1

    def test_declining_a_referent_that_is_there_scores_zero(self):
        result = M.grounding_accuracy([
            {"truth": box(0.2, 0.2, 0.4, 0.4),
             "prediction": None, "prediction_absent": True},
        ])
        assert result["absent"]["missed_a_present_referent"] == 1
        assert result["acc@0.25"] == 0.0

    def test_an_empty_report_is_nan_not_zero(self):
        """Zero accuracy is a finding; no data is not."""
        result = M.grounding_accuracy([])
        assert math.isnan(result["mean_iou"])
        assert math.isnan(result["acc@0.5"])


class TestPointingAccuracy:
    def test_hits_and_misses(self):
        target = box(0.2, 0.2, 0.4, 0.4)
        result = M.pointing_accuracy([
            {"truth": target, "point": point(0.4, 0.4)},
            {"truth": target, "point": point(0.9, 0.9)},
        ])
        assert result["point_in_region"] == 0.5
        assert result["n_hits"] == 1

    def test_the_miss_distance_is_over_misses_only(self):
        """
        Averaged over hits as well it would mostly measure how large the
        objects are, not how badly the model missed.
        """
        target = box(0.2, 0.2, 0.4, 0.4)
        result = M.pointing_accuracy([
            {"truth": target, "point": point(0.4, 0.4)},     # a hit
            {"truth": target, "point": point(0.9, 0.4)},     # a miss
        ])
        assert result["mean_miss_distance"] == pytest.approx(0.5, abs=0.01)

    def test_a_perfect_model_has_no_miss_distance(self):
        result = M.pointing_accuracy([
            {"truth": box(0.2, 0.2, 0.4, 0.4), "point": point(0.4, 0.4)},
        ])
        assert result["point_in_region"] == 1.0
        assert math.isnan(result["mean_miss_distance"])

    def test_unanswered_is_excluded_here_too(self):
        result = M.pointing_accuracy([
            {"truth": box(0.2, 0.2, 0.4, 0.4), "point": point(0.4, 0.4)},
            {"truth": None, "point": point(0.1, 0.1)},
        ])
        assert result["n_scored"] == 1
        assert result["n_unanswered_excluded"] == 1

    def test_a_point_is_scored_against_a_mask_exactly(self):
        from potato.export.cv_utils import polygons_to_rle

        rle = polygons_to_rle([[[2, 2], [8, 2], [8, 8], [2, 8]]], 10, 10)
        mask = {"type": "mask", "label": "a", "rle": rle}
        assert M.point_in_region(point(0.5, 0.5), mask)
        assert not M.point_in_region(point(0.05, 0.05), mask)


class TestTheTwoMeasuresAreNotInterchangeable:
    def test_iou_against_a_point_is_always_zero(self):
        """
        Which is why pointing is scored as a hit rate. Scoring points the way
        boxes are scored reports total failure for a model pointing perfectly.
        """
        landmark = {"type": "landmark", "coordinates": {"x": 0.4, "y": 0.4}}
        assert M.region_similarity(box(0.2, 0.2, 0.4, 0.4), landmark) == 0.0

        result = M.pointing_accuracy([
            {"truth": box(0.2, 0.2, 0.4, 0.4), "point": point(0.4, 0.4)}])
        assert result["point_in_region"] == 1.0
