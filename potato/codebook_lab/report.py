"""
Console + CSV reporting for a codebook_lab run: a variant x label
accuracy matrix, plus a verdict on whether the hybrid actually beat every
single variant.
"""

from __future__ import annotations

import csv
import os
from typing import List, Optional

from .models import VariantScore


def _fmt(pct: float) -> str:
    return f"{pct * 100:.1f}%"


def print_leaderboard(
    scores: List[VariantScore], label_names: List[str],
    hybrid_score: Optional[VariantScore] = None,
) -> None:
    all_scores = list(scores) + ([hybrid_score] if hybrid_score else [])
    id_width = max([len("variant")] + [len(s.variant_id) for s in all_scores]) + 2
    col_width = max(10, max((len(n) for n in label_names), default=0) + 2)

    header = "variant".ljust(id_width) + "".join(
        n[:col_width - 1].ljust(col_width) for n in label_names) + "overall"
    print(header)
    print("-" * len(header))

    ranked = sorted(scores, key=lambda s: s.overall_accuracy, reverse=True)
    for s in ranked:
        per_label = s.per_label_accuracy()
        row = s.variant_id.ljust(id_width) + "".join(
            _fmt(per_label.get(n, 0.0)).ljust(col_width) for n in label_names
        ) + _fmt(s.overall_accuracy)
        print(row)

    if hybrid_score:
        print("-" * len(header))
        per_label = hybrid_score.per_label_accuracy()
        row = hybrid_score.variant_id.ljust(id_width) + "".join(
            _fmt(per_label.get(n, 0.0)).ljust(col_width) for n in label_names
        ) + _fmt(hybrid_score.overall_accuracy)
        print(row)

        best_single = ranked[0] if ranked else None
        print()
        if best_single is None:
            return
        if hybrid_score.overall_accuracy > best_single.overall_accuracy:
            print(
                f"Hybrid wins overall: {_fmt(hybrid_score.overall_accuracy)} "
                f"vs best single variant {best_single.variant_id} "
                f"({_fmt(best_single.overall_accuracy)}).")
        elif hybrid_score.overall_accuracy == best_single.overall_accuracy:
            print(
                f"Hybrid ties the best single variant "
                f"({best_single.variant_id}) at {_fmt(hybrid_score.overall_accuracy)}.")
        else:
            print(
                f"Hybrid did NOT beat the best single variant: "
                f"{_fmt(hybrid_score.overall_accuracy)} vs "
                f"{best_single.variant_id} ({_fmt(best_single.overall_accuracy)}). "
                f"Per-label wins don't always compose — check for cross-label "
                f"interactions (an exclusion rule tuned for one label narrowing "
                f"another) in the individual predictions.")


def write_leaderboard_csv(
    path: str, scores: List[VariantScore], label_names: List[str],
    hybrid_score: Optional[VariantScore] = None,
) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    all_scores = list(scores) + ([hybrid_score] if hybrid_score else [])
    with open(path, "wt", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["variant", *label_names, "overall"])
        for s in all_scores:
            per_label = s.per_label_accuracy()
            writer.writerow([
                s.variant_id,
                *[f"{per_label.get(n, 0.0):.4f}" for n in label_names],
                f"{s.overall_accuracy:.4f}",
            ])
