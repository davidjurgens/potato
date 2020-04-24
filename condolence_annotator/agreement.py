import argparse
import krippendorff
import ujson

from collections import defaultdict
import numpy as np


def get_nans(shape):
    ar = np.empty(shape)
    ar[:] = np.NaN
    return ar


def flatten(annotations):
    return [{a["user"]: a["label"] for a in ann} for ann in annotations]


def main(args):
    with open(args.file, "r") as f:
        annotations = [ujson.loads(line)["annotations"] for line in f]
    users = set([a["user"] for ann in annotations for a in ann])
    annotations = flatten(annotations)
    annotations = annotations[:385]
    data = [[ np.nan if user not in a or int(a[user]) == -1 else int(a[user]) for a in annotations ] for user in users]
    skip_data = [[ np.nan if user not in a else int(a[user]) < 0 for a in annotations ] for user in users]
    labeled = ~np.isnan(data)
    skipped = [[ False if user not in a else int(a[user]) < 0 for a in annotations ] for user in users]
    print("calculating over:")
    for user, skip in zip(labeled, skipped):
        print("labeled:", sum(user))
        print("skipped:", sum(skip))
    print(np.all(labeled, axis=0).sum())
    print("rating agreement:")
    print(krippendorff.alpha(data, level_of_measurement="ordinal"))
    print("skip agreement:")
    print(krippendorff.alpha(skip_data, level_of_measurement="nominal"))
    with open(args.outfile, "w") as f:
        for row in zip(*data):
            f.write(",".join([str(a) for a in row]) + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Calculate Krippendorf's alpha from given JSON file of annotations"
    )
    parser.add_argument("file", help="path to JSON file")
    parser.add_argument("outfile", help="write path to CSV")
    main(parser.parse_args())
