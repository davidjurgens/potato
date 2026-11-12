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
trajectory     how often the model favours the corrected agent trace over
               the original; token F1 against the correction for a writer
trace          per-step accuracy and macro-F1 over correct/neutral/wrong,
               and whether the first wrong step is the annotators' one
relation       link precision, recall and F1 over (span offsets, type), and
               mention F1; UAS and LAS when the gold links are trees
coreference    MUC, B-cubed and entity CEAF F1, and CoNLL F1, their mean
event          trigger F1 and argument F1
ranking        Kendall's tau, pairwise and top-1 accuracy
bws            best, worst and best-worst accuracy
distribution   1 - Jensen-Shannon divergence from the annotators'
               distribution, cross-entropy, argmax accuracy
gloss          word and morpheme gloss accuracy
conv. tree     node-answer accuracy and macro-F1, exact path accuracy
pref. scale    direction accuracy, mean absolute error on the scale
geo            as geometry, in the raster's pixels
caption        token F1 per region and corpus BLEU-4
grounding      accuracy at IoU 0.5 (point-in-region for points), mean IoU,
               and how often an absent referent was declined
gui_click      verdict accuracy and macro-F1 over judged steps; click
               accuracy within 5% of the screenshot on approved steps
peaks          peak precision, recall and F1 within a tolerance
intervals      epoch accuracy and macro-F1, or interval F1 at IoU 0.5
episode        phase accuracy, macro-F1 and segment F1, outcome accuracy,
               reward Pearson's r
=============  ==========================================================

A classifier trained on soft targets (several annotators' votes as a
distribution) also gets ``soft_jsd``, ``soft_cross_entropy`` and ``ece``
on the rows that have one, when its predictions carry probabilities. The
structured kinds are scored in ``structured_metrics``.

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

__all__ = ["HEADLINE", "headline_of", "score_predictions", "score_split",
           "read_predictions"]

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
    "trajectory": "closer_to_correction",
    # Most steps in most traces are correct, so accuracy flatters a model that
    # never says "wrong".
    "trace": "step_macro_f1",
    "relation": "f1",
    "coreference": "conll_f1",
    "event": "argument_f1",
    "ranking": "kendall_tau",
    "bws": "best_worst_accuracy",
    "distribution": "distribution_agreement",
    "gloss": "morpheme_accuracy",
    "conversation_tree": "node_macro_f1",
    "preference_scale": "direction_accuracy",
    # Converted to the raster's pixels at bundle time, so scored as geometry.
    "geo": "map_50",
    "caption": "token_f1",
    # acc@0.5, or point-in-region when the scheme collects points.
    "grounding": "accuracy",
    # Most steps an agent takes are right; accuracy flatters a model that
    # always says "correct".
    "gui_click": "verdict_macro_f1",
    # max(0, 1 - WER) and max(0, 1 - DER): headlines are higher-is-better.
    "transcript": "word_accuracy",
    "segments": "diarization_accuracy",
    # Boxes on the rendered spectrogram; time and frequency map linearly to
    # its pixels, so IoU there is IoU in seconds by hertz.
    "acoustic": "map_50",
    # Dice per label over each volume, averaged over the labels painted.
    "volume": "mean_dice",
    # Volumetric IoU of oriented cuboids, matched per label.
    "spatial": "map_3d_50",
    # Identity over the video, not per-frame boxes: a model that swaps two
    # people's ids where they cross loses IDF1 though every frame matches.
    "track": "idf1",
    "peaks": "f1",
    # Epoch mode; a free-mode scheme's headline is interval_f1 (below).
    "intervals": "macro_f1",
    "episode": "phase_macro_f1",
}

#: Headlines to fall back on, in order, when a kind's own is not among the
#: metrics: a free-mode interval scheme has no epochs, and an episode scheme
#: without a phases layer is scored on its outcome or reward.
HEADLINE_FALLBACKS = {
    "intervals": ("interval_f1",),
    "episode": ("outcome_accuracy", "reward_pearson"),
}


def headline_of(kind: str, metrics: Dict[str, float]) -> Optional[str]:
    """The headline metric present in *metrics* for *kind*, or None."""
    for name in (HEADLINE.get(kind),) + tuple(HEADLINE_FALLBACKS.get(kind, ())):
        if name and name in metrics:
            return name
    return None

#: Kind to the ``structured_metrics`` function that scores it.
_STRUCTURED_SCORERS = {
    "relation": "score_relations", "coreference": "score_coreference",
    "event": "score_events", "ranking": "score_rankings", "bws": "score_bws",
    "distribution": "score_distributions", "gloss": "score_glosses",
    "conversation_tree": "score_trees",
    "preference_scale": "score_scale_preferences",
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

def _score_trajectories(gold: List[Any], predicted: List[Any]) -> Dict[str, float]:
    """A preference model answers "A" (the correction) or "B"; a writer
    answers with steps, which count as closer to the correction when their
    token F1 against it beats their F1 against the original."""
    closer, f1s, writer = 0, [], False
    for target, payload in zip(gold, predicted):
        label = _label(payload) if isinstance(payload, dict) else None
        if label in ("A", "B"):
            closer += label == "A"
            continue
        if payload is None:
            continue
        writer = True
        text = _text(payload)
        f1 = _token_f1(str(target.get("chosen", "")), text)
        f1s.append(f1)
        closer += f1 > _token_f1(str(target.get("rejected", "")), text)
    metrics = {"closer_to_correction": closer / len(gold)}
    if writer:
        metrics["token_f1"] = sum(f1s) / len(gold)
    return metrics


def _step_rewards(payload: Any) -> Dict[int, int]:
    """``{step_index: reward}`` from a process-reward prediction."""
    steps = payload.get("steps") if isinstance(payload, dict) else payload
    out: Dict[int, int] = {}
    for n, step in enumerate(steps if isinstance(steps, list) else []):
        if isinstance(step, dict):
            try:
                out[int(step.get("index", n))] = int(step.get("reward"))
            except (TypeError, ValueError):
                continue
    return out


def _first_error(rewards: Dict[int, int]) -> Optional[int]:
    wrong = [i for i, r in rewards.items() if r == -1]
    return min(wrong) if wrong else None


def _score_traces(gold: List[Any], predicted: List[Any]) -> Dict[str, float]:
    """Step labels pooled over traces, and the first wrong step per trace,
    the question a first_error annotator answered."""
    step_gold: List[str] = []
    step_pred: List[Optional[str]] = []
    first_hits = 0
    for target, payload in zip(gold, predicted):
        predicted_rewards = _step_rewards(payload)
        rated = {i: r for i, r in enumerate(target) if r is not None}
        for index, reward in rated.items():
            step_gold.append(str(reward))
            guess = predicted_rewards.get(index)
            step_pred.append(None if guess is None else str(guess))
        first_hits += _first_error(rated) == _first_error(
            {i: r for i, r in predicted_rewards.items() if i in rated})
    if not step_gold:
        return {}
    labels = _score_labels(step_gold, step_pred, ordinal=False)
    return {"step_accuracy": labels["accuracy"],
            "step_macro_f1": labels["macro_f1"],
            "first_error_accuracy": first_hits / len(gold),
            "n_steps": float(len(step_gold)),
            # Per step: a trace cut by max_length has a prediction (the
            # early steps) but no rating for the rest.
            "step_coverage": sum(1 for p in step_pred if p is not None)
            / len(step_pred)}


def _score_volumes(gold: List[Any], predicted: List[Any]) -> Dict[str, float]:
    """Dice per label per volume against the annotated masks, over every
    label either side painted: a label the model left out of a volume that
    has it scores 0, and so does one it painted where nobody did (scored on
    the annotated labels alone, painting extra labels cost nothing).
    ``mean_dice`` averages every (volume, label) pair; ``dice_<label>``
    each label's. Slices that do not decode are left out of the guess."""
    from potato.media.volume_masks import dice, label_volume
    per_label: Dict[str, List[float]] = {}
    for target, payload in zip(gold, predicted):
        shape = target.get("shape")
        guess = payload if isinstance(payload, dict) else {}
        masks = guess.get("masks") if isinstance(guess.get("masks"), dict) else {}
        clean = {"masks": {}}
        for label, slices in masks.items():
            if not isinstance(slices, dict):
                continue
            kept = {}
            for k, counts in slices.items():
                try:
                    if 0 <= int(k) < int(shape[2]):
                        kept[str(int(k))] = counts
                except (TypeError, ValueError):
                    continue
            clean["masks"][str(label)] = kept
        for label in set(target.get("masks") or {}) | set(clean["masks"]):
            try:
                score = dice(label_volume(target, shape, label),
                             label_volume(clean, shape, label))
            except ValueError:   # runs that do not fit the slice
                score = 0.0
            if score is not None:
                per_label.setdefault(label, []).append(score)
    pairs = [s for scores in per_label.values() for s in scores]
    if not pairs:
        return {}
    out = {"mean_dice": sum(pairs) / len(pairs)}
    for label, scores in per_label.items():
        out["dice_%s" % label] = sum(scores) / len(scores)
    return out


def score_split(rows: Iterable[Dict[str, Any]],
                predictions: Dict[Tuple[str, str], Any],
                schema_name: str, kind: str,
                trees: Optional[bool] = None) -> Tuple[Dict[str, float], int]:
    """Metrics for one schema over one split, and how many rows were scored.

    A labelled row the model gave no prediction for counts as wrong, not as
    missing: a trainer that skips the hard items must not score higher for
    it. Rows with no target for the schema are not scored. *trees* is for
    relations: whether every training answer is a dependency tree.
    """
    gold_raw, pred_raw, ids, soft, steps = [], [], [], [], []
    for row in rows:
        target = (row.get("targets") or {}).get(schema_name)
        if target is None or target == "" or (target == [] and kind != "span"):
            continue
        if kind == "preference" and str(target).lower() == "tie":
            # "No preference" says nothing about which response is better,
            # and a model that ranks two responses never answers it.
            continue
        gold_raw.append(target)
        soft.append((row.get("soft_targets") or {}).get(schema_name))
        steps.append(row.get("steps"))
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
        if any(soft):
            from potato.training.structured_metrics import soft_label_scores
            metrics.update(soft_label_scores(soft, pred_raw, gold))
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
    elif kind in ("geometry", "geo", "acoustic"):
        metrics = _score_geometry(ids, gold_raw, pred_raw)
    elif kind == "track":
        from potato.training.tracking import score_tracks
        metrics = score_tracks(gold_raw, pred_raw)
        if not metrics:
            return {}, n
    elif kind == "spatial":
        from potato.training.spatial import score_cuboids
        metrics = score_cuboids(gold_raw, pred_raw)
        if not metrics:
            return {}, n
    elif kind == "volume":
        metrics = _score_volumes(gold_raw, pred_raw)
        if not metrics:
            return {}, n
    elif kind in ("transcript", "segments"):
        from potato.training import audio_metrics
        metrics = (audio_metrics.score_transcripts(gold_raw, pred_raw) if kind == "transcript"
                   else audio_metrics.score_diarization(gold_raw, pred_raw))
        if not metrics:
            return {}, n
    elif kind in ("caption", "grounding", "gui_click"):
        from potato.training import vision_metrics
        if kind == "caption":
            metrics = vision_metrics.score_captions(gold_raw, pred_raw)
        elif kind == "grounding":
            metrics = vision_metrics.score_grounding(gold_raw, pred_raw)
        else:
            metrics = vision_metrics.score_gui_clicks(gold_raw, pred_raw, steps)
        if not metrics:
            return {}, n
    elif kind in ("peaks", "intervals", "episode"):
        from potato.training import science_metrics
        scorer = {"peaks": science_metrics.score_peaks,
                  "intervals": science_metrics.score_intervals,
                  "episode": science_metrics.score_episodes}[kind]
        metrics = scorer(gold_raw, pred_raw)
        if not metrics:
            return {}, n
    elif kind == "temporal":
        metrics = _score_segments(gold_raw, pred_raw)
    elif kind == "trajectory":
        metrics = _score_trajectories(gold_raw, pred_raw)
    elif kind == "trace":
        metrics = _score_traces(gold_raw, pred_raw)
        if not metrics:
            return {}, n
    elif kind in _STRUCTURED_SCORERS:
        from potato.training import structured_metrics
        scorer = getattr(structured_metrics, _STRUCTURED_SCORERS[kind])
        metrics = scorer(gold_raw, pred_raw, trees=trees) if kind == "relation" \
            else scorer(gold_raw, pred_raw)
        if not metrics:
            return {}, n
    else:
        return {}, n

    metrics["n"] = float(n)
    metrics["coverage"] = sum(1 for p in pred_raw if p is not None) / n
    return metrics, n


def _trained_on_trees(bundle, schema_name: str) -> Optional[bool]:
    """Whether every training answer for a relation scheme is a dependency
    tree, the test hf-relation decodes trees on; None without a train split."""
    from potato.training.structured import is_tree_answer
    targets = [(row.get("targets") or {}).get(schema_name)
               for row in bundle.read_split("train")]
    targets = [t for t in targets if t]
    return all(is_tree_answer(t) for t in targets) if targets else None


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
        trees = _trained_on_trees(bundle, name) if kind == "relation" else None
        for split in splits:
            # A tiled image is scored whole, on its merged predictions.
            from potato.training.tiling import scoring_rows
            metrics, n = score_split(scoring_rows(bundle, split), predictions,
                                     name, kind, trees=trees)
            for metric, value in metrics.items():
                out["%s_%s%s" % (split, prefix_extra, metric)] = round(value, 4)
            headline = headline_of(kind, metrics)
            if position == 0 and headline in metrics \
                    and "heldout_score" not in out:
                out["heldout_score"] = round(metrics[headline], 4)
                out["heldout_metric"] = "%s %s" % (split, headline)
    return out
