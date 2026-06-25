"""
Aggregation of k judge samples into a single prediction + confidence.

For each (model, item, schema) we draw ``k`` samples from the LLM. This module
reduces those raw samples to a modal prediction and an empirical confidence
(the vote fraction = share of the k samples agreeing with the modal answer).

Confidence is intentionally computed over *all* k draws including failures:
a ``None`` sample (parse error / invalid label) counts toward the denominator
so the confidence honestly reflects how often the judge produced a usable,
consistent answer.

Per-schema reducers:
- radio / likert : modal label; confidence = count(modal) / k
- multiselect    : per-label vote fraction; predicted set = labels with
                   fraction >= ``multiselect_threshold``; confidence = mean
                   fraction over the predicted set (or 1 - mean fraction over
                   rejected labels when the set is empty)
- span           : delegated to span aggregation (Phase 7); not handled here.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


def span_iou(a: Tuple[int, int], b: Tuple[int, int]) -> float:
    """Character-offset IoU of two [start, end) spans. 0 if disjoint."""
    s1, e1 = a
    s2, e2 = b
    inter = max(0, min(e1, e2) - max(s1, s2))
    if inter == 0:
        return 0.0
    union = (e1 - s1) + (e2 - s2) - inter
    return inter / union if union > 0 else 0.0


@dataclass
class ModelItemResult:
    """A single judge model's aggregated verdict for one (item, schema)."""
    model: str
    instance_id: str
    schema_name: str
    annotation_type: str
    modal_label: Any                       # str | int | list[str] | None
    confidence: float                      # 0.0 - 1.0 (vote fraction)
    k: int
    samples: List[Any] = field(default_factory=list)  # raw per-draw values (None = failed)
    # Per-label vote fractions for multiselect (label -> fraction); empty otherwise.
    per_label_confidence: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "instance_id": self.instance_id,
            "schema_name": self.schema_name,
            "annotation_type": self.annotation_type,
            "modal_label": self.modal_label,
            "confidence": self.confidence,
            "k": self.k,
            "samples": self.samples,
            "per_label_confidence": self.per_label_confidence,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ModelItemResult":
        return cls(
            model=d["model"],
            instance_id=d["instance_id"],
            schema_name=d["schema_name"],
            annotation_type=d.get("annotation_type", "radio"),
            modal_label=d.get("modal_label"),
            confidence=float(d.get("confidence", 0.0)),
            k=int(d.get("k", 0)),
            samples=d.get("samples", []),
            per_label_confidence=d.get("per_label_confidence", {}),
        )


def _aggregate_categorical(samples: List[Any], k: int):
    """Modal label + vote fraction for single-label schemas (radio/likert).

    None samples count toward k (the denominator) but are never the modal
    label unless every draw failed.
    """
    valid = [s for s in samples if s is not None]
    if not valid:
        return None, 0.0
    counts = Counter(str(s) for s in valid)
    modal_str, modal_count = counts.most_common(1)[0]
    # Recover the original (typed) value for the modal label.
    modal_value = next(s for s in valid if str(s) == modal_str)
    confidence = modal_count / k if k else 0.0
    return modal_value, confidence


def _aggregate_multiselect(samples: List[Any], k: int, threshold: float):
    """Per-label vote fraction; predicted set = labels with fraction >= threshold.

    Each sample is a list (possibly empty) of selected label names. None
    samples count toward k.
    """
    per_label: Dict[str, int] = Counter()
    for s in samples:
        if s is None:
            continue
        for lab in s:
            per_label[str(lab)] += 1
    per_label_conf = {lab: cnt / k for lab, cnt in per_label.items()} if k else {}
    predicted = sorted([lab for lab, frac in per_label_conf.items() if frac >= threshold])
    if predicted:
        confidence = sum(per_label_conf[lab] for lab in predicted) / len(predicted)
    elif per_label_conf:
        # No label cleared the bar: confidence in the (empty) prediction is how
        # strongly the judges agreed to *exclude* the labels they saw.
        confidence = 1.0 - (sum(per_label_conf.values()) / len(per_label_conf))
    else:
        confidence = 1.0  # every draw selected nothing -> confident empty set
    return predicted, confidence, per_label_conf


def _aggregate_span(samples: List[Any], k: int, cluster_threshold: float, keep_threshold: float):
    """Cluster spans across k samples (EXPERIMENTAL).

    Each non-None sample is a list of span dicts {start, end, label}. Spans are
    greedily clustered when they share a label and overlap (IoU >=
    cluster_threshold). A cluster's support is the number of distinct samples
    that contributed to it; confidence = support / k. Clusters with confidence
    >= keep_threshold are kept; the representative span is the modal exact
    (start, end) within the cluster.

    Returns (modal_spans, mean_confidence) where modal_spans is a list of
    {start, end, label, confidence}.
    """
    clusters: List[Dict[str, Any]] = []  # each: {label, rep:(s,e), members:[(s,e,sample_idx)], samples:set}
    for idx, sample in enumerate(samples):
        if not sample:
            continue
        for sp in sample:
            try:
                s, e, lab = int(sp["start"]), int(sp["end"]), str(sp["label"])
            except (KeyError, TypeError, ValueError):
                continue
            if e <= s:
                continue
            placed = False
            for c in clusters:
                if c["label"] == lab and span_iou(c["rep"], (s, e)) >= cluster_threshold:
                    c["members"].append((s, e, idx))
                    c["samples"].add(idx)
                    placed = True
                    break
            if not placed:
                clusters.append({"label": lab, "rep": (s, e),
                                 "members": [(s, e, idx)], "samples": {idx}})

    modal_spans = []
    confidences = []
    for c in clusters:
        support = len(c["samples"])
        confidence = support / k if k else 0.0
        if confidence < keep_threshold:
            continue
        # representative = modal exact (start,end) among members
        offset_counts = Counter((s, e) for s, e, _ in c["members"])
        (rs, re), _ = offset_counts.most_common(1)[0]
        modal_spans.append({"start": rs, "end": re, "label": c["label"],
                            "confidence": round(confidence, 6)})
        confidences.append(confidence)

    modal_spans.sort(key=lambda d: (d["start"], d["end"], d["label"]))
    mean_conf = sum(confidences) / len(confidences) if confidences else 0.0
    return modal_spans, mean_conf


def aggregate(
    model: str,
    instance_id: str,
    schema_name: str,
    annotation_type: str,
    samples: List[Any],
    k: int,
    multiselect_threshold: float = 0.5,
    span_cluster_threshold: float = 0.5,
    span_keep_threshold: float = 0.5,
) -> ModelItemResult:
    """Reduce raw samples to a ModelItemResult for the given schema type."""
    per_label_conf: Dict[str, float] = {}
    if annotation_type == "multiselect":
        modal, confidence, per_label_conf = _aggregate_multiselect(
            samples, k, multiselect_threshold
        )
    elif annotation_type == "span":
        modal, confidence = _aggregate_span(
            samples, k, span_cluster_threshold, span_keep_threshold
        )
    else:
        # radio, likert, select, and any other single-label categorical type
        modal, confidence = _aggregate_categorical(samples, k)

    return ModelItemResult(
        model=model,
        instance_id=instance_id,
        schema_name=schema_name,
        annotation_type=annotation_type,
        modal_label=modal,
        confidence=round(confidence, 6),
        k=k,
        samples=samples,
        per_label_confidence={kk: round(v, 6) for kk, v in per_label_conf.items()},
    )
