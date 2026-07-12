"""Agreement and coverage metrics for Paper Mode.

Krippendorff's alpha uses ``simpledorff`` (the same implementation as the admin
dashboard). Pairwise Cohen's kappa is implemented directly over label records so
it works without a Flask context. Multiselect schemes get per-record alpha over
(instance, label) selection units; radio/likert get standard per-instance alpha.
"""

import logging
import statistics
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

from potato.paper.collect import LabelRecord, ProjectData

logger = logging.getLogger(__name__)


def _alpha_nominal(units: Dict[Any, List[str]]) -> Optional[float]:
    """Krippendorff's alpha (nominal) over unit -> list of values."""
    rows = [
        {"unit": unit, "annotator": f"{unit}#{i}", "value": value}
        for unit, values in units.items()
        for i, value in enumerate(values)
        if len(values) >= 2
    ]
    if not rows or len({r["value"] for r in rows}) < 2:
        return None
    try:
        import pandas as pd
        import simpledorff
        from simpledorff.metrics import nominal_metric

        return float(simpledorff.calculate_krippendorffs_alpha_for_df(
            pd.DataFrame(rows),
            experiment_col="unit",
            annotator_col="annotator",
            class_col="value",
            metric_fn=nominal_metric,
        ))
    except Exception:
        logger.exception("Krippendorff's alpha computation failed")
        return None


def cohen_kappa(pairs: List[Tuple[str, str]]) -> Optional[float]:
    """Cohen's kappa for a list of (rater_a_value, rater_b_value) pairs."""
    n = len(pairs)
    if n == 0:
        return None
    observed = sum(1 for a, b in pairs if a == b) / n
    counts_a = Counter(a for a, _ in pairs)
    counts_b = Counter(b for _, b in pairs)
    expected = sum(
        (counts_a[c] / n) * (counts_b.get(c, 0) / n) for c in counts_a
    )
    if expected >= 1.0:
        return 1.0 if observed >= 1.0 else 0.0
    return (observed - expected) / (1 - expected)


def _units_for_scheme(records: List[LabelRecord], scheme: Dict[str, Any]
                      ) -> Dict[Any, List[str]]:
    """unit -> values. Radio/likert: unit = instance, value = chosen label.
    Multiselect: unit = (instance, label), value = 'selected'/'not' per
    annotator who annotated that instance at all."""
    name = scheme.get("name")
    stype = scheme.get("annotation_type")
    scheme_records = [r for r in records if r.schema == name]
    if stype != "multiselect":
        units: Dict[Any, List[str]] = defaultdict(list)
        # Latest value per (annotator, instance) — duplicates shouldn't occur,
        # but be safe.
        latest: Dict[Tuple[str, str], str] = {}
        for r in scheme_records:
            latest[(r.annotator, r.instance_id)] = r.value
        for (annotator, instance_id), value in latest.items():
            units[instance_id].append(value)
        return dict(units)

    # Multiselect: which annotators touched each instance
    annotators_by_instance: Dict[str, set] = defaultdict(set)
    selected: Dict[Tuple[str, str], set] = defaultdict(set)
    for r in scheme_records:
        annotators_by_instance[r.instance_id].add(r.annotator)
        selected[(r.instance_id, r.annotator)].add(r.value)
    labels = []
    for label in scheme.get("labels", []) or []:
        labels.append(label.get("name") if isinstance(label, dict) else str(label))
    units = defaultdict(list)
    for instance_id, annotators in annotators_by_instance.items():
        for label in labels:
            for annotator in annotators:
                value = "selected" if label in selected[(instance_id, annotator)] else "not"
                units[(instance_id, label)].append(value)
    return dict(units)


def _pairwise_kappas(records: List[LabelRecord], scheme_name: str
                     ) -> List[Tuple[str, str, float, int]]:
    """(annotator_a, annotator_b, kappa, shared_items) for every pair with overlap."""
    by_annotator: Dict[str, Dict[str, str]] = defaultdict(dict)
    for r in records:
        if r.schema == scheme_name:
            by_annotator[r.annotator][r.instance_id] = r.value
    names = sorted(by_annotator)
    results = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            shared = sorted(set(by_annotator[a]) & set(by_annotator[b]))
            if len(shared) < 2:
                continue
            pairs = [(by_annotator[a][iid], by_annotator[b][iid]) for iid in shared]
            kappa = cohen_kappa(pairs)
            if kappa is not None:
                results.append((a, b, kappa, len(shared)))
    return results


def interpret_alpha(alpha: Optional[float]) -> str:
    """Krippendorff's own guidance (2004)."""
    if alpha is None:
        return "not computable"
    if alpha >= 0.8:
        return "acceptable agreement"
    if alpha >= 0.667:
        return "tentative agreement"
    return "low agreement"


def compute_metrics(project: ProjectData) -> Dict[str, Any]:
    """All numbers the LaTeX report needs, per scheme and overall."""
    records = project.records

    # -- coverage ------------------------------------------------------------
    annotations_per_instance = Counter(
        (r.instance_id, r.schema) for r in records)
    by_instance = Counter(r.instance_id for r in records)
    per_annotator_items: Dict[str, set] = defaultdict(set)
    for r in records:
        per_annotator_items[r.annotator].add(r.instance_id)

    # -- per scheme ----------------------------------------------------------
    schemes_out = []
    for scheme in project.schemes:
        name = scheme.get("name")
        scheme_records = [r for r in records if r.schema == name]
        if not scheme_records:
            continue
        distribution = Counter(r.value for r in scheme_records)
        units = _units_for_scheme(records, scheme)
        multi = {u: v for u, v in units.items() if len(v) >= 2}
        alpha = _alpha_nominal(units)
        kappas = _pairwise_kappas(records, name) \
            if scheme.get("annotation_type") != "multiselect" else []
        kappa_values = [k for _, _, k, _ in kappas]
        schemes_out.append({
            "name": name,
            "annotation_type": scheme.get("annotation_type"),
            "description": scheme.get("description", ""),
            "distribution": dict(distribution.most_common()),
            "total_labels": sum(distribution.values()),
            "alpha": alpha,
            "alpha_interpretation": interpret_alpha(alpha),
            "multi_annotated_units": len(multi),
            "total_units": len(units),
            "pairwise_kappa": {
                "n_pairs": len(kappa_values),
                "mean": statistics.mean(kappa_values) if kappa_values else None,
                "min": min(kappa_values) if kappa_values else None,
                "max": max(kappa_values) if kappa_values else None,
            },
        })

    # -- annotators ----------------------------------------------------------
    annotators_out = []
    for annotator in sorted(per_annotator_items):
        timings = project.timings.get(annotator, [])
        annotators_out.append({
            "annotator": annotator,
            "items": len(per_annotator_items[annotator]),
            "labels": sum(1 for r in records if r.annotator == annotator),
            "median_seconds": round(statistics.median(timings), 1) if timings else None,
        })

    # -- timing overall --------------------------------------------------------
    all_seconds = [s for timings in project.timings.values() for s in timings]

    return {
        "task_name": project.task_name,
        "n_annotators": len(per_annotator_items),
        "n_annotated_instances": len(project.instance_ids),
        "n_total_items": project.total_items,
        "n_label_records": len(records),
        "mean_annotations_per_instance": (
            round(statistics.mean(by_instance.values()), 2) if by_instance else 0
        ),
        "instances_single_annotated": sum(
            1 for (_iid, _s), c in annotations_per_instance.items() if c == 1),
        "schemes": schemes_out,
        "skipped_schemes": [
            {"name": s.get("name"), "annotation_type": s.get("annotation_type")}
            for s in project.skipped_schemes
        ],
        "annotators": annotators_out,
        "timing": {
            "median_seconds_per_item": (
                round(statistics.median(all_seconds), 1) if all_seconds else None),
            "total_person_hours": (
                round(sum(all_seconds) / 3600.0, 2) if all_seconds else None),
        },
    }
