#!/usr/bin/env python3
"""
Setup script for the Machine Annotators demo.

Writes the output of three annotation pipelines and one LLM reviewer into
annotation_output/ as user states, plus two human curators who have labelled
part of the data. The pipelines and the LLM are declared under
`machine_annotators` in config.yaml, so the server stamps their origin when it
loads these states.

It also writes data/loci.json, including each locus's `tool_disagreement`:
the share of the four machine raters that did NOT give the most common label.
That field drives the triage queue, so a curator who logs in is served the
loci the tools disagree about first.

The loci and every label below are synthetic. The locus tags use a made-up
TOY_ prefix, and the pipeline names are placeholders, not real tools.

Usage (from the repository root or this directory):
    python examples/advanced/machine-annotators/setup_demo.py
    python examples/advanced/machine-annotators/setup_demo.py --clean   # also drop decisions
"""

import argparse
import json
import os
import shutil
from collections import Counter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "annotation_output")
DATA_FILE = os.path.join(SCRIPT_DIR, "data", "loci.json")

SCHEMA = "function_category"

# ---------------------------------------------------------------------------
# The loci. `text` is what the curator reads.
# ---------------------------------------------------------------------------

LOCI = [
    ("TOY_00010", "1,236 bp, + strand",
     "Best hit: ABC transporter ATP-binding protein (62% identity). "
     "Walker A and Walker B motifs present."),
    ("TOY_00020", "462 bp, + strand",
     "Best hit: 50S ribosomal protein L7/L12 (91% identity)."),
    ("TOY_00030", "1,050 bp, - strand",
     "Best hit: glyceraldehyde-3-phosphate dehydrogenase (78% identity)."),
    ("TOY_00040", "387 bp, - strand",
     "No hit above threshold. One predicted transmembrane helix."),
    ("TOY_00050", "1,488 bp, + strand",
     "Best hit: DNA-binding response regulator (44% identity). "
     "Receiver domain and a winged-helix DNA-binding domain."),
    ("TOY_00060", "1,317 bp, + strand",
     "Best hit: MFS transporter (38% identity). Twelve predicted "
     "transmembrane helices. Second hit: sugar permease (35% identity)."),
    ("TOY_00070", "693 bp, - strand",
     "Best hit: flagellar motor switch protein FliN (57% identity)."),
    ("TOY_00080", "921 bp, + strand",
     "Best hit: DUF1287 domain-containing protein (29% identity)."),
    ("TOY_00090", "1,803 bp, - strand",
     "Best hit: penicillin-binding protein 2 (66% identity)."),
    ("TOY_00100", "558 bp, + strand",
     "Best hit: GNAT family N-acetyltransferase (33% identity). "
     "Acetyl-CoA binding motif present."),
    ("TOY_00110", "2,445 bp, + strand",
     "Best hit: DNA gyrase subunit B (84% identity)."),
    ("TOY_00120", "774 bp, - strand",
     "Best hit: hypothetical protein (41% identity). Weak similarity "
     "to an ABC transporter permease."),
]

# ---------------------------------------------------------------------------
# Machine raters. pipeline_a and pipeline_b use the same reference database
# (see config.yaml), so they tend to be wrong together -- the correlated-error
# case the docs warn about.
# ---------------------------------------------------------------------------

MACHINE_LABELS = {
    "pipeline_a": {
        "TOY_00010": "transport", "TOY_00020": "information_processing",
        "TOY_00030": "metabolism", "TOY_00040": "hypothetical",
        "TOY_00050": "information_processing", "TOY_00060": "metabolism",
        "TOY_00070": "cellular_processes", "TOY_00080": "hypothetical",
        "TOY_00090": "cellular_processes", "TOY_00100": "metabolism",
        "TOY_00110": "information_processing", "TOY_00120": "transport",
    },
    "pipeline_b": {
        "TOY_00010": "transport", "TOY_00020": "information_processing",
        "TOY_00030": "metabolism", "TOY_00040": "hypothetical",
        "TOY_00050": "information_processing", "TOY_00060": "metabolism",
        "TOY_00070": "cellular_processes", "TOY_00080": "metabolism",
        "TOY_00090": "cellular_processes", "TOY_00100": "metabolism",
        "TOY_00110": "information_processing", "TOY_00120": "transport",
    },
    "pipeline_c": {
        "TOY_00010": "transport", "TOY_00020": "information_processing",
        "TOY_00030": "metabolism", "TOY_00040": "cellular_processes",
        "TOY_00050": "cellular_processes", "TOY_00060": "transport",
        "TOY_00070": "cellular_processes", "TOY_00080": "hypothetical",
        "TOY_00090": "cellular_processes", "TOY_00100": "hypothetical",
        "TOY_00110": "information_processing", "TOY_00120": "hypothetical",
    },
    "llm_reviewer": {
        "TOY_00010": "transport", "TOY_00020": "information_processing",
        "TOY_00030": "metabolism", "TOY_00040": "hypothetical",
        "TOY_00050": "cellular_processes", "TOY_00060": "transport",
        "TOY_00070": "cellular_processes", "TOY_00080": "hypothetical",
        "TOY_00090": "metabolism", "TOY_00100": "metabolism",
        "TOY_00110": "information_processing", "TOY_00120": "hypothetical",
    },
}

# Two human curators, each covering the first eight loci.
HUMAN_LABELS = {
    "curator_1": {
        "TOY_00010": "transport", "TOY_00020": "information_processing",
        "TOY_00030": "metabolism", "TOY_00040": "hypothetical",
        "TOY_00050": "cellular_processes", "TOY_00060": "transport",
        "TOY_00070": "cellular_processes", "TOY_00080": "hypothetical",
    },
    "curator_2": {
        "TOY_00010": "transport", "TOY_00020": "information_processing",
        "TOY_00030": "metabolism", "TOY_00040": "cellular_processes",
        "TOY_00050": "cellular_processes", "TOY_00060": "transport",
        "TOY_00070": "cellular_processes", "TOY_00080": "hypothetical",
    },
}

DEMO_USERS = tuple(MACHINE_LABELS) + tuple(HUMAN_LABELS)

USER_STATE_TEMPLATE = {
    "current_phase_and_page": ["annotation", "annotation"],
    "completed_phase_and_pages": [],
    "max_assignments": -1,
    "instance_id_to_span_to_value": {},
    "phase_to_page_to_label_to_value": {},
    "phase_to_page_to_span_to_value": {},
    "instance_id_to_keyword_highlight_state": {},
}


def tool_disagreement(locus_id):
    """Share of machine raters that did not give the most common label."""
    labels = [by_locus[locus_id] for by_locus in MACHINE_LABELS.values()]
    top = Counter(labels).most_common(1)[0][1]
    return round(1 - top / len(labels), 2)


def write_data_file():
    items = []
    for locus_id, coords, evidence in LOCI:
        items.append({
            "id": locus_id,
            "text": f"Locus {locus_id} ({coords}). {evidence}",
            "tool_disagreement": tool_disagreement(locus_id),
        })
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)
        f.write("\n")
    print(f"  Wrote {DATA_FILE}")


def build_user_state(user_id, labels):
    state = json.loads(json.dumps(USER_STATE_TEMPLATE))
    state["user_id"] = user_id
    ordering = list(labels)
    state["instance_id_ordering"] = ordering
    state["current_instance_index"] = len(ordering) - 1
    state["instance_id_to_label_to_value"] = {
        locus_id: [[{"schema": SCHEMA, "name": label}, True]]
        for locus_id, label in labels.items()
    }
    return state


def write_user_state(user_id, labels):
    user_dir = os.path.join(OUTPUT_DIR, user_id)
    os.makedirs(user_dir, exist_ok=True)
    path = os.path.join(user_dir, "user_state.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(build_user_state(user_id, labels), f, indent=2)
    print(f"  Wrote {path}")


def clean_stale_users():
    """Remove annotator directories this script did not create, so leftover
    test or browser sessions do not show up as extra raters."""
    if not os.path.isdir(OUTPUT_DIR):
        return
    for entry in sorted(os.listdir(OUTPUT_DIR)):
        if entry in DEMO_USERS or entry == "adjudication":
            continue
        path = os.path.join(OUTPUT_DIR, entry)
        if os.path.isdir(path):
            shutil.rmtree(path)
            print(f"  Removed stale annotator directory {path}")


def main():
    parser = argparse.ArgumentParser(description="Reset the machine annotators demo")
    parser.add_argument("--clean", action="store_true",
                        help="Also remove adjudication decisions")
    args = parser.parse_args()

    print("Writing synthetic loci and annotations...")
    write_data_file()
    clean_stale_users()
    for user_id, labels in {**MACHINE_LABELS, **HUMAN_LABELS}.items():
        write_user_state(user_id, labels)

    if args.clean:
        adj_dir = os.path.join(OUTPUT_DIR, "adjudication")
        if os.path.isdir(adj_dir):
            shutil.rmtree(adj_dir)
            print(f"  Removed {adj_dir}")

    print("Done. Start the server from the repository root with:")
    print("  python potato/flask_server.py start "
          "examples/advanced/machine-annotators/config.yaml -p 8000")


if __name__ == "__main__":
    main()
