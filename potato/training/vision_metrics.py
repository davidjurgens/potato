"""Held-out metrics for region captions, grounding and GUI clicks.

Standard library only, like the rest of ``evaluation``: the worker scores on
a GPU host that may have nothing but torch.

Predictions take the shape each scheme stores, so a payload can be written
back as a prelabel unchanged:

- caption: ``{"captions": [{region, caption}]}``, one per gold region, in
  the gold order (the trainer captions the regions it is given);
- grounding: ``{"regions": {expression id: [object]}, "absent": [ids]}``;
- gui_click: ``[{index, verdict, point, confidence}]``.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence

__all__ = ["score_captions", "score_grounding", "score_gui_clicks",
           "bleu4", "CLICK_RADIUS"]

#: How close (as a fraction of the screenshot, Euclidean in normalized
#: units) a predicted click must land to the agent's approved click.
CLICK_RADIUS = 0.05


def _tokens(text: str) -> List[str]:
    from potato.training.evaluation import _tokens as tokens
    return tokens(text)


def bleu4(references: Sequence[str], hypotheses: Sequence[str]) -> float:
    """Corpus BLEU-4 with add-one smoothing on the higher orders, so one
    short caption with no 4-gram match does not zero the corpus."""
    matches = [0] * 4
    totals = [0] * 4
    ref_len = hyp_len = 0
    for ref, hyp in zip(references, hypotheses):
        r, h = _tokens(ref), _tokens(hyp)
        ref_len += len(r)
        hyp_len += len(h)
        for n in range(1, 5):
            r_grams = Counter(tuple(r[i:i + n]) for i in range(len(r) - n + 1))
            h_grams = Counter(tuple(h[i:i + n]) for i in range(len(h) - n + 1))
            matches[n - 1] += sum(min(c, r_grams[g]) for g, c in h_grams.items())
            totals[n - 1] += max(len(h) - n + 1, 0)
    if not hyp_len or not totals[0] or not matches[0]:
        return 0.0
    log_precision = 0.0
    for n in range(4):
        smooth = 0 if n == 0 else 1
        log_precision += math.log((matches[n] + smooth) / (totals[n] + smooth)) / 4
    brevity = 1.0 if hyp_len > ref_len else math.exp(1 - ref_len / hyp_len)
    return brevity * math.exp(log_precision)


def _captions(payload: Any) -> List[str]:
    entries = payload.get("captions") if isinstance(payload, dict) else payload
    return [str(e.get("caption") or "") if isinstance(e, dict) else ""
            for e in (entries if isinstance(entries, list) else [])]


def score_captions(gold: List[Any], predicted: List[Any]) -> Dict[str, float]:
    """Token F1 per region, averaged over every gold region (a region with no
    caption predicted scores 0), and corpus BLEU-4."""
    from potato.training.evaluation import _token_f1
    references, hypotheses, f1s = [], [], []
    for target, payload in zip(gold, predicted):
        guesses = _captions(payload)
        for n, entry in enumerate(target or []):
            reference = str(entry.get("caption") or "")
            guess = guesses[n] if n < len(guesses) else ""
            references.append(reference)
            hypotheses.append(guess)
            f1s.append(_token_f1(reference, guess) if guess else 0.0)
    if not f1s:
        return {}
    return {"token_f1": sum(f1s) / len(f1s), "bleu4": bleu4(references, hypotheses),
            "n_regions": float(len(f1s))}


def _point_of(region: Optional[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    """A landmark's point, or the centre of any other region."""
    if not isinstance(region, dict):
        return None
    coords = region.get("coordinates")
    if region.get("type") == "landmark" and isinstance(coords, dict):
        try:
            return {"x": float(coords["x"]), "y": float(coords["y"])}
        except (KeyError, TypeError, ValueError):
            return None
    from potato.grounding.metrics import region_center
    return region_center(region)


def score_grounding(gold: List[Any], predicted: List[Any]) -> Dict[str, float]:
    """``grounding.metrics`` over every answered expression: accuracy at IoU
    0.5 (point-in-region for pointing), mean IoU, and how often an absent
    referent was correctly declined. The headline, ``accuracy``, is acc@0.5
    or point-in-region by the scheme's region type."""
    from potato.grounding.metrics import grounding_accuracy, pointing_accuracy
    pairs: List[Dict[str, Any]] = []
    pointing = False
    for target, payload in zip(gold, predicted):
        if not isinstance(target, dict):
            continue
        pointing = pointing or target.get("region_type") == "point"
        regions = (payload or {}).get("regions") if isinstance(payload, dict) else {}
        regions = regions if isinstance(regions, dict) else {}
        absent = {str(a) for a in ((payload or {}).get("absent") or [])} \
            if isinstance(payload, dict) else set()
        for expression in target.get("expressions") or []:
            eid = str(expression.get("id"))
            guesses = [r for r in regions.get(eid) or [] if isinstance(r, dict)]
            truth = (expression.get("regions") or [None])[0]
            pairs.append({"truth": truth, "truth_absent": bool(expression.get("absent")),
                          "prediction": guesses[0] if guesses else None,
                          "prediction_absent": eid in absent,
                          "point": _point_of(guesses[0]) if guesses else None})
    if not pairs:
        return {}
    boxes = grounding_accuracy(pairs)
    absent = boxes["absent"]
    out = {"mean_iou": boxes["mean_iou"],
           "acc_25": boxes["acc@0.25"], "acc_50": boxes["acc@0.5"],
           "acc_75": boxes["acc@0.75"],
           "n_expressions": float(len(pairs))}
    if absent["n_truth_absent"]:
        out["absent_accuracy"] = absent["correctly_declined"] / absent["n_truth_absent"]
    if pointing:
        points = pointing_accuracy(pairs)
        out["point_in_region"] = points["point_in_region"]
        out["accuracy"] = points["point_in_region"]
    else:
        out["accuracy"] = boxes["acc@0.5"]
    # NaN (nothing with a referent scored) is not a number a page can chart.
    return {k: (0.0 if isinstance(v, float) and math.isnan(v) else v)
            for k, v in out.items()}


def score_gui_clicks(gold: List[Any], predicted: List[Any],
                     steps: List[Any], radius: float = CLICK_RADIUS
                     ) -> Dict[str, float]:
    """Verdict accuracy and macro-F1 over the judged steps, and click
    accuracy over the steps judged ``correct`` that have a click: the
    model's point within *radius* of the agent's approved one.

    A step judged wrong has no gold click (the agent's was wrong, and nobody
    said where the right one was), so it is scored on the verdict alone."""
    from potato.training.evaluation import _score_labels
    verdict_gold: List[str] = []
    verdict_pred: List[Optional[str]] = []
    hits = clicks = 0
    distances: List[float] = []
    for target, payload, row_steps in zip(gold, predicted, steps):
        guesses = {}
        for entry in payload if isinstance(payload, list) else []:
            if isinstance(entry, dict):
                try:
                    guesses[int(entry.get("index"))] = entry
                except (TypeError, ValueError):
                    continue
        points = {int(s.get("index", n)): s.get("point")
                  for n, s in enumerate(row_steps or []) if isinstance(s, dict)}
        for judged in target or []:
            index = int(judged["index"])
            guess = guesses.get(index) or {}
            verdict_gold.append(str(judged["verdict"]))
            verdict_pred.append(str(guess["verdict"]) if guess.get("verdict") else None)
            agent = points.get(index)
            if judged["verdict"] != "correct" or not isinstance(agent, dict):
                continue
            clicks += 1
            point = guess.get("point")
            if not isinstance(point, dict):
                continue
            try:
                distance = math.hypot(float(point["x"]) - float(agent["x"]),
                                      float(point["y"]) - float(agent["y"]))
            except (KeyError, TypeError, ValueError):
                continue
            distances.append(distance)
            hits += distance <= radius
    if not verdict_gold:
        return {}
    labels = _score_labels(verdict_gold, verdict_pred, ordinal=False)
    out = {"verdict_accuracy": labels["accuracy"],
           "verdict_macro_f1": labels["macro_f1"],
           "n_steps": float(len(verdict_gold))}
    if clicks:
        out["click_accuracy"] = hits / clicks
        out["n_clicks"] = float(clicks)
    if distances:
        out["mean_click_distance"] = sum(distances) / len(distances)
    return out
