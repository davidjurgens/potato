"""
Console + CSV reporting for a codebook_lab run: a variant x label
score matrix (accuracy for single-label runs, F1 / macro-F1 for
multi-label runs), plus a verdict on whether the hybrid actually beat every
single variant.
"""

from __future__ import annotations

import csv
import os
from typing import List, Optional

from .models import VariantScore


def _fmt(pct: float) -> str:
    return f"{pct * 100:.1f}%"


# Above this many labels the variant x label matrix is too wide for a
# terminal; print_leaderboard switches to a compact view and the full
# matrix lives only in leaderboard.csv.
MAX_MATRIX_LABELS = 8


def print_leaderboard(
    scores: List[VariantScore], label_names: List[str],
    hybrid_score: Optional[VariantScore] = None,
) -> None:
    all_scores = list(scores) + ([hybrid_score] if hybrid_score else [])
    if any(s.multi_label for s in all_scores):
        print("Per-label F1; overall = macro-F1 across labels.\n")
    ranked = sorted(scores, key=lambda s: s.overall_score, reverse=True)
    if len(label_names) > MAX_MATRIX_LABELS:
        _print_compact(ranked, label_names, hybrid_score)
    else:
        _print_matrix(ranked, label_names, hybrid_score)

    if hybrid_score:
        best_single = ranked[0] if ranked else None
        print()
        if best_single is None:
            return
        if hybrid_score.overall_score > best_single.overall_score:
            print(
                f"Hybrid wins overall: {_fmt(hybrid_score.overall_score)} "
                f"vs best single variant {best_single.variant_id} "
                f"({_fmt(best_single.overall_score)}).")
        elif hybrid_score.overall_score == best_single.overall_score:
            print(
                f"Hybrid ties the best single variant "
                f"({best_single.variant_id}) at {_fmt(hybrid_score.overall_score)}.")
        else:
            print(
                f"Hybrid did NOT beat the best single variant: "
                f"{_fmt(hybrid_score.overall_score)} vs "
                f"{best_single.variant_id} ({_fmt(best_single.overall_score)}). "
                f"Per-label wins don't always compose — check for cross-label "
                f"interactions (an exclusion rule tuned for one label narrowing "
                f"another) in the individual predictions.")


def _print_matrix(
    ranked: List[VariantScore], label_names: List[str],
    hybrid_score: Optional[VariantScore],
) -> None:
    all_scores = list(ranked) + ([hybrid_score] if hybrid_score else [])
    id_width = max([len("variant")] + [len(s.variant_id) for s in all_scores]) + 2
    col_width = max(10, max((len(n) for n in label_names), default=0) + 2)

    def row(s: VariantScore) -> str:
        per_label = s.per_label_score()
        return s.variant_id.ljust(id_width) + "".join(
            _fmt(per_label.get(n, 0.0)).ljust(col_width) for n in label_names
        ) + _fmt(s.overall_score)

    header = "variant".ljust(id_width) + "".join(
        n[:col_width - 1].ljust(col_width) for n in label_names) + "overall"
    print(header)
    print("-" * len(header))
    for s in ranked:
        print(row(s))
    if hybrid_score:
        print("-" * len(header))
        print(row(hybrid_score))


def _print_compact(
    ranked: List[VariantScore], label_names: List[str],
    hybrid_score: Optional[VariantScore],
) -> None:
    """Two narrow tables instead of one huge matrix: variants ranked by
    overall score, then each label's seed / best-variant / hybrid score."""
    all_scores = list(ranked) + ([hybrid_score] if hybrid_score else [])
    id_width = max([len("variant")] + [len(s.variant_id) for s in all_scores]) + 2

    header = "variant".ljust(id_width) + "overall".ljust(10) + "exact match"
    print(header)
    print("-" * len(header))
    for s in all_scores:
        if s is hybrid_score:
            print("-" * len(header))
        print(s.variant_id.ljust(id_width) + _fmt(s.overall_score).ljust(10)
              + _fmt(s.overall_accuracy))

    seed = next((s for s in ranked if s.variant_id == "seed"), None)
    label_width = max([len("label")] + [len(n) for n in label_names]) + 2
    print()
    header = ("label".ljust(label_width) + "seed".ljust(9)
              + "best variant".ljust(id_width) + "best".ljust(9) + "hybrid")
    print(header)
    print("-" * len(header))
    per_label = {s.variant_id: s.per_label_score() for s in all_scores}
    for n in label_names:
        best = max(ranked, key=lambda s: per_label[s.variant_id].get(n, 0.0),
                   default=None)
        if best is None:
            continue
        print(
            n.ljust(label_width)
            + (_fmt(per_label["seed"].get(n, 0.0)) if seed else "-").ljust(9)
            + best.variant_id.ljust(id_width)
            + _fmt(per_label[best.variant_id].get(n, 0.0)).ljust(9)
            + (_fmt(per_label[hybrid_score.variant_id].get(n, 0.0))
               if hybrid_score else "-"))
    print("\n(Full variant x label matrix in leaderboard.csv.)")


def write_leaderboard_csv(
    path: str, scores: List[VariantScore], label_names: List[str],
    hybrid_score: Optional[VariantScore] = None,
) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    all_scores = list(scores) + ([hybrid_score] if hybrid_score else [])
    with open(path, "wt", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["variant", *label_names, "overall", "exact_match"])
        for s in all_scores:
            per_label = s.per_label_score()
            writer.writerow([
                s.variant_id,
                *[f"{per_label.get(n, 0.0):.4f}" for n in label_names],
                f"{s.overall_score:.4f}",
                f"{s.overall_accuracy:.4f}",
            ])
