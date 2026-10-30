"""Scoring a run's predictions against the held-out labels.

Every trainer already predicts on the val and test splits, because those
predictions are what write-back publishes. This module scores those same
predictions against the targets the bundle recorded for them, so every trainer
gets a held-out score with no scoring code of its own, and the score on the
Training page is measured on items the model was not fitted on.

The metrics are deliberately few and standard, one family per schema kind:

=============  ==========================================================
nominal        accuracy, macro-F1
ordinal        accuracy, macro-F1, mean absolute error when labels are numbers
multilabel     micro-F1, macro-F1, exact match
span           precision, recall and F1 over exact (start, end, label) matches
text           exact match, and token-overlap F1 (the SQuAD measure)
preference     as nominal: which response was preferred (ties not scored)
geometry       COCO mAP at IoU 0.5 and averaged over 0.5 to 0.95
temporal       precision, recall and F1 over segments matched at IoU 0.5
continuous     exact-value accuracy, mean absolute error (a slider's steps)
=============  ==========================================================

Metric names carry the split: ``val_accuracy``, ``test_macro_f1``. Each split
also gets a headline, ``<split>_score``, and the result names which metric the
headline is in ``heldout_metric``, so a page can show one number without
knowing every kind.

Standard library only, apart from geometry, which reuses the COCO average
precision in ``potato.server_utils.iaa.detection_ap`` (also standard library).
The worker runs this on a GPU host that may not have scikit-learn.
"""

from __future__ import annotations

import json
import re
import string
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = ["HEADLINE", "score_predictions", "score_split", "read_predictions"]

#: The headline metric per kind, in the order a page should prefer them.
HEADLINE = {
    "nominal": "macro_f1",
    "ordinal": "macro_f1",
    "multilabel": "micro_f1",
    "span": "f1",
    "text": "token_f1",
    "preference": "accuracy",
    # mAP@0.5 rather than COCO's 0.5:0.95: two annotators' boxes for the same
    # object rarely overlap at 0.9, so the stricter thresholds partly measure
    # how consistently people draw, and the run is judged against people.
    "geometry": "map_50",
    "temporal": "f1",
    # A slider asked as a decision question has a few steps; an exact step is
    # the headline, and the distance is mae.
    "continuous": "accuracy",
}

#: IoU at which a predicted segment matches an annotated one.
SEGMENT_IOU = 0.5


def read_predictions(path: str) -> Dict[Tuple[str, str], Any]:
    """``{(instance_id, schema_name): payload}`` from predictions.jsonl."""
    out: Dict[Tuple[str, str], Any] = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            key = (str(record.get("instance_id", "")),
                   str(record.get("schema_name", "")))
            out[key] = record.get("payload")
    return out


# ------------------------------------------------------------- payloads

def _label(payload: Any) -> Optional[str]:
    if isinstance(payload, dict):
        value = payload.get("label", payload.get("name"))
        return None if value is None else str(value)
    if isinstance(payload, list):
        return _label(payload[0]) if payload else None
    return None if payload is None else str(payload)


def _label_set(payload: Any) -> set:
    if payload is None:
        return set()
    if isinstance(payload, (str, dict)):
        payload = [payload]
    out = set()
    for entry in payload:
        name = _label(entry)
        if name:
            out.add(name)
    return out


def _span_set(spans: Any) -> set:
    out = set()
    for span in spans or []:
        if not isinstance(span, dict):
            continue
        try:
            start, end = int(span["start"]), int(span["end"])
        except (KeyError, TypeError, ValueError):
            continue
        name = span.get("label") or span.get("name") or ""
        out.add((start, end, str(name)))
    return out


def _text(payload: Any) -> str:
    if isinstance(payload, dict):
        payload = payload.get("text", payload.get("label", ""))
    return "" if payload is None else str(payload)


_PUNCT = re.compile("[%s]" % re.escape(string.punctuation))


def _tokens(text: str) -> List[str]:
    return _PUNCT.sub(" ", text.lower()).split()


# --------------------------------------------------------------- metrics

def _f1(precision: float, recall: float) -> float:
    return 0.0 if precision + recall == 0 else \
        2 * precision * recall / (precision + recall)


def _macro_f1(gold: Sequence[str], predicted: Sequence[Optional[str]]) -> float:
    """Macro-F1 over the labels that occur in either list.

    A label nobody used and the model never predicted is left out rather
    than counted as a perfect zero-over-zero.
    """
    labels = sorted(set(gold) | {p for p in predicted if p is not None})
    if not labels:
        return 0.0
    scores = []
    for label in labels:
        tp = sum(1 for g, p in zip(gold, predicted) if g == label and p == label)
        fp = sum(1 for g, p in zip(gold, predicted) if g != label and p == label)
        fn = sum(1 for g, p in zip(gold, predicted) if g == label and p != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        scores.append(_f1(precision, recall))
    return sum(scores) / len(scores)


def _number(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _score_labels(gold: List[str], predicted: List[Optional[str]],
                  ordinal: bool) -> Dict[str, float]:
    n = len(gold)
    out = {"accuracy": sum(1 for g, p in zip(gold, predicted) if g == p) / n,
           "macro_f1": _macro_f1(gold, predicted)}
    if ordinal:
        pairs = [(_number(g), _number(p)) for g, p in zip(gold, predicted)]
        pairs = [(g, p) for g, p in pairs if g is not None and p is not None]
        if pairs and len(pairs) == n:
            out["mae"] = sum(abs(g - p) for g, p in pairs) / n
    return out


def _score_multilabel(gold: List[set], predicted: List[set]) -> Dict[str, float]:
    tp = sum(len(g & p) for g, p in zip(gold, predicted))
    fp = sum(len(p - g) for g, p in zip(gold, predicted))
    fn = sum(len(g - p) for g, p in zip(gold, predicted))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0

    labels = sorted(set().union(*gold, *predicted)) if gold else []
    per_label = []
    for label in labels:
        ltp = sum(1 for g, p in zip(gold, predicted) if label in g and label in p)
        lfp = sum(1 for g, p in zip(gold, predicted) if label not in g and label in p)
        lfn = sum(1 for g, p in zip(gold, predicted) if label in g and label not in p)
        lp = ltp / (ltp + lfp) if ltp + lfp else 0.0
        lr = ltp / (ltp + lfn) if ltp + lfn else 0.0
        per_label.append(_f1(lp, lr))

    return {"micro_f1": _f1(precision, recall),
            "macro_f1": sum(per_label) / len(per_label) if per_label else 0.0,
            "exact_match": sum(1 for g, p in zip(gold, predicted) if g == p)
            / len(gold)}


def _score_spans(gold: List[set], predicted: List[set]) -> Dict[str, float]:
    tp = sum(len(g & p) for g, p in zip(gold, predicted))
    n_pred = sum(len(p) for p in predicted)
    n_gold = sum(len(g) for g in gold)
    precision = tp / n_pred if n_pred else 0.0
    recall = tp / n_gold if n_gold else 0.0
    return {"precision": precision, "recall": recall,
            "f1": _f1(precision, recall)}


def _token_f1(gold: str, predicted: str) -> float:
    g, p = _tokens(gold), _tokens(predicted)
    if not g and not p:
        return 1.0
    common = sum((Counter(g) & Counter(p)).values())
    if not common:
        return 0.0
    return _f1(common / len(p), common / len(g))


def _score_text(gold: List[str], predicted: List[str]) -> Dict[str, float]:
    n = len(gold)
    exact = sum(1 for g, p in zip(gold, predicted)
                if " ".join(_tokens(g)) == " ".join(_tokens(p)))
    return {"exact_match": exact / n,
            "token_f1": sum(_token_f1(g, p) for g, p in zip(gold, predicted)) / n}


def _number(value: Any) -> Optional[float]:
    if isinstance(value, (dict, list)):
        value = _label(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _score_numbers(gold: List[Any], predicted: List[Any]) -> Dict[str, float]:
    """Exact-value accuracy and mean absolute error. A missing prediction is
    wrong for accuracy and left out of the error, which ``coverage`` shows."""
    pairs = [(_number(g), _number(p)) for g, p in zip(gold, predicted)]
    exact = sum(1 for g, p in pairs if g is not None and p is not None
                and abs(g - p) < 1e-9)
    errors = [abs(g - p) for g, p in pairs if g is not None and p is not None]
    return {"accuracy": exact / len(pairs) if pairs else 0.0,
            "mae": sum(errors) / len(errors) if errors else 0.0}


def _objects(value: Any) -> List[Dict[str, Any]]:
    """A geometry payload or target as a list of objects. Image prelabels
    travel as a JSON string, which is what the image widget reads back."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    if isinstance(value, dict):
        value = value.get("objects", value.get("segments", [value]))
    return [o for o in (value or []) if isinstance(o, dict)] \
        if isinstance(value, list) else []


def _as_box(obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """An annotated shape as its bounding box, in the same normalized units
    as the image widget's boxes."""
    if obj.get("type") == "bbox":
        return obj
    from potato.export.cv_utils import normalize_annotation_object
    canonical = normalize_annotation_object(obj, 1.0, 1.0)
    if not canonical or not canonical.get("bbox"):
        return None
    x, y, w, h = (float(v) for v in canonical["bbox"][:4])
    if obj.get("type") == "mask":
        # A mask's RLE is in pixels of its own size, [height, width].
        size = (obj.get("rle") or {}).get("size") or []
        if len(size) < 2 or not size[0] or not size[1]:
            return None
        x, w = x / float(size[1]), w / float(size[1])
        y, h = y / float(size[0]), h / float(size[0])
    return {"type": "bbox", "label": obj.get("label"),
            "coordinates": {"x": x, "y": y, "width": w, "height": h}}


def _as_outline(obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """An annotated outline (polygon, ellipse, freeform, mask) as a polygon
    in normalized units; None for a box or point. A mask in several pieces
    is represented by its largest piece."""
    from potato.training.trainers._segmentation import outline_polygons
    rings = outline_polygons(obj, 1, 1)
    if not rings:
        return None

    def area(ring):
        return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1)
                       in zip(ring, ring[1:] + ring[:1]))) / 2.0

    ring = max(rings, key=area)
    return {"type": "polygon", "label": obj.get("label"),
            "coordinates": [{"x": x, "y": y} for x, y in ring]}


def _score_geometry(ids: List[str], gold: List[Any],
                    predicted: List[Any]) -> Dict[str, float]:
    from potato.server_utils.iaa.detection_ap import mean_average_precision
    predictions = {i: _objects(p) for i, p in zip(ids, predicted)}
    truth = {i: _objects(g) for i, g in zip(ids, gold)}
    kinds = {o.get("type") for objs in predictions.values() for o in objs}
    if kinds <= {"bbox"}:
        # A box detector is scored against each annotated shape's bounding
        # box, as COCO's box mAP is. The IoU underneath scores a box against
        # a polygon as 0 -- right for two annotators who drew different
        # kinds of shape, and it made every polygon a detector found a miss.
        truth = {i: [b for b in map(_as_box, objs) if b]
                 for i, objs in truth.items()}
    elif kinds <= {"polygon"}:
        # A segmentation model's outlines are scored against the annotated
        # outlines as polygons: an ellipse or a brush mask becomes one. A box
        # is not an outline, so it is left out here as it is in training.
        truth = {i: [p for p in map(_as_outline, objs) if p]
                 for i, objs in truth.items()}
    result = mean_average_precision(predictions, truth)
    return {"map_50": float(result.get("mAP_50") or 0.0),
            "map_50_95": float(result.get("mAP_50_95") or 0.0),
            "n_objects": float(result.get("n_truth") or 0),
            "n_predicted_objects": float(result.get("n_predictions") or 0)}


def _segment(value: Dict[str, Any]) -> Optional[Tuple[float, float, str]]:
    try:
        start = float(value.get("start", value.get("start_time")))
        end = float(value.get("end", value.get("end_time")))
    except (TypeError, ValueError):
        return None
    return min(start, end), max(start, end), str(value.get("label", ""))


def _segment_iou(a: Tuple[float, float, str], b: Tuple[float, float, str]) -> float:
    overlap = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    if union <= 0:
        return 1.0 if a[0] == b[0] else 0.0
    return overlap / union


def _score_segments(gold: List[Any], predicted: List[Any]) -> Dict[str, float]:
    """Each annotated segment matches at most one predicted segment of the same
    label, at IoU >= SEGMENT_IOU, best overlap first."""
    tp = n_gold = n_pred = 0
    ious: List[float] = []
    for g_raw, p_raw in zip(gold, predicted):
        g = [s for s in map(_segment, _objects(g_raw)) if s]
        p = [s for s in map(_segment, _objects(p_raw)) if s]
        n_gold += len(g)
        n_pred += len(p)
        pairs = sorted(((_segment_iou(a, b), i, j)
                        for i, a in enumerate(g) for j, b in enumerate(p)
                        if a[2] == b[2]), reverse=True)
        used_g, used_p = set(), set()
        for iou, i, j in pairs:
            if iou < SEGMENT_IOU or i in used_g or j in used_p:
                continue
            used_g.add(i)
            used_p.add(j)
            tp += 1
            ious.append(iou)
    precision = tp / n_pred if n_pred else 0.0
    recall = tp / n_gold if n_gold else 0.0
    return {"precision": precision, "recall": recall,
            "f1": _f1(precision, recall),
            "matched_iou": sum(ious) / len(ious) if ious else 0.0}


# --------------------------------------------------------------- scoring

def score_split(rows: Iterable[Dict[str, Any]],
                predictions: Dict[Tuple[str, str], Any],
                schema_name: str, kind: str) -> Tuple[Dict[str, float], int]:
    """Metrics for one schema over one split, and how many rows were scored.

    A labelled row the model gave no prediction for counts as wrong, not as
    missing: a trainer that skips the hard items must not score higher for
    it. Rows with no target for the schema are not scored.
    """
    gold_raw, pred_raw, ids = [], [], []
    for row in rows:
        target = (row.get("targets") or {}).get(schema_name)
        if target is None or target == "" or (target == [] and kind != "span"):
            continue
        if kind == "preference" and str(target).lower() == "tie":
            # "No preference" says nothing about which response is better,
            # and a model that ranks two responses never answers it.
            continue
        gold_raw.append(target)
        ids.append(str(row.get("instance_id", "")))
        pred_raw.append(predictions.get((str(row.get("instance_id", "")),
                                         schema_name)))

    n = len(gold_raw)
    if not n:
        return {}, 0

    if kind in ("nominal", "ordinal", "preference"):
        gold = [str(g) for g in gold_raw]
        predicted = [_label(p) for p in pred_raw]
        metrics = _score_labels(gold, predicted, ordinal=kind == "ordinal")
    elif kind == "multilabel":
        metrics = _score_multilabel([_label_set(g) for g in gold_raw],
                                    [_label_set(p) for p in pred_raw])
    elif kind == "span":
        metrics = _score_spans([_span_set(g) for g in gold_raw],
                               [_span_set(p) for p in pred_raw])
    elif kind == "text":
        metrics = _score_text([_text(g) for g in gold_raw],
                              [_text(p) for p in pred_raw])
    elif kind == "continuous":
        metrics = _score_numbers(gold_raw, pred_raw)
    elif kind == "geometry":
        metrics = _score_geometry(ids, gold_raw, pred_raw)
    elif kind == "temporal":
        metrics = _score_segments(gold_raw, pred_raw)
    else:
        return {}, n

    metrics["n"] = float(n)
    metrics["coverage"] = sum(1 for p in pred_raw if p is not None) / n
    return metrics, n


def score_predictions(bundle, predictions: Dict[Tuple[str, str], Any],
                      schemas: Sequence[Any],
                      splits: Sequence[str] = ("val", "test"),
                      selected_on: str = "") -> Dict[str, Any]:
    """Held-out metrics for every schema over the named splits.

    *schemas* are ``SchemaSpec``s. Metric names are ``<split>_<metric>`` for
    the first schema and ``<split>_<schema>_<metric>`` for the others, so a
    single-schema run, the usual case, reads plainly.

    The result also carries ``heldout_score`` and ``heldout_metric``: the
    first schema's headline on the first split that has rows. A split named
    by *selected_on* goes last, because a trainer that picked its checkpoint
    on val has already seen how it scores there.
    """
    if selected_on in splits:
        splits = [s for s in splits if s != selected_on] + [selected_on]
    out: Dict[str, Any] = {}
    for position, schema in enumerate(schemas):
        kind = getattr(schema, "kind", "")
        name = getattr(schema, "name", "")
        prefix_extra = "" if position == 0 else "%s_" % name
        for split in splits:
            metrics, n = score_split(bundle.read_split(split), predictions,
                                     name, kind)
            for metric, value in metrics.items():
                out["%s_%s%s" % (split, prefix_extra, metric)] = round(value, 4)
            headline = HEADLINE.get(kind)
            if position == 0 and headline in metrics \
                    and "heldout_score" not in out:
                out["heldout_score"] = round(metrics[headline], 4)
                out["heldout_metric"] = "%s %s" % (split, headline)
    return out
