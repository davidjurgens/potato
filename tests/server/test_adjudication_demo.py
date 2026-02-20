"""
Server integration tests for the Adjudication Demo example.

Starts the server with the real adjudication demo config and validates
that pre-loaded annotation data populates the adjudication queue, that
Phase 3 annotator signals fire correctly, and that decisions can be
submitted and persisted.
"""

import json
import os
import pytest
import requests
import shutil

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port


# Locate the demo config relative to repo root
REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
DEMO_DIR = os.path.join(
    REPO_ROOT, "examples", "advanced", "adjudication"
)
CONFIG_FILE = os.path.join(DEMO_DIR, "config.yaml")


class TestAdjudicationDemo:
    """Integration tests that start the server with the real demo config."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Start the server using the real adjudication demo config."""
        # Clean up any previous adjudication decisions so the queue is fresh
        adj_output = os.path.join(DEMO_DIR, "annotation_output", "adjudication")
        if os.path.exists(adj_output):
            shutil.rmtree(adj_output)

        server = FlaskTestServer(
            port=find_free_port(),
            config_file=CONFIG_FILE,
        )
        if not server.start():
            pytest.fail("Failed to start Flask test server for demo config")

        request.cls.server = server
        request.cls.base_url = server.base_url
        yield server
        server.stop()

        # Clean up decisions written during test
        if os.path.exists(adj_output):
            shutil.rmtree(adj_output)

    # -- helpers --

    def _login(self, session, username):
        """Register + login a user."""
        session.post(
            f"{self.base_url}/register",
            data={"email": username, "pass": "pass"},
        )
        session.post(
            f"{self.base_url}/auth",
            data={"email": username, "pass": "pass"},
        )

    # ================================================================
    # Queue population tests (validates the instance_annotators fix)
    # ================================================================

    def test_queue_is_populated(self):
        """The queue should have items from pre-loaded user state data."""
        session = requests.Session()
        self._login(session, "adjudicator")
        resp = session.get(f"{self.base_url}/adjudicate/api/queue")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] > 0, "Queue should be populated from pre-loaded data"

    def test_queue_items_have_multiple_annotators(self):
        """Every queued item should have >= 2 annotators."""
        session = requests.Session()
        self._login(session, "adjudicator")
        resp = session.get(f"{self.base_url}/adjudicate/api/queue")
        data = resp.json()
        for item in data["items"]:
            assert item["num_annotators"] >= 2, (
                f"Item {item['instance_id']} has only {item['num_annotators']} annotators"
            )

    def test_queue_has_all_eight_items(self):
        """All 8 data items should be in the queue (show_all_items=true)."""
        session = requests.Session()
        self._login(session, "adjudicator")
        resp = session.get(f"{self.base_url}/adjudicate/api/queue")
        data = resp.json()
        ids = {item["instance_id"] for item in data["items"]}
        for i in range(1, 9):
            assert f"item_{i:03d}" in ids, f"item_{i:03d} should be in the queue"

    def test_queue_items_have_three_annotators(self):
        """Every item should have exactly 3 annotators."""
        session = requests.Session()
        self._login(session, "adjudicator")
        resp = session.get(f"{self.base_url}/adjudicate/api/queue")
        data = resp.json()
        for item in data["items"]:
            assert item["num_annotators"] == 3, (
                f"Item {item['instance_id']} should have 3 annotators, "
                f"got {item['num_annotators']}"
            )

    # ================================================================
    # Item detail + Phase 3 fields
    # ================================================================

    def test_item_detail_has_phase3_fields(self):
        """Item detail should include annotator_signals and similar_items."""
        session = requests.Session()
        self._login(session, "adjudicator")
        resp = session.get(f"{self.base_url}/adjudicate/api/item/item_001")
        assert resp.status_code == 200
        data = resp.json()
        assert "annotator_signals" in data
        assert "similar_items" in data
        assert "item_text" in data
        assert "item_data" in data

    def test_item_text_is_correct(self):
        """Item text should match the data file content."""
        session = requests.Session()
        self._login(session, "adjudicator")
        resp = session.get(f"{self.base_url}/adjudicate/api/item/item_001")
        data = resp.json()
        assert "restaurant" in data["item_text"].lower()

    def test_annotator_signals_have_metrics(self):
        """Each annotator's signals should include metrics dict."""
        session = requests.Session()
        self._login(session, "adjudicator")
        resp = session.get(f"{self.base_url}/adjudicate/api/item/item_001")
        data = resp.json()
        signals = data["annotator_signals"]
        assert len(signals) > 0
        for user_id, sig in signals.items():
            assert "metrics" in sig
            assert "flags" in sig
            assert "total_time_ms" in sig["metrics"]

    def test_fast_decision_flag_fires(self):
        """user_2 has times < 2000ms; at least one fast_decision flag should fire."""
        session = requests.Session()
        self._login(session, "adjudicator")
        resp = session.get(f"{self.base_url}/adjudicate/api/item/item_001")
        data = resp.json()
        user_2_signals = data["annotator_signals"].get("user_2", {})
        flag_types = [f["type"] for f in user_2_signals.get("flags", [])]
        assert "fast_decision" in flag_types, (
            f"Expected fast_decision flag for user_2 on item_001, got {flag_types}"
        )

    def test_excessive_changes_flag_fires(self):
        """user_3 has annotation_changes=6 on item_001; excessive_changes should fire."""
        session = requests.Session()
        self._login(session, "adjudicator")
        resp = session.get(f"{self.base_url}/adjudicate/api/item/item_001")
        data = resp.json()
        user_3_signals = data["annotator_signals"].get("user_3", {})
        flag_types = [f["type"] for f in user_3_signals.get("flags", [])]
        assert "excessive_changes" in flag_types, (
            f"Expected excessive_changes flag for user_3 on item_001, got {flag_types}"
        )

    def test_similar_items_empty_when_disabled(self):
        """Similarity is not enabled; similar_items should be empty list."""
        session = requests.Session()
        self._login(session, "adjudicator")
        resp = session.get(f"{self.base_url}/adjudicate/api/item/item_001")
        data = resp.json()
        assert data["similar_items"] == []

    # ================================================================
    # Stats endpoint
    # ================================================================

    def test_stats_endpoint(self):
        """Stats endpoint should return counts matching queue size."""
        session = requests.Session()
        self._login(session, "adjudicator")
        resp = session.get(f"{self.base_url}/adjudicate/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 8
        assert data["pending"] == 8
        assert data["completed"] == 0

    # ================================================================
    # Admin overview endpoint
    # ================================================================

    def test_admin_adjudication_overview(self):
        """Admin adjudication overview should report enabled and queue_stats."""
        session = requests.Session()
        self._login(session, "adjudicator")
        resp = session.get(
            f"{self.base_url}/admin/api/adjudication",
            headers={"X-API-Key": "demo-admin-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("enabled") is True
        assert "queue_stats" in data
        assert data["queue_stats"]["total"] == 8

    # ================================================================
    # Submit a decision
    # ================================================================

    def test_submit_decision(self):
        """Submitting a decision should persist and update queue status."""
        session = requests.Session()
        self._login(session, "adjudicator")

        resp = session.post(
            f"{self.base_url}/adjudicate/api/submit",
            json={
                "instance_id": "item_002",
                "label_decisions": {"sentiment": "positive"},
                "source": {"sentiment": "annotator_user_1"},
                "confidence": "high",
                "notes": "All annotators agree",
                "error_taxonomy": [],
            },
        )
        assert resp.status_code == 200

        # Verify the decision persisted
        resp2 = session.get(f"{self.base_url}/adjudicate/api/item/item_002")
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["decision"] is not None
        assert data["decision"]["confidence"] == "high"
        assert data["item"]["status"] == "completed"

    # ================================================================
    # Access control
    # ================================================================

    def test_non_adjudicator_rejected(self):
        """Regular users should get 403 from adjudication API."""
        session = requests.Session()
        self._login(session, "regular_user")
        resp = session.get(f"{self.base_url}/adjudicate/api/queue")
        assert resp.status_code == 403

    def test_unauthenticated_rejected(self):
        """Unauthenticated requests should get 401."""
        session = requests.Session()
        resp = session.get(f"{self.base_url}/adjudicate/api/queue")
        assert resp.status_code == 401
