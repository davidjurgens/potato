"""
Inter-Annotator Agreement Calculation Module

This module provides functionality for calculating inter-annotator agreement metrics,
including Krippendorff's alpha, Cohen's kappa (pairwise), and Fleiss' kappa
(N raters), from annotation data. It supports both rating agreement (interval
metric) and skip agreement (nominal metric) calculations.

The module processes annotation files in JSON format and outputs agreement statistics
along with a CSV file containing the processed annotation data.
"""

import argparse
from itertools import combinations
import simpledorff
from simpledorff.metrics import *
import ujson
import pandas as pd

from collections import defaultdict
import numpy as np


def get_nans(shape):
    """
    Create a numpy array filled with NaN values.

    Args:
        shape: The shape of the array to create

    Returns:
        numpy.ndarray: Array filled with NaN values
    """
    ar = np.empty(shape)
    ar[:] = np.NaN
    return ar


def cohen_kappa_pairwise(reliability_df):
    """
    Compute Cohen's kappa for every pair of annotators and return aggregate stats.

    Cohen's kappa is defined for exactly two raters. With N>2 raters we compute
    kappa for each pair on the items they both rated, then return the mean and the
    per-pair breakdown. Pairs that share fewer than 2 items are skipped.

    Args:
        reliability_df: long-format DataFrame with columns
            unit (item id), annotator (user), annotation (label value).

    Returns:
        dict with keys: mean_kappa (float | None), pairs (list of
            {annotator_a, annotator_b, kappa, n_items}), n_pairs_evaluated,
            n_pairs_skipped.
    """
    from sklearn.metrics import cohen_kappa_score

    annotators = sorted(reliability_df["annotator"].unique())
    pairs = []
    skipped = 0

    for a, b in combinations(annotators, 2):
        a_rows = reliability_df[reliability_df["annotator"] == a].set_index("unit")["annotation"]
        b_rows = reliability_df[reliability_df["annotator"] == b].set_index("unit")["annotation"]
        shared = a_rows.index.intersection(b_rows.index)
        if len(shared) < 2:
            skipped += 1
            continue

        y_a = a_rows.loc[shared].astype(str).tolist()
        y_b = b_rows.loc[shared].astype(str).tolist()
        try:
            kappa = float(cohen_kappa_score(y_a, y_b))
        except Exception:
            skipped += 1
            continue
        pairs.append({
            "annotator_a": a,
            "annotator_b": b,
            "kappa": round(kappa, 4),
            "n_items": int(len(shared)),
        })

    mean_kappa = (sum(p["kappa"] for p in pairs) / len(pairs)) if pairs else None
    return {
        "mean_kappa": round(mean_kappa, 4) if mean_kappa is not None else None,
        "pairs": pairs,
        "n_pairs_evaluated": len(pairs),
        "n_pairs_skipped": skipped,
    }


def fleiss_kappa(reliability_df):
    """
    Compute Fleiss' kappa for N raters over a categorical label set.

    Fleiss' kappa assumes the same number of ratings per item but tolerates
    different rater identities per item. Items with fewer than 2 ratings are
    dropped; the remaining items are padded by repeating their available
    ratings up to the per-item rater count (`n_raters = max ratings per item`).
    When per-item rater counts vary widely the metric is approximate; we report
    `n_raters` and `n_items_evaluated` so the caller can judge.

    Args:
        reliability_df: long-format DataFrame with columns
            unit (item id), annotator (user), annotation (label value).

    Returns:
        dict with keys: kappa (float | None), n_items_evaluated (int),
            n_raters (int), n_categories (int), interpretation (str).
    """
    if reliability_df.empty:
        return {"kappa": None, "n_items_evaluated": 0, "n_raters": 0,
                "n_categories": 0, "interpretation": "No data"}

    df = reliability_df.copy()
    df["annotation"] = df["annotation"].astype(str)

    counts_by_item = df.groupby(["unit", "annotation"]).size().unstack(fill_value=0)
    items_with_ratings = counts_by_item.sum(axis=1)
    counts_by_item = counts_by_item.loc[items_with_ratings >= 2]

    if counts_by_item.empty:
        return {"kappa": None, "n_items_evaluated": 0, "n_raters": 0,
                "n_categories": int(df["annotation"].nunique()),
                "interpretation": "No items with >=2 raters"}

    n_raters = int(counts_by_item.sum(axis=1).max())
    n_items = int(counts_by_item.shape[0])
    n_categories = int(counts_by_item.shape[1])

    matrix = counts_by_item.to_numpy(dtype=float)
    row_sums = matrix.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1.0
    matrix = matrix * (n_raters / row_sums)

    p_j = matrix.sum(axis=0) / (n_items * n_raters)
    if n_raters < 2:
        return {"kappa": None, "n_items_evaluated": n_items, "n_raters": n_raters,
                "n_categories": n_categories,
                "interpretation": "Need >=2 raters per item"}
    p_i = (np.sum(matrix ** 2, axis=1) - n_raters) / (n_raters * (n_raters - 1))
    p_bar = float(p_i.mean())
    p_e = float(np.sum(p_j ** 2))

    if p_e >= 1.0:
        kappa = 1.0 if p_bar >= 1.0 else 0.0
    else:
        kappa = (p_bar - p_e) / (1 - p_e)

    return {
        "kappa": round(float(kappa), 4),
        "n_items_evaluated": n_items,
        "n_raters": n_raters,
        "n_categories": n_categories,
        "interpretation": interpret_kappa(kappa),
    }


def interpret_kappa(kappa):
    """Landis & Koch (1977) interpretation bands for kappa-family metrics."""
    if kappa is None:
        return "No agreement computable"
    if kappa < 0:
        return "Worse than chance"
    if kappa < 0.21:
        return "Slight"
    if kappa < 0.41:
        return "Fair"
    if kappa < 0.61:
        return "Moderate"
    if kappa < 0.81:
        return "Substantial"
    return "Almost perfect"


def flatten(annotations):
    """
    Flatten annotation data structure for processing.

    Converts a list of annotation dictionaries into a format where each
    annotation is a dictionary mapping user IDs to their labels.

    Args:
        annotations: List of annotation dictionaries

    Returns:
        list: Flattened annotation data structure

    Example:
        Input: [{"user": "user1", "label": "positive"}, {"user": "user2", "label": "negative"}]
        Output: [{"user1": "positive", "user2": "negative"}]
    """
    return [{a["user"]: a["label"] for a in ann} for ann in annotations]


def main(args):
    """
    Main function for calculating inter-annotator agreement.

    This function processes annotation data from a JSON file, calculates
    Krippendorff's alpha for both rating agreement and skip agreement,
    and outputs the results along with a CSV file of the processed data.

    Args:
        args: Command line arguments containing file paths

    Side Effects:
        - Reads annotation data from input file
        - Prints agreement statistics to console
        - Writes processed data to output CSV file

    The function processes the first 385 annotations by default and handles
    missing annotations and skipped items appropriately.
    """
    # Load annotation data from JSON file
    with open(args.file, "r") as f:
        annotations = [ujson.loads(line)["annotations"] for line in f]

    # Extract unique user IDs from all annotations
    users = set([a["user"] for ann in annotations for a in ann])
    annotations = flatten(annotations)

    # Limit to first 385 annotations (configurable limit)
    annotations = annotations[:385]

    # Create data matrix for agreement calculation
    # Each row represents a user, each column represents an annotation
    # -1 values indicate skipped annotations, NaN indicates missing annotations
    data = [
        [np.nan if user not in a or int(a[user]) == -1 else int(a[user]) for a in annotations]
        for user in users
    ]

    # Create skip data matrix (boolean indicating if annotation was skipped)
    skip_data = [
        [np.nan if user not in a else int(a[user]) < 0 for a in annotations] for user in users
    ]

    # Calculate statistics for each user
    labeled = ~np.isnan(data)
    skipped = [
        [False if user not in a else int(a[user]) < 0 for a in annotations] for user in users
    ]

    # Print summary statistics
    print("calculating over:")
    for user, skip in zip(labeled, skipped):
        print("labeled:", sum(user))
        print("skipped:", sum(skip))

    # Count instances where all users provided annotations
    print(np.all(labeled, axis=0).sum())

    # Calculate and print Krippendorff's alpha for rating agreement
    # Uses interval metric for continuous rating scales
    print("rating agreement:")
    print(simpledorff.calculate_krippendorffs_alpha(pd.DataFrame(data),metric_fn=interval_metric))

    # Calculate and print Krippendorff's alpha for skip agreement
    # Uses nominal metric for binary skip/no-skip decisions
    print("skip agreement:")
    print(simpledorff.calculate_krippendorffs_alpha(pd.DataFrame(data),metric_fn=nominal_metric))

    # Write processed data to CSV file
    with open(args.outfile, "w") as f:
        for row in zip(*data):
            f.write(",".join([str(a) for a in row]) + "\n")


if __name__ == "__main__":
    # Set up command line argument parsing
    parser = argparse.ArgumentParser(
        description="Calculate Krippendorf's alpha from given JSON file of annotations"
    )
    parser.add_argument("file", help="path to JSON file")
    parser.add_argument("outfile", help="write path to CSV")
    main(parser.parse_args())
