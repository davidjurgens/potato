"""Calibrating a decision model's probabilities to one study's annotators.

A decision model (hosted Jev, OpenJev, laya-serve, in-process Laya) returns a
probability for every option of a question. Two things can be wrong with
those numbers for a given study: they can be over- or under-confident, and
the model's idea of how common each option is can differ from this study's
data. A calibration fitted on items annotators have labelled corrects both,
per question:

``temperature``
    ``p' = softmax(log p / T)``. One number per question; it changes how
    confident the model is, never which option it picks.

``temperature+bias``
    ``p' = softmax(log p / T + b)``, with one offset per option (the first is
    fixed at 0). It can change the pick: an option the model under-predicts
    for this study gets a positive offset. It needs more labelled items per
    option than temperature alone, and an L2 penalty keeps offsets small
    when the data is thin.

The fitted calibration is a JSON file, the same for every backend::

    {"v": 1, "method": "temperature", "questions": {
        "sentiment": {"kind": "choice", "options": ["pos", "neg"],
                      "temperature": 1.7, "bias": {"pos": 0.0, "neg": 0.2}}},
     "n": {"sentiment": 180}, "metrics": {...}}

and a decision endpoint applies it when ``ai_config.calibration`` names it.
Applying it is standard library only; fitting uses scipy, a core dependency.
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = ["CALIBRATION_VERSION", "METHODS", "load_calibration",
           "calibrate_distribution", "apply_calibration", "fit_question",
           "expected_calibration_error", "negative_log_likelihood"]

CALIBRATION_VERSION = 1
METHODS = ("temperature", "temperature+bias")

#: Probabilities are clipped here before the log: a model that says 0.0
#: would otherwise make its log -inf and the option unreachable by any bias.
_EPS = 1e-6
#: The fitted temperature is kept inside this range. Outside it the data is
#: saying something a single number cannot fix.
T_MIN, T_MAX = 0.05, 20.0

#: Fewest wrong answers on the fitting data for a fit to mean anything. With
#: none, the likelihood keeps rising as the temperature falls, so the fit
#: runs to T_MIN and every later answer reads as certain.
MIN_ERRORS = 2


def load_calibration(path: str) -> Dict[str, Any]:
    with open(path) as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or int(data.get("v", 0)) != CALIBRATION_VERSION \
            or not isinstance(data.get("questions"), dict):
        raise ValueError("%s is not a Potato decision-model calibration "
                         "(version %d)" % (path, CALIBRATION_VERSION))
    return data


def _softmax(scores: Sequence[float]) -> List[float]:
    top = max(scores)
    exps = [math.exp(s - top) for s in scores]
    total = sum(exps)
    return [e / total for e in exps]


def calibrate_distribution(probabilities: Dict[str, float],
                           entry: Dict[str, Any]) -> Dict[str, float]:
    """One answer's probabilities with a question's calibration applied.

    Options the calibration does not know (the scheme gained a label after it
    was fitted) keep an offset of 0.
    """
    options = list(probabilities)
    temperature = float(entry.get("temperature", 1.0) or 1.0)
    bias = entry.get("bias") or {}
    scores = [math.log(max(float(probabilities[o]), _EPS)) / temperature
              + float(bias.get(o, 0.0)) for o in options]
    return dict(zip(options, _softmax(scores)))


def apply_calibration(answers: List[Any], calibration: Optional[Dict[str, Any]]
                      ) -> List[Any]:
    """DecisionAnswers with calibrated probabilities, value and confidence.

    A question the calibration does not cover, and a yes/no (``noul``)
    answer, pass through unchanged.
    """
    if not calibration:
        return answers
    questions = calibration.get("questions") or {}
    out = []
    for answer in answers:
        entry = questions.get(answer.id)
        probs = getattr(answer, "probabilities", None)
        if not entry or not probs or set(probs) == {"yes", "no"}:
            out.append(answer)
            continue
        calibrated = calibrate_distribution(probs, entry)
        value = max(calibrated, key=calibrated.get)
        out.append(type(answer)(id=answer.id, value=value,
                                confidence=calibrated[value],
                                probabilities=calibrated, raw=answer.raw))
    return out


# ------------------------------------------------------------------ fitting

def negative_log_likelihood(pairs: Sequence[Tuple[Dict[str, float], str]],
                            entry: Optional[Dict[str, Any]] = None) -> float:
    """Mean ``-log p(gold)`` over ``(probabilities, gold)`` pairs."""
    if not pairs:
        return 0.0
    total = 0.0
    for probs, gold in pairs:
        p = calibrate_distribution(probs, entry) if entry else probs
        total -= math.log(max(float(p.get(gold, 0.0)), _EPS))
    return total / len(pairs)


def expected_calibration_error(pairs: Sequence[Tuple[Dict[str, float], str]],
                               entry: Optional[Dict[str, Any]] = None,
                               bins: int = 10) -> float:
    """ECE over the top choice: |accuracy - confidence| per confidence bin,
    weighted by the bin's share of items."""
    if not pairs:
        return 0.0
    totals = [[0, 0.0, 0.0] for _ in range(bins)]
    for probs, gold in pairs:
        p = calibrate_distribution(probs, entry) if entry else probs
        choice = max(p, key=p.get)
        confidence = float(p[choice])
        b = min(bins - 1, int(confidence * bins))
        totals[b][0] += 1
        totals[b][1] += confidence
        totals[b][2] += 1.0 if choice == gold else 0.0
    # Per bin, |sum of correct - sum of confidence| / n is the bin's share
    # times |accuracy - mean confidence|.
    return sum(abs(acc - conf) for _count, conf, acc in totals) / float(len(pairs))


def fit_question(pairs: Sequence[Tuple[Dict[str, float], str]],
                 options: Sequence[str], method: str = "temperature",
                 l2: float = 0.01) -> Dict[str, Any]:
    """Fit one question's calibration by minimizing NLL on *pairs*.

    Returns ``{"temperature", "bias", "fitted", "note"}``. It returns the
    identity (``fitted: False`` and the reason in ``note``) when there are
    fewer than two usable pairs, when the model got fewer than MIN_ERRORS of
    them wrong, or when the temperature lands on a bound of
    [T_MIN, T_MAX]: in each case applying the fit would make the answers
    less trustworthy than leaving them alone.
    """
    import numpy
    from scipy.optimize import minimize

    if method not in METHODS:
        raise ValueError("method must be one of %s" % ", ".join(METHODS))
    options = list(options)
    index = {o: i for i, o in enumerate(options)}
    usable = [(p, g) for p, g in pairs if g in index]
    def identity(note: str) -> Dict[str, Any]:
        return {"temperature": 1.0, "bias": {o: 0.0 for o in options},
                "fitted": False, "note": note}

    if len(usable) < 2:
        return identity("fewer than two labelled items")
    errors = sum(1 for p, g in usable if max(options, key=lambda o: float(
        p.get(o, 0.0))) != g)
    if errors < MIN_ERRORS:
        return identity("the model got %d of %d items wrong; at least %d "
                        "mistakes are needed to fit a calibration"
                        % (errors, len(usable), MIN_ERRORS))

    logs = numpy.array([[math.log(max(float(p.get(o, 0.0)), _EPS)) for o in options]
                        for p, _ in usable])
    gold = numpy.array([index[g] for _, g in usable])
    with_bias = method == "temperature+bias" and len(options) > 1

    def loss(theta):
        temperature = math.exp(theta[0])
        scores = logs / temperature
        if with_bias:
            scores = scores + numpy.concatenate([[0.0], theta[1:]])
        scores = scores - scores.max(axis=1, keepdims=True)
        log_z = numpy.log(numpy.exp(scores).sum(axis=1))
        nll = -(scores[numpy.arange(len(gold)), gold] - log_z).mean()
        if with_bias:
            nll = nll + l2 * float((theta[1:] ** 2).sum())
        return nll

    start = numpy.zeros(len(options) if with_bias else 1)
    bounds = [(math.log(T_MIN), math.log(T_MAX))] + \
        [(-10.0, 10.0)] * (len(start) - 1)
    result = minimize(loss, start, method="L-BFGS-B", bounds=bounds)
    theta = result.x if result.success or result.fun <= loss(start) else start
    temperature = math.exp(float(theta[0]))
    if temperature <= T_MIN * 1.001 or temperature >= T_MAX * 0.999:
        return identity("the fitted temperature reached its bound (%.3g); "
                        "the labels do not support a calibration"
                        % temperature)
    bias = {o: 0.0 for o in options}
    if with_bias:
        for o, b in zip(options[1:], theta[1:]):
            bias[o] = round(float(b), 6)
    return {"temperature": round(temperature, 6), "bias": bias,
            "fitted": True, "note": ""}
