#!/usr/bin/env python3
"""
Setup script for the MACE Competence Estimation Demo.

Generates synthetic annotation data from 5 annotators with different
quality profiles so MACE can estimate their competence.

Annotator profiles:
  - reliable_1:  Expert annotator, always correct
  - reliable_2:  Good annotator, mostly correct (8/10)
  - moderate:    Average annotator, correct ~60% of the time
  - spammer:     Low-quality annotator, nearly random
  - biased:      Always picks "positive" regardless of content

Ground truth labels (for reference):
  review_01: positive    review_06: positive
  review_02: negative    review_07: negative
  review_03: positive    review_08: neutral
  review_04: neutral     review_09: positive
  review_05: negative    review_10: negative

Usage:
    python setup_demo.py          # regenerate annotation data
    python setup_demo.py --clean  # also remove cached MACE results
"""

import argparse
import json
import os
import random
import shutil
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "annotation_output")

ITEM_IDS = [f"review_{i:02d}" for i in range(1, 11)]
LABELS = ["positive", "negative", "neutral"]

# Ground truth: what a correct annotator would label each item
GROUND_TRUTH = {
    "review_01": "positive",
    "review_02": "negative",
    "review_03": "positive",
    "review_04": "neutral",
    "review_05": "negative",
    "review_06": "positive",
    "review_07": "negative",
    "review_08": "neutral",
    "review_09": "positive",
    "review_10": "negative",
}

# ---------------------------------------------------------------
# Annotator definitions
# ---------------------------------------------------------------

# reliable_1: perfect agreement with ground truth
RELIABLE_1_LABELS = {
    item_id: label for item_id, label in GROUND_TRUTH.items()
}

# reliable_2: mostly correct, wrong on review_04 and review_08
RELIABLE_2_LABELS = dict(GROUND_TRUTH)
RELIABLE_2_LABELS["review_04"] = "positive"   # wrong (should be neutral)
RELIABLE_2_LABELS["review_08"] = "negative"   # wrong (should be neutral)

# moderate: correct ~60%, wrong on review_02, 04, 07, 08
MODERATE_LABELS = dict(GROUND_TRUTH)
MODERATE_LABELS["review_02"] = "neutral"    # wrong (should be negative)
MODERATE_LABELS["review_04"] = "positive"   # wrong (should be neutral)
MODERATE_LABELS["review_07"] = "neutral"    # wrong (should be negative)
MODERATE_LABELS["review_08"] = "positive"   # wrong (should be neutral)

# spammer: nearly random, only 3/10 correct by chance
SPAMMER_LABELS = {
    "review_01": "negative",   # wrong
    "review_02": "positive",   # wrong
    "review_03": "neutral",    # wrong
    "review_04": "neutral",    # correct (by chance)
    "review_05": "positive",   # wrong
    "review_06": "negative",   # wrong
    "review_07": "positive",   # wrong
    "review_08": "neutral",    # correct (by chance)
    "review_09": "negative",   # wrong
    "review_10": "negative",   # correct (by chance)
}

# biased: always picks "positive"
BIASED_LABELS = {item_id: "positive" for item_id in ITEM_IDS}

# ---------------------------------------------------------------
# Behavioral data generation
# ---------------------------------------------------------------
# Generates full BehavioralData-compatible dicts with session timing,
# interactions, annotation changes, scroll depth, and navigation history.

def _make_behavioral(item_id, total_time_ms, final_label, base_time,
                     annotation_changes=None, scroll_depth=80.0,
                     deliberation_clicks=0):
    """Build a full BehavioralData-compatible dict for one instance.

    Args:
        item_id: Instance ID
        total_time_ms: Total annotation time in milliseconds
        final_label: The label that was ultimately selected
        base_time: Unix timestamp for the start of this annotation session
        annotation_changes: Optional list of annotation change dicts
        scroll_depth: Maximum scroll depth (0-100)
        deliberation_clicks: Number of extra interaction events to include
    """
    session_start = base_time
    session_end = base_time + total_time_ms / 1000.0

    # Build interaction events: at minimum a "click" on the final label
    interactions = []
    # Reading / focus event
    interactions.append({
        "event_type": "focus_in",
        "timestamp": session_start + 0.5,
        "target": f"instance:{item_id}",
        "instance_id": item_id,
        "client_timestamp": (session_start + 0.5) * 1000,
        "metadata": {},
    })
    # Deliberation clicks (e.g. scrolling, hovering over options)
    for c in range(deliberation_clicks):
        t = session_start + (total_time_ms / 1000.0) * (c + 1) / (deliberation_clicks + 2)
        interactions.append({
            "event_type": "click",
            "timestamp": t,
            "target": f"label:{random.choice(LABELS)}",
            "instance_id": item_id,
            "client_timestamp": t * 1000,
            "metadata": {"deliberation": True},
        })
    # Final label selection
    select_time = session_end - 1.0
    interactions.append({
        "event_type": "click",
        "timestamp": select_time,
        "target": f"label:{final_label}",
        "instance_id": item_id,
        "client_timestamp": select_time * 1000,
        "metadata": {},
    })
    # Save event
    interactions.append({
        "event_type": "save",
        "timestamp": session_end - 0.2,
        "target": "nav:next",
        "instance_id": item_id,
        "client_timestamp": (session_end - 0.2) * 1000,
        "metadata": {},
    })

    return {
        "instance_id": item_id,
        "session_start": session_start,
        "session_end": session_end,
        "total_time_ms": total_time_ms,
        "interactions": interactions,
        "ai_usage": [],
        "annotation_changes": annotation_changes or [],
        "navigation_history": [
            {"action": "navigate_to", "instance_id": item_id, "timestamp": session_start},
            {"action": "navigate_away", "instance_id": item_id, "timestamp": session_end},
        ],
        "focus_time_by_element": {
            f"instance:{item_id}": int(total_time_ms * 0.7),
            f"schema:sentiment": int(total_time_ms * 0.3),
        },
        "scroll_depth_max": scroll_depth,
        "keyword_highlights_shown": [],
    }


def _build_behavioral_data(labels, time_profile, base_time, change_map=None):
    """Build behavioral data for all items for one annotator.

    Args:
        labels: Dict of item_id -> final label
        time_profile: Dict of item_id -> (total_time_ms, scroll_depth, deliberation_clicks)
        base_time: Starting unix timestamp (each item advances from previous)
        change_map: Optional dict of item_id -> list of annotation change dicts
    """
    behavioral = {}
    current_time = base_time
    for item_id in ITEM_IDS:
        total_ms, scroll, delib = time_profile[item_id]
        changes = (change_map or {}).get(item_id, [])
        behavioral[item_id] = _make_behavioral(
            item_id, total_ms, labels[item_id], current_time,
            annotation_changes=changes, scroll_depth=scroll,
            deliberation_clicks=delib,
        )
        # Next item starts after a short break
        current_time += total_ms / 1000.0 + random.uniform(1.0, 3.0)
    return behavioral


# Use a fixed seed for reproducibility
random.seed(42)
_BASE_TIME = 1738700000.0  # A fixed reference timestamp

# reliable_1: careful reader, consistent times 8-18s, high scroll depth
RELIABLE_1_TIME_PROFILE = {
    "review_01": (15000, 95.0, 0), "review_02": (12000, 90.0, 0),
    "review_03": (10000, 85.0, 0), "review_04": (18000, 98.0, 1),
    "review_05": (8000, 80.0, 0),  "review_06": (14000, 92.0, 0),
    "review_07": (11000, 88.0, 0), "review_08": (16000, 95.0, 1),
    "review_09": (9000, 82.0, 0),  "review_10": (7000, 78.0, 0),
}
RELIABLE_1_BEHAVIORAL = _build_behavioral_data(
    RELIABLE_1_LABELS, RELIABLE_1_TIME_PROFILE, _BASE_TIME)

# reliable_2: good annotator, deliberates on hard items (04, 08)
RELIABLE_2_TIME_PROFILE = {
    "review_01": (12000, 88.0, 0), "review_02": (14000, 90.0, 0),
    "review_03": (11000, 85.0, 0),
    "review_04": (20000, 98.0, 3),  # deliberated, changed mind
    "review_05": (9000, 80.0, 0),  "review_06": (13000, 87.0, 0),
    "review_07": (10000, 84.0, 0),
    "review_08": (22000, 98.0, 3),  # deliberated, changed mind
    "review_09": (8000, 78.0, 0),  "review_10": (10000, 82.0, 0),
}
RELIABLE_2_CHANGES = {
    "review_04": [
        {"timestamp": 5000, "schema_name": "sentiment", "action": "select",
         "new_value": "neutral", "source": "user"},
        {"timestamp": 12000, "schema_name": "sentiment", "action": "select",
         "new_value": "positive", "source": "user"},
    ],
    "review_08": [
        {"timestamp": 4000, "schema_name": "sentiment", "action": "select",
         "new_value": "neutral", "source": "user"},
        {"timestamp": 14000, "schema_name": "sentiment", "action": "select",
         "new_value": "negative", "source": "user"},
    ],
}
RELIABLE_2_BEHAVIORAL = _build_behavioral_data(
    RELIABLE_2_LABELS, RELIABLE_2_TIME_PROFILE, _BASE_TIME + 300,
    change_map=RELIABLE_2_CHANGES)

# moderate: average speed, moderate scroll, some deliberation
MODERATE_TIME_PROFILE = {
    item_id: (8000 + i * 1000, 60.0 + i * 3, 1 if i % 3 == 0 else 0)
    for i, item_id in enumerate(ITEM_IDS)
}
MODERATE_BEHAVIORAL = _build_behavioral_data(
    MODERATE_LABELS, MODERATE_TIME_PROFILE, _BASE_TIME + 600)

# spammer: very fast times (barely reading), low scroll depth, no deliberation
SPAMMER_TIME_PROFILE = {
    item_id: (500 + i * 200, 10.0 + i * 2, 0)
    for i, item_id in enumerate(ITEM_IDS)
}
SPAMMER_BEHAVIORAL = _build_behavioral_data(
    SPAMMER_LABELS, SPAMMER_TIME_PROFILE, _BASE_TIME + 900)

# biased: moderate times but never changes mind, moderate scroll
BIASED_TIME_PROFILE = {
    item_id: (3000 + i * 500, 45.0 + i * 4, 0)
    for i, item_id in enumerate(ITEM_IDS)
}
BIASED_BEHAVIORAL = _build_behavioral_data(
    BIASED_LABELS, BIASED_TIME_PROFILE, _BASE_TIME + 1200)

# User state template (matches Potato's expected format)
USER_STATE_TEMPLATE = {
    "current_phase_and_page": ["annotation", "annotation"],
    "completed_phase_and_pages": [],
    "max_assignments": -1,
    "instance_id_to_span_to_value": {},
    "phase_to_page_to_label_to_value": {},
    "phase_to_page_to_span_to_value": {},
    "training_state": {
        "completed_questions": {},
        "total_correct": 0,
        "total_attempts": 0,
        "total_mistakes": 0,
        "passed": False,
        "failed": False,
        "current_question_index": 0,
        "training_instances": [],
        "show_feedback": False,
        "feedback_message": "",
        "allow_retry": False,
        "max_mistakes": -1,
        "max_mistakes_per_question": -1,
        "category_scores": {},
    },
    "instance_id_to_keyword_highlight_state": {},
}


def build_user_state(user_id, labels, behavioral):
    """Build a complete user_state.json dict from label and behavioral data."""
    state = dict(USER_STATE_TEMPLATE)
    state["user_id"] = user_id
    state["instance_id_ordering"] = list(ITEM_IDS)
    state["current_instance_index"] = len(ITEM_IDS) - 1

    # Convert labels to the list-of-pairs format used by Potato
    # Format: {item_id: [[{"schema": "sentiment", "name": label}, True]]}
    label_map = {}
    for item_id, label in labels.items():
        label_map[item_id] = [
            [{"schema": "sentiment", "name": label}, True]
        ]
    state["instance_id_to_label_to_value"] = label_map
    state["instance_id_to_behavioral_data"] = behavioral
    return state


def write_user_state(user_id, state):
    """Write a user_state.json file for the given user."""
    user_dir = os.path.join(OUTPUT_DIR, user_id)
    os.makedirs(user_dir, exist_ok=True)
    filepath = os.path.join(user_dir, "user_state.json")
    with open(filepath, "w") as f:
        json.dump(state, f, indent=2)
    print(f"  Wrote {filepath}")


def clean_mace_cache():
    """Remove cached MACE results."""
    mace_dir = os.path.join(OUTPUT_DIR, "mace")
    if os.path.exists(mace_dir):
        shutil.rmtree(mace_dir)
        print(f"  Removed {mace_dir}")


def main():
    parser = argparse.ArgumentParser(description="Reset MACE demo data")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Also remove cached MACE results",
    )
    args = parser.parse_args()

    print("Generating synthetic annotation data for MACE demo...")
    print()

    annotators = [
        ("reliable_1", RELIABLE_1_LABELS, RELIABLE_1_BEHAVIORAL),
        ("reliable_2", RELIABLE_2_LABELS, RELIABLE_2_BEHAVIORAL),
        ("moderate", MODERATE_LABELS, MODERATE_BEHAVIORAL),
        ("spammer", SPAMMER_LABELS, SPAMMER_BEHAVIORAL),
        ("biased", BIASED_LABELS, BIASED_BEHAVIORAL),
    ]

    for user_id, labels, behavioral in annotators:
        state = build_user_state(user_id, labels, behavioral)
        write_user_state(user_id, state)

    if args.clean:
        print("\nCleaning MACE cache...")
        clean_mace_cache()

    print()
    print("Done! Start the server with:")
    print("  python potato/flask_server.py start "
          "project-hub/simple_examples/simple-mace-demo/config.yaml -p 8000")
    print()
    print("Then trigger MACE and view results:")
    print('  curl -X POST http://localhost:8000/admin/api/mace/trigger '
          '-H "X-API-Key: demo-mace-key"')
    print('  curl http://localhost:8000/admin/api/mace/overview '
          '-H "X-API-Key: demo-mace-key" | python -m json.tool')
    print('  curl "http://localhost:8000/admin/api/mace/predictions?schema=sentiment" '
          '-H "X-API-Key: demo-mace-key" | python -m json.tool')
    print()
    print("Expected competence ranking (high to low):")
    print("  reliable_1 > reliable_2 > moderate > biased ~ spammer")


if __name__ == "__main__":
    main()
