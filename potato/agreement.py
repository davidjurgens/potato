"""
Inter-Annotator Agreement Calculation Module

This module provides functionality for calculating inter-annotator agreement metrics,
specifically Krippendorff's alpha, from annotation data. It supports both rating
agreement (interval metric) and skip agreement (nominal metric) calculations.

The module processes annotation files in JSON format and outputs agreement statistics
along with a CSV file containing the processed annotation data.
"""

import argparse
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
