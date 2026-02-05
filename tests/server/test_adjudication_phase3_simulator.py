"""
Server integration tests for Phase 3 adjudication features using the simulator framework.

Uses the simulator to generate multi-annotator annotations with biased strategies
so that items have systematic disagreements, then verifies Phase 3 features:
- Annotator signals (behavioral flags and metrics) in item endpoint
- Similar items endpoint (disabled when not configured)
- Admin adjudication overview endpoint with queue stats, error taxonomy, disagreement patterns
- Signals and admin data updates correctly after decisions are submitted
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


ADMIN_API_KEY = "test-sim-phase3-key"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def test_data_dir():
    """Create a test directory for the Phase 3 adjudication simulator tests."""
    test_dir = create_test_directory("adjudication_phase3_sim")
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
    """Create a test config with adjudication enabled, admin API key, and 3 biased users."""
    config = {
        "annotation_task_name": "Adjudication Phase 3 Simulator Test",
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
        # Admin API key for admin endpoints
        "admin_api_key": ADMIN_API_KEY,
        # Adjudication config
        "adjudication": {
            "enabled": True,
            "adjudicator_users": ["adj_expert"],
            "min_annotations": 2,
            "agreement_threshold": 0.99,
            "show_all_items": True,
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
    so that they systematically disagree on items.
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
            user_id="sim_user_rand",
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


def _get_first_queue_item_id(base_url):
    """Return the instance_id of the first item in the adjudication queue."""
    s = _adj_session(base_url)
    queue = s.get(f"{base_url}/adjudicate/api/queue").json()
    if not queue["items"]:
        return None
    return queue["items"][0]["instance_id"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPhase3ItemEndpoint:
    """Tests that /adjudicate/api/item/<id> includes Phase 3 fields."""

    def test_item_includes_annotator_signals(self, flask_server, simulator_results):
        """Response should contain annotator_signals dict."""
        s = _adj_session(flask_server.base_url)
        item_id = _get_first_queue_item_id(flask_server.base_url)
        if not item_id:
            pytest.skip("No items in queue")

        resp = s.get(f"{flask_server.base_url}/adjudicate/api/item/{item_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "annotator_signals" in data, "Response must include annotator_signals"
        assert isinstance(data["annotator_signals"], dict)

    def test_annotator_signals_structure(self, flask_server, simulator_results):
        """Each annotator signal entry should have user_id, instance_id, flags, metrics."""
        s = _adj_session(flask_server.base_url)
        item_id = _get_first_queue_item_id(flask_server.base_url)
        if not item_id:
            pytest.skip("No items in queue")

        data = s.get(f"{flask_server.base_url}/adjudicate/api/item/{item_id}").json()
        for user_id, signal in data["annotator_signals"].items():
            assert "user_id" in signal, f"Signal for {user_id} missing user_id"
            assert "instance_id" in signal, f"Signal for {user_id} missing instance_id"
            assert "flags" in signal, f"Signal for {user_id} missing flags"
            assert "metrics" in signal, f"Signal for {user_id} missing metrics"
            assert isinstance(signal["flags"], list)
            assert isinstance(signal["metrics"], dict)

    def test_annotator_signals_has_metrics(self, flask_server, simulator_results):
        """Each signal's metrics dict should contain total_time_ms at minimum."""
        s = _adj_session(flask_server.base_url)
        item_id = _get_first_queue_item_id(flask_server.base_url)
        if not item_id:
            pytest.skip("No items in queue")

        data = s.get(f"{flask_server.base_url}/adjudicate/api/item/{item_id}").json()
        for user_id, signal in data["annotator_signals"].items():
            assert "total_time_ms" in signal["metrics"], (
                f"Signal for {user_id} missing total_time_ms in metrics"
            )

    def test_item_includes_similar_items(self, flask_server, simulator_results):
        """Response should contain similar_items list (empty since not configured)."""
        s = _adj_session(flask_server.base_url)
        item_id = _get_first_queue_item_id(flask_server.base_url)
        if not item_id:
            pytest.skip("No items in queue")

        data = s.get(f"{flask_server.base_url}/adjudicate/api/item/{item_id}").json()
        assert "similar_items" in data, "Response must include similar_items"
        assert isinstance(data["similar_items"], list)
        # Similarity is not configured, so the list should be empty
        assert len(data["similar_items"]) == 0, (
            "similar_items should be empty when similarity is not configured"
        )

    def test_annotator_signals_per_annotator(self, flask_server, simulator_results):
        """Signals dict should have an entry for each annotator on the item."""
        s = _adj_session(flask_server.base_url)
        item_id = _get_first_queue_item_id(flask_server.base_url)
        if not item_id:
            pytest.skip("No items in queue")

        data = s.get(f"{flask_server.base_url}/adjudicate/api/item/{item_id}").json()
        item_annotations = data["item"]["annotations"]
        annotator_signals = data["annotator_signals"]

        # Every annotator in the item's annotations should have a signal entry
        for user_id in item_annotations:
            assert user_id in annotator_signals, (
                f"Missing signal entry for annotator {user_id}"
            )


class TestPhase3SimilarEndpoint:
    """Tests for GET /adjudicate/api/similar/<instance_id>."""

    def test_similar_endpoint_returns_structure(self, flask_server, simulator_results):
        """Response should have enabled, instance_id, similar_items, and count."""
        s = _adj_session(flask_server.base_url)
        item_id = _get_first_queue_item_id(flask_server.base_url)
        if not item_id:
            pytest.skip("No items in queue")

        resp = s.get(f"{flask_server.base_url}/adjudicate/api/similar/{item_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data
        assert "instance_id" in data
        assert "similar_items" in data
        assert "count" in data
        assert data["instance_id"] == item_id

    def test_similar_endpoint_disabled_when_not_configured(self, flask_server, simulator_results):
        """When similarity is not configured, enabled should be False and count 0."""
        s = _adj_session(flask_server.base_url)
        item_id = _get_first_queue_item_id(flask_server.base_url)
        if not item_id:
            pytest.skip("No items in queue")

        data = s.get(f"{flask_server.base_url}/adjudicate/api/similar/{item_id}").json()
        assert data["enabled"] is False
        assert data["count"] == 0
        assert data["similar_items"] == []

    def test_similar_endpoint_requires_adjudicator(self, flask_server, simulator_results):
        """A regular simulator user should get 403 on the similar endpoint."""
        s = requests.Session()
        s.post(
            f"{flask_server.base_url}/register",
            data={"email": "sim_user_pos", "pass": "simulated_password_123"},
        )
        s.post(
            f"{flask_server.base_url}/auth",
            data={"email": "sim_user_pos", "pass": "simulated_password_123"},
        )
        resp = s.get(f"{flask_server.base_url}/adjudicate/api/similar/item_000")
        assert resp.status_code == 403

    def test_similar_endpoint_unauthenticated(self, flask_server, simulator_results):
        """An unauthenticated request should get 401."""
        s = requests.Session()
        resp = s.get(f"{flask_server.base_url}/adjudicate/api/similar/item_000")
        assert resp.status_code == 401


class TestPhase3AdminOverview:
    """Tests for GET /admin/api/adjudication using X-API-Key header."""

    def test_overview_returns_enabled(self, flask_server, simulator_results):
        """Admin overview should report enabled as True."""
        resp = requests.get(
            f"{flask_server.base_url}/admin/api/adjudication",
            headers={"X-API-Key": ADMIN_API_KEY},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True

    def test_overview_has_queue_stats(self, flask_server, simulator_results):
        """Admin overview should include queue_stats with total, completed, pending, completion_rate."""
        data = requests.get(
            f"{flask_server.base_url}/admin/api/adjudication",
            headers={"X-API-Key": ADMIN_API_KEY},
        ).json()
        assert "queue_stats" in data
        qs = data["queue_stats"]
        assert "total" in qs
        assert "completed" in qs
        assert "pending" in qs
        assert "completion_rate" in qs
        assert qs["total"] > 0, "Queue should have items after simulation"

    def test_overview_has_adjudicator_details(self, flask_server, simulator_results):
        """Admin overview should include adjudicator_details dict."""
        data = requests.get(
            f"{flask_server.base_url}/admin/api/adjudication",
            headers={"X-API-Key": ADMIN_API_KEY},
        ).json()
        assert "adjudicator_details" in data
        assert isinstance(data["adjudicator_details"], dict)

    def test_overview_has_error_taxonomy_counts(self, flask_server, simulator_results):
        """Admin overview should include error_taxonomy_counts dict."""
        data = requests.get(
            f"{flask_server.base_url}/admin/api/adjudication",
            headers={"X-API-Key": ADMIN_API_KEY},
        ).json()
        assert "error_taxonomy_counts" in data
        assert isinstance(data["error_taxonomy_counts"], dict)

    def test_overview_has_disagreement_patterns(self, flask_server, simulator_results):
        """Admin overview should include disagreement_patterns list with schema/avg_agreement/num_items."""
        data = requests.get(
            f"{flask_server.base_url}/admin/api/adjudication",
            headers={"X-API-Key": ADMIN_API_KEY},
        ).json()
        assert "disagreement_patterns" in data
        patterns = data["disagreement_patterns"]
        assert isinstance(patterns, list)
        assert len(patterns) > 0, "Should have at least one schema pattern"
        for entry in patterns:
            assert "schema" in entry
            assert "avg_agreement" in entry
            assert "num_items" in entry

    def test_overview_has_similarity_stats(self, flask_server, simulator_results):
        """Admin overview should include similarity_stats dict (empty since not configured)."""
        data = requests.get(
            f"{flask_server.base_url}/admin/api/adjudication",
            headers={"X-API-Key": ADMIN_API_KEY},
        ).json()
        assert "similarity_stats" in data
        assert isinstance(data["similarity_stats"], dict)
        # Similarity not configured, so empty
        assert data["similarity_stats"] == {}

    def test_overview_has_guideline_flag_count(self, flask_server, simulator_results):
        """Admin overview should include guideline_flag_count."""
        data = requests.get(
            f"{flask_server.base_url}/admin/api/adjudication",
            headers={"X-API-Key": ADMIN_API_KEY},
        ).json()
        assert "guideline_flag_count" in data
        assert isinstance(data["guideline_flag_count"], int)


class TestPhase3SignalsAfterDecisions:
    """Tests that signals/admin data updates correctly as decisions are submitted."""

    def test_stats_include_adjudicator_after_decisions(self, flask_server, simulator_results):
        """After submitting decisions, admin overview should show the adjudicator with counts."""
        s = _adj_session(flask_server.base_url)

        # Get pending items and submit 2 decisions
        queue = s.get(f"{flask_server.base_url}/adjudicate/api/queue").json()
        pending = [it for it in queue["items"] if it["status"] == "pending"]
        if len(pending) < 2:
            pytest.skip("Not enough pending items for this test")

        for i in range(2):
            item_id = pending[i]["instance_id"]
            s.post(
                f"{flask_server.base_url}/adjudicate/api/submit",
                json={
                    "instance_id": item_id,
                    "label_decisions": {"sentiment": "positive"},
                    "source": {"sentiment": "adjudicator"},
                    "confidence": "high",
                    "notes": f"Phase 3 test decision {i}",
                    "error_taxonomy": ["ambiguous_text"],
                    "time_spent_ms": 5000 + i * 1000,
                },
            )

        # Check admin overview
        data = requests.get(
            f"{flask_server.base_url}/admin/api/adjudication",
            headers={"X-API-Key": ADMIN_API_KEY},
        ).json()

        adj_details = data["adjudicator_details"]
        assert "adj_expert" in adj_details, (
            "adj_expert should appear in adjudicator_details after submissions"
        )
        assert adj_details["adj_expert"]["completed"] >= 2

    def test_error_taxonomy_counts_populated(self, flask_server, simulator_results):
        """After submitting decisions with error_taxonomy tags, they appear in overview."""
        s = _adj_session(flask_server.base_url)

        # Submit a decision with a specific error taxonomy
        queue = s.get(f"{flask_server.base_url}/adjudicate/api/queue").json()
        pending = [it for it in queue["items"] if it["status"] == "pending"]
        if not pending:
            pytest.skip("No pending items for this test")

        item_id = pending[0]["instance_id"]
        s.post(
            f"{flask_server.base_url}/adjudicate/api/submit",
            json={
                "instance_id": item_id,
                "label_decisions": {"sentiment": "negative"},
                "source": {"sentiment": "adjudicator"},
                "confidence": "medium",
                "error_taxonomy": ["guideline_gap", "annotator_error"],
                "time_spent_ms": 8000,
            },
        )

        # Check admin overview
        data = requests.get(
            f"{flask_server.base_url}/admin/api/adjudication",
            headers={"X-API-Key": ADMIN_API_KEY},
        ).json()

        counts = data["error_taxonomy_counts"]
        assert len(counts) > 0, "error_taxonomy_counts should be populated after submissions"
        # We submitted "ambiguous_text" in earlier test and "guideline_gap" here
        assert "ambiguous_text" in counts or "guideline_gap" in counts, (
            "At least one of our submitted taxonomy tags should appear"
        )

    def test_guideline_flag_count(self, flask_server, simulator_results):
        """After submitting a decision with guideline_update_flag, the count increments."""
        s = _adj_session(flask_server.base_url)

        # Get baseline guideline_flag_count
        baseline = requests.get(
            f"{flask_server.base_url}/admin/api/adjudication",
            headers={"X-API-Key": ADMIN_API_KEY},
        ).json()
        baseline_count = baseline.get("guideline_flag_count", 0)

        # Submit a decision with guideline_update_flag=True
        queue = s.get(f"{flask_server.base_url}/adjudicate/api/queue").json()
        pending = [it for it in queue["items"] if it["status"] == "pending"]
        if not pending:
            pytest.skip("No pending items for this test")

        item_id = pending[0]["instance_id"]
        resp = s.post(
            f"{flask_server.base_url}/adjudicate/api/submit",
            json={
                "instance_id": item_id,
                "label_decisions": {"sentiment": "neutral"},
                "source": {"sentiment": "adjudicator"},
                "confidence": "low",
                "notes": "Guideline needs clarification",
                "error_taxonomy": ["guideline_gap"],
                "guideline_update_flag": True,
                "guideline_update_notes": "Unclear definition of neutral",
                "time_spent_ms": 15000,
            },
        )
        assert resp.status_code == 200

        # Check guideline_flag_count increased
        data = requests.get(
            f"{flask_server.base_url}/admin/api/adjudication",
            headers={"X-API-Key": ADMIN_API_KEY},
        ).json()
        assert data["guideline_flag_count"] > baseline_count, (
            "guideline_flag_count should increment after submitting with guideline_update_flag"
        )

    def test_disagreement_patterns_has_sentiment(self, flask_server, simulator_results):
        """Disagreement patterns should include the sentiment schema entry."""
        data = requests.get(
            f"{flask_server.base_url}/admin/api/adjudication",
            headers={"X-API-Key": ADMIN_API_KEY},
        ).json()
        patterns = data["disagreement_patterns"]
        schema_names = [p["schema"] for p in patterns]
        assert "sentiment" in schema_names, (
            "disagreement_patterns should include the 'sentiment' schema"
        )

        # Find the sentiment entry and verify its structure
        sentiment_entry = [p for p in patterns if p["schema"] == "sentiment"][0]
        assert isinstance(sentiment_entry["avg_agreement"], float)
        assert sentiment_entry["num_items"] > 0
