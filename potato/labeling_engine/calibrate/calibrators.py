"""
Mapping a source's raw confidence to the probability its label is right.

Fitted per source version on the dev split of human calibration labels. The
contracts never depend on it for validity: thresholds are chosen and tested on
raw confidence, and a monotone map does not change which items a threshold
accepts. Calibration is for the reliability diagram, for ranking items across
sources, and for telling a researcher what "0.9" from this model means.

The method follows sample size, using the thresholds from
``potato/training/calibration.py`` (isotonic overfits small samples badly,
Platt scaling has two parameters), and is kept only if it improves the Brier
score under cross-validation. Otherwise the identity map is used and the
reason is recorded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from potato.training.calibration import (
    MIN_SAMPLES_FOR_CALIBRATION, MIN_SAMPLES_FOR_ISOTONIC)


@dataclass
class Calibrator:
    method: str = "identity"            # identity | platt | isotonic
    params: Dict[str, Any] = field(default_factory=dict)
    n: int = 0
    reason: str = ""

    def transform(self, scores: Sequence[float]) -> np.ndarray:
        s = np.clip(np.asarray(scores, dtype=float), 0.0, 1.0)
        if self.method == "platt":
            a, b = self.params["a"], self.params["b"]
            return 1.0 / (1.0 + np.exp(-(a * _logit(s) + b)))
        if self.method == "isotonic":
            return np.interp(s, self.params["x"], self.params["y"])
        return s

    def to_dict(self) -> Dict[str, Any]:
        return {"method": self.method, "params": self.params, "n": self.n,
                "reason": self.reason}

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "Calibrator":
        d = d or {}
        return cls(method=d.get("method", "identity"), params=d.get("params") or {},
                   n=int(d.get("n", 0)), reason=d.get("reason", ""))


def _logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def _fit_platt(s, y) -> Dict[str, float]:
    from sklearn.linear_model import LogisticRegression
    if len(set(y.tolist())) < 2:
        raise ValueError("one outcome only")
    lr = LogisticRegression(C=1e6, max_iter=1000)
    lr.fit(_logit(s).reshape(-1, 1), y)
    return {"a": float(lr.coef_[0][0]), "b": float(lr.intercept_[0])}


def _fit_isotonic(s, y) -> Dict[str, List[float]]:
    from sklearn.isotonic import IsotonicRegression
    iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    iso.fit(s, y)
    xs = np.unique(s)
    return {"x": xs.tolist(), "y": iso.predict(xs).tolist()}


def _cv_brier(method: str, s, y, folds: int = 2, seed: int = 0) -> float:
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(s))
    parts = np.array_split(order, folds)
    errs = []
    for k in range(folds):
        test = parts[k]
        train = np.concatenate([parts[j] for j in range(folds) if j != k])
        if method == "identity":
            pred = s[test]
        else:
            fit = _fit_platt if method == "platt" else _fit_isotonic
            cal = Calibrator(method, fit(s[train], y[train]))
            pred = cal.transform(s[test])
        errs.append(np.mean((pred - y[test]) ** 2))
    return float(np.mean(errs))


def fit_calibrator(scores: Sequence[float], correct: Sequence[bool]) -> Calibrator:
    s = np.clip(np.asarray(scores, dtype=float), 0.0, 1.0)
    y = np.asarray(correct, dtype=float)
    n = int(s.size)
    if n < MIN_SAMPLES_FOR_CALIBRATION:
        return Calibrator(n=n, reason=f"{n} dev labels; calibration needs "
                                      f"{MIN_SAMPLES_FOR_CALIBRATION}")
    if len(set(y.tolist())) < 2:
        return Calibrator(n=n, reason="every dev label agrees with the model, or none "
                                      "does; there is nothing to fit")
    method = "isotonic" if n >= MIN_SAMPLES_FOR_ISOTONIC else "platt"
    try:
        base = _cv_brier("identity", s, y)
        cand = _cv_brier(method, s, y)
    except ValueError as e:
        return Calibrator(n=n, reason=f"{method} could not be fitted: {e}")
    if cand >= base:
        return Calibrator(n=n, reason=f"{method} did not improve the cross-validated "
                                      f"Brier score ({cand:.4f} vs {base:.4f})")
    fit = _fit_platt if method == "platt" else _fit_isotonic
    return Calibrator(method=method, params=fit(s, y), n=n,
                      reason=f"cross-validated Brier {base:.4f} -> {cand:.4f}")
