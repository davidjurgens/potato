"""
Inter-Annotator Agreement (IAA) metrics for Potato.

This package computes IAA across the heterogeneous coverage sample produced
by the overlap-sampling feature. Metrics are dispatched per annotation schema
type (nominal, ordinal, continuous, multi-label, ranking, span).

Public entry points:
    compute_overlap_iaa(item_state_manager, user_state_manager, config)
        End-to-end report for overlap-sample items that have reached their cap.
    metrics_for_schema(annotation_type)
        Inspect which metric functions apply to a given schema type.

Lower-level metric functions live in nominal/ordinal/continuous/multilabel/ranking/span
modules; alpha.py wraps Krippendorff's alpha (delegated to ``simpledorff``).
"""

from potato.server_utils.iaa import nominal, ordinal, continuous, multilabel, ranking, span, alpha
from potato.server_utils.iaa.dispatcher import (
    metrics_for_schema,
    compute_overlap_iaa,
    SchemaKind,
    classify_schema,
)

__all__ = [
    "nominal",
    "ordinal",
    "continuous",
    "multilabel",
    "ranking",
    "span",
    "alpha",
    "metrics_for_schema",
    "compute_overlap_iaa",
    "SchemaKind",
    "classify_schema",
]
