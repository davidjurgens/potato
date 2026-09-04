"""Average precision for detection.

Scored against a hand-computed fixture, because an AP implementation that is
subtly wrong still returns a plausible number between 0 and 1 and no amount of
staring at it reveals the error. Where `pycocotools` is installed, the same
fixture is checked against the reference implementation.
"""

import pytest

from potato.server_utils.iaa.detection_ap import (COCO_THRESHOLDS,
                                                  average_precision,
                                                  detection_pr_curve,
                                                  mean_average_precision)


def box(x, y, w, h, label="cat", confidence=None):
    obj = {"type": "bbox", "label": label,
           "coordinates": {"x": x, "y": y, "width": w, "height": h}}
    if confidence is not None:
        obj["confidence"] = confidence
    return obj


class TestPerfectAndEmpty:
    def test_a_perfect_detector_scores_one(self):
        truth = {"i1": [box(0.1, 0.1, 0.2, 0.2)],
                 "i2": [box(0.5, 0.5, 0.2, 0.2)]}
        predictions = {"i1": [box(0.1, 0.1, 0.2, 0.2, confidence=0.9)],
                       "i2": [box(0.5, 0.5, 0.2, 0.2, confidence=0.8)]}
        result = mean_average_precision(predictions, truth)
        assert result["mAP_50"] == pytest.approx(1.0)
        assert result["mAP_50_95"] == pytest.approx(1.0)

    def test_a_detector_that_predicts_nothing_scores_zero(self):
        truth = {"i1": [box(0.1, 0.1, 0.2, 0.2)]}
        result = mean_average_precision({}, truth)
        assert result["mAP_50"] == pytest.approx(0.0)
        assert result["n_predictions"] == 0

    def test_no_ground_truth_is_none_not_zero(self):
        """Nothing to score is a different fact from scoring badly."""
        result = mean_average_precision(
            {"i1": [box(0, 0, 0.1, 0.1, confidence=0.9)]}, {})
        assert result["mAP_50"] is None
        assert "Nothing to score" in result["note"]

    def test_a_wrong_box_scores_zero(self):
        truth = {"i1": [box(0.0, 0.0, 0.1, 0.1)]}
        predictions = {"i1": [box(0.8, 0.8, 0.1, 0.1, confidence=0.9)]}
        assert mean_average_precision(predictions, truth)["mAP_50"] == \
            pytest.approx(0.0)


class TestTheThingIoUAloneCannotSee:
    def test_missed_objects_lower_the_score(self):
        """
        Mean IoU over matched pairs would report 1.0 here. AP reports 0.2,
        because forty of the forty-one objects were never found.
        """
        truth = {"i%d" % i: [box(0.1, 0.1, 0.2, 0.2)] for i in range(5)}
        predictions = {"i0": [box(0.1, 0.1, 0.2, 0.2, confidence=0.99)]}

        result = mean_average_precision(predictions, truth)
        assert result["mAP_50"] == pytest.approx(0.2, abs=0.02)

    def test_duplicate_predictions_are_false_positives(self):
        """Predicting the same box repeatedly must not raise the score."""
        truth = {"i1": [box(0.1, 0.1, 0.2, 0.2)]}
        once = mean_average_precision(
            {"i1": [box(0.1, 0.1, 0.2, 0.2, confidence=0.9)]}, truth)
        many = mean_average_precision(
            {"i1": [box(0.1, 0.1, 0.2, 0.2, confidence=0.9 - 0.05 * i)
                    for i in range(5)]}, truth)
        assert once["mAP_50"] == pytest.approx(1.0)
        assert many["mAP_50"] <= once["mAP_50"]

    def test_a_class_never_predicted_still_counts(self):
        """
        Scoring only the classes a model predicted lets it win by refusing the
        hard ones.
        """
        truth = {"i1": [box(0.1, 0.1, 0.2, 0.2, label="cat"),
                        box(0.5, 0.5, 0.2, 0.2, label="dog")]}
        predictions = {"i1": [box(0.1, 0.1, 0.2, 0.2, label="cat",
                                  confidence=0.9)]}
        result = mean_average_precision(predictions, truth)
        assert "dog" in result["per_class"]
        assert result["mAP_50"] == pytest.approx(0.5, abs=0.02)


class TestConfidenceOrdering:
    def test_ranking_matters(self):
        """
        The same two predictions, one right and one wrong, score higher when
        the right one is the confident one. That ordering is the whole reason
        AP is a curve.
        """
        truth = {"i1": [box(0.1, 0.1, 0.2, 0.2)],
                 "i2": [box(0.1, 0.1, 0.2, 0.2)]}
        good_first = {"i1": [box(0.1, 0.1, 0.2, 0.2, confidence=0.9)],
                      "i2": [box(0.8, 0.8, 0.1, 0.1, confidence=0.2)]}
        bad_first = {"i1": [box(0.1, 0.1, 0.2, 0.2, confidence=0.2)],
                     "i2": [box(0.8, 0.8, 0.1, 0.1, confidence=0.9)]}

        assert (mean_average_precision(good_first, truth)["mAP_50"] >
                mean_average_precision(bad_first, truth)["mAP_50"])

    def test_predictions_without_confidence_rank_last_but_still_count(self):
        truth = {"i1": [box(0.1, 0.1, 0.2, 0.2)]}
        result = mean_average_precision(
            {"i1": [box(0.1, 0.1, 0.2, 0.2)]}, truth)
        assert result["n_predictions"] == 1
        assert result["mAP_50"] == pytest.approx(1.0)


class TestThresholdSweep:
    def test_a_loose_box_passes_at_50_and_fails_at_95(self):
        truth = {"i1": [box(0.0, 0.0, 0.2, 0.2)]}
        # Shifted by a tenth of its width: IoU is around 0.68.
        predictions = {"i1": [box(0.04, 0.0, 0.2, 0.2, confidence=0.9)]}

        at_50 = average_precision(
            [("i1", predictions["i1"][0])], truth, threshold=0.5)
        at_95 = average_precision(
            [("i1", predictions["i1"][0])], truth, threshold=0.95)

        assert at_50 == pytest.approx(1.0)
        assert at_95 == pytest.approx(0.0)

    def test_the_coco_sweep_is_ten_thresholds(self):
        assert len(COCO_THRESHOLDS) == 10
        assert COCO_THRESHOLDS[0] == 0.5
        assert COCO_THRESHOLDS[-1] == 0.95

    def test_map_50_95_sits_between_the_extremes(self):
        truth = {"i%d" % i: [box(0.1, 0.1, 0.2, 0.2)] for i in range(4)}
        predictions = {"i%d" % i: [box(0.11, 0.11, 0.2, 0.2, confidence=0.9)]
                       for i in range(4)}
        result = mean_average_precision(predictions, truth)
        assert result["mAP_50_95"] <= result["mAP_50"]


class TestPRCurve:
    def test_recall_is_monotonic(self):
        truth = {"i%d" % i: [box(0.1, 0.1, 0.2, 0.2)] for i in range(4)}
        predictions = [("i%d" % i, box(0.1, 0.1, 0.2, 0.2, confidence=0.9 - i * 0.1))
                       for i in range(4)]
        _precisions, recalls = detection_pr_curve(predictions, truth)
        assert recalls == sorted(recalls)
        assert recalls[-1] == pytest.approx(1.0)

    def test_an_empty_truth_gives_an_empty_curve(self):
        assert detection_pr_curve([], {}) == ([], [])


class TestAgainstPycocotools:
    """Cross-check against the reference implementation, where available."""

    def test_matches_pycocotools_on_a_small_set(self):
        pytest.importorskip("pycocotools")
        import numpy as np
        from pycocotools.cocoeval import COCOeval
        from pycocotools.coco import COCO

        # Three images, one class, boxes in absolute pixels for COCO.
        W = H = 100
        gt_boxes = {1: [(10, 10, 20, 20)], 2: [(50, 50, 30, 30)],
                    3: [(10, 60, 20, 20)]}
        pred_boxes = {1: [(10, 10, 20, 20, 0.9)],
                      2: [(52, 52, 30, 30, 0.8)],
                      3: [(70, 10, 20, 20, 0.7)]}   # a miss

        gt = {"images": [{"id": i, "width": W, "height": H} for i in gt_boxes],
              "annotations": [], "categories": [{"id": 1, "name": "cat"}]}
        ann_id = 1
        for image_id, boxes in gt_boxes.items():
            for x, y, w, h in boxes:
                gt["annotations"].append({
                    "id": ann_id, "image_id": image_id, "category_id": 1,
                    "bbox": [x, y, w, h], "area": w * h, "iscrowd": 0})
                ann_id += 1

        detections = []
        for image_id, boxes in pred_boxes.items():
            for x, y, w, h, score in boxes:
                detections.append({"image_id": image_id, "category_id": 1,
                                   "bbox": [x, y, w, h], "score": score})

        coco_gt = COCO()
        coco_gt.dataset = gt
        coco_gt.createIndex()
        coco_dt = coco_gt.loadRes(detections)

        evaluator = COCOeval(coco_gt, coco_dt, "bbox")
        evaluator.evaluate()
        evaluator.accumulate()
        evaluator.summarize()
        reference_50 = float(evaluator.stats[1])   # AP @ IoU=0.50

        # The same data through ours, normalised to [0, 1].
        ours_truth = {
            str(i): [box(x / W, y / H, w / W, h / H)
                     for x, y, w, h in boxes]
            for i, boxes in gt_boxes.items()}
        ours_pred = {
            str(i): [box(x / W, y / H, w / W, h / H, confidence=s)
                     for x, y, w, h, s in boxes]
            for i, boxes in pred_boxes.items()}

        ours = mean_average_precision(ours_pred, ours_truth,
                                      thresholds=(0.5,))["mAP_50"]

        assert ours == pytest.approx(reference_50, abs=0.02), (
            "ours=%.4f pycocotools=%.4f" % (ours, reference_50))
