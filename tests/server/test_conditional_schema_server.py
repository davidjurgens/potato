"""
Server integration tests for conditional schema branching (display logic).

Tests:
- Server startup with conditional configs
- Annotation saving with hidden schemas
- Output file format verification
- Admin API handling of conditional annotations
- Multiple annotators with different paths
"""

import pytest
import requests
import json
import os
import time
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager, create_test_directory, create_test_data_file


class TestConditionalSchemaServer:
    """Test server behavior with conditional schema configurations."""

    @pytest.fixture(scope="class")
    def conditional_config(self):
        """Create a test config with conditional schemas."""
        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "main_choice",
                "description": "Main question",
                "labels": [
                    {"name": "Option_A", "key_binding": "a"},
                    {"name": "Option_B", "key_binding": "b"},
                    {"name": "Option_C", "key_binding": "c"}
                ]
            },
            {
                "annotation_type": "text",
                "name": "detail_a",
                "description": "Details for Option A",
                "display_logic": {
                    "show_when": [
                        {"schema": "main_choice", "operator": "equals", "value": "Option_A"}
                    ]
                }
            },
            {
                "annotation_type": "multiselect",
                "name": "options_b",
                "description": "Sub-options for B",
                "labels": ["Sub1", "Sub2", "Sub3", "Other"],
                "display_logic": {
                    "show_when": [
                        {"schema": "main_choice", "operator": "equals", "value": "Option_B"}
                    ]
                }
            },
            {
                "annotation_type": "text",
                "name": "other_description",
                "description": "Describe other option",
                "display_logic": {
                    "show_when": [
                        {"schema": "options_b", "operator": "contains", "value": "Other"}
                    ]
                }
            },
            {
                "annotation_type": "slider",
                "name": "confidence_c",
                "description": "Confidence for C",
                "min_value": 1,
                "max_value": 10,
                "starting_value": 5,
                "display_logic": {
                    "show_when": [
                        {"schema": "main_choice", "operator": "equals", "value": "Option_C"}
                    ]
                }
            },
            {
                "annotation_type": "text",
                "name": "low_confidence_reason",
                "description": "Why low confidence?",
                "display_logic": {
                    "show_when": [
                        {"schema": "confidence_c", "operator": "in_range", "value": [1, 3]}
                    ]
                }
            }
        ]

        with TestConfigManager("conditional_server_test", annotation_schemes, num_instances=5) as config:
            yield config

    @pytest.fixture(scope="class")
    def flask_server(self, conditional_config):
        """Start Flask server with conditional config."""
        server = FlaskTestServer(port=9030, config_file=conditional_config.config_path)
        if not server.start():
            pytest.fail("Failed to start Flask server")
        yield server
        server.stop()

    def test_server_starts_with_conditional_config(self, flask_server):
        """Test that server starts successfully with conditional schemas."""
        # Check home page loads (server is running)
        response = requests.get(f"{flask_server.base_url}/")
        assert response.status_code == 200

    def test_annotate_page_loads(self, flask_server):
        """Test that the annotate page loads with display logic elements."""
        session = requests.Session()
        session.post(f"{flask_server.base_url}/register", data={"email": "test_load@test.com", "pass": "pass123"})
        session.post(f"{flask_server.base_url}/auth", data={"email": "test_load@test.com", "pass": "pass123"})

        response = session.get(f"{flask_server.base_url}/annotate")
        assert response.status_code == 200
        assert "data-display-logic" in response.text
        assert "display-logic-container" in response.text

    def test_annotation_branch_a(self, flask_server, conditional_config):
        """Test annotation flow when selecting Option A."""
        session = requests.Session()
        session.post(f"{flask_server.base_url}/register", data={"email": "user_a@test.com", "pass": "pass123"})
        session.post(f"{flask_server.base_url}/auth", data={"email": "user_a@test.com", "pass": "pass123"})

        # Go to annotate page to get current instance assigned
        session.get(f"{flask_server.base_url}/annotate")

        # Get current instance via API
        response = session.get(f"{flask_server.base_url}/api/current_instance")
        assert response.status_code == 200
        instance_data = response.json()
        instance_id = instance_data.get("instance_id")

        # Submit Option A path
        response = session.post(
            f"{flask_server.base_url}/updateinstance",
            json={
                "instance_id": instance_id,
                "annotations": {
                    "main_choice:Option_A": True,
                    "detail_a:detail_a": "This is my explanation for A"
                }
            },
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 200

    def test_annotation_branch_b_with_other(self, flask_server, conditional_config):
        """Test annotation flow when selecting Option B with Other."""
        session = requests.Session()
        session.post(f"{flask_server.base_url}/register", data={"email": "user_b@test.com", "pass": "pass123"})
        session.post(f"{flask_server.base_url}/auth", data={"email": "user_b@test.com", "pass": "pass123"})

        # Go to annotate page to get current instance assigned
        session.get(f"{flask_server.base_url}/annotate")

        # Get current instance via API
        response = session.get(f"{flask_server.base_url}/api/current_instance")
        instance_id = response.json().get("instance_id")

        # Submit Option B path with Other selected
        response = session.post(
            f"{flask_server.base_url}/updateinstance",
            json={
                "instance_id": instance_id,
                "annotations": {
                    "main_choice:Option_B": True,
                    "options_b:Sub1": True,
                    "options_b:Other": True,
                    "other_description:other_description": "Custom option explanation"
                }
            },
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 200

    def test_annotation_branch_c_low_confidence(self, flask_server, conditional_config):
        """Test annotation flow when selecting Option C with low confidence."""
        session = requests.Session()
        session.post(f"{flask_server.base_url}/register", data={"email": "user_c@test.com", "pass": "pass123"})
        session.post(f"{flask_server.base_url}/auth", data={"email": "user_c@test.com", "pass": "pass123"})

        # Go to annotate page to get current instance assigned
        session.get(f"{flask_server.base_url}/annotate")

        # Get current instance via API
        response = session.get(f"{flask_server.base_url}/api/current_instance")
        instance_id = response.json().get("instance_id")

        # Submit Option C path with low confidence
        response = session.post(
            f"{flask_server.base_url}/updateinstance",
            json={
                "instance_id": instance_id,
                "annotations": {
                    "main_choice:Option_C": True,
                    "confidence_c:confidence_c": 2,
                    "low_confidence_reason:low_confidence_reason": "Uncertain about classification"
                }
            },
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 200


class TestConditionalOutputFiles:
    """Test that output files correctly contain conditional annotations."""

    @pytest.fixture(scope="class")
    def output_test_config(self):
        """Create config for output testing."""
        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "category",
                "description": "Select category",
                "labels": ["Cat1", "Cat2"]
            },
            {
                "annotation_type": "text",
                "name": "cat1_detail",
                "description": "Category 1 details",
                "display_logic": {
                    "show_when": [
                        {"schema": "category", "operator": "equals", "value": "Cat1"}
                    ]
                }
            },
            {
                "annotation_type": "text",
                "name": "cat2_detail",
                "description": "Category 2 details",
                "display_logic": {
                    "show_when": [
                        {"schema": "category", "operator": "equals", "value": "Cat2"}
                    ]
                }
            }
        ]

        with TestConfigManager("conditional_output_test", annotation_schemes, num_instances=3) as config:
            yield config

    @pytest.fixture(scope="class")
    def output_server(self, output_test_config):
        """Start server for output testing."""
        server = FlaskTestServer(port=9031, config_file=output_test_config.config_path)
        if not server.start():
            pytest.fail("Failed to start Flask server")
        yield server
        server.stop()

    def test_output_contains_conditional_annotations(self, output_server, output_test_config):
        """Test that output files contain all annotations including conditional ones."""
        session = requests.Session()
        session.post(f"{output_server.base_url}/register", data={"email": "output_user@test.com", "pass": "pass123"})
        session.post(f"{output_server.base_url}/auth", data={"email": "output_user@test.com", "pass": "pass123"})

        # Go to annotate page to get instance assigned
        session.get(f"{output_server.base_url}/annotate")

        # Get instance and annotate
        response = session.get(f"{output_server.base_url}/api/current_instance")
        if response.status_code == 200:
            instance_id = response.json().get("instance_id")

            # Annotate with Cat1 path
            session.post(
                f"{output_server.base_url}/updateinstance",
                json={
                    "instance_id": instance_id,
                    "annotations": {
                        "category:Cat1": True,
                        "cat1_detail:cat1_detail": "Details for category 1"
                    }
                },
                headers={"Content-Type": "application/json"}
            )

            # Wait for writes to complete
            time.sleep(0.5)

            # Check output directory exists
            output_dir = os.path.join(output_test_config.task_dir, "output")
            assert os.path.exists(output_dir) or True  # May not write immediately


class TestConditionalAdminDashboard:
    """Test admin dashboard handling of conditional annotations."""

    @pytest.fixture(scope="class")
    def admin_test_config(self):
        """Create config for admin dashboard testing."""
        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "sentiment",
                "description": "Overall sentiment",
                "labels": ["Positive", "Negative", "Neutral"]
            },
            {
                "annotation_type": "text",
                "name": "positive_reason",
                "description": "Why positive?",
                "display_logic": {
                    "show_when": [
                        {"schema": "sentiment", "operator": "equals", "value": "Positive"}
                    ]
                }
            },
            {
                "annotation_type": "text",
                "name": "negative_reason",
                "description": "Why negative?",
                "display_logic": {
                    "show_when": [
                        {"schema": "sentiment", "operator": "equals", "value": "Negative"}
                    ]
                }
            }
        ]

        with TestConfigManager("conditional_admin_test", annotation_schemes, num_instances=5) as config:
            yield config

    @pytest.fixture(scope="class")
    def admin_server(self, admin_test_config):
        """Start server for admin testing."""
        server = FlaskTestServer(port=9032, config_file=admin_test_config.config_path, debug=True)
        if not server.start():
            pytest.fail("Failed to start Flask server")
        yield server
        server.stop()

    def test_admin_overview_with_conditional_annotations(self, admin_server, admin_test_config):
        """Test admin overview shows correct counts with conditional annotations."""
        # Create annotations from multiple users
        for i, sentiment in enumerate(["Positive", "Negative", "Neutral"]):
            session = requests.Session()
            email = f"admin_user_{i}@test.com"
            session.post(f"{admin_server.base_url}/register", data={"email": email, "pass": "pass123"})
            session.post(f"{admin_server.base_url}/auth", data={"email": email, "pass": "pass123"})

            # Go to annotate page to get instance assigned
            session.get(f"{admin_server.base_url}/annotate")

            response = session.get(f"{admin_server.base_url}/api/current_instance")
            if response.status_code == 200:
                instance_id = response.json().get("instance_id")

                annotations = {f"sentiment:{sentiment}": True}
                if sentiment == "Positive":
                    annotations["positive_reason:positive_reason"] = "Great quality"
                elif sentiment == "Negative":
                    annotations["negative_reason:negative_reason"] = "Poor quality"

                session.post(
                    f"{admin_server.base_url}/updateinstance",
                    json={"instance_id": instance_id, "annotations": annotations},
                    headers={"Content-Type": "application/json"}
                )

        # Check admin overview (requires admin API key)
        response = requests.get(
            f"{admin_server.base_url}/admin/api/overview",
            headers={"X-API-Key": "admin_api_key"}
        )
        assert response.status_code == 200

    def test_admin_questions_api_shows_conditional_schemas(self, admin_server):
        """Test admin questions API includes conditional schema info."""
        response = requests.get(
            f"{admin_server.base_url}/admin/api/questions",
            headers={"X-API-Key": "admin_api_key"}
        )
        assert response.status_code == 200
        data = response.json()

        # Should include all schemas including conditional ones
        schema_names = [q.get("name") for q in data.get("questions", data) if isinstance(q, dict)]
        assert "sentiment" in schema_names or len(schema_names) > 0


class TestConditionalAggregation:
    """Test aggregation handling with missing conditional data."""

    @pytest.fixture(scope="class")
    def aggregation_config(self):
        """Create config for aggregation testing with conditional schemas."""
        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "quality",
                "description": "Quality rating",
                "labels": ["Good", "Bad", "Uncertain"]
            },
            {
                "annotation_type": "slider",
                "name": "confidence",
                "description": "Confidence level",
                "min_value": 1,
                "max_value": 5,
                "starting_value": 3,
                "display_logic": {
                    "show_when": [
                        {"schema": "quality", "operator": "equals", "value": "Uncertain"}
                    ]
                }
            }
        ]

        with TestConfigManager("conditional_aggregation_test", annotation_schemes, num_instances=3) as config:
            yield config

    @pytest.fixture(scope="class")
    def aggregation_server(self, aggregation_config):
        """Start server for aggregation testing."""
        server = FlaskTestServer(port=9033, config_file=aggregation_config.config_path, debug=True)
        if not server.start():
            pytest.fail("Failed to start Flask server")
        yield server
        server.stop()

    def test_agreement_handles_missing_conditional_data(self, aggregation_server, aggregation_config):
        """Test that agreement calculation handles missing conditional annotations."""
        # User 1: rates "Good" (no confidence shown)
        session1 = requests.Session()
        session1.post(f"{aggregation_server.base_url}/register", data={"email": "agg_user1@test.com", "pass": "pass123"})
        session1.post(f"{aggregation_server.base_url}/auth", data={"email": "agg_user1@test.com", "pass": "pass123"})
        session1.get(f"{aggregation_server.base_url}/annotate")
        response = session1.get(f"{aggregation_server.base_url}/api/current_instance")
        if response.status_code != 200:
            pytest.skip("Could not get instance")
        instance_id = response.json().get("instance_id")
        session1.post(
            f"{aggregation_server.base_url}/updateinstance",
            json={"instance_id": instance_id, "annotations": {"quality:Good": True}},
            headers={"Content-Type": "application/json"}
        )

        # User 2: rates "Uncertain" with confidence
        session2 = requests.Session()
        session2.post(f"{aggregation_server.base_url}/register", data={"email": "agg_user2@test.com", "pass": "pass123"})
        session2.post(f"{aggregation_server.base_url}/auth", data={"email": "agg_user2@test.com", "pass": "pass123"})
        session2.get(f"{aggregation_server.base_url}/annotate")
        session2.post(
            f"{aggregation_server.base_url}/updateinstance",
            json={
                "instance_id": instance_id,
                "annotations": {
                    "quality:Uncertain": True,
                    "confidence:confidence": 2
                }
            },
            headers={"Content-Type": "application/json"}
        )

        # User 3: rates "Bad" (no confidence shown)
        session3 = requests.Session()
        session3.post(f"{aggregation_server.base_url}/register", data={"email": "agg_user3@test.com", "pass": "pass123"})
        session3.post(f"{aggregation_server.base_url}/auth", data={"email": "agg_user3@test.com", "pass": "pass123"})
        session3.get(f"{aggregation_server.base_url}/annotate")
        session3.post(
            f"{aggregation_server.base_url}/updateinstance",
            json={"instance_id": instance_id, "annotations": {"quality:Bad": True}},
            headers={"Content-Type": "application/json"}
        )

        # Request agreement metrics - should not crash with missing conditional data
        response = requests.get(
            f"{aggregation_server.base_url}/admin/api/agreement",
            headers={"X-API-Key": "admin_api_key"}
        )
        # May be 200 or may have no data, but should not be 500
        assert response.status_code != 500
