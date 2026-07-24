"""Psychometrics manager: live IRT refits, adaptive routing, and reporting.

The manager owns the current fitted :class:`~potato.psychometrics.irt.IRTModel`
snapshot for the configured scheme. It re-collects observations from the
user state manager on demand and refits lazily — whenever ``refit_interval``
new labels have arrived (or on force, for the dashboard). Fits are
deterministic and take milliseconds at annotation-study scale, so there is
no background thread; readers always get a consistent snapshot under a lock.

Adaptive routing (``assignment_strategy: psychometric``) calls
:meth:`PsychometricsManager.rank_items` from the item assignment loop: items
are ranked by exact one-step expected information gain for the requesting
annotator, with items already past the confidence threshold (and the
min-annotator floor) deprioritized so no further budget is spent on them.
"""

import logging
import threading
from typing import Any, Dict, Hashable, List, Optional, Tuple

from potato.psychometrics.config import (
    PsychometricsConfig,
    parse_psychometrics_config,
)
from potato.psychometrics.irt import IRTModel

logger = logging.getLogger(__name__)

# Label values that mean "not selected" in stored annotations.
_FALSY_VALUES = {None, "", 0, False, "false", "False", "unchecked", "0"}


class PsychometricsManager:
    """Live psychometric model over the task's annotations."""

    def __init__(self, app_config: Dict[str, Any]):
        self.app_config = app_config
        self.ps_config: PsychometricsConfig = parse_psychometrics_config(app_config)
        self._lock = threading.Lock()
        self._model: Optional[IRTModel] = None
        self._fitted_obs_count: int = -1

    # ------------------------------------------------------------------
    # Observations
    # ------------------------------------------------------------------

    def collect_observations(self) -> List[Tuple[str, str, str]]:
        """Flatten stored annotations into (item_id, user_id, label) triples.

        Only the configured scheme is read, and only single-selection
        responses count (an item/user pair with zero or multiple selected
        labels for the scheme is skipped — the model covers categorical
        single-choice schemes).
        """
        schema = self.ps_config.schema
        if not schema:
            return []
        from potato.user_state_management import get_user_state_manager

        observations: List[Tuple[str, str, str]] = []
        for user_state in get_user_state_manager().get_all_users():
            user_id = getattr(user_state, "user_id", None)
            if not user_id:
                continue
            for instance_id, annotations in user_state.get_all_annotations().items():
                names = [
                    label_obj.get_name()
                    for label_obj, value in (annotations.get("labels") or {}).items()
                    if label_obj.get_schema() == schema
                    and not (isinstance(value, Hashable) and value in _FALSY_VALUES)
                ]
                if len(names) == 1:
                    observations.append((instance_id, user_id, names[0]))
        return observations

    # ------------------------------------------------------------------
    # Model lifecycle
    # ------------------------------------------------------------------

    def get_model(self, force: bool = False) -> IRTModel:
        """Current model snapshot, refit if stale (or ``force``)."""
        with self._lock:
            observations = self.collect_observations()
            n = len(observations)
            stale = (
                force
                or self._model is None
                or abs(n - self._fitted_obs_count) >= self.ps_config.refit_interval
                or (not self._model.fitted and n != self._fitted_obs_count)
            )
            if stale:
                model = IRTModel(
                    discrimination_flag_threshold=(
                        self.ps_config.discrimination_flag_threshold
                    )
                )
                model.fit(observations)
                self._model = model
                self._fitted_obs_count = n
            return self._model

    # ------------------------------------------------------------------
    # Adaptive routing
    # ------------------------------------------------------------------

    def rank_items(
        self, user_id: str, candidate_ids: List[str]
    ) -> Optional[List[str]]:
        """Rank candidate items for an annotator by expected information gain.

        Returns None during cold start (model unfitted or fewer than
        ``min_observations`` labels) so the caller falls back to its base
        strategy — early random assignment builds the annotator overlap the
        model needs. Items already past the confidence threshold with enough
        annotators are EXCLUDED from the returned list: that is the early
        stop, and the source of the saved-judgment budget. Ties break
        deterministically by item id.
        """
        model = self.get_model()
        if not model.fitted or model.num_observations < self.ps_config.min_observations:
            return None

        threshold = self.ps_config.confidence_threshold
        min_ann = self.ps_config.min_annotators_per_item
        scored = []
        for iid in candidate_ids:
            report = model.item_report(iid)
            if (
                report is not None
                and report.prob >= threshold
                and report.n_annotators >= min_ann
            ):
                continue  # resolved: stop spending judgments on it
            gain = model.expected_information_gain(iid, user_id)
            scored.append((gain, iid))
        scored.sort(key=lambda t: (-t[0], repr(t[1])))
        return [iid for (_, iid) in scored]

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def _target_annotators_per_item(self) -> Optional[int]:
        """Configured annotators-per-item cap (None when unlimited/unset)."""
        raw = self.app_config.get(
            "num_annotators_per_item", self.app_config.get("max_annotations_per_item")
        )
        if isinstance(raw, dict):
            raw = raw.get("default")
        try:
            cap = int(raw)
        except (TypeError, ValueError):
            return None
        return cap if cap > 0 else None

    def _raw_alpha(self, observations: List[Tuple[str, str, str]]) -> Optional[float]:
        """Krippendorff's alpha over the raw labels (context stat)."""
        if len(observations) < 4:
            return None
        try:
            import pandas as pd
            from simpledorff import calculate_krippendorffs_alpha_for_df

            df = pd.DataFrame(
                observations, columns=["instance_id", "annotator", "label"]
            )
            return float(
                calculate_krippendorffs_alpha_for_df(
                    df,
                    experiment_col="instance_id",
                    annotator_col="annotator",
                    class_col="label",
                )
            )
        except Exception:  # alpha is contextual; never break stats over it
            return None

    def get_stats(self) -> Dict[str, Any]:
        """Dashboard payload: abilities, item estimates, flags, savings."""
        observations = self.collect_observations()
        model = self.get_model(force=True)
        adaptive = str(self.app_config.get("assignment_strategy", "")) == "psychometric"
        payload: Dict[str, Any] = {
            "schema": self.ps_config.schema,
            "adaptive_routing": adaptive,
            "fitted": model.fitted,
            "degenerate_reason": model.degenerate_reason,
            "n_observations": len(observations),
            "n_items": model.num_items,
            "n_annotators": model.num_annotators,
            "min_observations": self.ps_config.min_observations,
            "confidence_threshold": self.ps_config.confidence_threshold,
            "class_labels": [str(c) for c in model.class_labels],
            "em_iterations": model.em_iterations,
            "annotators": [],
            "items": [],
            "flagged_items": [],
            "summary": {},
        }
        if not model.fitted:
            return payload

        annotators = [
            {
                "annotator": str(ann_id),
                "theta": round(est.theta, 3),
                "se": round(est.se, 3),
                "n_labels": est.n_labels,
            }
            for ann_id, est in model.abilities().items()
        ]
        annotators.sort(key=lambda a: -a["theta"])
        payload["annotators"] = annotators

        threshold = self.ps_config.confidence_threshold
        min_ann = self.ps_config.min_annotators_per_item
        cap = self._target_annotators_per_item()
        items = []
        saved_judgments = 0
        confident = 0
        for item_id, est in model.items().items():
            resolved = est.prob >= threshold and est.n_annotators >= min_ann
            if resolved:
                confident += 1
                if cap is not None:
                    saved_judgments += max(0, cap - est.n_annotators)
            items.append(
                {
                    "instance_id": str(item_id),
                    "map_label": str(est.map_label),
                    "prob": round(est.prob, 4),
                    "prob_lo": round(est.prob_lo, 4),
                    "prob_hi": round(est.prob_hi, 4),
                    "entropy": round(est.entropy, 3),
                    "difficulty": round(est.difficulty, 3),
                    "discrimination": (
                        round(est.discrimination, 3)
                        if est.discrimination is not None
                        else None
                    ),
                    "n_annotators": est.n_annotators,
                    "resolved": resolved,
                    "flagged": est.flagged,
                }
            )
        items.sort(key=lambda r: -r["entropy"])
        payload["items"] = items
        payload["flagged_items"] = [r for r in items if r["flagged"]]

        mean_conf = sum(r["prob"] for r in items) / len(items) if items else 0.0
        summary: Dict[str, Any] = {
            "mean_confidence": round(mean_conf, 4),
            "resolved_items": confident,
            "resolved_pct": round(100.0 * confident / len(items), 1) if items else 0.0,
            "raw_alpha": self._raw_alpha(observations),
            "target_annotators_per_item": cap,
            "saved_judgments": saved_judgments if cap is not None else None,
            "cost_per_judgment": self.ps_config.cost_per_judgment,
        }
        if cap is not None and self.ps_config.cost_per_judgment is not None:
            summary["saved_cost"] = round(
                saved_judgments * self.ps_config.cost_per_judgment, 2
            )
        payload["summary"] = summary
        return payload

    def export_records(self) -> Dict[str, Any]:
        """Full enriched export: labels with error bars + annotator abilities."""
        model = self.get_model(force=True)
        record: Dict[str, Any] = {
            "generated_by": "potato.psychometrics",
            "model": "multiclass GLAD (Whitehill et al. 2009), EM, MAP labels",
            "schema": self.ps_config.schema,
            "fitted": model.fitted,
            "class_labels": [str(c) for c in model.class_labels],
            "items": [],
            "annotators": [],
        }
        if not model.fitted:
            record["degenerate_reason"] = model.degenerate_reason
            return record
        for item_id, est in model.items().items():
            record["items"].append(
                {
                    "instance_id": str(item_id),
                    "label": str(est.map_label),
                    "prob": est.prob,
                    "prob_lo": est.prob_lo,
                    "prob_hi": est.prob_hi,
                    "posterior": {str(k): v for k, v in est.posterior.items()},
                    "entropy_bits": est.entropy,
                    "difficulty": est.difficulty,
                    "discrimination": est.discrimination,
                    "n_annotators": est.n_annotators,
                    "flagged_negative_discrimination": est.flagged,
                }
            )
        for ann_id, est in model.abilities().items():
            record["annotators"].append(
                {
                    "annotator": str(ann_id),
                    "ability": est.theta,
                    "ability_se": est.se,
                    "n_labels": est.n_labels,
                }
            )
        return record


_manager: Optional[PsychometricsManager] = None


def init_psychometrics_manager(app_config: Dict[str, Any]) -> None:
    """Create the module singleton when ``psychometrics.enabled`` is set."""
    global _manager
    if not (app_config.get("psychometrics") or {}).get("enabled", False):
        _manager = None
        return
    _manager = PsychometricsManager(app_config)
    logger.info(
        "Psychometrics initialized (schema=%s)", _manager.ps_config.schema
    )


def get_psychometrics_manager() -> Optional[PsychometricsManager]:
    return _manager


def clear_psychometrics_manager() -> None:
    global _manager
    _manager = None
