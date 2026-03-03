#!/usr/bin/env python3
"""
Setup script for demo pre-populated annotation data.

Generates synthetic annotations for:
  - Task 01 (Sentiment + MACE): 5 annotators with varying quality
  - Task 09 (Adjudication): 3 annotators with deliberate disagreements

Usage:
    python demo/setup_data.py
"""

import json
import os
import random
import shutil

DEMO_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------
# Shared template
# ---------------------------------------------------------------

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


def write_user_state(output_dir, user_id, state):
    """Write a user_state.json file."""
    user_dir = os.path.join(output_dir, user_id)
    os.makedirs(user_dir, exist_ok=True)
    filepath = os.path.join(user_dir, "user_state.json")
    with open(filepath, "w") as f:
        json.dump(state, f, indent=2)
    print(f"  Wrote {filepath}")


def build_user_state(user_id, item_ids, labels, behavioral=None):
    """Build a complete user_state.json dict."""
    state = dict(USER_STATE_TEMPLATE)
    state["user_id"] = user_id
    state["instance_id_ordering"] = list(item_ids)
    state["current_instance_index"] = len(item_ids) - 1
    state["instance_id_to_label_to_value"] = labels
    state["instance_id_to_behavioral_data"] = behavioral or {}
    return state


# ---------------------------------------------------------------
# Helper for behavioral data
# ---------------------------------------------------------------

def make_behavioral(item_id, total_time_ms, base_time):
    """Build a minimal BehavioralData dict for one instance."""
    return {
        "instance_id": item_id,
        "session_start": base_time,
        "session_end": base_time + total_time_ms / 1000.0,
        "total_time_ms": total_time_ms,
        "interactions": [],
        "ai_usage": [],
        "annotation_changes": [],
        "navigation_history": [],
        "focus_time_by_element": {},
        "scroll_depth_max": random.uniform(60, 100),
        "keyword_highlights_shown": [],
    }


# ===============================================================
# TASK 01: Sentiment + MACE (5 annotators)
# ===============================================================

TASK01_OUTPUT = os.path.join(DEMO_DIR, "01-sentiment-admin", "annotation_output")
TASK01_ITEMS = [f"review_{i:02d}" for i in range(1, 11)]
TASK01_LABELS = ["positive", "negative", "neutral", "mixed"]

TASK01_GROUND_TRUTH = {
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

# reliable_1: perfect
TASK01_RELIABLE1 = dict(TASK01_GROUND_TRUTH)

# reliable_2: 80% correct
TASK01_RELIABLE2 = dict(TASK01_GROUND_TRUTH)
TASK01_RELIABLE2["review_04"] = "positive"
TASK01_RELIABLE2["review_08"] = "negative"

# moderate: 60% correct
TASK01_MODERATE = dict(TASK01_GROUND_TRUTH)
TASK01_MODERATE["review_02"] = "neutral"
TASK01_MODERATE["review_04"] = "positive"
TASK01_MODERATE["review_07"] = "neutral"
TASK01_MODERATE["review_08"] = "positive"

# spammer: nearly random
TASK01_SPAMMER = {
    "review_01": "negative", "review_02": "positive", "review_03": "neutral",
    "review_04": "neutral", "review_05": "positive", "review_06": "negative",
    "review_07": "positive", "review_08": "neutral", "review_09": "negative",
    "review_10": "negative",
}

# biased: always positive
TASK01_BIASED = {item_id: "positive" for item_id in TASK01_ITEMS}


def build_task01_labels(raw_labels):
    """Convert {item: label} to potato format for task 01 (sentiment only)."""
    label_map = {}
    for item_id, label in raw_labels.items():
        label_map[item_id] = [
            [{"schema": "sentiment", "name": label}, True]
        ]
    return label_map


def build_task01_behavioral(raw_labels, time_range, base_time):
    """Build behavioral data with varying annotation times."""
    random.seed(42)
    behavioral = {}
    current_time = base_time
    for item_id in TASK01_ITEMS:
        total_ms = random.randint(time_range[0], time_range[1])
        behavioral[item_id] = make_behavioral(item_id, total_ms, current_time)
        current_time += total_ms / 1000.0 + random.uniform(1.0, 3.0)
    return behavioral


def setup_task01():
    """Generate pre-populated annotations for Task 01."""
    print("Task 01: Generating MACE demo data (5 annotators)...")

    if os.path.exists(TASK01_OUTPUT):
        shutil.rmtree(TASK01_OUTPUT)

    base_time = 1738700000.0
    annotators = [
        ("reliable_1", TASK01_RELIABLE1, (8000, 18000), base_time),
        ("reliable_2", TASK01_RELIABLE2, (8000, 22000), base_time + 300),
        ("moderate",   TASK01_MODERATE,  (6000, 14000), base_time + 600),
        ("spammer",    TASK01_SPAMMER,   (500, 2000),   base_time + 900),
        ("biased",     TASK01_BIASED,    (3000, 6000),  base_time + 1200),
    ]

    for user_id, raw_labels, time_range, bt in annotators:
        labels = build_task01_labels(raw_labels)
        behavioral = build_task01_behavioral(raw_labels, time_range, bt)
        state = build_user_state(user_id, TASK01_ITEMS, labels, behavioral)
        write_user_state(TASK01_OUTPUT, user_id, state)


# ===============================================================
# TASK 09: Adjudication (3 annotators with disagreements)
# ===============================================================

TASK09_OUTPUT = os.path.join(DEMO_DIR, "09-adjudication", "annotation_output")
TASK09_ITEMS = [f"item_{i:03d}" for i in range(1, 9)]

USER_1_LABELS = {
    "item_001": [
        [{"schema": "sentiment", "name": "mixed"}, True],
        [{"schema": "topics", "name": "food"}, True],
        [{"schema": "topics", "name": "service"}, True],
    ],
    "item_002": [
        [{"schema": "sentiment", "name": "positive"}, True],
        [{"schema": "topics", "name": "food"}, True],
    ],
    "item_003": [
        [{"schema": "sentiment", "name": "neutral"}, True],
    ],
    "item_004": [
        [{"schema": "sentiment", "name": "negative"}, True],
        [{"schema": "topics", "name": "food"}, True],
        [{"schema": "topics", "name": "price"}, True],
    ],
    "item_005": [
        [{"schema": "sentiment", "name": "negative"}, True],
        [{"schema": "topics", "name": "service"}, True],
        [{"schema": "topics", "name": "food"}, True],
    ],
    "item_006": [
        [{"schema": "sentiment", "name": "positive"}, True],
        [{"schema": "topics", "name": "ambiance"}, True],
    ],
    "item_007": [
        [{"schema": "sentiment", "name": "neutral"}, True],
    ],
    "item_008": [
        [{"schema": "sentiment", "name": "positive"}, True],
        [{"schema": "topics", "name": "service"}, True],
    ],
}

USER_2_LABELS = {
    "item_001": [
        [{"schema": "sentiment", "name": "positive"}, True],
        [{"schema": "topics", "name": "food"}, True],
    ],
    "item_002": [
        [{"schema": "sentiment", "name": "positive"}, True],
    ],
    "item_003": [
        [{"schema": "sentiment", "name": "negative"}, True],
    ],
    "item_004": [
        [{"schema": "sentiment", "name": "neutral"}, True],
        [{"schema": "topics", "name": "food"}, True],
    ],
    "item_005": [
        [{"schema": "sentiment", "name": "negative"}, True],
        [{"schema": "topics", "name": "service"}, True],
    ],
    "item_006": [
        [{"schema": "sentiment", "name": "positive"}, True],
        [{"schema": "topics", "name": "ambiance"}, True],
    ],
    "item_007": [
        [{"schema": "sentiment", "name": "neutral"}, True],
    ],
    "item_008": [
        [{"schema": "sentiment", "name": "positive"}, True],
        [{"schema": "topics", "name": "service"}, True],
    ],
}

USER_3_LABELS = {
    "item_001": [
        [{"schema": "sentiment", "name": "negative"}, True],
        [{"schema": "topics", "name": "service"}, True],
    ],
    "item_002": [
        [{"schema": "sentiment", "name": "neutral"}, True],
    ],
    "item_003": [
        [{"schema": "sentiment", "name": "positive"}, True],
        [{"schema": "topics", "name": "ambiance"}, True],
    ],
    "item_004": [
        [{"schema": "sentiment", "name": "mixed"}, True],
        [{"schema": "topics", "name": "food"}, True],
        [{"schema": "topics", "name": "price"}, True],
    ],
    "item_005": [
        [{"schema": "sentiment", "name": "positive"}, True],
        [{"schema": "topics", "name": "food"}, True],
        [{"schema": "topics", "name": "service"}, True],
    ],
    "item_006": [
        [{"schema": "sentiment", "name": "negative"}, True],
        [{"schema": "topics", "name": "price"}, True],
    ],
    "item_007": [
        [{"schema": "sentiment", "name": "positive"}, True],
    ],
    "item_008": [
        [{"schema": "sentiment", "name": "negative"}, True],
        [{"schema": "topics", "name": "service"}, True],
    ],
}

USER_1_BEHAVIORAL = {
    "item_001": {"total_time_ms": 45000, "annotation_changes": []},
    "item_002": {"total_time_ms": 12000, "annotation_changes": []},
    "item_003": {"total_time_ms": 38000, "annotation_changes": []},
    "item_004": {"total_time_ms": 25000, "annotation_changes": []},
    "item_005": {"total_time_ms": 8000, "annotation_changes": []},
    "item_006": {"total_time_ms": 15000, "annotation_changes": []},
    "item_007": {"total_time_ms": 20000, "annotation_changes": []},
    "item_008": {"total_time_ms": 18000, "annotation_changes": []},
}

USER_2_BEHAVIORAL = {
    "item_001": {"total_time_ms": 800, "annotation_changes": []},
    "item_002": {"total_time_ms": 1200, "annotation_changes": []},
    "item_003": {"total_time_ms": 900, "annotation_changes": []},
    "item_004": {"total_time_ms": 30000, "annotation_changes": []},
    "item_005": {"total_time_ms": 1500, "annotation_changes": []},
    "item_006": {"total_time_ms": 700, "annotation_changes": []},
    "item_007": {"total_time_ms": 1100, "annotation_changes": []},
    "item_008": {"total_time_ms": 15000, "annotation_changes": []},
}

USER_3_BEHAVIORAL = {
    "item_001": {"total_time_ms": 32000, "annotation_changes": []},
    "item_002": {"total_time_ms": 20000, "annotation_changes": []},
    "item_003": {"total_time_ms": 40000, "annotation_changes": []},
    "item_004": {"total_time_ms": 18000, "annotation_changes": []},
    "item_005": {"total_time_ms": 15000, "annotation_changes": []},
    "item_006": {"total_time_ms": 28000, "annotation_changes": []},
    "item_007": {"total_time_ms": 35000, "annotation_changes": []},
    "item_008": {"total_time_ms": 22000, "annotation_changes": []},
}


def setup_task09():
    """Generate pre-populated annotations for Task 09."""
    print("\nTask 09: Generating adjudication demo data (3 annotators)...")

    if os.path.exists(TASK09_OUTPUT):
        shutil.rmtree(TASK09_OUTPUT)

    annotators = [
        ("user_1", USER_1_LABELS, USER_1_BEHAVIORAL),
        ("user_2", USER_2_LABELS, USER_2_BEHAVIORAL),
        ("user_3", USER_3_LABELS, USER_3_BEHAVIORAL),
    ]

    for user_id, labels, behavioral in annotators:
        state = build_user_state(user_id, TASK09_ITEMS, labels, behavioral)
        write_user_state(TASK09_OUTPUT, user_id, state)


# ===============================================================
# Main
# ===============================================================

def main():
    print("=" * 60)
    print("Demo Data Setup")
    print("=" * 60)
    print()

    setup_task01()
    setup_task09()

    print()
    print("=" * 60)
    print("Done! Pre-populated data generated for tasks 01 and 09.")
    print("=" * 60)


if __name__ == "__main__":
    main()
