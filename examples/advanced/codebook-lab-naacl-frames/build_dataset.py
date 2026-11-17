#!/usr/bin/env python
"""
Build seed_codebook.yaml, dev.yaml and test.yaml for the immigration-frames
codebook_lab experiment from naacl_2021_data.zip (Mendelsohn, Budak &
Jurgens, "Modeling Framing in Immigration Discourse on Social Media",
NAACL 2021).

  - seed_codebook.yaml: the 14 issue-generic policy frames, with
    definitions paraphrased from the Policy Frames Codebook (Boydstun et
    al. 2014) that the NAACL annotators worked from, plus one real
    *train*-split tweet per frame that carries only that frame.
  - dev.yaml: every *dev*-split tweet with at least one frame. The
    hybridizer picks each label's winning variant on this set.
  - test.yaml: every *test*-split tweet with at least one frame. Seed,
    variants and hybrid are compared here, on items none of them were
    selected on.

Tweets with no frame at all are dropped (63 dev, 73 test): a platinum
item needs at least one label. Their absence slightly softens the
penalty for over-labeling.

Usage:
    python examples/advanced/codebook-lab-naacl-frames/build_dataset.py
    python examples/advanced/codebook-lab-naacl-frames/build_dataset.py --zip /path/to/naacl_2021_data.zip
"""

from __future__ import annotations

import argparse
import collections
import csv
import io
import os
import random
import sys
import zipfile
from typing import Dict, List, Tuple

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))

MEMBER = "naacl_2021_data/binarized_annotations/{split}/Issue-General.tsv"

# Paraphrased from the Policy Frames Codebook (Boydstun, Gross, Resnik &
# Smith 2014), in the order the NAACL release lists its columns.
DEFINITIONS: Dict[str, str] = {
    "Capacity and Resources": (
        "The availability or lack of physical, geographical, spatial, human "
        "or financial resources, or the capacity of existing systems to "
        "carry out policy goals."),
    "Crime and Punishment": (
        "Violation of laws and their enforcement: crimes, policing, "
        "breaking laws, loopholes, fines, sentencing and punishment."),
    "Cultural Identity": (
        "The social norms, trends, values and customs that make up a "
        "culture, as they relate to the issue."),
    "Economic": (
        "The costs, benefits, or monetary and financial implications of "
        "the issue for an individual, a family, a community or the "
        "economy as a whole."),
    "External Regulation and Reputation": (
        "A country's external relations with other nations, or relations "
        "between states or groups: treaties, trade agreements, and how a "
        "country is perceived internationally."),
    "Fairness and Equality": (
        "Equality or inequality in how laws, punishment, rewards and "
        "resources are applied or distributed among individuals or "
        "groups; the balance between one group's rights or interests and "
        "another's."),
    "Health and Safety": (
        "Health care access and effectiveness, illness, disease, "
        "sanitation, mental health, and physical safety of people, "
        "infrastructure and buildings."),
    "Legality, Constitutionality, Jurisdiction": (
        "The legal, constitutional or jurisdictional aspects of the issue: "
        "court cases, existing laws, rights and freedoms, and which body "
        "or level of government has authority."),
    "Morality and Ethics": (
        "Any perspective compelled by religious doctrine, duty, honor, "
        "righteousness, or another sense of ethics or social "
        "responsibility."),
    "Policy Prescription and Evaluation": (
        "Particular policies proposed for addressing a problem, and "
        "whether proposed or existing policies will work or are "
        "effective."),
    "Political Factors and Implications": (
        "The political considerations around the issue: the efforts, "
        "stances and maneuvering of politicians, parties and advocacy "
        "groups, elections, and attempts to sway voters."),
    "Public Sentiment": (
        "General social attitudes, protests, polling and demographic "
        "information, and the consequences of diverging from public "
        "opinion."),
    "Quality of Life": (
        "The effects of the issue on people's wealth, mobility, access to "
        "resources, happiness, social structures, ease of day-to-day "
        "life and quality of community life."),
    "Security and Defense": (
        "Security, threats to security, and protection of one's person, "
        "family, in-group or nation, including border security and "
        "terrorism."),
}


def load_split(zip_path: str, split: str, frames: List[str] = None
               ) -> Tuple[List[str], List[Tuple[str, str, List[str]]]]:
    """(frame names in column order, [(tweet_id, text, gold_frames)])."""
    csv.field_size_limit(10 ** 8)
    with zipfile.ZipFile(zip_path) as zf:
        raw = zf.read(MEMBER.format(split=split)).decode("utf-8")
    reader = csv.DictReader(io.StringIO(raw), delimiter="\t")
    columns = [c for c in reader.fieldnames if c not in ("", "text", "id", "labels")]
    rows = []
    for r in reader:
        gold = [f for f in columns if r[f] == "1"]
        rows.append((r["id"], r["text"], gold))
    return columns, rows


def build_seed(train, frames, rng):
    """One single-frame train tweet per frame, 8-40 words."""
    pools: Dict[str, List[Tuple[str, str]]] = collections.defaultdict(list)
    for tid, text, gold in train:
        if len(gold) == 1 and 8 <= len(text.split()) <= 40:
            pools[gold[0]].append((tid, text))

    codes = []
    for f in frames:
        positives = []
        if pools[f]:
            _, text = rng.choice(sorted(pools[f]))
            positives.append({
                "text": text,
                "why": f"Annotated with {f} and no other frame.",
            })
        codes.append({
            "name": f,
            "definition": DEFINITIONS[f],
            "clarification": "",
            "negative_clarification": "",
            "positive_examples": positives,
            "negative_examples": [],
            "exclusion_rules": [],
        })
    return codes


def build_platinum(rows):
    return [
        {"id": tid, "text": text, "labels": gold}
        for tid, text, gold in rows if gold
    ]


def _write_yaml(path: str, header: str, data) -> None:
    with open(path, "wt", encoding="utf-8") as fh:
        fh.write(header)
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True, width=100)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--zip", default=os.path.join(REPO_ROOT, "naacl_2021_data.zip"))
    ap.add_argument("--out-dir", default=HERE)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    frames, train = load_split(args.zip, "train")
    missing = set(frames) - set(DEFINITIONS)
    if missing:
        raise SystemExit(f"No definition for frame(s): {sorted(missing)}")

    rng = random.Random(args.seed)
    seed_codes = build_seed(train, frames, rng)
    _write_yaml(
        os.path.join(args.out_dir, "seed_codebook.yaml"),
        "# Generated by build_dataset.py — Policy Frames Codebook definitions\n"
        "# (Boydstun et al. 2014, paraphrased) + one single-frame train tweet\n"
        "# per frame from naacl_2021_data (Mendelsohn et al. 2021).\n\n",
        seed_codes)

    for split in ("dev", "test"):
        _, rows = load_split(args.zip, split)
        platinum = build_platinum(rows)
        counts = collections.Counter(l for ex in platinum for l in ex["labels"])
        _write_yaml(
            os.path.join(args.out_dir, f"{split}.yaml"),
            f"# Generated by build_dataset.py. {len(platinum)} of {len(rows)} "
            f"naacl_2021_data *{split}*\n"
            "# tweets (Issue-General frames); tweets with no frame are "
            "dropped.\n\n",
            platinum)
        print(f"{split}: {len(platinum)} items; per frame: " + ", ".join(
            f"{f}={counts[f]}" for f in sorted(frames, key=lambda x: counts[x])))

    print(f"Wrote {len(seed_codes)} codes to {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
