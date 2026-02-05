"""
Server integration tests for adjudication using the simulator framework.

Uses the simulator to generate multi-annotator annotations with varying
competence levels, then verifies that the adjudication API correctly:
- Builds a queue from disagreement items
- Returns full annotation data per item
- Accepts and persists adjudication decisions
- Tracks progress statistics
- Supports the full adjudicate-submit-next workflow
"""

import json
import os
import pytest
import requests
import yaml

from potato.simulator import SimulatorManager, SimulatorConfig, UserConfig
from potato.simulator.config import (
    CompetenceLevel,
    AnnotationStrategyType,
    BiasedStrategyConfig,
)
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import create_test_directory


# Skip if server tests are disabled
pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_SERVER_TESTS", "0") == "1",
    reason="Server tests skipped via environment variable",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def test_data_dir():
    """Create a test directory for the adjudication simulator tests."""
    test_dir = create_test_directory("adjudication_simulator")
    yield test_dir


@pytest.fixture(scope="module")
def test_data_file(test_data_dir):
    """Create a JSONL data file with 20 items."""
    items = [
        {
            "id": f"item_{i:03d}",
            "text": f"This is test sentence number {i} with some content to annotate.",
        }
        for i in range(20)
    ]
    data_file = os.path.join(test_data_dir, "test_data.jsonl")
    with open(data_file, "w") as f:
        for item in items:
            f.write(json.dumps(item) + "\n")
    return data_file


@pytest.fixture(scope="module")
def test_config(test_data_dir, test_data_file):
    """Create a test config with adjudication enabled and multiple annotators allowed."""
    config = {
        "annotation_task_name": "Adjudication Simulator Test",
        "task_dir": os.path.abspath(test_data_dir),
        "data_files": [os.path.basename(test_data_file)],
        "output_annotation_dir": "output",
        "output_annotation_format": "json",
        "item_properties": {"id_key": "id", "text_key": "text"},
        "annotation_schemes": [
            {
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": [
                    {"name": "positive", "tooltip": "Positive"},
                    {"name": "negative", "tooltip": "Negative"},
                    {"name": "neutral", "tooltip": "Neutral"},
                ],
                "description": "What is the sentiment of this text?",
            }
        ],
        "user_config": {"allow_anonymous": True},
        # Allow 3 annotators per item so the simulator can create overlap
        "max_annotations_per_item": 3,
        # Adjudication config
        "adjudication": {
            "enabled": True,
            "adjudicator_users": ["adj_expert"],
            "min_annotations": 2,
            "agreement_threshold": 0.99,
            "show_all_items": True,  # Show all items so test is deterministic
            "show_annotator_names": True,
            "show_timing_data": True,
            "require_confidence": True,
            "error_taxonomy": ["ambiguous_text", "guideline_gap", "annotator_error"],
        },
        "debug": True,
    }
    config_file = os.path.join(test_data_dir, "config.yaml")
    with open(config_file, "w") as f:
        yaml.dump(config, f)
    return config_file


@pytest.fixture(scope="module")
def flask_server(test_config):
    """Start a Flask server for the tests."""
    server = FlaskTestServer(
        port=find_free_port(), debug=False, config_file=test_config
    )
    started = server.start()
    if not started:
        pytest.skip("Failed to start Flask server")
    yield server
    server.stop()


@pytest.fixture(scope="module")
def simulator_results(flask_server):
    """
    Run the simulator to create annotations from 3 users with biased strategies
    so that they systematically disagree on some items.
    """
    users = [
        UserConfig(
            user_id="sim_user_pos",
            competence=CompetenceLevel.AVERAGE,
            strategy=AnnotationStrategyType.BIASED,
            biased_config=BiasedStrategyConfig(
                label_weights={"positive": 0.8, "negative": 0.1, "neutral": 0.1}
            ),
        ),
        UserConfig(
            user_id="sim_user_neg",
            competence=CompetenceLevel.AVERAGE,
            strategy=AnnotationStrategyType.BIASED,
            biased_config=BiasedStrategyConfig(
                label_weights={"positive": 0.1, "negative": 0.8, "neutral": 0.1}
            ),
        ),
        UserConfig(
            user_id="sim_user_neu",
            competence=CompetenceLevel.AVERAGE,
            strategy=AnnotationStrategyType.RANDOM,
        ),
    ]

    config = SimulatorConfig(
        users=users,
        user_count=3,
        parallel_users=1,
        delay_between_users=0.0,
        simulate_wait=False,
    )

    manager = SimulatorManager(config, flask_server.base_url)
    results = manager.run_sequential(max_annotations_per_user=20)

    # Verify simulator ran
    total = sum(len(r.annotations) for r in results.values())
    assert total > 0, "Simulator should produce annotations"

    return results


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _adj_session(base_url):
    """Return a requests.Session logged in as the adjudicator."""
    s = requests.Session()
    s.post(f"{base_url}/register", data={"email": "adj_expert", "pass": "pass"})
    s.post(f"{base_url}/auth", data={"email": "adj_expert", "pass": "pass"})
    return s


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestQueuePopulation:
    """Verify the adjudication queue is populated from simulator annotations."""

    def test_queue_has_items(self, flask_server, simulator_results):
        """After simulation, the queue should contain items with disagreements."""
        s = _adj_session(flask_server.base_url)
        resp = s.get(f"{flask_server.base_url}/adjudicate/api/queue")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] > 0, "Queue should have items after simulation"

    def test_queue_items_have_multiple_annotators(self, flask_server, simulator_results):
        """Each queued item should have >= min_annotations annotators."""
        s = _adj_session(flask_server.base_url)
        resp = s.get(f"{flask_server.base_url}/adjudicate/api/queue")
        data = resp.json()
        for item in data["items"]:
            assert item["num_annotators"] >= 2, (
                f"Item {item['instance_id']} has only {item['num_annotators']} annotators"
            )

    def test_queue_items_have_annotations(self, flask_server, simulator_results):
        """Each queued item should carry per-annotator label data."""
        s = _adj_session(flask_server.base_url)
        resp = s.get(f"{flask_server.base_url}/adjudicate/api/queue")
        data = resp.json()
        for item in data["items"]:
            assert len(item["annotations"]) >= 2, (
                f"Item {item['instance_id']} has no annotation data"
            )

    def test_queue_sorted_by_agreement(self, flask_server, simulator_results):
        """Queue items should be sorted lowest-agreement first."""
        s = _adj_session(flask_server.base_url)
        resp = s.get(f"{flask_server.base_url}/adjudicate/api/queue")
        data = resp.json()
        items = data["items"]
        if len(items) >= 2:
            agreements = [it["overall_agreement"] for it in items]
            assert agreements == sorted(agreements), "Queue should be sorted by agreement ascending"

    def test_queue_item_structure(self, flask_server, simulator_results):
        """Each queue item must have the full expected schema."""
        s = _adj_session(flask_server.base_url)
        resp = s.get(f"{flask_server.base_url}/adjudicate/api/queue")
        data = resp.json()
        required_fields = [
            "instance_id", "annotations", "span_annotations",
            "behavioral_data", "agreement_scores", "overall_agreement",
            "num_annotators", "status",
        ]
        for item in data["items"]:
            for fld in required_fields:
                assert fld in item, f"Missing field '{fld}' in queue item"


class TestItemDetail:
    """Tests for retrieving individual item details."""

    def test_item_endpoint_returns_full_data(self, flask_server, simulator_results):
        """GET /adjudicate/api/item/<id> should return annotator data."""
        s = _adj_session(flask_server.base_url)
        # Get queue to pick a real item id
        queue = s.get(f"{flask_server.base_url}/adjudicate/api/queue").json()
        if not queue["items"]:
            pytest.skip("No items in queue")
        item_id = queue["items"][0]["instance_id"]

        resp = s.get(f"{flask_server.base_url}/adjudicate/api/item/{item_id}")
        assert resp.status_code == 200
        data = resp.json()
        # Response wraps item in "item" key
        assert "item" in data
        assert data["item"]["instance_id"] == item_id
        assert "annotations" in data["item"]
        assert "agreement_scores" in data["item"]
        assert "item_text" in data

    def test_item_annotations_contain_sentiment(self, flask_server, simulator_results):
        """Annotations in the item detail should include the sentiment schema."""
        s = _adj_session(flask_server.base_url)
        queue = s.get(f"{flask_server.base_url}/adjudicate/api/queue").json()
        if not queue["items"]:
            pytest.skip("No items in queue")
        item_id = queue["items"][0]["instance_id"]

        data = s.get(f"{flask_server.base_url}/adjudicate/api/item/{item_id}").json()
        for user_id, annots in data["item"]["annotations"].items():
            assert "sentiment" in annots, (
                f"User {user_id}'s annotation should contain 'sentiment'"
            )


class TestAdjudicationDecisionWorkflow:
    """End-to-end workflow: pick item → submit decision → verify persistence."""

    def test_submit_decision_on_queued_item(self, flask_server, simulator_results):
        """Submitting a decision on a queued item should succeed."""
        s = _adj_session(flask_server.base_url)
        queue = s.get(f"{flask_server.base_url}/adjudicate/api/queue").json()
        pending = [it for it in queue["items"] if it["status"] == "pending"]
        if not pending:
            pytest.skip("No pending items in queue")

        item_id = pending[0]["instance_id"]
        resp = s.post(
            f"{flask_server.base_url}/adjudicate/api/submit",
            json={
                "instance_id": item_id,
                "label_decisions": {"sentiment": "positive"},
                "source": {"sentiment": "adjudicator"},
                "confidence": "high",
                "notes": "Clear positive sentiment from simulator data",
                "error_taxonomy": ["ambiguous_text"],
                "time_spent_ms": 12000,
            },
        )
        assert resp.status_code == 200, f"Submit failed: {resp.text}"
        data = resp.json()
        assert data.get("status") in ("success", "ok")

    def test_decided_item_shows_completed(self, flask_server, simulator_results):
        """After submitting a decision, the item status should change to completed."""
        s = _adj_session(flask_server.base_url)
        # Submit on second item
        queue = s.get(f"{flask_server.base_url}/adjudicate/api/queue").json()
        pending = [it for it in queue["items"] if it["status"] == "pending"]
        if not pending:
            pytest.skip("No pending items left")
        item_id = pending[0]["instance_id"]

        s.post(
            f"{flask_server.base_url}/adjudicate/api/submit",
            json={
                "instance_id": item_id,
                "label_decisions": {"sentiment": "negative"},
                "source": {"sentiment": "adjudicator"},
                "confidence": "medium",
            },
        )

        # Re-fetch queue (all filter) and check status
        resp = s.get(f"{flask_server.base_url}/adjudicate/api/queue?filter=all")
        data = resp.json()
        decided = [it for it in data["items"] if it["instance_id"] == item_id]
        if decided:
            assert decided[0]["status"] == "completed"

    def test_skip_then_submit(self, flask_server, simulator_results):
        """Skipping and then later submitting on a different item should work."""
        s = _adj_session(flask_server.base_url)
        queue = s.get(f"{flask_server.base_url}/adjudicate/api/queue").json()
        pending = [it for it in queue["items"] if it["status"] == "pending"]
        if len(pending) < 2:
            pytest.skip("Not enough pending items")

        # Skip the first
        skip_id = pending[0]["instance_id"]
        resp = s.post(f"{flask_server.base_url}/adjudicate/api/skip/{skip_id}")
        assert resp.status_code == 200

        # Submit on the second
        submit_id = pending[1]["instance_id"]
        resp = s.post(
            f"{flask_server.base_url}/adjudicate/api/submit",
            json={
                "instance_id": submit_id,
                "label_decisions": {"sentiment": "neutral"},
                "source": {"sentiment": "adjudicator"},
                "confidence": "low",
                "notes": "Ambiguous",
                "error_taxonomy": ["guideline_gap"],
            },
        )
        assert resp.status_code == 200


class TestStatistics:
    """Verify adjudication statistics reflect real progress."""

    def test_stats_reflect_simulation(self, flask_server, simulator_results):
        """Stats endpoint should report the total from the queue."""
        s = _adj_session(flask_server.base_url)
        stats = s.get(f"{flask_server.base_url}/adjudicate/api/stats").json()
        assert stats["total"] > 0
        assert "completed" in stats
        assert "pending" in stats
        assert "completion_rate" in stats
        assert isinstance(stats["completion_rate"], (int, float))

    def test_stats_completed_grows(self, flask_server, simulator_results):
        """After submitting decisions, the completed count should increase."""
        s = _adj_session(flask_server.base_url)
        stats = s.get(f"{flask_server.base_url}/adjudicate/api/stats").json()
        # We submitted at least 2 decisions in TestAdjudicationDecisionWorkflow
        # (test_submit_decision_on_queued_item + test_decided_item_shows_completed)
        assert stats["completed"] >= 1, (
            "Completed count should increase after submissions"
        )


class TestNextItemFlow:
    """Test the /api/next auto-assignment flow."""

    def test_next_returns_pending_item(self, flask_server, simulator_results):
        """Next endpoint should return a pending item or a message."""
        s = _adj_session(flask_server.base_url)
        resp = s.get(f"{flask_server.base_url}/adjudicate/api/next")
        assert resp.status_code == 200
        data = resp.json()
        if data.get("item") is not None:
            assert "instance_id" in data["item"]
            assert data["item"]["status"] == "pending"
        else:
            assert "message" in data

    def test_next_after_full_adjudication(self, flask_server, simulator_results):
        """Adjudicating all remaining items should eventually return 'no items'."""
        s = _adj_session(flask_server.base_url)

        # Submit decisions on up to 30 items (more than the queue should hold)
        for _ in range(30):
            resp = s.get(f"{flask_server.base_url}/adjudicate/api/next")
            data = resp.json()
            if data.get("item") is None:
                break
            item_id = data["item"]["instance_id"]
            s.post(
                f"{flask_server.base_url}/adjudicate/api/submit",
                json={
                    "instance_id": item_id,
                    "label_decisions": {"sentiment": "neutral"},
                    "source": {"sentiment": "adjudicator"},
                    "confidence": "medium",
                },
            )

        # After exhausting the queue, next should say no items
        resp = s.get(f"{flask_server.base_url}/adjudicate/api/next")
        data = resp.json()
        assert "message" in data, "After adjudicating everything, next should return a message"


class TestNonAdjudicatorAccess:
    """Ensure simulator users (regular annotators) cannot access adjudication."""

    def test_simulator_user_cannot_access_queue(self, flask_server, simulator_results):
        """A simulator-created user should get 403 on adjudication API."""
        s = requests.Session()
        s.post(
            f"{flask_server.base_url}/register",
            data={"email": "sim_user_pos", "pass": "simulated_password_123"},
        )
        s.post(
            f"{flask_server.base_url}/auth",
            data={"email": "sim_user_pos", "pass": "simulated_password_123"},
        )
        resp = s.get(f"{flask_server.base_url}/adjudicate/api/queue")
        assert resp.status_code == 403

    def test_simulator_user_cannot_submit_decision(self, flask_server, simulator_results):
        """A regular user should not be able to submit adjudication decisions."""
        s = requests.Session()
        s.post(
            f"{flask_server.base_url}/register",
            data={"email": "sim_user_neg", "pass": "simulated_password_123"},
        )
        s.post(
            f"{flask_server.base_url}/auth",
            data={"email": "sim_user_neg", "pass": "simulated_password_123"},
        )
        resp = s.post(
            f"{flask_server.base_url}/adjudicate/api/submit",
            json={
                "instance_id": "item_000",
                "label_decisions": {"sentiment": "positive"},
            },
        )
        assert resp.status_code == 403
