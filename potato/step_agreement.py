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
    """Compute Cohen's kappa at step level (pairwise, for 2 annotators)."""
    step_labels = defaultdict(lambda: defaultdict(dict))  # step -> {annotator: label}
    per_instance = {}
    all_annotators = set()

    for instance_id, annotator_data in annotations.items():
        instance_steps = defaultdict(dict)

        for annotator_id, ann_data in annotator_data.items():
            all_annotators.add(annotator_id)
            step_annotations = _extract_step_annotations(ann_data, scheme_name)

            for step_idx, label in step_annotations.items():
                step_labels[step_idx][annotator_id] = label
                instance_steps[step_idx][annotator_id] = label

        if instance_steps:
            per_instance[instance_id] = _kappa_from_step_dict(instance_steps)

    # Per-step kappa
    per_step = {}
    for step_idx in sorted(step_labels.keys()):
        annotator_labels = step_labels[step_idx]
        if len(annotator_labels) >= 2:
            per_step[step_idx] = _kappa_from_annotator_dict(annotator_labels)

    # Overall (flatten all step labels)
    all_labels = defaultdict(dict)
    for step_idx, annotator_dict in step_labels.items():
        for ann_id, label in annotator_dict.items():
            key = f"{step_idx}"
            all_labels[key][ann_id] = label

    overall = _kappa_from_step_dict(all_labels) if all_labels else None

    return {
        "metric": "cohens_kappa",
        "overall": overall,
        "per_step": per_step,
        "per_instance": per_instance,
        "n_instances": len(annotations),
        "n_annotators": len(all_annotators),
        "n_steps": len(step_labels),
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


def _kappa_from_annotator_dict(
    annotator_labels: Dict[str, str]
) -> Optional[float]:
    """Compute Cohen's kappa for two annotators on one item."""
    annotators = list(annotator_labels.keys())
    if len(annotators) < 2:
        return None

    # Take first two annotators
    a1_label = annotator_labels[annotators[0]]
    a2_label = annotator_labels[annotators[1]]

    # Simple agreement for single item
    return 1.0 if a1_label == a2_label else 0.0


def _kappa_from_step_dict(
    step_dict: Dict[Any, Dict[str, str]]
) -> Optional[float]:
    """Compute Cohen's kappa across multiple items (steps)."""
    if not step_dict:
        return None

    # Collect all annotator pairs
    all_annotators = set()
    for annotator_labels in step_dict.values():
        all_annotators.update(annotator_labels.keys())

    if len(all_annotators) < 2:
        return None

    annotators = sorted(all_annotators)[:2]  # Use first two annotators

    # Build label vectors
    labels_a = []
    labels_b = []
    all_labels = set()

    for step_idx, annotator_labels in step_dict.items():
        if annotators[0] in annotator_labels and annotators[1] in annotator_labels:
            la = annotator_labels[annotators[0]]
            lb = annotator_labels[annotators[1]]
            labels_a.append(la)
            labels_b.append(lb)
            all_labels.add(la)
            all_labels.add(lb)

    if len(labels_a) < 2:
        return None

    # Compute Cohen's kappa
    try:
        from sklearn.metrics import cohen_kappa_score
        return float(cohen_kappa_score(labels_a, labels_b))
    except ImportError:
        # Fallback: simple agreement
        agreements = sum(1 for a, b in zip(labels_a, labels_b) if a == b)
        return agreements / len(labels_a) if labels_a else None
