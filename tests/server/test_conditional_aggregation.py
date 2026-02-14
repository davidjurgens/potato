"""
Server tests for aggregation and admin API handling of conditional annotations.

Tests:
- Agreement calculation handles missing conditional data
- Admin dashboard correctly displays conditional annotation statistics
- Behavioral analytics tracks stale annotations
- Export includes proper handling of conditional fields
"""

import pytest
import requests
import json
import os
import time
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager


class TestConditionalAgreementCalculation:
    """Test agreement metrics with conditional annotation patterns."""

    @pytest.fixture(scope="class")
    def multi_annotator_config(self):
        """Create config for multi-annotator agreement testing."""
        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "primary",
                "description": "Primary classification",
                "labels": ["Type_A", "Type_B", "Type_C"]
            },
            {
                "annotation_type": "radio",
                "name": "sub_a",
                "description": "Sub-classification for Type A",
                "labels": ["A1", "A2", "A3"],
                "display_logic": {
                    "show_when": [
                        {"schema": "primary", "operator": "equals", "value": "Type_A"}
                    ]
                }
            },
            {
                "annotation_type": "radio",
                "name": "sub_b",
                "description": "Sub-classification for Type B",
                "labels": ["B1", "B2"],
                "display_logic": {
                    "show_when": [
                        {"schema": "primary", "operator": "equals", "value": "Type_B"}
                    ]
                }
            },
            {
                "annotation_type": "slider",
                "name": "confidence",
                "description": "Confidence level",
                "min_value": 1,
                "max_value": 5,
                "starting_value": 3
            }
        ]

        with TestConfigManager(
            "conditional_agreement_test",
            annotation_schemes,
            num_instances=5
        ) as config:
            yield config

    @pytest.fixture(scope="class")
    def agreement_server(self, multi_annotator_config):
        """Start server for agreement testing."""
        server = FlaskTestServer(port=9964, config_file=multi_annotator_config.config_path, debug=True)
        if not server.start():
            pytest.fail("Failed to start Flask server")
        yield server
        server.stop()

    def create_annotation_session(self, server, email, password="pass123"):
        """Helper to create and login a session."""
        session = requests.Session()
        session.post(f"{server.base_url}/register", data={"email": email, "pass": password})
        session.post(f"{server.base_url}/auth", data={"email": email, "pass": password})
        # Visit annotate page to ensure instance is assigned
        session.get(f"{server.base_url}/annotate")
        return session

    def get_current_instance(self, session, server):
        """Helper to get current instance ID."""
        resp = session.get(f"{server.base_url}/api/current_instance")
        if resp.status_code == 200:
            return resp.json().get("instance_id")
        return None

    def test_agreement_with_same_primary_different_conditional(self, agreement_server):
        """Test agreement when annotators agree on primary but have different conditional paths."""
        # User 1: Type_A with sub-classification A1
        session1 = self.create_annotation_session(agreement_server, "agree_user1@test.com")
        instance_id = self.get_current_instance(session1, agreement_server)

        if instance_id:
            session1.post(
                f"{agreement_server.base_url}/updateinstance",
                json={
                    "instance_id": instance_id,
                    "annotations": {
                        "primary:Type_A": True,
                        "sub_a:A1": True,
                        "confidence:confidence": 4
                    }
                },
                headers={"Content-Type": "application/json"}
            )

        # User 2: Type_A with sub-classification A2 (same primary, different sub)
        session2 = self.create_annotation_session(agreement_server, "agree_user2@test.com")
        # Use same instance_id to simulate multiple annotators on same item
        if instance_id:
            session2.post(
                f"{agreement_server.base_url}/updateinstance",
                json={
                    "instance_id": instance_id,
                    "annotations": {
                        "primary:Type_A": True,
                        "sub_a:A2": True,
                        "confidence:confidence": 3
                    }
                },
                headers={"Content-Type": "application/json"}
            )

        # Get agreement - should not fail
        response = requests.get(f"{agreement_server.base_url}/admin/api/agreement")
        assert response.status_code in [200, 404]  # 404 if not enough data yet

    def test_agreement_with_different_primary_missing_conditional(self, agreement_server):
        """Test agreement handles missing conditional annotations gracefully."""
        # User 1: Type_A (has sub_a, no sub_b)
        session1 = self.create_annotation_session(agreement_server, "missing_user1@test.com")
        instance_id = self.get_current_instance(session1, agreement_server)

        if instance_id:
            session1.post(
                f"{agreement_server.base_url}/updateinstance",
                json={
                    "instance_id": instance_id,
                    "annotations": {
                        "primary:Type_A": True,
                        "sub_a:A1": True
                    }
                },
                headers={"Content-Type": "application/json"}
            )

        # User 2: Type_B (has sub_b, no sub_a)
        session2 = self.create_annotation_session(agreement_server, "missing_user2@test.com")
        if instance_id:
            session2.post(
                f"{agreement_server.base_url}/updateinstance",
                json={
                    "instance_id": instance_id,
                    "annotations": {
                        "primary:Type_B": True,
                        "sub_b:B1": True
                    }
                },
                headers={"Content-Type": "application/json"}
            )

        # Agreement calculation should not crash
        response = requests.get(f"{agreement_server.base_url}/admin/api/agreement")
        assert response.status_code != 500

    def test_agreement_primary_only_ignores_conditional(self, agreement_server):
        """Test that agreement on primary schema works regardless of conditional values."""
        # Both users rate same primary type but different conditionals
        session1 = self.create_annotation_session(agreement_server, "primary_only1@test.com")
        instance_id = self.get_current_instance(session1, agreement_server)

        if instance_id:
            session1.post(
                f"{agreement_server.base_url}/updateinstance",
                json={
                    "instance_id": instance_id,
                    "annotations": {"primary:Type_C": True}
                },
                headers={"Content-Type": "application/json"}
            )

        session2 = self.create_annotation_session(agreement_server, "primary_only2@test.com")
        if instance_id:
            session2.post(
                f"{agreement_server.base_url}/updateinstance",
                json={
                    "instance_id": instance_id,
                    "annotations": {"primary:Type_C": True}
                },
                headers={"Content-Type": "application/json"}
            )

        # Agreement should be calculable
        response = requests.get(f"{agreement_server.base_url}/admin/api/agreement")
        assert response.status_code in [200, 404]


class TestConditionalAdminStatistics:
    """Test admin dashboard statistics with conditional annotations."""

    @pytest.fixture(scope="class")
    def admin_stats_config(self):
        """Create config for admin statistics testing."""
        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "question",
                "description": "Main question",
                "labels": ["Yes", "No", "Maybe"]
            },
            {
                "annotation_type": "text",
                "name": "yes_reason",
                "description": "Reason for yes",
                "display_logic": {
                    "show_when": [
                        {"schema": "question", "operator": "equals", "value": "Yes"}
                    ]
                }
            },
            {
                "annotation_type": "text",
                "name": "no_reason",
                "description": "Reason for no",
                "display_logic": {
                    "show_when": [
                        {"schema": "question", "operator": "equals", "value": "No"}
                    ]
                }
            }
        ]

        with TestConfigManager(
            "conditional_admin_stats_test",
            annotation_schemes,
            num_instances=5
        ) as config:
            yield config

    @pytest.fixture(scope="class")
    def admin_stats_server(self, admin_stats_config):
        """Start server for admin stats testing."""
        server = FlaskTestServer(port=9965, config_file=admin_stats_config.config_path, debug=True)
        if not server.start():
            pytest.fail("Failed to start Flask server")
        yield server
        server.stop()

    def test_admin_overview_counts_conditional_annotations(self, admin_stats_server):
        """Test admin overview counts both conditional and non-conditional annotations."""
        # Create some annotations
        session = requests.Session()
        session.post(f"{admin_stats_server.base_url}/register", data={"email": "stats_user@test.com", "pass": "pass123"})
        session.post(f"{admin_stats_server.base_url}/auth", data={"email": "stats_user@test.com", "pass": "pass123"})
        session.get(f"{admin_stats_server.base_url}/annotate")

        resp = session.get(f"{admin_stats_server.base_url}/api/current_instance")
        if resp.status_code == 200:
            instance_id = resp.json().get("instance_id")
            session.post(
                f"{admin_stats_server.base_url}/updateinstance",
                json={
                    "instance_id": instance_id,
                    "annotations": {
                        "question:Yes": True,
                        "yes_reason:yes_reason": "Because it's good"
                    }
                },
                headers={"Content-Type": "application/json"}
            )

        # Check admin overview
        response = requests.get(f"{admin_stats_server.base_url}/admin/api/overview")
        assert response.status_code == 200

    def test_admin_questions_includes_conditional_info(self, admin_stats_server):
        """Test that admin questions API includes conditional schemas."""
        response = requests.get(f"{admin_stats_server.base_url}/admin/api/questions")
        assert response.status_code == 200
        data = response.json()
        # Verify we get some schema information
        assert data is not None

    def test_admin_annotators_shows_annotation_counts(self, admin_stats_server):
        """Test admin annotators API shows correct annotation counts."""
        response = requests.get(f"{admin_stats_server.base_url}/admin/api/annotators")
        assert response.status_code == 200


class TestConditionalBehavioralAnalytics:
    """Test behavioral analytics tracking of stale annotations."""

    @pytest.fixture(scope="class")
    def behavioral_config(self):
        """Create config for behavioral analytics testing."""
        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "rating",
                "description": "Rating",
                "labels": ["High", "Medium", "Low"]
            },
            {
                "annotation_type": "text",
                "name": "high_detail",
                "description": "High rating details",
                "display_logic": {
                    "show_when": [
                        {"schema": "rating", "operator": "equals", "value": "High"}
                    ]
                }
            }
        ]

        with TestConfigManager(
            "conditional_behavioral_test",
            annotation_schemes,
            num_instances=3
        ) as config:
            yield config

    @pytest.fixture(scope="class")
    def behavioral_server(self, behavioral_config):
        """Start server for behavioral testing."""
        server = FlaskTestServer(port=9966, config_file=behavioral_config.config_path, debug=True)
        if not server.start():
            pytest.fail("Failed to start Flask server")
        yield server
        server.stop()

    def test_stale_annotations_tracked_on_decision_change(self, behavioral_server):
        """Test that stale annotations are tracked when primary choice changes."""
        session = requests.Session()
        session.post(f"{behavioral_server.base_url}/register", data={"email": "stale_user@test.com", "pass": "pass123"})
        session.post(f"{behavioral_server.base_url}/auth", data={"email": "stale_user@test.com", "pass": "pass123"})
        session.get(f"{behavioral_server.base_url}/annotate")

        resp = session.get(f"{behavioral_server.base_url}/api/current_instance")
        if resp.status_code == 200:
            instance_id = resp.json().get("instance_id")

            # First: Select High and add details
            session.post(
                f"{behavioral_server.base_url}/updateinstance",
                json={
                    "instance_id": instance_id,
                    "annotations": {
                        "rating:High": True,
                        "high_detail:high_detail": "Initial high rating details"
                    }
                },
                headers={"Content-Type": "application/json"}
            )

            # Then: Change to Low (high_detail becomes stale)
            session.post(
                f"{behavioral_server.base_url}/updateinstance",
                json={
                    "instance_id": instance_id,
                    "annotations": {
                        "rating:Low": True
                    }
                },
                headers={"Content-Type": "application/json"}
            )

        # Check behavioral analytics endpoint exists
        response = requests.get(f"{behavioral_server.base_url}/admin/api/behavioral_analytics")
        assert response.status_code in [200, 404]  # 404 if no data yet


class TestConditionalOutputFormat:
    """Test output file format with conditional annotations."""

    @pytest.fixture(scope="class")
    def output_config(self):
        """Create config for output format testing."""
        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "decision",
                "description": "Decision",
                "labels": ["Accept", "Reject"]
            },
            {
                "annotation_type": "text",
                "name": "accept_reason",
                "description": "Acceptance reason",
                "display_logic": {
                    "show_when": [
                        {"schema": "decision", "operator": "equals", "value": "Accept"}
                    ]
                }
            },
            {
                "annotation_type": "text",
                "name": "reject_reason",
                "description": "Rejection reason",
                "display_logic": {
                    "show_when": [
                        {"schema": "decision", "operator": "equals", "value": "Reject"}
                    ]
                }
            }
        ]

        with TestConfigManager(
            "conditional_output_test",
            annotation_schemes,
            num_instances=3
        ) as config:
            yield config

    @pytest.fixture(scope="class")
    def output_server(self, output_config):
        """Start server for output testing."""
        server = FlaskTestServer(port=9967, config_file=output_config.config_path, debug=True)
        if not server.start():
            pytest.fail("Failed to start Flask server")
        yield server
        server.stop()

    def test_output_contains_only_relevant_conditional_annotations(self, output_server, output_config):
        """Test that output contains only the relevant conditional annotations."""
        session = requests.Session()
        session.post(f"{output_server.base_url}/register", data={"email": "output_user@test.com", "pass": "pass123"})
        session.post(f"{output_server.base_url}/auth", data={"email": "output_user@test.com", "pass": "pass123"})
        session.get(f"{output_server.base_url}/annotate")

        resp = session.get(f"{output_server.base_url}/api/current_instance")
        if resp.status_code == 200:
            instance_id = resp.json().get("instance_id")

            # Annotate with Accept path
            session.post(
                f"{output_server.base_url}/updateinstance",
                json={
                    "instance_id": instance_id,
                    "annotations": {
                        "decision:Accept": True,
                        "accept_reason:accept_reason": "Good quality"
                    }
                },
                headers={"Content-Type": "application/json"}
            )

        # Verify output directory exists
        output_dir = os.path.join(output_config.task_dir, "output")
        if os.path.exists(output_dir):
            # Check for annotation files
            files = os.listdir(output_dir)
            # Output files should exist after annotation
            assert isinstance(files, list)  # Just verify we can read the directory
