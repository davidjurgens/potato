#!/usr/bin/env python
"""
Build seed_codebook.yaml and platinum.yaml for the GoEmotions codebook_lab
experiment from the public GoEmotions release (Demszky et al., ACL 2020;
https://github.com/google-research/google-research/tree/master/goemotions).

  - seed_codebook.yaml: the 27 emotion definitions annotators were given
    (paper, Table "emotion definitions") plus "neutral", each with one
    real positive example drawn from the *train* split where every rater
    agreed on exactly that one label.
  - platinum.yaml: a label-stratified sample of the *test* split, kept to
    items where every gold label was chosen by a strict majority of
    raters and no rater flagged the item as very unclear — i.e. the
    "must get right" items, not the contested ones.

Usage:
    python examples/advanced/codebook-lab-goemotions/build_dataset.py
    python examples/advanced/codebook-lab-goemotions/build_dataset.py --per-label 12 --seed 1

Downloads ~45MB on first run into --data-dir (default
~/.cache/potato/goemotions) and reuses it afterwards.
"""

from __future__ import annotations

import argparse
import collections
import csv
import os
import random
import sys
import urllib.request
from typing import Dict, List, Tuple

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))

SPLIT_URL = ("https://raw.githubusercontent.com/google-research/"
             "google-research/master/goemotions/data/{name}")
RATER_URL = ("https://storage.googleapis.com/gresearch/goemotions/data/"
             "full_dataset/goemotions_{i}.csv")

# Definitions shown to GoEmotions annotators (Demszky et al. 2020).
# "neutral" had no published definition; this one is ours.
DEFINITIONS: Dict[str, str] = {
    "admiration": "Finding something impressive or worthy of respect.",
    "amusement": "Finding something funny or being entertained.",
    "anger": "A strong feeling of displeasure or antagonism.",
    "annoyance": "Mild anger, irritation.",
    "approval": "Having or expressing a favorable opinion.",
    "caring": "Displaying kindness and concern for others.",
    "confusion": "Lack of understanding, uncertainty.",
    "curiosity": "A strong desire to know or learn something.",
    "desire": "A strong feeling of wanting something or wishing for something to happen.",
    "disappointment": "Sadness or displeasure caused by the nonfulfillment of one's hopes or expectations.",
    "disapproval": "Having or expressing an unfavorable opinion.",
    "disgust": "Revulsion or strong disapproval aroused by something unpleasant or offensive.",
    "embarrassment": "Self-consciousness, shame, or awkwardness.",
    "excitement": "Feeling of great enthusiasm and eagerness.",
    "fear": "Being afraid or worried.",
    "gratitude": "A feeling of thankfulness and appreciation.",
    "grief": "Intense sorrow, especially caused by someone's death.",
    "joy": "A feeling of pleasure and happiness.",
    "love": "A strong positive emotion of regard and affection.",
    "nervousness": "Apprehension, worry, anxiety.",
    "optimism": "Hopefulness and confidence about the future or the success of something.",
    "pride": "Pleasure or satisfaction due to one's own achievements or the achievements of those with whom one is closely associated.",
    "realization": "Becoming aware of something.",
    "relief": "Reassurance and relaxation following release from anxiety or distress.",
    "remorse": "Regret or guilty feeling.",
    "sadness": "Emotional pain, sorrow.",
    "surprise": "Feeling astonished, startled by something unexpected.",
    "neutral": "The comment expresses none of the other emotions.",
}


def _fetch(url: str, dest: str) -> None:
    if os.path.exists(dest):
        return
    print(f"Downloading {url}", file=sys.stderr)
    tmp = dest + ".part"
    urllib.request.urlretrieve(url, tmp)
    os.replace(tmp, dest)


def download(data_dir: str) -> None:
    os.makedirs(data_dir, exist_ok=True)
    for name in ("emotions.txt", "train.tsv", "test.tsv"):
        _fetch(SPLIT_URL.format(name=name), os.path.join(data_dir, name))
    for i in (1, 2, 3):
        _fetch(RATER_URL.format(i=i),
               os.path.join(data_dir, f"goemotions_{i}.csv"))


def load_split(data_dir: str, name: str, emotions: List[str]
               ) -> Dict[str, Tuple[str, List[str]]]:
    """{comment_id: (text, gold_labels)} — gold = labels >=2 raters chose."""
    out = {}
    with open(os.path.join(data_dir, name), encoding="utf-8") as fh:
        for text, label_ids, cid in csv.reader(fh, delimiter="\t",
                                                quoting=csv.QUOTE_NONE):
            out[cid] = (text, [emotions[int(i)] for i in label_ids.split(",")])
    return out


def load_rater_votes(data_dir: str, emotions: List[str], ids: set):
    """Per-comment rater count, vote count per emotion, and unclear flags."""
    n_raters = collections.Counter()
    unclear = collections.Counter()
    votes: Dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    for i in (1, 2, 3):
        path = os.path.join(data_dir, f"goemotions_{i}.csv")
        with open(path, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                cid = row["id"]
                if cid not in ids:
                    continue
                n_raters[cid] += 1
                if row["example_very_unclear"] == "True":
                    unclear[cid] += 1
                for e in emotions:
                    if row[e] == "1":
                        votes[cid][e] += 1
    return n_raters, unclear, votes


def build_seed(train, votes, n_raters, unclear, emotions, rng):
    """One unanimous, single-label train example per emotion."""
    pools: Dict[str, List[str]] = collections.defaultdict(list)
    for cid, (text, gold) in train.items():
        n = n_raters[cid]
        if len(gold) != 1 or n < 3 or unclear[cid]:
            continue
        label = gold[0]
        # Unanimous and nobody chose anything else.
        if votes[cid][label] == n and sum(votes[cid].values()) == n:
            if 5 <= len(text.split()) <= 30:
                pools[label].append(cid)

    codes = []
    for e in emotions:
        positives = []
        if pools[e]:
            cid = rng.choice(sorted(pools[e]))
            positives.append({
                "text": train[cid][0],
                "why": f"All {n_raters[cid]} raters chose only {e}.",
            })
        codes.append({
            "name": e,
            "definition": DEFINITIONS[e],
            "clarification": "",
            "negative_clarification": "",
            "positive_examples": positives,
            "negative_examples": [],
            "exclusion_rules": [],
        })
    return codes


def build_platinum(test, votes, n_raters, unclear, emotions, per_label, rng):
    """Label-stratified sample of high-agreement test items. Rarest labels
    are filled first so they aren't crowded out; an item already chosen
    for one label counts toward every label it carries. Within a label,
    unanimous items are taken before merely-majority ones (GoEmotions
    gold is noisy, and unanimity alone leaves several labels empty)."""
    def agreement(cid: str) -> float:
        return min(votes[cid][e] / n_raters[cid] for e in test[cid][1])

    eligible = [
        cid for cid, (_, gold) in test.items()
        if n_raters[cid] and not unclear[cid]
        and all(votes[cid][e] * 2 > n_raters[cid] for e in gold)
    ]
    by_label: Dict[str, List[str]] = collections.defaultdict(list)
    for cid in sorted(eligible):
        for e in test[cid][1]:
            by_label[e].append(cid)

    chosen: List[str] = []
    chosen_set = set()
    counts = collections.Counter()
    for e in sorted(emotions, key=lambda x: len(by_label[x])):
        pool = [c for c in by_label[e] if c not in chosen_set]
        rng.shuffle(pool)
        pool.sort(key=agreement, reverse=True)  # stable: shuffled within ties
        for cid in pool:
            if counts[e] >= per_label:
                break
            chosen.append(cid)
            chosen_set.add(cid)
            for label in test[cid][1]:
                counts[label] += 1

    examples = [
        {"id": cid, "text": test[cid][0], "labels": test[cid][1]}
        for cid in sorted(chosen)
    ]
    n_unanimous = sum(agreement(c) == 1.0 for c in chosen)
    return examples, counts, len(eligible), n_unanimous


def _write_yaml(path: str, header: str, data) -> None:
    with open(path, "wt", encoding="utf-8") as fh:
        fh.write(header)
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True, width=100)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-dir", default=os.path.expanduser(
        "~/.cache/potato/goemotions"))
    ap.add_argument("--out-dir", default=HERE)
    ap.add_argument("--per-label", type=int, default=8,
                    help="Target platinum items per label (rare labels "
                         "get all eligible items if fewer exist)")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    download(args.data_dir)
    with open(os.path.join(args.data_dir, "emotions.txt"), encoding="utf-8") as fh:
        emotions = fh.read().split()
    missing = set(emotions) - set(DEFINITIONS)
    if missing:
        raise SystemExit(f"No definition for emotion(s): {sorted(missing)}")

    train = load_split(args.data_dir, "train.tsv", emotions)
    test = load_split(args.data_dir, "test.tsv", emotions)
    n_raters, unclear, votes = load_rater_votes(
        args.data_dir, emotions, set(train) | set(test))

    rng = random.Random(args.seed)
    seed_codes = build_seed(train, votes, n_raters, unclear, emotions, rng)
    platinum, counts, n_eligible, n_unanimous = build_platinum(
        test, votes, n_raters, unclear, emotions, args.per_label, rng)

    _write_yaml(
        os.path.join(args.out_dir, "seed_codebook.yaml"),
        "# Generated by build_dataset.py — GoEmotions annotator definitions\n"
        "# (Demszky et al. 2020) + one unanimous train-split example per label.\n"
        "# \"neutral\" has no published definition; ours is a placeholder.\n\n",
        seed_codes)
    _write_yaml(
        os.path.join(args.out_dir, "platinum.yaml"),
        f"# Generated by build_dataset.py (--per-label {args.per_label} "
        f"--seed {args.seed}).\n"
        f"# {len(platinum)} GoEmotions *test* items, stratified by label, "
        f"drawn from the {n_eligible}\n"
        "# test items where every gold label had strict-majority rater "
        "agreement and\n# no rater flagged the item as very unclear. "
        "Unanimous items are preferred\n# within each label "
        f"({n_unanimous}/{len(platinum)} here are unanimous).\n"
        "# Source: https://github.com/google-research/google-research/"
        "tree/master/goemotions\n\n",
        platinum)

    print(f"Wrote {len(seed_codes)} codes and {len(platinum)} platinum items "
          f"({n_unanimous} unanimous) to {args.out_dir}")
    print("Platinum items per label: " + ", ".join(
        f"{e}={counts[e]}" for e in sorted(emotions, key=lambda x: counts[x])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
