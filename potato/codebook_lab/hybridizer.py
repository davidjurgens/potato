"""
Build a "best of breed" hybrid codebook: for each label, take the
structured fields (definition/clarification/examples/exclusion_rules)
from whichever scored variant did best on that specific label, ties
broken by that variant's overall accuracy.
"""

from __future__ import annotations

import logging
from typing import Dict, List

from .models import CodebookVariant, VariantScore

logger = logging.getLogger(__name__)


def build_hybrid(
    variants: List[CodebookVariant], scores: List[VariantScore],
    hybrid_id: str = "hybrid",
) -> CodebookVariant:
    """``variants``/``scores`` should be the same set and order the
    caller scored — typically every generated variant plus the seed
    (scored as its own variant) so the seed can win a label too."""
    if not variants or not scores:
        raise ValueError("build_hybrid needs at least one scored variant")

    by_id = {v.variant_id: v for v in variants}
    score_by_id = {s.variant_id: s for s in scores}
    label_names = variants[0].label_names()

    chosen_codes = []
    sources: Dict[str, str] = {}
    for label in label_names:
        best_id = None
        best_acc = -1.0
        for s in scores:
            acc = s.per_label_accuracy().get(label, 0.0)
            better = (
                acc > best_acc
                or (acc == best_acc and best_id is not None
                    and score_by_id[s.variant_id].overall_accuracy
                    > score_by_id[best_id].overall_accuracy)
            )
            if best_id is None or better:
                best_acc = acc
                best_id = s.variant_id
        source = by_id[best_id]
        code = source.code(label)
        if code is None:
            raise ValueError(
                f"Winning variant {best_id} for label {label!r} has no "
                f"code for it — variant sets are inconsistent")
        chosen_codes.append(code)
        sources[label] = f"{best_id}({best_acc:.0%})"
        logger.info("Hybrid label %r <- %s", label, sources[label])

    origin = "hybrid:" + ",".join(f"{l}={v}" for l, v in sources.items())
    return CodebookVariant(
        variant_id=hybrid_id, codes=chosen_codes, origin=origin,
        notes="Best-per-label pick across: " + ", ".join(
            f"{l}→{v}" for l, v in sources.items()),
    )
