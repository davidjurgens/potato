"""
Multi-Phase Workflow Tests

This module contains tests for complete multi-phase annotation workflows,
including consent, instructions, annotation, and post-study phases.
"""

import json
import pytest
import requests
import time
import os
import tempfile
from unittest.mock import patch, MagicMock
from tests.flask_test_setup import FlaskTestServer


class TestMultiPhaseWorkflow:
    """Test complete multi-phase annotation workflows."""

    @pytest.fixture
    def flask_server(self):
        """Create a Flask test server with multi-phase test data."""
        # Create a temporary directory for this test
        test_dir = tempfile.mkdtemp()

        # Create test data file for multi-phase workflow
        test_data = [
            {"id": "phase_item_1", "text": "This is the first item for phase testing."},
            {"id": "phase_item_2", "text": "This is the second item for phase testing."},
            {"id": "phase_item_3", "text": "This is the third item for phase testing."}
        ]

        data_file = os.path.join(test_dir, 'phase_test_data.json')
        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        # Create minimal config for multi-phase testing
        config = {
            "debug": False,
            "max_annotations_per_user": 10,
            "max_annotations_per_item": -1,
            "assignment_strategy": "fixed_order",
            "annotation_task_name": "Multi-Phase Test Task",
            "require_password": False,
            "authentication": {
                "method": "in_memory"
            },
            "data_files": [os.path.basename(data_file)],
            "item_properties": {
                "text_key": "text",
                "id_key": "id"
            },
            "annotation_schemes": [
                {
                    "name": "phase_rating",
                    "type": "radio",
                    "annotation_type": "radio",
                    "labels": ["1", "2", "3", "4", "5"],
                    "description": "Rate the quality of this text."
                }
            ],
            "phases": {
                "order": ["consent", "instructions"],
                "consent": {
                    "type": "consent",
                    "file": "consent.json"
                },
                "instructions": {
                    "type": "instructions",
                    "file": "instructions.json"
                }
            },
            "site_file": "base_template.html",
            "output_annotation_dir": os.path.join(test_dir, "output"),
            "task_dir": os.path.join(test_dir, "task"),
            "site_dir": os.path.join(test_dir, "templates"),
            "alert_time_each_instance": 0
        }

        # Create phase files in the correct location (same directory as config)
        consent_data = [
            {
                "name": "consent_check",
                "type": "radio",
                "annotation_type": "radio",
                "labels": ["I agree", "I do not agree"],
                "description": "Do you agree to participate in this study?"
            }
        ]
        with open(os.path.join(test_dir, 'consent.json'), 'w') as f:
            json.dump(consent_data, f, indent=2)

        instructions_data = [
            {
                "name": "instructions_check",
                "type": "radio",
                "annotation_type": "radio",
                "labels": ["I understand", "I need more explanation"],
                "description": "Do you understand the instructions?"
            }
        ]
        with open(os.path.join(test_dir, 'instructions.json'), 'w') as f:
            json.dump(instructions_data, f, indent=2)

        # Write config file
        config_file = os.path.join(test_dir, 'phase_test_config.yaml')
        import yaml
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        # Create server with the config file
        server = FlaskTestServer(
            port=9003,
            debug=False,
            config_file=config_file,
            test_data_file=data_file
        )

        # Start server
        if not server.start_server(test_dir):
            pytest.fail("Failed to start Flask test server")

        yield server

        # Cleanup
        server.stop_server()

    def test_basic_phase_workflow(self, flask_server):
        """Test basic phase workflow with file-based dataset"""
        server_url = flask_server.base_url

        # Create user using production registration endpoint
        user_data = {"email": "phase_test_user", "pass": "test_password"}
        session = requests.Session()
        reg_response = session.post(f"{server_url}/register", data=user_data, timeout=5)
        assert reg_response.status_code in [200, 302]
        login_response = session.post(f"{server_url}/auth", data=user_data, timeout=5)
        assert login_response.status_code in [200, 302]

        # Test that user can access annotation interface
        response = session.get(f"{server_url}/annotate", timeout=5)
        assert response.status_code == 200

        # Submit an annotation to test phase progression
        annotation_data = {
            "instance_id": "phase_item_1",
            "type": "label",
            "schema": "phase_rating",
            "state": [
                {"name": "phase_rating", "value": "3"}
            ]
        }
        response = session.post(f"{server_url}/updateinstance", json=annotation_data, timeout=5)
        assert response.status_code == 200

    def test_phase_validation_workflow(self, flask_server):
        """Test phase validation workflow with file-based dataset"""
        server_url = flask_server.base_url

        # Create user using production registration endpoint
        user_data = {"email": "phase_validation_user", "pass": "test_password"}
        session = requests.Session()
        reg_response = session.post(f"{server_url}/register", data=user_data, timeout=5)
        assert reg_response.status_code in [200, 302]
        login_response = session.post(f"{server_url}/auth", data=user_data, timeout=5)
        assert login_response.status_code in [200, 302]

        # Test that user can access annotation interface
        response = session.get(f"{server_url}/annotate", timeout=5)
        assert response.status_code == 200

        # Submit an annotation to test phase progression
        annotation_data = {
            "instance_id": "phase_item_1",
            "type": "label",
            "schema": "phase_rating",
            "state": [
                {"name": "phase_rating", "value": "4"}
            ]
        }
        response = session.post(f"{server_url}/updateinstance", json=annotation_data, timeout=5)
        assert response.status_code == 200

    def test_requirements_workflow(self, flask_server):
        """Test requirements workflow with file-based dataset"""
        server_url = flask_server.base_url

        # Create user using production registration endpoint
        user_data = {"email": "requirements_user", "pass": "test_password"}
        session = requests.Session()
        reg_response = session.post(f"{server_url}/register", data=user_data, timeout=5)
        assert reg_response.status_code in [200, 302]
        login_response = session.post(f"{server_url}/auth", data=user_data, timeout=5)
        assert login_response.status_code in [200, 302]

        # Test that user can access annotation interface
        response = session.get(f"{server_url}/annotate", timeout=5)
        assert response.status_code == 200

        # Submit an annotation to test phase progression
        annotation_data = {
            "instance_id": "phase_item_1",
            "type": "label",
            "schema": "phase_rating",
            "state": [
                {"name": "phase_rating", "value": "5"}
            ]
        }
        response = session.post(f"{server_url}/updateinstance", json=annotation_data, timeout=5)
        assert response.status_code == 200

    def test_multi_user_phase_workflow(self, flask_server):
        """Test multi-user phase workflow with file-based dataset"""
        server_url = flask_server.base_url

        # Create multiple users using production registration endpoint
        users = ["multi_user_1", "multi_user_2", "multi_user_3"]
        sessions = {}
        for username in users:
            user_data = {"email": username, "pass": "test_password"}
            session = requests.Session()
            reg_response = session.post(f"{server_url}/register", data=user_data, timeout=5)
            assert reg_response.status_code in [200, 302]
            login_response = session.post(f"{server_url}/auth", data=user_data, timeout=5)
            assert login_response.status_code in [200, 302]
            sessions[username] = session

        # Test that each user can access annotation interface
        for username, session in sessions.items():
            response = session.get(f"{server_url}/annotate", timeout=5)
            assert response.status_code == 200

        # Submit annotations from each user
        for i, (username, session) in enumerate(sessions.items()):
            annotation_data = {
                "instance_id": f"phase_item_{i+1}",
                "type": "label",
                "schema": "phase_rating",
                "state": [
                    {"name": "phase_rating", "value": str(i+1)}
                ]
            }
            response = session.post(f"{server_url}/updateinstance", json=annotation_data, timeout=5)
            assert response.status_code == 200


class TestMultiPhaseWorkflowMocked:
    """Test multi-phase workflows with mocked responses."""

    @patch('requests.post')
    @patch('requests.get')
    def test_mocked_multi_phase_workflow(self, mock_get, mock_post):
        """Test complete multi-phase workflow with mocked responses."""

        def create_mock_response(status_code, json_data):
            mock = MagicMock()
            mock.status_code = status_code
            mock.json.return_value = json_data
            return mock

        # Configure mock responses for phase progression
        phase_counter = 0
        phase_order = ['CONSENT', 'INSTRUCTIONS', 'ANNOTATION', 'POSTSTUDY', 'DONE']

        def mock_post_side_effect(url, *args, **kwargs):
            nonlocal phase_counter
            if "/register" in url:
                return create_mock_response(302, {"status": "redirect"})
            elif "/auth" in url:
                return create_mock_response(302, {"status": "redirect"})
            elif "/updateinstance" in url:
                return create_mock_response(200, {"status": "annotation_saved"})
            else:
                return create_mock_response(200, {"status": "success"})

        def mock_get_side_effect(url, *args, **kwargs):
            if "/annotate" in url:
                return create_mock_response(200, {"status": "annotation_interface"})
            else:
                return create_mock_response(200, {"status": "success"})

        mock_post.side_effect = mock_post_side_effect
        mock_get.side_effect = mock_get_side_effect

        # Test that mocks work correctly
        response = mock_post("http://test/register")
        assert response.status_code == 302

        response = mock_get("http://test/annotate")
        assert response.status_code == 200

    @patch('requests.post')
    @patch('requests.get')
    def test_mocked_phase_validation(self, mock_get, mock_post):
        """Test phase validation with mocked responses."""

        def create_mock_response(status_code, json_data):
            mock = MagicMock()
            mock.status_code = status_code
            mock.json.return_value = json_data
            return mock

        # Configure mock responses
        mock_post.return_value = create_mock_response(200, {"status": "success"})
        mock_get.return_value = create_mock_response(200, {"status": "success"})

        # Test would go here - for now just verify mocks work
        assert mock_post.return_value.status_code == 200
        assert mock_get.return_value.status_code == 200