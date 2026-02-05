"""
Server integration tests for the MACE Competence Estimation Demo.

Starts the server with the real simple-mace-demo config (which has
pre-loaded annotations from 5 annotators of varying quality) and
validates that MACE correctly differentiates annotator competence
and predicts labels.

Annotator profiles:
  - reliable_1:  Expert, always correct
  - reliable_2:  Good, mostly correct (8/10)
  - moderate:    Average, ~60% correct
  - spammer:     Nearly random answers
  - biased:      Always picks "positive"

Tests:
- MACE trigger processes the sentiment schema
- Overview returns competence scores for all 5 annotators
- Spammer has lowest competence
- Reliable annotators have higher competence than spammer/biased
- Predictions match ground truth for unambiguous items
- Predictions endpoint works with instance_id filter
- Admin auth required for all endpoints
- MACE overview returns correct structure before and after trigger
"""

import os
import pytest
import requests
import shutil

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port


REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
DEMO_DIR = os.path.join(
    REPO_ROOT, "project-hub", "simple_examples", "simple-mace-demo"
)
CONFIG_FILE = os.path.join(DEMO_DIR, "config.yaml")

# Admin API key from the demo config
ADMIN_KEY = "demo-mace-key"

# Ground truth labels for verification
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


class TestMACEDemo:
    """Integration tests that start the server with the real MACE demo config."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Start the server using the real simple-mace-demo config."""
        # Clean any cached MACE results
        mace_output = os.path.join(DEMO_DIR, "annotation_output", "mace")
        if os.path.exists(mace_output):
            shutil.rmtree(mace_output)

        server = FlaskTestServer(
            port=find_free_port(),
            config_file=CONFIG_FILE,
        )
        if not server.start():
            pytest.fail("Failed to start Flask test server for MACE demo config")

        request.cls.server = server
        request.cls.base_url = server.base_url
        yield server
        server.stop()

        # Clean up MACE results written during test
        if os.path.exists(mace_output):
            shutil.rmtree(mace_output)

    # -- helpers --

    def _admin_get(self, path, params=None):
        """Make an admin API GET request."""
        return requests.get(
            f"{self.base_url}{path}",
            headers={"X-API-Key": ADMIN_KEY},
            params=params,
            timeout=10,
        )

    def _admin_post(self, path, json_data=None):
        """Make an admin API POST request."""
        return requests.post(
            f"{self.base_url}{path}",
            headers={"X-API-Key": ADMIN_KEY},
            json=json_data,
            timeout=10,
        )

    # ================================================================
    # Auth Tests
    # ================================================================

    def test_overview_requires_auth(self):
        """Overview endpoint should require admin API key."""
        resp = requests.get(
            f"{self.base_url}/admin/api/mace/overview", timeout=10
        )
        assert resp.status_code == 403

    def test_trigger_requires_auth(self):
        """Trigger endpoint should require admin API key."""
        resp = requests.post(
            f"{self.base_url}/admin/api/mace/trigger", timeout=10
        )
        assert resp.status_code == 403

    def test_predictions_requires_auth(self):
        """Predictions endpoint should require admin API key."""
        resp = requests.get(
            f"{self.base_url}/admin/api/mace/predictions",
            params={"schema": "sentiment"},
            timeout=10,
        )
        assert resp.status_code == 403

    # ================================================================
    # Overview before trigger
    # ================================================================

    def test_overview_before_trigger(self):
        """Overview should show MACE enabled but no results before trigger."""
        resp = self._admin_get("/admin/api/mace/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert "has_results" in data

    # ================================================================
    # Trigger MACE
    # ================================================================

    def test_trigger_processes_sentiment(self):
        """Triggering MACE should process the sentiment schema."""
        resp = self._admin_post("/admin/api/mace/trigger")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["schemas_processed"] == 1
        assert "sentiment" in data["schemas"]

    # ================================================================
    # Competence Scores (run after trigger)
    # ================================================================

    def test_overview_has_results(self):
        """After trigger, overview should show results."""
        # Trigger first to ensure results exist
        self._admin_post("/admin/api/mace/trigger")

        resp = self._admin_get("/admin/api/mace/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_results"] is True
        assert len(data["schemas"]) == 1
        assert data["schemas"][0]["schema_name"] == "sentiment"

    def test_all_annotators_have_scores(self):
        """All 5 pre-loaded annotators should have competence scores."""
        self._admin_post("/admin/api/mace/trigger")
        resp = self._admin_get("/admin/api/mace/overview")
        data = resp.json()

        competence = data["annotator_competence"]
        expected_users = {"reliable_1", "reliable_2", "moderate", "spammer", "biased"}
        assert expected_users.issubset(set(competence.keys())), (
            f"Expected {expected_users} to be subset of {set(competence.keys())}"
        )

    def test_competence_scores_in_range(self):
        """All competence scores should be between 0 and 1."""
        self._admin_post("/admin/api/mace/trigger")
        resp = self._admin_get("/admin/api/mace/overview")
        data = resp.json()

        for user_id, info in data["annotator_competence"].items():
            assert 0.0 <= info["average"] <= 1.0, (
                f"{user_id} competence {info['average']} is out of range"
            )

    def test_spammer_has_lowest_competence(self):
        """Spammer should have the lowest competence score."""
        self._admin_post("/admin/api/mace/trigger")
        resp = self._admin_get("/admin/api/mace/overview")
        data = resp.json()

        competence = data["annotator_competence"]
        spammer_score = competence["spammer"]["average"]
        for user_id, info in competence.items():
            if user_id != "spammer":
                assert spammer_score <= info["average"], (
                    f"Spammer ({spammer_score:.3f}) should have lower "
                    f"competence than {user_id} ({info['average']:.3f})"
                )

    def test_reliable_higher_than_spammer(self):
        """Reliable annotators should have higher competence than spammer."""
        self._admin_post("/admin/api/mace/trigger")
        resp = self._admin_get("/admin/api/mace/overview")
        data = resp.json()

        competence = data["annotator_competence"]
        spammer_score = competence["spammer"]["average"]
        for user_id in ["reliable_1", "reliable_2"]:
            assert competence[user_id]["average"] > spammer_score + 0.1, (
                f"{user_id} ({competence[user_id]['average']:.3f}) should be "
                f"significantly higher than spammer ({spammer_score:.3f})"
            )

    def test_reliable_higher_than_biased(self):
        """Reliable annotators should have higher competence than biased."""
        self._admin_post("/admin/api/mace/trigger")
        resp = self._admin_get("/admin/api/mace/overview")
        data = resp.json()

        competence = data["annotator_competence"]
        biased_score = competence["biased"]["average"]
        for user_id in ["reliable_1", "reliable_2"]:
            assert competence[user_id]["average"] > biased_score, (
                f"{user_id} ({competence[user_id]['average']:.3f}) should be "
                f"higher than biased ({biased_score:.3f})"
            )

    def test_schema_metadata(self):
        """Schema metadata should include annotator/instance counts."""
        self._admin_post("/admin/api/mace/trigger")
        resp = self._admin_get("/admin/api/mace/overview")
        data = resp.json()

        schema_info = data["schemas"][0]
        assert schema_info["num_annotators"] >= 5
        assert schema_info["num_instances"] == 10

    # ================================================================
    # Predictions
    # ================================================================

    def test_predictions_for_sentiment(self):
        """Predictions should return labels for all 10 items."""
        self._admin_post("/admin/api/mace/trigger")
        resp = self._admin_get(
            "/admin/api/mace/predictions",
            params={"schema": "sentiment"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["predicted_labels"]) == 10
        assert len(data["label_entropy"]) == 10

    def test_predictions_match_ground_truth_on_clear_items(self):
        """MACE predictions should match ground truth for clearly positive/negative items."""
        self._admin_post("/admin/api/mace/trigger")
        resp = self._admin_get(
            "/admin/api/mace/predictions",
            params={"schema": "sentiment"},
        )
        data = resp.json()
        preds = data["predicted_labels"]

        # These items have strong consensus among reliable annotators
        clear_items = {
            "review_01": "positive",
            "review_03": "positive",
            "review_05": "negative",
            "review_06": "positive",
            "review_09": "positive",
            "review_10": "negative",
        }
        for item_id, expected_label in clear_items.items():
            assert preds[item_id] == expected_label, (
                f"Expected {item_id} to be '{expected_label}', got '{preds[item_id]}'"
            )

    def test_predictions_entropy_low_for_consensus(self):
        """Items with strong consensus should have low entropy."""
        self._admin_post("/admin/api/mace/trigger")
        resp = self._admin_get(
            "/admin/api/mace/predictions",
            params={"schema": "sentiment"},
        )
        data = resp.json()
        entropy = data["label_entropy"]

        # review_01 and review_03 have strong consensus (4/5 or 5/5 agree)
        for item_id in ["review_01", "review_03", "review_09"]:
            assert entropy[item_id] < 0.5, (
                f"{item_id} should have low entropy, got {entropy[item_id]:.4f}"
            )

    def test_predictions_single_instance(self):
        """Predictions for a single instance should work."""
        self._admin_post("/admin/api/mace/trigger")
        resp = self._admin_get(
            "/admin/api/mace/predictions",
            params={"schema": "sentiment", "instance_id": "review_01"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "predicted_label" in data
        assert "entropy" in data
        assert data["predicted_label"] == "positive"

    def test_predictions_missing_schema(self):
        """Predictions without schema should return 400."""
        resp = self._admin_get("/admin/api/mace/predictions")
        assert resp.status_code == 400

    def test_predictions_unknown_schema(self):
        """Predictions for unknown schema should return error."""
        self._admin_post("/admin/api/mace/trigger")
        resp = self._admin_get(
            "/admin/api/mace/predictions",
            params={"schema": "nonexistent"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data

    # ================================================================
    # Config section in overview
    # ================================================================

    def test_overview_includes_config(self):
        """Overview should include the MACE config parameters."""
        self._admin_post("/admin/api/mace/trigger")
        resp = self._admin_get("/admin/api/mace/overview")
        data = resp.json()

        assert "config" in data
        cfg = data["config"]
        assert cfg["trigger_every_n"] == 5
        assert cfg["min_annotations_per_item"] == 3
        assert cfg["min_items"] == 3
        assert cfg["num_restarts"] == 10
        assert cfg["num_iters"] == 50
