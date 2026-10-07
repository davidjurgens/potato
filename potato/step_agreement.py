"""
Step-Level Inter-Annotator Agreement

Computes agreement metrics (Krippendorff's alpha, Cohen's kappa) at
the individual step level within agent traces. This is useful for
evaluating whether annotators agree on per-step assessments of agent
behavior (e.g., "Was this action correct?").

Usage:
    from potato.step_agreement import compute_step_agreement

    results = compute_step_agreement(annotations, metric="krippendorff_alpha")
"""

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


def compute_step_agreement(
    annotations: Dict[str, Dict[str, Any]],
    scheme_name: str = "",
    metric: str = "krippendorff_alpha",
    level_of_measurement: str = "nominal",
) -> Dict[str, Any]:
    """
    Compute inter-annotator agreement at the step level.

    Args:
        annotations: Dict mapping instance_id -> {annotator_id: {scheme_name: [{step_index: label}]}}
        scheme_name: Name of the annotation scheme to analyze
        metric: "krippendorff_alpha" or "cohens_kappa"
        level_of_measurement: "nominal", "ordinal", or "interval"

    Returns:
        Dict with:
            - overall: float - Overall agreement across all steps
            - per_step: Dict[int, float] - Agreement per step index
            - per_instance: Dict[str, float] - Agreement per instance
            - n_instances: int
            - n_annotators: int
            - n_steps: int
    """
    if metric == "cohens_kappa":
        return _compute_step_cohens_kappa(annotations, scheme_name)
    else:
        return _compute_step_krippendorff_alpha(
            annotations, scheme_name, level_of_measurement
        )


def _compute_step_krippendorff_alpha(
    annotations: Dict[str, Dict[str, Any]],
    scheme_name: str,
    level_of_measurement: str = "nominal",
) -> Dict[str, Any]:
    """Compute Krippendorff's alpha at step level."""
    # Collect step-level annotations across all instances
    # step_index -> [(annotator, instance_id, label)]. The instance is the
    # unit alpha compares across: without it every rating was its own unit,
    # nothing was pairable, and alpha was None even under perfect agreement.
    step_data = defaultdict(list)
    per_instance = {}
    all_annotators = set()

    for instance_id, annotator_data in annotations.items():
        instance_step_data = defaultdict(dict)

        for annotator_id, ann_data in annotator_data.items():
            all_annotators.add(annotator_id)
            step_annotations = _extract_step_annotations(ann_data, scheme_name)

            for step_idx, label in step_annotations.items():
                step_data[step_idx].append((annotator_id, instance_id, label))
                instance_step_data[step_idx][annotator_id] = label

        # Compute per-instance agreement
        if instance_step_data:
            instance_alpha = _alpha_from_step_dict(
                instance_step_data, level_of_measurement
            )
            per_instance[instance_id] = instance_alpha

    # Compute per-step agreement
    per_step = {}
    all_step_pairs = []
    for step_idx in sorted(step_data.keys()):
        rows = step_data[step_idx]
        if len(rows) >= 2:
            per_step[step_idx] = _alpha_from_pairs(rows, level_of_measurement)
            # Overall: each (instance, step) is its own unit.
            all_step_pairs.extend((annotator, f"{instance_id}#{step_idx}", label)
                                  for annotator, instance_id, label in rows)

    # Compute overall
    overall = None
    if all_step_pairs:
        overall = _alpha_from_pairs(all_step_pairs, level_of_measurement)

    return {
        "metric": "krippendorff_alpha",
        "overall": overall,
        "per_step": per_step,
        "per_instance": per_instance,
        "n_instances": len(annotations),
        "n_annotators": len(all_annotators),
        "n_steps": len(step_data),
        "level_of_measurement": level_of_measurement,
    }


def _compute_step_cohens_kappa(
    annotations: Dict[str, Dict[str, Any]],
    scheme_name: str,
) -> Dict[str, Any]:
    """Mean pairwise Cohen's kappa at step level.

    Per step, the units are the instances; per instance, the steps; overall,
    every (instance, step). Labels used to be stored per step only, so each
    instance overwrote the last, and per-step "kappa" was raw agreement
    between whichever two annotators were inserted first.
    """
    by_step = defaultdict(dict)        # step -> {instance: {annotator: label}}
    per_instance = {}
    overall_units = {}                 # (instance, step) -> {annotator: label}
    all_annotators = set()

    for instance_id, annotator_data in annotations.items():
        instance_steps = defaultdict(dict)

        for annotator_id, ann_data in annotator_data.items():
            all_annotators.add(annotator_id)
            step_annotations = _extract_step_annotations(ann_data, scheme_name)

            for step_idx, label in step_annotations.items():
                by_step[step_idx].setdefault(instance_id, {})[annotator_id] = label
                instance_steps[step_idx][annotator_id] = label
                overall_units.setdefault((instance_id, step_idx), {})[annotator_id] = label

        if instance_steps:
            per_instance[instance_id] = _kappa_from_step_dict(instance_steps)

    per_step = {step_idx: _kappa_from_step_dict(by_step[step_idx])
                for step_idx in sorted(by_step)}
    overall = _kappa_from_step_dict(overall_units) if overall_units else None

    return {
        "metric": "cohens_kappa",
        "overall": overall,
        "per_step": per_step,
        "per_instance": per_instance,
        "n_instances": len(annotations),
        "n_annotators": len(all_annotators),
        "n_steps": len(by_step),
    }
def _extract_step_annotations(
    ann_data: Any, scheme_name: str
) -> Dict[int, str]:
    """Extract step-level annotations from an annotator's data."""
    result = {}

    if isinstance(ann_data, dict):
        # Look for step-level annotations in the scheme
        scheme_data = ann_data.get(scheme_name, ann_data)

        if isinstance(scheme_data, list):
            # List of {step_index: label} dicts
            for item in scheme_data:
                if isinstance(item, dict):
                    for k, v in item.items():
                        try:
                            step_idx = int(k)
                            result[step_idx] = str(v)
                        except (ValueError, TypeError):
                            pass
        elif isinstance(scheme_data, dict):
            # Direct {step_index: label} mapping
            for k, v in scheme_data.items():
                try:
                    step_idx = int(k)
                    result[step_idx] = str(v)
                except (ValueError, TypeError):
                    pass

    return result


def _alpha_from_pairs(
    rows: List[Tuple[str, Any, str]], level: str
) -> Optional[float]:
    """Krippendorff's alpha from (annotator, unit, label) rows.

    ``level`` was accepted and then dropped, so ordinal and interval steps
    were scored as nominal.
    """
    if len(rows) < 2:
        return None
    try:
        from potato.server_utils.iaa.alpha import krippendorff_alpha

        if level not in ("nominal", "ordinal", "interval"):
            level = "nominal"
        alpha = krippendorff_alpha(rows, level=level)
        return float(alpha) if not np.isnan(alpha) else None

    except Exception as e:
        logger.warning(f"Failed to compute alpha: {e}")
        return None


def _alpha_from_step_dict(
    step_dict: Dict[Any, Dict[str, str]], level: str = "nominal"
) -> Optional[float]:
    """Alpha within one instance, from {step_idx: {annotator: label}}; each
    step is a unit."""
    rows = []
    for step_idx, annotator_labels in step_dict.items():
        for ann_id, label in annotator_labels.items():
            rows.append((ann_id, step_idx, label))
    return _alpha_from_pairs(rows, level) if rows else None


def _kappa_from_step_dict(
    step_dict: Dict[Any, Dict[str, str]]
) -> Optional[float]:
    """Mean Cohen's kappa over annotator pairs, each pair on the units both
    labelled; ``step_dict`` maps unit -> {annotator: label}. None when no
    pair's kappa is defined (one annotator, under two shared units, or one
    label throughout), never a NaN that would break the JSON response."""
    from potato.server_utils.iaa.nominal import mean_cohen_kappa_over_shared_items

    units = [labels for labels in step_dict.values() if len(labels) >= 2]
    if not units:
        return None
    try:
        value = mean_cohen_kappa_over_shared_items(units)
    except ImportError:
        return None
    return float(value) if value == value else None
