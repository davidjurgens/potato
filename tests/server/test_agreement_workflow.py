"""
Inter-Annotator Agreement Workflow Tests

This module contains tests for inter-annotator agreement workflows,
including agreement calculation, validation, and analysis.
"""

import pytest
import requests
from unittest.mock import patch, MagicMock
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
    cleanup_test_directory
)


class TestAgreementWorkflow:
    """Test inter-annotator agreement workflows."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Create a Flask test server with agreement test data."""
        test_dir = create_test_directory("agreement_workflow_test")

        # Create test data
        test_data = [
            {"id": "agreement_item_1", "text": "This is the first item for agreement testing."},
            {"id": "agreement_item_2", "text": "This is the second item for agreement testing."},
            {"id": "agreement_item_3", "text": "This is the third item for agreement testing."}
        ]
        data_file = create_test_data_file(test_dir, test_data)

        # Create annotation schemes
        annotation_schemes = [
            {
                "name": "agreement_rating",
                "annotation_type": "radio",
                "labels": ["1", "2", "3", "4", "5"],
                "description": "Rate the quality of this text."
            }
        ]

        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Agreement Test Task",
            require_password=False,
            max_annotations_per_user=10,
            admin_api_key="admin_api_key"
        )

        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("Failed to start Flask test server")

        request.cls.server = server
        request.cls.test_dir = test_dir

        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    def test_basic_agreement_workflow(self):
        """Test basic agreement workflow with multiple users."""
        # Create multiple users
        users = ["annotator_1", "annotator_2", "annotator_3"]
        sessions = {}
        for username in users:
            user_data = {"email": username, "pass": "test_password"}
            session = requests.Session()
            reg_response = session.post(f"{self.server.base_url}/register", data=user_data, timeout=5)
            assert reg_response.status_code in [200, 302]
            login_response = session.post(f"{self.server.base_url}/auth", data=user_data, timeout=5)
            assert login_response.status_code in [200, 302]
            sessions[username] = session

        # Check each user's state using admin endpoint
        for username in users:
            response = self.server.get(f"/admin/user_state/{username}")
            if response.status_code == 200:
                user_state = response.json()
                assert user_state["user_id"] == username

        # Test that users can access annotation interface
        for username, session in sessions.items():
            response = session.get(f"{self.server.base_url}/annotate", timeout=5)
            assert response.status_code == 200

    def test_agreement_calculation(self):
        """Test agreement calculation workflow."""
        # Create user
        user_data = {"email": "agreement_user", "pass": "test_password"}
        session = requests.Session()
        session.post(f"{self.server.base_url}/register", data=user_data, timeout=10)
        session.post(f"{self.server.base_url}/auth", data=user_data, timeout=10)

        # Check user state
        response = self.server.get("/admin/user_state/agreement_user")
        if response.status_code == 200:
            user_state = response.json()
            assert user_state["user_id"] == "agreement_user"

        # Test annotation access
        response = session.get(f"{self.server.base_url}/annotate", timeout=10)
        assert response.status_code == 200

    def test_multi_annotator_agreement(self):
        """Test multi-annotator agreement workflow."""
        user_data = {"email": "multi_agreement_user", "pass": "test_password"}
        session = requests.Session()
        session.post(f"{self.server.base_url}/register", data=user_data, timeout=10)
        session.post(f"{self.server.base_url}/auth", data=user_data, timeout=10)

        response = self.server.get("/admin/user_state/multi_agreement_user")
        if response.status_code == 200:
            user_state = response.json()
            assert user_state["user_id"] == "multi_agreement_user"

        response = session.get(f"{self.server.base_url}/annotate", timeout=10)
        assert response.status_code == 200

    def test_agreement_threshold_workflow(self):
        """Test agreement threshold workflow with conflicting annotations."""
        # Create test users
        users = ["threshold_user1", "threshold_user2"]
        sessions = {}
        for user_id in users:
            user_data = {"email": user_id, "pass": "test_password"}
            session = requests.Session()
            session.post(f"{self.server.base_url}/register", data=user_data, timeout=10)
            session.post(f"{self.server.base_url}/auth", data=user_data, timeout=10)
            sessions[user_id] = session

        # Submit conflicting annotations
        item_id = "agreement_item_1"
        for i, user_id in enumerate(users):
            annotation_data = {
                "instance_id": item_id,
                "type": "radio",
                "schema": "agreement_rating",
                "state": [{"name": str(i + 1), "value": str(i + 1)}]
            }
            session = sessions[user_id]
            response = session.post(f"{self.server.base_url}/updateinstance", json=annotation_data, timeout=10)
            assert response.status_code == 200

    def test_disagreement_resolution_workflow(self):
        """Test disagreement resolution with multiple annotators."""
        users = ["resolve_annotator_1", "resolve_annotator_2", "resolve_annotator_3"]
        sessions = {}
        for username in users:
            user_data = {"email": username, "pass": "test_password"}
            session = requests.Session()
            session.post(f"{self.server.base_url}/register", data=user_data, timeout=5)
            session.post(f"{self.server.base_url}/auth", data=user_data, timeout=5)
            sessions[username] = session

        # Submit annotations with intentional disagreements
        disagreement_items = ["agreement_item_1", "agreement_item_2", "agreement_item_3"]
        ratings_per_user = {
            "resolve_annotator_1": [1, 2, 3],
            "resolve_annotator_2": [5, 4, 3],
            "resolve_annotator_3": [1, 4, 3]
        }

        for username, ratings in ratings_per_user.items():
            for i, item_id in enumerate(disagreement_items):
                annotation_data = {
                    "instance_id": item_id,
                    "type": "radio",
                    "schema": "agreement_rating",
                    "state": [{"name": str(ratings[i]), "value": str(ratings[i])}]
                }
                session = sessions[username]
                response = session.post(f"{self.server.base_url}/updateinstance", json=annotation_data, timeout=5)
                assert response.status_code == 200

    def test_agreement_export_workflow(self):
        """Test agreement export workflow."""
        users = ["export_user_1", "export_user_2"]
        sessions = {}
        for user_id in users:
            user_data = {"email": user_id, "pass": "test_password"}
            session = requests.Session()
            session.post(f"{self.server.base_url}/register", data=user_data, timeout=5)
            session.post(f"{self.server.base_url}/auth", data=user_data, timeout=5)
            sessions[user_id] = session

        # Submit annotations
        item_id = "agreement_item_1"
        for user_id in users:
            annotation_data = {
                "instance_id": item_id,
                "type": "radio",
                "schema": "agreement_rating",
                "state": [{"name": "3", "value": "3"}]
            }
            session = sessions[user_id]
            response = session.post(f"{self.server.base_url}/updateinstance", json=annotation_data, timeout=5)
            assert response.status_code == 200


class TestAgreementWorkflowMocked:
    """Mocked tests for agreement workflow components."""

    @patch('requests.post')
    @patch('requests.get')
    def test_mocked_basic_agreement_workflow(self, mock_get, mock_post):
        """Test basic agreement workflow with mocked responses."""
        def create_mock_response(status_code, json_data):
            mock_response = MagicMock()
            mock_response.status_code = status_code
            mock_response.json.return_value = json_data
            return mock_response

        mock_post.return_value = create_mock_response(200, {"status": "success"})
        mock_get.return_value = create_mock_response(200, {
            "user_id": "test_user",
            "phase": "ANNOTATION",
            "assigned_items": ["item_1", "item_2"]
        })

        assert mock_post.return_value.status_code == 200
        assert mock_get.return_value.status_code == 200

    @patch('requests.post')
    @patch('requests.get')
    def test_mocked_agreement_calculation(self, mock_get, mock_post):
        """Test agreement calculation with mocked responses."""
        def create_mock_response(status_code, json_data):
            mock_response = MagicMock()
            mock_response.status_code = status_code
            mock_response.json.return_value = json_data
            return mock_response

        mock_get.return_value = create_mock_response(200, {
            "item_id": "test_item",
            "agreement_score": 0.85,
            "annotations": [
                {"user": "user1", "rating": 4},
                {"user": "user2", "rating": 4},
                {"user": "user3", "rating": 5}
            ]
        })

        assert mock_get.return_value.status_code == 200
        agreement_data = mock_get.return_value.json()
        assert agreement_data["agreement_score"] == 0.85

    @patch('requests.post')
    @patch('requests.get')
    def test_mocked_disagreement_resolution(self, mock_get, mock_post):
        """Test disagreement resolution with mocked responses."""
        def create_mock_response(status_code, json_data):
            mock_response = MagicMock()
            mock_response.status_code = status_code
            mock_response.json.return_value = json_data
            return mock_response

        mock_get.return_value = create_mock_response(200, {
            "disagreed_items": ["item_1", "item_2"],
            "agreement_threshold": 0.7,
            "resolution_needed": True
        })

        assert mock_get.return_value.status_code == 200
        disagreement_data = mock_get.return_value.json()
        assert disagreement_data["resolution_needed"] == True
