#!/usr/bin/env python
"""
Build the Episodic-vs-Thematic data for the solo-mode prompt-trajectory
experiment from naacl_2021_data.zip (Mendelsohn, Budak & Jurgens, NAACL 2021).

Scope:
  - narrative frame only, and only tweets with exactly ONE of
    {Episodic, Thematic} (drops "both" and "neither"), so the task is a
    clean binary choice;
  - one topic: tweets whose Issue-General frames include --topic
    (default "Crime and Punishment").

Outputs (in this directory):
  data/train.json        --n-train items from the *train* split, balanced
                         E/T, no labels (what solo mode serves the "human")
  data/train_gold.json   {id: label} for those items (the simulated human)
  data/eval.json         every matching *dev* + *test* tweet, with labels
                         (held out; reference models are scored here)

Usage (from repo root):
  python examples/advanced/solo-narrative-frames/build_data.py
"""

from __future__ import annotations

import argparse
import ast
import csv
import io
import json
import os
import random
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
MEMBER = "naacl_2021_data/annotated_data/{split}.tsv"


def _list(s: str):
    return ast.literal_eval(s) if s.strip() else []


def load(zip_path: str, split: str, topic: str):
    csv.field_size_limit(10 ** 8)
    with zipfile.ZipFile(zip_path) as zf:
        raw = zf.read(MEMBER.format(split=split)).decode("utf-8")
    rows = []
    for r in csv.DictReader(io.StringIO(raw), delimiter="\t"):
        narrative = _list(r["Narrative"])
        if len(narrative) != 1 or topic not in _list(r["Issue-General"]):
            continue
        rows.append({"id": r["id_str"], "text": r["text"], "label": narrative[0],
                     "split": split, "country": r["country"], "year": r["year"]})
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--zip", default=os.path.join(REPO_ROOT, "naacl_2021_data.zip"))
    ap.add_argument("--topic", default="Crime and Punishment")
    ap.add_argument("--n-train", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    rng = random.Random(args.seed)
    train = load(args.zip, "train", args.topic)
    by_label = {l: sorted([r for r in train if r["label"] == l], key=lambda r: r["id"])
                for l in ("Episodic", "Thematic")}
    half = args.n_train // 2
    picked = rng.sample(by_label["Episodic"], half) + \
        rng.sample(by_label["Thematic"], args.n_train - half)
    rng.shuffle(picked)

    evals = load(args.zip, "dev", args.topic) + load(args.zip, "test", args.topic)

    os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
    with open(os.path.join(HERE, "data", "train.json"), "w") as f:
        json.dump([{"id": r["id"], "text": r["text"]} for r in picked], f, indent=1,
                  ensure_ascii=False)
    with open(os.path.join(HERE, "data", "train_gold.json"), "w") as f:
        json.dump({r["id"]: r["label"] for r in picked}, f, indent=1)
    with open(os.path.join(HERE, "data", "eval.json"), "w") as f:
        json.dump(evals, f, indent=1, ensure_ascii=False)

    def counts(rows):
        return {l: sum(r["label"] == l for r in rows) for l in ("Episodic", "Thematic")}
    print(f"topic={args.topic!r}")
    print(f"train pool {len(train)} {counts(train)} -> picked {len(picked)} {counts(picked)}")
    print(f"eval (dev+test) {len(evals)} {counts(evals)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
