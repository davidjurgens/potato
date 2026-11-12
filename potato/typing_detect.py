"""
Writing-process detection: is this response composed, transcribed, or pasted?

Consumes the :class:`~potato.typing_dynamics.TypingSummary` produced from a
keystroke stream and returns a set of named flags, each carrying the evidence
that fired it.

Design commitments
------------------
**Flags, not a score.** Each flag corresponds to one behavioural claim and
reports the feature values behind it. A researcher can defend, discard or
re-threshold any single flag. Collapsing them into one opaque number would make
that impossible, and the number would be reported as if it meant something it
does not.

**No shipped "trained model".** There is no labeled corpus in this repository,
so shipping pre-fitted coefficients would be fabricating validation. The default
tier is rule-based with visible thresholds. Researchers with labeled data can fit
a real classifier with :func:`fit_supervised`, which is the path that reproduces
the 96-99% accuracies in the literature.

**Calibration over constants.** Conijn, Roeser & van Zaanen (2019,
doi:10.1007/s11145-019-09953-8) show keystroke features vary substantially by
writing task, and Roeser, De Maeyer, Leijten & Van Waes (2021,
doi:10.1007/s11145-021-10203-z) show fixed pause thresholds give biased
estimates because inter-key intervals are a mixture process. So the built-in
defaults are starting points, and :func:`calibrate` refits them against a
project's own annotator population using robust statistics.

**Flags are evidence for human review, never an automatic rejection.** A fast
touch-typist producing a clean draft genuinely resembles transcription. The
false-positive discussion in ``docs/advanced/writing_process_detection.md`` is
part of the feature, not a disclaimer bolted on.

Grounding for the individual rules
----------------------------------
- ``paste_dominant``, ``silent_insertion``: Asher, Gold, Chen & Carvalho (2026),
  AMPPS 9(1), doi:10.1177/25152459261424723 — pasting into the response field,
  and keystroke counts anomalously low relative to response length, are the two
  operative signals for AI-assisted cheating in crowdsourced samples.
- ``transcription_rhythm``: Crossley, Tian, Choi, Holmes & Morris (2024), EDM
  2024, doi:10.5281/zenodo.12729864 — transcription is linear and
  burst-oriented, with fewer insertions/deletions and lower process variance
  than authentic composition. Corroborated by Deane, Zhang, Hao & Li
  (doi:10.1111/jedm.12431) and Zhang, Feng, He, Li & Zhu
  (doi:10.1016/j.asw.2026.101070).
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from potato.typing_dynamics import TypingSummary

logger = logging.getLogger(__name__)


#: Default thresholds. Deliberately conservative: a missed paste costs a
#: researcher one bad row, a false accusation costs an annotator their
#: reputation and the study its ethics standing.
DEFAULT_THRESHOLDS: Dict[str, float] = {
    # Fraction of the final text that arrived via paste.
    "paste_dominant.pasted_fraction": 0.5,
    # Fraction of inserted characters with no originating keystroke.
    "silent_insertion.ratio": 0.3,
    # Dispersion of log inter-key intervals. Human typing is bursty and
    # irregular; sustained metronomic rhythm suggests copying from a source.
    "transcription_rhythm.iki_log_cv": 0.06,
    "transcription_rhythm.revision_ratio": 0.02,
    "transcription_rhythm.pause_2s_per_100_chars": 0.5,
    # Time away from the tab immediately before a large insertion.
    "offscreen_composition.blur_ms": 10000,
    "offscreen_composition.insert_chars": 80,
    # Sustained typing speed. 900 chars/min is roughly 180 wpm, comfortably
    # above competitive typing speeds sustained over a whole response.
    "implausible_speed.chars_per_min": 900,
}

#: A flag needs enough text behind it to mean anything. Below this, short
#: answers ("yes", "n/a") would trip the rhythm rules constantly.
MIN_CHARS_FOR_RHYTHM_FLAGS = 80
MIN_KEYSTROKES_FOR_RHYTHM_FLAGS = 40

#: Flags whose thresholds :func:`calibrate` can refit from project data. The
#: paste and integrity rules are excluded on purpose — "half the text was
#: pasted" means the same thing in every project, and calibrating it against a
#: population where most people paste would define the problem away.
CALIBRATABLE = (
    "transcription_rhythm.iki_log_cv",
    "implausible_speed.chars_per_min",
    "offscreen_composition.blur_ms",
)


@dataclass
class Flag:
    """One fired detection rule and the evidence behind it."""

    name: str
    explanation: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    severity: str = "review"      # "review" or "suspect"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "explanation": self.explanation,
            "evidence": self.evidence,
            "severity": self.severity,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Flag":
        return cls(
            name=data.get("name", ""),
            explanation=data.get("explanation", ""),
            evidence=data.get("evidence", {}),
            severity=data.get("severity", "review"),
        )


@dataclass
class Verdict:
    """The full result of evaluating one typing session."""

    level: str = "ok"                       # "ok" | "review" | "suspect"
    flags: List[Flag] = field(default_factory=list)
    suppressed: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def flag_names(self) -> List[str]:
        return [f.name for f in self.flags]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "flags": [f.to_dict() for f in self.flags],
            "flag_names": self.flag_names,
            "suppressed": self.suppressed,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Verdict":
        return cls(
            level=data.get("level", "ok"),
            flags=[Flag.from_dict(f) for f in data.get("flags", [])],
            suppressed=data.get("suppressed", []),
            notes=data.get("notes", []),
        )


def _threshold(key: str, overrides: Optional[Dict[str, float]]) -> float:
    if overrides and key in overrides:
        return float(overrides[key])
    return DEFAULT_THRESHOLDS[key]


def evaluate(
    summary: TypingSummary,
    *,
    thresholds: Optional[Dict[str, float]] = None,
) -> Verdict:
    """Apply the rule-based flags to one session summary.

    Args:
        summary: The session's computed features.
        thresholds: Overrides for :data:`DEFAULT_THRESHOLDS`, typically the merge
            of a project's config block and its calibration fit.

    Returns:
        A :class:`Verdict`. ``level`` is ``"suspect"`` if any flag has that
        severity, ``"review"`` if any fired at all, otherwise ``"ok"``.
    """
    verdict = Verdict()
    th = thresholds

    def t(key: str) -> float:
        return _threshold(key, th)

    # -- paste_dominant -------------------------------------------------
    # Self-quoting and quoting the passage under annotation are legitimate, so
    # only externally-sourced pastes count toward the fraction.
    external_pastes = sum(
        count for source, count in (summary.paste_sources or {}).items()
        if source not in ("self", "instance_text")
    )
    if summary.pasted_fraction >= t("paste_dominant.pasted_fraction"):
        if external_pastes or not summary.paste_sources:
            verdict.flags.append(Flag(
                name="paste_dominant",
                explanation=(
                    f"{summary.pasted_fraction:.0%} of the final text arrived by "
                    f"paste rather than typing."
                ),
                evidence={
                    "pasted_fraction": round(summary.pasted_fraction, 3),
                    "pasted_chars": summary.pasted_chars,
                    "final_chars": summary.final_chars,
                    "paste_events": summary.paste_events,
                    "largest_paste_chars": summary.largest_paste_chars,
                    "paste_sources": summary.paste_sources,
                    "threshold": t("paste_dominant.pasted_fraction"),
                },
                severity="suspect",
            ))
        else:
            verdict.suppressed.append("paste_dominant")
            verdict.notes.append(
                "Large paste, but its source was the annotator's own text or the "
                "passage under annotation."
            )

    # -- silent_insertion ------------------------------------------------
    # Uses the source-aware ratio, so quoting the passage under annotation or
    # re-arranging your own draft does not read the same as text arriving from
    # somewhere off-screen.
    #
    # Suppressed on soft keyboards and during IME composition, where keydown is
    # unreliable and every insertion would otherwise look silent.
    if summary.external_insert_ratio >= t("silent_insertion.ratio"):
        if summary.virtual_keyboard:
            verdict.suppressed.append("silent_insertion")
            verdict.notes.append(
                "Silent-insertion rule skipped: soft keyboard, where keydown "
                "events are not reliably emitted."
            )
        elif summary.composition_events > 0:
            verdict.suppressed.append("silent_insertion")
            verdict.notes.append(
                "Silent-insertion rule skipped: IME composition in use."
            )
        else:
            verdict.flags.append(Flag(
                name="silent_insertion",
                explanation=(
                    f"{summary.external_insert_ratio:.0%} of inserted characters "
                    f"came from outside the page with no corresponding keystroke "
                    f"({summary.keystrokes} keys for {summary.chars_inserted} chars)."
                ),
                evidence={
                    "external_insert_ratio": round(summary.external_insert_ratio, 3),
                    "external_insert_chars": summary.external_insert_chars,
                    "silent_insert_ratio": round(summary.silent_insert_ratio, 3),
                    "keystrokes": summary.keystrokes,
                    "chars_inserted": summary.chars_inserted,
                    "chars_per_keystroke": round(summary.chars_per_keystroke, 2),
                    "paste_chars_by_source": summary.paste_chars_by_source,
                    "threshold": t("silent_insertion.ratio"),
                },
                severity="suspect",
            ))

    # -- transcription_rhythm --------------------------------------------
    # Conjunctive by design. Any single one of these has an innocent reading; all
    # three together is the copy-typing signature reported by Crossley et al.
    rhythm_eligible = (
        summary.final_chars >= MIN_CHARS_FOR_RHYTHM_FLAGS
        and summary.keystrokes >= MIN_KEYSTROKES_FOR_RHYTHM_FLAGS
        and summary.iki_median_ms > 0
    )
    if rhythm_eligible:
        pause_2s = (summary.pause_counts or {}).get("2000", 0)
        pause_rate = pause_2s * 100.0 / max(1, summary.final_chars)
        regular = summary.iki_log_cv <= t("transcription_rhythm.iki_log_cv")
        unrevised = summary.revision_ratio <= t("transcription_rhythm.revision_ratio")
        unpaused = pause_rate <= t("transcription_rhythm.pause_2s_per_100_chars")

        if regular and unrevised and unpaused:
            verdict.flags.append(Flag(
                name="transcription_rhythm",
                explanation=(
                    "Typing rhythm is unusually regular with almost no pausing or "
                    "revision — the pattern of copying existing text rather than "
                    "composing."
                ),
                evidence={
                    "iki_log_cv": round(summary.iki_log_cv, 4),
                    "iki_median_ms": round(summary.iki_median_ms, 1),
                    "revision_ratio": round(summary.revision_ratio, 4),
                    "pause_2s_per_100_chars": round(pause_rate, 3),
                    "final_chars": summary.final_chars,
                    "thresholds": {
                        "iki_log_cv": t("transcription_rhythm.iki_log_cv"),
                        "revision_ratio": t("transcription_rhythm.revision_ratio"),
                        "pause_2s_per_100_chars":
                            t("transcription_rhythm.pause_2s_per_100_chars"),
                    },
                },
                severity="review",
            ))
    elif summary.final_chars:
        verdict.suppressed.append("transcription_rhythm")

    # -- offscreen_composition -------------------------------------------
    # Sized on externally-sourced characters, not on the raw paste size. Time
    # away only matters if the annotator came back with text from somewhere
    # else; stepping away and then quoting the passage on screen is ordinary
    # behaviour and must not read as suspect.
    if summary.max_blur_before_insert_ms >= t("offscreen_composition.blur_ms"):
        if summary.external_insert_chars >= t("offscreen_composition.insert_chars"):
            verdict.flags.append(Flag(
                name="offscreen_composition",
                explanation=(
                    f"A large insertion from outside the page "
                    f"({summary.external_insert_chars} chars) followed "
                    f"{summary.max_blur_before_insert_ms / 1000:.0f}s away from the page."
                ),
                evidence={
                    "max_blur_before_insert_ms": summary.max_blur_before_insert_ms,
                    "external_insert_chars": summary.external_insert_chars,
                    "largest_paste_chars": summary.largest_paste_chars,
                    "blur_events": summary.blur_events,
                    "blur_total_ms": summary.blur_total_ms,
                    "paste_chars_by_source": summary.paste_chars_by_source,
                    "thresholds": {
                        "blur_ms": t("offscreen_composition.blur_ms"),
                        "insert_chars": t("offscreen_composition.insert_chars"),
                    },
                },
                severity="suspect",
            ))
        elif summary.largest_paste_chars >= t("offscreen_composition.insert_chars"):
            verdict.suppressed.append("offscreen_composition")
            verdict.notes.append(
                "Large insertion after time away, but its source was the "
                "annotator's own text or the passage under annotation."
            )

    # -- implausible_speed -----------------------------------------------
    if summary.active_ms > 5000 and summary.chars_typed > 100:
        cpm = summary.chars_typed / (summary.active_ms / 60000.0)
        if cpm >= t("implausible_speed.chars_per_min"):
            verdict.flags.append(Flag(
                name="implausible_speed",
                explanation=(
                    f"Sustained typing at {cpm:.0f} characters/minute "
                    f"(~{cpm / 5:.0f} wpm) over the whole response."
                ),
                evidence={
                    "chars_per_min": round(cpm, 1),
                    "chars_typed": summary.chars_typed,
                    "active_ms": summary.active_ms,
                    "threshold": t("implausible_speed.chars_per_min"),
                },
                severity="review",
            ))

    # -- synthetic_input --------------------------------------------------
    if summary.untrusted_events > 0:
        verdict.flags.append(Flag(
            name="synthetic_input",
            explanation=(
                f"{summary.untrusted_events} input events were not user-generated "
                f"(isTrusted=false), indicating scripted or automated entry."
            ),
            evidence={
                "untrusted_events": summary.untrusted_events,
                "event_count": summary.event_count,
            },
            severity="suspect",
        ))

    if any(f.severity == "suspect" for f in verdict.flags):
        verdict.level = "suspect"
    elif verdict.flags:
        verdict.level = "review"
    return verdict


# --------------------------------------------------------------------------
# Tier 2 — project calibration
# --------------------------------------------------------------------------


def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _mad(values: Sequence[float], center: float) -> float:
    """Median absolute deviation, scaled to be comparable to a standard deviation."""
    if not values:
        return 0.0
    return 1.4826 * _median([abs(v - center) for v in values])


def _percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    k = (len(ordered) - 1) * pct
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return float(ordered[int(k)])
    return float(ordered[lo] * (hi - k) + ordered[hi] * (k - lo))


#: How far a calibrated threshold may drift from the built-in default, as a
#: multiplicative bound. Without this, a homogeneous population produces a
#: threshold that hugs its own median and flags a fixed slice of honest
#: annotators; with it, calibration can adapt to a genuinely different task but
#: cannot invent a problem where none exists.
MAX_CALIBRATION_DRIFT = 3.0


def calibrate(
    rows: Sequence[Dict[str, Any]],
    *,
    tail_fraction: float = 0.05,
    min_sessions: int = 30,
) -> Dict[str, Any]:
    """Fit detector thresholds to a project's own annotator population.

    Keystroke features vary substantially by writing task (Conijn et al. 2019),
    and fixed thresholds on a mixture-distributed quantity are biased (Roeser et
    al. 2021), so a threshold that works for one study's prompt may be far too
    strict or too lax for another's. Calibration sets each threshold at a tail
    percentile of *this* project's sessions.

    **What this does and does not mean.** A percentile cutoff is a relative
    outlier definition: by construction it flags roughly ``tail_fraction`` of
    sessions even in a population where nobody is doing anything wrong. It tells
    you where to look first. It is not evidence, and a calibrated flag must never
    be read as one. Thresholds are additionally clamped to within
    :data:`MAX_CALIBRATION_DRIFT` of the built-in defaults, so a homogeneous
    population cannot drag the cutoff onto its own median.

    Args:
        rows: Session feature dicts from ``typing_store.feature_matrix()``.
        tail_fraction: Share of the population the fitted threshold should sit
            at the edge of.
        min_sessions: Below this the estimate is too noisy to trust, and the
            defaults are left in force.

    Returns:
        ``{"thresholds": {...}, "n_sessions": int, "detail": {...}}``. An empty
        ``thresholds`` means no fit was made, so callers can distinguish "fitted
        to something close to the defaults" from "did not fit at all".
    """
    usable = [
        r for r in rows
        if r.get("final_chars") and r["final_chars"] >= MIN_CHARS_FOR_RHYTHM_FLAGS
        and not r.get("virtual_keyboard")
    ]
    if len(usable) < min_sessions:
        return {
            "thresholds": {},
            "n_sessions": len(usable),
            "detail": {
                "status": "insufficient_data",
                "required": min_sessions,
                "note": (
                    "Not enough sessions to estimate this project's distribution; "
                    "built-in defaults remain in force."
                ),
            },
        }

    thresholds: Dict[str, float] = {}
    detail: Dict[str, Any] = {
        "status": "fitted",
        "tail_fraction": tail_fraction,
        "max_drift": MAX_CALIBRATION_DRIFT,
        "caveat": (
            "Percentile thresholds flag a fixed share of sessions by "
            "construction, including in an entirely honest population. Treat a "
            "calibrated flag as a place to look, not as a finding."
        ),
    }

    def _record(key: str, raw: float, stats: Dict[str, Any]) -> None:
        default = DEFAULT_THRESHOLDS[key]
        lo, hi = default / MAX_CALIBRATION_DRIFT, default * MAX_CALIBRATION_DRIFT
        clamped = min(max(raw, lo), hi)
        thresholds[key] = clamped
        stats.update({
            "raw": raw, "fitted": clamped, "default": default,
            "clamped": clamped != raw,
        })
        detail[key] = stats

    # Rhythm regularity: the suspicious tail is the unusually REGULAR one, so we
    # take the low percentile.
    cvs = [float(r["iki_log_cv"]) for r in usable if r.get("iki_log_cv")]
    if len(cvs) >= min_sessions:
        _record(
            "transcription_rhythm.iki_log_cv",
            max(0.005, _percentile(cvs, tail_fraction)),
            {"median": _median(cvs), "mad": _mad(cvs, _median(cvs)), "n": len(cvs)},
        )

    # Typing speed: the suspicious tail is the fast one, so we take the high
    # percentile.
    speeds = []
    for r in usable:
        active_ms = r.get("active_ms") or 0
        chars = r.get("chars_typed") or 0
        if active_ms > 5000 and chars > 100:
            speeds.append(chars / (active_ms / 60000.0))
    if len(speeds) >= min_sessions:
        _record(
            "implausible_speed.chars_per_min",
            _percentile(speeds, 1.0 - tail_fraction),
            {"median": _median(speeds), "mad": _mad(speeds, _median(speeds)),
             "n": len(speeds)},
        )

    return {"thresholds": thresholds, "n_sessions": len(usable), "detail": detail}


# --------------------------------------------------------------------------
# Tier 3 — supervised scorer (researcher-trained)
# --------------------------------------------------------------------------

#: Feature columns fed to a supervised model, in a fixed order so a saved model
#: stays interpretable.
SUPERVISED_FEATURES = [
    "keystrokes", "final_chars", "chars_typed", "chars_deleted", "active_ms",
    "iki_median_ms", "iki_log_cv", "pause_2s", "pause_10s", "pause_total_ms",
    "bursts", "burst_mean_chars", "revision_ratio", "paste_events",
    "pasted_chars", "pasted_fraction", "silent_insert_ratio", "blur_total_ms",
    "max_blur_before_insert_ms",
]


def _check_sklearn():
    """Import scikit-learn lazily, mirroring the pyarrow guard in the Parquet
    exporter. Keeping ML out of the boot path is a hard rule in this codebase."""
    import sklearn  # noqa: F401
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_score
    from sklearn.preprocessing import StandardScaler
    return RandomForestClassifier, LogisticRegression, cross_val_score, StandardScaler


def fit_supervised(
    rows: Sequence[Dict[str, Any]],
    labels: Sequence[int],
    *,
    model: str = "random_forest",
    cv_folds: int = 5,
) -> Dict[str, Any]:
    """Train a classifier on the researcher's own labeled sessions.

    This is the path that reproduces the published accuracies (Crossley et al.
    report 99% with a random forest on authentic vs. transcribed essays) — but
    only because the researcher supplies real labels. Nothing pre-fitted ships
    with Potato.

    Args:
        rows: Session feature dicts.
        labels: 1 for non-composed (transcribed/pasted), 0 for composed.
        model: ``"random_forest"`` or ``"logistic"``.
        cv_folds: Cross-validation folds for the reported accuracy.

    Returns:
        Fitted model, feature importances and cross-validated accuracy.

    Raises:
        ImportError: scikit-learn is not installed.
        ValueError: fewer than two classes present.
    """
    RandomForest, Logistic, cross_val_score, StandardScaler = _check_sklearn()

    if len(set(labels)) < 2:
        raise ValueError(
            "Need both composed (0) and non-composed (1) examples to fit a model; "
            f"got only class {set(labels)}."
        )

    X = [[float(r.get(f) or 0) for f in SUPERVISED_FEATURES] for r in rows]
    y = list(labels)

    if model == "logistic":
        scaler = StandardScaler().fit(X)
        clf = Logistic(max_iter=1000, class_weight="balanced")
        Xf = scaler.transform(X)
    else:
        scaler = None
        clf = RandomForest(n_estimators=300, class_weight="balanced", random_state=0)
        Xf = X

    scores = cross_val_score(clf, Xf, y, cv=min(cv_folds, len(set(y)) * 2))
    clf.fit(Xf, y)

    if hasattr(clf, "feature_importances_"):
        importances = dict(zip(SUPERVISED_FEATURES,
                               [float(v) for v in clf.feature_importances_]))
    else:
        importances = dict(zip(SUPERVISED_FEATURES,
                               [float(v) for v in clf.coef_[0]]))

    return {
        "model": clf,
        "scaler": scaler,
        "model_type": model,
        "features": list(SUPERVISED_FEATURES),
        "cv_accuracy_mean": float(scores.mean()),
        "cv_accuracy_std": float(scores.std()),
        "n_samples": len(y),
        "n_positive": int(sum(y)),
        "feature_importances": dict(
            sorted(importances.items(), key=lambda kv: -abs(kv[1]))
        ),
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _load_project(config_path: str):
    """Resolve (task_dir, project_name) from a Potato config file."""
    import yaml
    with open(config_path) as f:
        cfg = yaml.safe_load(f) or {}
    import os
    task_dir = cfg.get("task_dir") or os.path.dirname(os.path.abspath(config_path))
    if not os.path.isabs(task_dir):
        task_dir = os.path.join(os.path.dirname(os.path.abspath(config_path)), task_dir)
    project = cfg.get("annotation_task_name") or os.path.basename(
        os.path.normpath(task_dir))
    return os.path.abspath(task_dir), project


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m potato.typing_detect",
        description="Calibrate or inspect writing-process detection thresholds.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_cal = sub.add_parser(
        "calibrate",
        help="Fit detector thresholds to this project's annotator population.")
    p_cal.add_argument("config", help="Path to the Potato config.yaml")
    p_cal.add_argument("--tail-fraction", type=float, default=0.05,
                       help="Share of sessions the threshold sits at the edge of "
                            "(default 0.05)")
    p_cal.add_argument("--min-sessions", type=int, default=30,
                       help="Minimum sessions required to fit (default 30)")
    p_cal.add_argument("--dry-run", action="store_true",
                       help="Print the fit without saving it")

    p_rep = sub.add_parser("report", help="Summarize flags across the project.")
    p_rep.add_argument("config", help="Path to the Potato config.yaml")

    args = parser.parse_args(argv)
    from potato import typing_store

    task_dir, project = _load_project(args.config)

    if args.command == "calibrate":
        rows = typing_store.feature_matrix(task_dir, project)
        result = calibrate(rows, tail_fraction=args.tail_fraction,
                           min_sessions=args.min_sessions)
        print(json.dumps(result["detail"], indent=2))
        if not result["thresholds"]:
            print(f"\nNo thresholds fitted ({result['n_sessions']} usable sessions).")
            return 1
        print(f"\nFitted thresholds from {result['n_sessions']} sessions:")
        for name, value in sorted(result["thresholds"].items()):
            print(f"  {name}: {value:.4f}  (default {DEFAULT_THRESHOLDS[name]})")
        if args.dry_run:
            print("\n--dry-run: not saved.")
        else:
            typing_store.save_calibration(
                task_dir, project, result["thresholds"],
                result["n_sessions"], result["detail"])
            print("\nSaved to typing_calibration.")
        return 0

    if args.command == "report":
        rows = typing_store.sessions_for_user  # noqa: F841  (kept for symmetry)
        agg = typing_store.aggregate_by_user(task_dir, project)
        if not agg:
            print("No typing sessions recorded for this project.")
            return 1
        header = (f"{'user':<20}{'sess':>6}{'chars':>8}{'paste%':>8}"
                  f"{'silent%':>9}{'log_cv':>8}{'pause/100':>11}")
        print(header)
        print("-" * len(header))
        for a in agg:
            print(f"{a['user_id'][:19]:<20}{a['sessions']:>6}{a['chars'] or 0:>8}"
                  f"{(a['pasted_char_fraction'] or 0) * 100:>7.1f}%"
                  f"{(a['mean_silent_insert_ratio'] or 0) * 100:>8.1f}%"
                  f"{a['iki_log_cv'] or 0:>8.3f}"
                  f"{a['pause_2s_per_100_chars'] or 0:>11.2f}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
