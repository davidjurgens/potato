#!/usr/bin/env python3
"""
Setup script for the Adjudication Demo.

Regenerates the synthetic annotation data (user_state.json files) in
annotation_output/ so the adjudication queue is populated immediately
when the server starts.

Usage:
    python setup_demo.py          # regenerate from this directory
    python setup_demo.py --clean  # also remove adjudication decisions

This is useful for:
- Resetting the demo after items have been adjudicated
- Documenting the user_state.json format for custom pre-loaded data
- Showing how annotations can be pre-generated programmatically
"""

import argparse
import json
import os
import shutil

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "annotation_output")

# Template for a user_state.json file
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

ITEM_IDS = [f"item_{i:03d}" for i in range(1, 9)]


def _change(ts, schema, action="select", value=None):
    """Helper to create an annotation change dict."""
    return {
        "timestamp": ts,
        "schema_name": schema,
        "action": action,
        "new_value": value,
        "source": "user",
    }


# ---------------------------------------------------------------
# Annotation definitions per user
# ---------------------------------------------------------------

USER_1_LABELS = {
    "item_001": [
        ({"schema": "sentiment", "name": "mixed"}, True),
        ({"schema": "topics", "name": "food"}, True),
        ({"schema": "topics", "name": "service"}, True),
    ],
    "item_002": [
        ({"schema": "sentiment", "name": "positive"}, True),
        ({"schema": "topics", "name": "recommendation"}, True),
    ],
    "item_003": [
        ({"schema": "sentiment", "name": "neutral"}, True),
        ({"schema": "topics", "name": "ambiance"}, True),
    ],
    "item_004": [
        ({"schema": "sentiment", "name": "negative"}, True),
        ({"schema": "topics", "name": "food"}, True),
        ({"schema": "topics", "name": "price"}, True),
    ],
    "item_005": [
        ({"schema": "sentiment", "name": "negative"}, True),
        ({"schema": "topics", "name": "service"}, True),
        ({"schema": "topics", "name": "food"}, True),
    ],
    "item_006": [
        ({"schema": "sentiment", "name": "positive"}, True),
        ({"schema": "topics", "name": "ambiance"}, True),
    ],
    "item_007": [
        ({"schema": "sentiment", "name": "neutral"}, True),
    ],
    "item_008": [
        ({"schema": "sentiment", "name": "positive"}, True),
        ({"schema": "topics", "name": "service"}, True),
    ],
}

USER_1_BEHAVIORAL = {
    "item_001": {
        "total_time_ms": 45000,
        "annotation_changes": [
            _change(1000, "sentiment", value="neutral"),
            _change(5000, "sentiment", value="mixed"),
        ],
    },
    "item_002": {"total_time_ms": 12000, "annotation_changes": []},
    "item_003": {
        "total_time_ms": 38000,
        "annotation_changes": [
            _change(2000, "sentiment", value="positive"),
            _change(8000, "sentiment", value="negative"),
            _change(15000, "sentiment", value="neutral"),
        ],
    },
    "item_004": {
        "total_time_ms": 25000,
        "annotation_changes": [_change(3000, "sentiment", value="negative")],
    },
    "item_005": {"total_time_ms": 8000, "annotation_changes": []},
    "item_006": {
        "total_time_ms": 15000,
        "annotation_changes": [_change(4000, "sentiment", value="positive")],
    },
    "item_007": {"total_time_ms": 20000, "annotation_changes": []},
    "item_008": {"total_time_ms": 18000, "annotation_changes": []},
}

USER_2_LABELS = {
    "item_001": [
        ({"schema": "sentiment", "name": "positive"}, True),
        ({"schema": "topics", "name": "food"}, True),
    ],
    "item_002": [
        ({"schema": "sentiment", "name": "positive"}, True),
        ({"schema": "topics", "name": "recommendation"}, True),
    ],
    "item_003": [
        ({"schema": "sentiment", "name": "negative"}, True),
    ],
    "item_004": [
        ({"schema": "sentiment", "name": "neutral"}, True),
        ({"schema": "topics", "name": "food"}, True),
    ],
    "item_005": [
        ({"schema": "sentiment", "name": "negative"}, True),
        ({"schema": "topics", "name": "service"}, True),
    ],
    "item_006": [
        ({"schema": "sentiment", "name": "positive"}, True),
        ({"schema": "topics", "name": "ambiance"}, True),
    ],
    "item_007": [
        ({"schema": "sentiment", "name": "neutral"}, True),
    ],
    "item_008": [
        ({"schema": "sentiment", "name": "positive"}, True),
        ({"schema": "topics", "name": "service"}, True),
    ],
}

# user_2 has very fast annotation times to trigger fast_decision signals
USER_2_BEHAVIORAL = {
    "item_001": {"total_time_ms": 800, "annotation_changes": []},
    "item_002": {"total_time_ms": 1200, "annotation_changes": []},
    "item_003": {"total_time_ms": 900, "annotation_changes": []},
    "item_004": {
        "total_time_ms": 30000,
        "annotation_changes": [
            _change(1000, "sentiment", value="positive"),
            _change(3000, "sentiment", value="negative"),
            _change(6000, "sentiment", value="mixed"),
            _change(10000, "topics", value="price"),
            _change(14000, "topics", "deselect", "price"),
            _change(18000, "sentiment", value="neutral"),
            _change(22000, "topics", value="food"),
        ],
    },
    "item_005": {"total_time_ms": 1500, "annotation_changes": []},
    "item_006": {"total_time_ms": 700, "annotation_changes": []},
    "item_007": {"total_time_ms": 1100, "annotation_changes": []},
    "item_008": {
        "total_time_ms": 15000,
        "annotation_changes": [
            _change(500, "sentiment", value="negative"),
            _change(1500, "sentiment", value="neutral"),
            _change(3000, "sentiment", value="mixed"),
            _change(5000, "sentiment", value="positive"),
            _change(7000, "topics", value="food"),
            _change(8500, "topics", "deselect", "food"),
            _change(10000, "topics", value="service"),
            _change(12000, "sentiment", value="positive"),
        ],
    },
}

# user_3 disagrees strongly with the majority on most items
USER_3_LABELS = {
    "item_001": [
        ({"schema": "sentiment", "name": "negative"}, True),
        ({"schema": "topics", "name": "service"}, True),
    ],
    "item_002": [
        ({"schema": "sentiment", "name": "neutral"}, True),
        ({"schema": "topics", "name": "recommendation"}, True),
    ],
    "item_003": [
        ({"schema": "sentiment", "name": "positive"}, True),
        ({"schema": "topics", "name": "ambiance"}, True),
    ],
    "item_004": [
        ({"schema": "sentiment", "name": "mixed"}, True),
        ({"schema": "topics", "name": "food"}, True),
        ({"schema": "topics", "name": "price"}, True),
    ],
    "item_005": [
        ({"schema": "sentiment", "name": "positive"}, True),
        ({"schema": "topics", "name": "food"}, True),
        ({"schema": "topics", "name": "service"}, True),
    ],
    "item_006": [
        ({"schema": "sentiment", "name": "negative"}, True),
        ({"schema": "topics", "name": "price"}, True),
    ],
    "item_007": [
        ({"schema": "sentiment", "name": "positive"}, True),
        ({"schema": "topics", "name": "recommendation"}, True),
    ],
    "item_008": [
        ({"schema": "sentiment", "name": "negative"}, True),
        ({"schema": "topics", "name": "service"}, True),
    ],
}

USER_3_BEHAVIORAL = {
    "item_001": {
        "total_time_ms": 32000,
        "annotation_changes": [
            _change(1000, "sentiment", value="positive"),
            _change(4000, "sentiment", value="mixed"),
            _change(8000, "topics", value="food"),
            _change(12000, "topics", "deselect", "food"),
            _change(18000, "sentiment", value="negative"),
            _change(24000, "topics", value="service"),
        ],
    },
    "item_002": {
        "total_time_ms": 20000,
        "annotation_changes": [_change(5000, "sentiment", value="neutral")],
    },
    "item_003": {
        "total_time_ms": 40000,
        "annotation_changes": [
            _change(2000, "sentiment", value="negative"),
            _change(10000, "sentiment", value="neutral"),
            _change(20000, "sentiment", value="positive"),
            _change(30000, "topics", value="ambiance"),
        ],
    },
    "item_004": {
        "total_time_ms": 18000,
        "annotation_changes": [
            _change(500, "sentiment", value="positive"),
            _change(1500, "sentiment", value="negative"),
            _change(3000, "sentiment", value="neutral"),
            _change(5000, "topics", value="service"),
            _change(7000, "topics", "deselect", "service"),
            _change(9000, "sentiment", value="mixed"),
            _change(11000, "topics", value="food"),
            _change(13000, "topics", value="price"),
            _change(15000, "sentiment", value="mixed"),
        ],
    },
    "item_005": {
        "total_time_ms": 15000,
        "annotation_changes": [
            _change(3000, "sentiment", value="negative"),
            _change(8000, "sentiment", value="positive"),
        ],
    },
    "item_006": {"total_time_ms": 28000, "annotation_changes": []},
    "item_007": {
        "total_time_ms": 35000,
        "annotation_changes": [_change(10000, "sentiment", value="positive")],
    },
    "item_008": {
        "total_time_ms": 22000,
        "annotation_changes": [
            _change(3000, "sentiment", value="positive"),
            _change(8000, "sentiment", value="negative"),
            _change(15000, "topics", value="service"),
        ],
    },
}


def build_user_state(user_id, labels, behavioral):
    """Build a complete user_state.json dict."""
    state = dict(USER_STATE_TEMPLATE)
    state["user_id"] = user_id
    state["instance_id_ordering"] = list(ITEM_IDS)
    state["current_instance_index"] = len(ITEM_IDS) - 1

    # Convert labels to the list-of-pairs format used by potato
    label_map = {}
    for item_id, pairs in labels.items():
        label_map[item_id] = [[pair[0], pair[1]] for pair in pairs]
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


def clean_decisions():
    """Remove adjudication decisions so the queue is fully pending."""
    adj_dir = os.path.join(OUTPUT_DIR, "adjudication")
    if os.path.exists(adj_dir):
        shutil.rmtree(adj_dir)
        print(f"  Removed {adj_dir}")


def main():
    parser = argparse.ArgumentParser(description="Reset adjudication demo data")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Also remove adjudication decisions",
    )
    args = parser.parse_args()

    print("Generating synthetic annotation data...")

    write_user_state(
        "user_1", build_user_state("user_1", USER_1_LABELS, USER_1_BEHAVIORAL)
    )
    write_user_state(
        "user_2", build_user_state("user_2", USER_2_LABELS, USER_2_BEHAVIORAL)
    )
    write_user_state(
        "user_3", build_user_state("user_3", USER_3_LABELS, USER_3_BEHAVIORAL)
    )

    if args.clean:
        print("Cleaning adjudication decisions...")
        clean_decisions()

    print("Done! Start the server with:")
    print("  python potato/flask_server.py start "
          "examples/advanced/adjudication/config.yaml -p 8000")


if __name__ == "__main__":
    main()
