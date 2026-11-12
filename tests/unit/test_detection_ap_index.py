"""The spatial index in detection AP gives the full scan's answer.

Scoring a whole slide (thousands of objects a side) compared every
prediction with every annotated object at every COCO threshold, and took
longer than training. The index skips only pairs whose IoU is exactly 0, so
every AP must equal the brute-force one.
"""

import random
import time

import pytest

from potato.server_utils.iaa import detection_ap
from potato.server_utils.iaa.detection_ap import (_interpolated_ap, _iou,
                                                  mean_average_precision)


def _brute_force_ap(predictions, truth, threshold):
    """The matching as it was before the index: every candidate, in order."""
    n_truth = sum(len(v) for v in truth.values())
    ranked = sorted(predictions, key=lambda p: (-detection_ap._confidence_of(p[1]), str(p[0])))
    claimed = {iid: set() for iid in truth}
    tp = fp = 0
    precisions, recalls = [], []
    for iid, prediction in ranked:
        best_index, best = -1, 0.0
        for index, candidate in enumerate(truth.get(iid, [])):
            if index in claimed.get(iid, ()):
                continue
            score = _iou(prediction, candidate)
            if score > best:
                best_index, best = index, score
        if best_index >= 0 and best >= threshold:
            claimed.setdefault(iid, set()).add(best_index)
            tp += 1
        else:
            fp += 1
        precisions.append(tp / (tp + fp))
        recalls.append(tp / n_truth)
    return _interpolated_ap(precisions, recalls)


def _shape(rng, kind, label):
    x, y = rng.random() * 0.9, rng.random() * 0.9
    w, h = 0.01 + rng.random() * 0.08, 0.01 + rng.random() * 0.08
    if kind == "bbox":
        return {"type": "bbox", "label": label,
                "coordinates": {"x": x, "y": y, "width": w, "height": h}}
    if kind == "polygon":
        return {"type": "polygon", "label": label, "coordinates": [
            {"x": x, "y": y}, {"x": x + w, "y": y}, {"x": x + w / 2, "y": y + h}]}
    return {"type": "landmark", "label": label, "coordinates": {"x": x, "y": y}}


def _jitter(rng, obj):
    out = dict(obj, confidence=round(rng.random(), 3))
    c = obj["coordinates"]
    d = lambda: (rng.random() - 0.5) * 0.02
    if isinstance(c, list):
        out["coordinates"] = [{"x": p["x"] + d(), "y": p["y"] + d()} for p in c]
    else:
        out["coordinates"] = dict(c, x=c["x"] + d(), y=c["y"] + d())
    return out


@pytest.mark.parametrize("seed", range(4))
def test_indexed_matching_equals_the_full_scan(seed):
    rng = random.Random(seed)
    truth, predicted = {}, {}
    for image in range(3):
        objects = [_shape(rng, rng.choice(["bbox", "polygon", "landmark"]),
                          rng.choice(["a", "b"])) for _ in range(60)]
        truth["i%d" % image] = objects
        predicted["i%d" % image] = (
            [_jitter(rng, o) for o in objects if rng.random() < 0.8]
            + [dict(_shape(rng, "bbox", "a"), confidence=rng.random()) for _ in range(15)])
    fast = mean_average_precision(predicted, truth)
    for label in ("a", "b"):
        preds = [(i, o) for i, objs in predicted.items() for o in objs if o["label"] == label]
        gold = {i: [o for o in objs if o["label"] == label] for i, objs in truth.items()}
        for threshold, value in fast["per_class"][label].items():
            assert value == pytest.approx(
                round(_brute_force_ap(preds, gold, float(threshold)), 4), abs=1e-4)


def test_a_slide_scale_image_scores_in_seconds():
    rng = random.Random(9)
    objects = [_shape(rng, "bbox", "nucleus") for _ in range(3000)]
    for n, obj in enumerate(objects):
        # Small, spread out, like nuclei.
        obj["coordinates"] = {"x": (n % 60) / 60, "y": (n // 60) / 50,
                              "width": 0.005, "height": 0.006}
    predictions = [dict(o, confidence=rng.random()) for o in objects]
    start = time.time()
    result = mean_average_precision({"slide": predictions}, {"slide": objects})
    assert time.time() - start < 30
    assert result["mAP_50"] == pytest.approx(1.0)


def test_zero_area_boxes_beside_a_large_one_do_not_hang():
    """The grid cell was twice the median extent, 0 for zero-area boxes and
    floored at 1e-9, so one large box was put in about 1e11 cells (audit 102)."""
    flat = [{"type": "bbox", "label": "a",
             "coordinates": {"x": n / 50, "y": 0.5, "width": 0.0, "height": 0.0}}
            for n in range(40)]
    big = {"type": "bbox", "label": "a",
           "coordinates": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}}
    truth = {"i": flat + [big]}
    start = time.time()
    result = mean_average_precision({"i": [dict(big, confidence=0.9)]}, truth)
    assert time.time() - start < 5
    assert result["n_truth"] == 41


@pytest.mark.parametrize("seed", range(10))
def test_degenerate_shapes_still_match_the_full_scan(seed):
    rng = random.Random(100 + seed)
    truth, predicted = {}, {}
    for image in range(2):
        objects = []
        for _ in range(30):
            obj = _shape(rng, rng.choice(["bbox", "polygon"]), "a")
            if rng.random() < 0.4 and obj["type"] == "bbox":
                obj["coordinates"]["width"] = 0.0
            objects.append(obj)
        truth["i%d" % image] = objects
        predicted["i%d" % image] = [_jitter(rng, o) for o in objects]
    fast = mean_average_precision(predicted, truth)
    preds = [(i, o) for i, objs in predicted.items() for o in objs]
    for threshold, value in fast["per_class"]["a"].items():
        assert value == pytest.approx(round(_brute_force_ap(preds, truth, float(threshold)), 4),
                                      abs=1e-4)
