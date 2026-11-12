"""Probability calibration that checks whether it helped.

Calibration is supposed to make a classifier's confidences mean what they say,
so that "0.9" is right about nine times in ten. Every downstream consumer here
depends on that: uncertainty sampling ranks by it, the review queue orders by
it, and the write-back layer has a confidence floor.

The trap is that calibrating a small training set makes confidences *worse*,
and does it silently. Fitting ``CalibratedClassifierCV(cv=3, method="isotonic")``
on fourteen examples of trivially separable text collapses every prediction to
exactly 0.5 -- the model still loads, still predicts, still reports a
probability, and has learned nothing. Sigmoid on the same data inverts the
labels outright. Isotonic regression wants on the order of a thousand samples;
below that it is fitting a step function to noise.

That matters most exactly where it is least visible. Active learning trains as
soon as ten annotations exist, which is far inside the range where isotonic
destroys the model, and a model that returns the same confidence for every item
ranks every item equally -- so the queue ordering silently becomes arbitrary
while the logs report a successful fit.

So this module does two things: it picks a method by sample size, and then it
**checks the result and backs out if calibration made the model worse**. The
thresholds are judgement calls; the check is not.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any, Callable, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

__all__ = ["CalibrationOutcome", "calibrate_if_it_helps",
           "MIN_SAMPLES_FOR_CALIBRATION", "MIN_SAMPLES_FOR_ISOTONIC"]

#: Below this many training samples, do not calibrate at all. A classifier's
#: raw probabilities are poorly calibrated at this size, but they are at least
#: monotonic in the evidence, which is all that ranking needs.
MIN_SAMPLES_FOR_CALIBRATION = 50

#: Isotonic regression is non-parametric and overfits hard on small samples.
#: Below this, use Platt scaling (sigmoid), which has two parameters.
MIN_SAMPLES_FOR_ISOTONIC = 1000

#: How much training accuracy calibration is allowed to cost before it is
#: judged to have failed. Calibration should barely move it; a large drop means
#: the folds were too small to learn anything.
MAX_ACCURACY_LOSS = 0.05


class CalibrationOutcome:
    """What happened, so it can be logged and shown rather than guessed at."""

    def __init__(self, model: Any, applied: bool, method: str = "",
                 reason: str = "", accuracy_before: Optional[float] = None,
                 accuracy_after: Optional[float] = None):
        self.model = model
        self.applied = applied
        self.method = method
        self.reason = reason
        self.accuracy_before = accuracy_before
        self.accuracy_after = accuracy_after

    def to_dict(self) -> dict:
        return {"applied": self.applied, "method": self.method,
                "reason": self.reason,
                "accuracy_before": self.accuracy_before,
                "accuracy_after": self.accuracy_after}

    def __repr__(self) -> str:
        if self.applied:
            return "<calibrated method=%s>" % self.method
        return "<uncalibrated: %s>" % self.reason


def _method_for(n_samples: int) -> str:
    return "isotonic" if n_samples >= MIN_SAMPLES_FOR_ISOTONIC else "sigmoid"


def calibrate_if_it_helps(
    pipeline: Any,
    features: Sequence[Any],
    targets: Sequence[Any],
    *,
    enabled: bool = True,
    min_samples: int = MIN_SAMPLES_FOR_CALIBRATION,
    log: Optional[Callable[[str, str], None]] = None,
) -> CalibrationOutcome:
    """Calibrate *pipeline*, keeping the result only if it did not hurt.

    Args:
        pipeline: an already-fitted estimator with ``predict``.
        features, targets: the training data it was fitted on.
        enabled: when False, returns the model untouched with a reason.
        min_samples: refuse to calibrate below this many samples.
        log: ``(level, message)`` sink, so callers can route this to a
            progress reporter or a logger.

    Returns:
        A :class:`CalibrationOutcome` whose ``.model`` is the one to keep.

    The accuracy check is on the training set, which is not a real estimate of
    calibration quality -- properly judging that needs a held-out set and a
    Brier score. It is here to catch collapse and inversion, which are total
    failures and show up plainly on any data at all.
    """
    def _log(level: str, message: str) -> None:
        if log is not None:
            log(level, message)
        else:
            getattr(logger, level, logger.info)(message)

    if not enabled:
        return CalibrationOutcome(pipeline, False, reason="disabled")

    if not hasattr(pipeline, "predict_proba"):
        return CalibrationOutcome(
            pipeline, False,
            reason="the estimator does not produce probabilities")

    n_samples = len(features)
    if n_samples < min_samples:
        reason = ("only %d training samples; calibration needs at least %d "
                  "to do more good than harm" % (n_samples, min_samples))
        _log("info", "Skipping calibration: %s" % reason)
        return CalibrationOutcome(pipeline, False, reason=reason)

    counts = Counter(str(t) for t in targets)
    smallest_class = min(counts.values()) if counts else 0
    folds = min(5, smallest_class)
    if folds < 2:
        reason = ("the smallest class has %d example(s), which cannot be "
                  "cross-validated" % smallest_class)
        _log("info", "Skipping calibration: %s" % reason)
        return CalibrationOutcome(pipeline, False, reason=reason)

    try:
        from sklearn.base import clone
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.metrics import accuracy_score

        before = float(accuracy_score(targets, pipeline.predict(features)))
        method = _method_for(n_samples)

        calibrated = CalibratedClassifierCV(
            clone(pipeline), cv=folds, method=method)
        calibrated.fit(features, targets)
        after = float(accuracy_score(targets, calibrated.predict(features)))

        if after < before - MAX_ACCURACY_LOSS:
            reason = ("%s calibration dropped training accuracy from %.2f to "
                      "%.2f, so the uncalibrated model was kept"
                      % (method, before, after))
            _log("warning", reason)
            return CalibrationOutcome(pipeline, False, method=method,
                                      reason=reason, accuracy_before=before,
                                      accuracy_after=after)

        if _is_degenerate(calibrated, features):
            reason = ("%s calibration returned the same probability for every "
                      "input, which would make confidence ranking arbitrary; "
                      "the uncalibrated model was kept" % method)
            _log("warning", reason)
            return CalibrationOutcome(pipeline, False, method=method,
                                      reason=reason, accuracy_before=before,
                                      accuracy_after=after)

        _log("info", "Applied %s calibration over %d folds" % (method, folds))
        return CalibrationOutcome(calibrated, True, method=method,
                                  accuracy_before=before, accuracy_after=after)

    except Exception as exc:  # noqa: BLE001 - never fail a fit over this
        reason = "calibration raised %s; the uncalibrated model was kept" % exc
        _log("warning", reason)
        return CalibrationOutcome(pipeline, False, reason=reason)


def _is_degenerate(model: Any, features: Sequence[Any],
                   sample: int = 64) -> bool:
    """Whether the model gives every input the same confidence.

    The specific shape of the isotonic collapse: predictions still come out,
    they are just all identical, so nothing that ranks by confidence can order
    anything. Cheap to check and unambiguous when it fires.
    """
    try:
        subset = list(features)[:sample]
        if len(subset) < 2:
            return False
        probabilities = model.predict_proba(subset)
        maxima = {round(float(max(row)), 6) for row in probabilities}
        return len(maxima) == 1
    except Exception:
        return False
