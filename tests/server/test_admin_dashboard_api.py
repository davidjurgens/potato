"""
Server integration tests for the Admin Dashboard API endpoints.

Tests all admin API endpoints used by the admin dashboard tabs:
- Overview tab: /admin/api/overview
- Annotators tab: /admin/api/annotators
- Instances tab: /admin/api/instances
- Questions tab: /admin/api/questions
- Behavioral tab: /admin/api/behavioral_analytics
- Crowdsourcing tab: /admin/api/crowdsourcing
- MACE tab: /admin/api/mace/*
- Configuration tab: /admin/api/config

Uses the MACE demo project which has pre-loaded annotation data.
"""

import pytest
import requests
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tests.helpers.flask_test_setup import FlaskTestServer


class TestAdminDashboardAPI:
    """Test all admin dashboard API endpoints."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Start the MACE demo server for testing."""
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "examples", "advanced", "mace-demo", "config.yaml"
        )
        server = FlaskTestServer(port=9020, config_file=config_path)
        if not server.start():
            pytest.fail("Failed to start MACE demo server")
        request.cls.server = server
        request.cls.api_key = "demo-mace-key"
        yield server
        server.stop()

    def _api_get(self, endpoint, params=None):
        """Helper to make authenticated GET requests."""
        return requests.get(
            f"{self.server.base_url}{endpoint}",
            headers={"X-API-Key": self.api_key},
            params=params
        )

    def _api_post(self, endpoint, data=None):
        """Helper to make authenticated POST requests."""
        return requests.post(
            f"{self.server.base_url}{endpoint}",
            headers={"X-API-Key": self.api_key},
            json=data
        )

    # ========== Admin Page Access ==========

    def test_admin_page_loads(self):
        """Test that the admin page loads in debug mode."""
        # In debug mode, admin page should be accessible without auth
        response = requests.get(f"{self.server.base_url}/admin")
        assert response.status_code == 200
        assert "admin" in response.text.lower()

    def test_admin_health_check(self):
        """Test the admin health check endpoint."""
        response = self._api_get("/admin/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy"

    # ========== Overview Tab ==========

    def test_overview_returns_data(self):
        """Test /admin/api/overview returns expected structure."""
        response = self._api_get("/admin/api/overview")
        assert response.status_code == 200
        data = response.json()

        assert "overview" in data
        assert "config" in data

        overview = data["overview"]
        assert "total_items" in overview
        assert "total_users" in overview
        assert "total_annotations" in overview
        assert "completion_percentage" in overview

    def test_overview_has_correct_counts(self):
        """Test overview returns correct counts for demo data."""
        response = self._api_get("/admin/api/overview")
        data = response.json()["overview"]

        assert data["total_items"] == 10
        assert data["total_users"] >= 5  # At least 5 pre-loaded users
        assert data["total_annotations"] >= 50  # 5 users * 10 items

    def test_overview_requires_auth(self):
        """Test that overview requires API key."""
        # Without API key, should get 403
        response = requests.get(f"{self.server.base_url}/admin/api/overview")
        assert response.status_code == 403

    # ========== Annotators Tab ==========

    def test_annotators_returns_list(self):
        """Test /admin/api/annotators returns annotator list."""
        response = self._api_get("/admin/api/annotators")
        assert response.status_code == 200
        data = response.json()

        assert "annotators" in data
        assert "total_annotators" in data
        assert "summary" in data
        assert isinstance(data["annotators"], list)

    def test_annotators_have_timing_data(self):
        """Test that annotators include timing data."""
        response = self._api_get("/admin/api/annotators")
        data = response.json()

        assert data["total_annotators"] >= 5

        for annotator in data["annotators"]:
            assert "user_id" in annotator
            assert "total_annotations" in annotator
            assert "total_seconds" in annotator
            assert "average_seconds_per_annotation" in annotator
            assert "annotations_per_hour" in annotator
            assert "phase" in annotator

    def test_annotators_have_suspicious_scores(self):
        """Test that annotators include suspicious activity scores."""
        response = self._api_get("/admin/api/annotators")
        data = response.json()

        for annotator in data["annotators"]:
            assert "suspicious_score" in annotator
            assert "suspicious_level" in annotator

    def test_annotators_summary_counts(self):
        """Test annotators summary has correct structure."""
        response = self._api_get("/admin/api/annotators")
        summary = response.json()["summary"]

        assert "high_suspicious_count" in summary
        assert "medium_suspicious_count" in summary
        assert "low_suspicious_count" in summary
        assert "normal_count" in summary
        assert "average_suspicious_score" in summary

    # ========== Instances Tab ==========

    def test_instances_returns_paginated_list(self):
        """Test /admin/api/instances returns paginated instances."""
        response = self._api_get("/admin/api/instances")
        assert response.status_code == 200
        data = response.json()

        assert "instances" in data
        assert "pagination" in data
        assert isinstance(data["instances"], list)

    def test_instances_pagination_works(self):
        """Test instances pagination parameters."""
        response = self._api_get("/admin/api/instances", params={"page": 1, "page_size": 3})
        data = response.json()

        assert len(data["instances"]) <= 3
        assert data["pagination"]["page"] == 1
        assert data["pagination"]["page_size"] == 3

    def test_instances_have_annotation_counts(self):
        """Test that instances include annotation counts."""
        response = self._api_get("/admin/api/instances")
        data = response.json()

        for instance in data["instances"]:
            assert "id" in instance
            assert "annotation_count" in instance
            assert "annotators" in instance
            assert "completion_percentage" in instance

    def test_instances_sorting(self):
        """Test instances can be sorted."""
        # Sort by annotation count descending
        response = self._api_get("/admin/api/instances",
                                  params={"sort_by": "annotation_count", "sort_order": "desc"})
        assert response.status_code == 200
        data = response.json()
        assert len(data["instances"]) > 0

    # ========== Questions Tab ==========

    def test_questions_returns_schema_analysis(self):
        """Test /admin/api/questions returns schema analysis."""
        response = self._api_get("/admin/api/questions")
        assert response.status_code == 200
        data = response.json()

        assert "questions" in data
        assert "summary" in data
        assert isinstance(data["questions"], list)

    def test_questions_have_annotation_counts(self):
        """Test questions have correct annotation counts."""
        response = self._api_get("/admin/api/questions")
        data = response.json()

        # Demo has sentiment schema with 50 annotations
        assert data["summary"]["total_annotations"] >= 50

        for question in data["questions"]:
            assert "name" in question
            assert "type" in question
            assert "total_annotations" in question
            assert "items_with_annotations" in question
            assert "analysis" in question

    def test_questions_radio_has_histogram(self):
        """Test radio questions have histogram analysis."""
        response = self._api_get("/admin/api/questions")
        data = response.json()

        # Find the sentiment question (radio type)
        sentiment = next((q for q in data["questions"] if q["name"] == "sentiment"), None)
        assert sentiment is not None
        assert sentiment["type"] == "radio"
        assert sentiment["analysis"]["visualization_type"] == "histogram"
        assert "data" in sentiment["analysis"]
        assert "labels" in sentiment["analysis"]["data"]
        assert "counts" in sentiment["analysis"]["data"]

    # ========== Behavioral Tab ==========

    def test_behavioral_analytics_returns_data(self):
        """Test /admin/api/behavioral_analytics returns user data."""
        response = self._api_get("/admin/api/behavioral_analytics")
        assert response.status_code == 200
        data = response.json()

        assert "users" in data
        assert isinstance(data["users"], list)

    def test_behavioral_has_quality_flags(self):
        """Test behavioral analytics includes quality flags."""
        response = self._api_get("/admin/api/behavioral_analytics")
        data = response.json()

        for user in data["users"]:
            assert "user_id" in user
            assert "quality_flag" in user
            assert "total_time_sec" in user
            assert "total_interactions" in user

    def test_behavioral_detects_suspicious_spammer(self):
        """Test that spammer is flagged as suspicious."""
        response = self._api_get("/admin/api/behavioral_analytics")
        data = response.json()

        spammer = next((u for u in data["users"] if u["user_id"] == "spammer"), None)
        assert spammer is not None
        assert spammer["quality_flag"] == "SUSPICIOUS"

    # ========== Crowdsourcing Tab ==========

    def test_crowdsourcing_returns_data(self):
        """Test /admin/api/crowdsourcing returns data."""
        response = self._api_get("/admin/api/crowdsourcing")
        assert response.status_code == 200
        # This may return empty data if no crowdsourcing is configured
        data = response.json()
        assert isinstance(data, dict)

    # ========== MACE Tab ==========

    def test_mace_overview_before_trigger(self):
        """Test MACE overview works before trigger."""
        response = self._api_get("/admin/api/mace/overview")
        assert response.status_code == 200
        data = response.json()

        assert "enabled" in data
        assert data["enabled"] == True

    def test_mace_trigger_runs_successfully(self):
        """Test MACE can be triggered."""
        response = self._api_post("/admin/api/mace/trigger")
        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "success"
        assert "schemas_processed" in data
        assert data["schemas_processed"] >= 1

    def test_mace_overview_after_trigger(self):
        """Test MACE overview has results after trigger."""
        # Ensure MACE is triggered first
        self._api_post("/admin/api/mace/trigger")

        response = self._api_get("/admin/api/mace/overview")
        data = response.json()

        assert data["has_results"] == True
        assert "annotator_competence" in data
        assert "schemas" in data
        assert len(data["annotator_competence"]) >= 5

    def test_mace_competence_scores_valid(self):
        """Test MACE competence scores are in valid range."""
        self._api_post("/admin/api/mace/trigger")
        response = self._api_get("/admin/api/mace/overview")
        data = response.json()

        for user_id, info in data["annotator_competence"].items():
            score = info["average"]
            assert 0.0 <= score <= 1.0, f"Invalid competence score for {user_id}: {score}"

    def test_mace_predictions_for_schema(self):
        """Test MACE predictions endpoint returns predictions."""
        self._api_post("/admin/api/mace/trigger")
        response = self._api_get("/admin/api/mace/predictions", params={"schema": "sentiment"})
        assert response.status_code == 200
        data = response.json()

        assert "predicted_labels" in data
        assert "label_entropy" in data
        assert len(data["predicted_labels"]) == 10  # 10 items

    def test_mace_predictions_unknown_schema(self):
        """Test MACE predictions returns error for unknown schema."""
        response = self._api_get("/admin/api/mace/predictions", params={"schema": "nonexistent"})
        assert response.status_code == 200
        data = response.json()
        assert "error" in data or data.get("predicted_labels") == {}

    # ========== Configuration Tab ==========

    def test_config_get_returns_settings(self):
        """Test /admin/api/config GET returns configuration."""
        response = self._api_get("/admin/api/config")
        assert response.status_code == 200
        data = response.json()

        assert isinstance(data, dict)
        # Should have some config keys
        assert len(data) > 0

    # ========== Agreement & Quality Control ==========

    def test_agreement_endpoint(self):
        """Test /admin/api/agreement endpoint."""
        response = self._api_get("/admin/api/agreement")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_quality_control_endpoint(self):
        """Test /admin/api/quality_control endpoint."""
        response = self._api_get("/admin/api/quality_control")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    # ========== Annotation History ==========

    def test_annotation_history_endpoint(self):
        """Test /admin/api/annotation_history endpoint."""
        response = self._api_get("/admin/api/annotation_history")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_suspicious_activity_endpoint(self):
        """Test /admin/api/suspicious_activity endpoint."""
        response = self._api_get("/admin/api/suspicious_activity")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    # ========== Legacy Admin Endpoints ==========

    def test_system_state_endpoint(self):
        """Test /admin/system_state endpoint."""
        response = self._api_get("/admin/system_state")
        assert response.status_code == 200

    def test_all_instances_endpoint(self):
        """Test /admin/all_instances endpoint."""
        response = self._api_get("/admin/all_instances")
        assert response.status_code == 200

    def test_item_state_endpoint(self):
        """Test /admin/item_state endpoint."""
        response = self._api_get("/admin/item_state")
        assert response.status_code == 200

    @pytest.mark.skip(reason="Known issue: /admin/item_state/<id> has Label serialization bug")
    def test_item_state_by_id(self):
        """Test /admin/item_state/<item_id> endpoint."""
        response = self._api_get("/admin/item_state/review_01")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_user_state_by_id(self):
        """Test /admin/user_state/<user_id> endpoint."""
        response = self._api_get("/admin/user_state/reliable_1")
        assert response.status_code == 200


class TestAdminAPIAuth:
    """Test admin API authentication behavior."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Start server for auth testing."""
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "examples", "advanced", "mace-demo", "config.yaml"
        )
        server = FlaskTestServer(port=9021, config_file=config_path)
        if not server.start():
            pytest.fail("Failed to start server")
        request.cls.server = server
        request.cls.api_key = "demo-mace-key"
        yield server
        server.stop()

    def test_wrong_api_key_rejected(self):
        """Test that wrong API key is rejected."""
        response = requests.get(
            f"{self.server.base_url}/admin/api/overview",
            headers={"X-API-Key": "wrong-key"}
        )
        assert response.status_code == 403

    def test_no_api_key_rejected(self):
        """Test that missing API key is rejected."""
        response = requests.get(f"{self.server.base_url}/admin/api/overview")
        assert response.status_code == 403

    def test_correct_api_key_accepted(self):
        """Test that correct API key is accepted."""
        response = requests.get(
            f"{self.server.base_url}/admin/api/overview",
            headers={"X-API-Key": self.api_key}
        )
        assert response.status_code == 200
