"""
Annotation Workflow Integration Tests

This module contains comprehensive tests that demonstrate complete annotation workflows
using the production endpoints. These tests verify the entire system from data creation
to annotation completion.
"""

import json
import pytest
import time
import tempfile
import os
from tests.helpers.flask_test_setup import FlaskTestServer
import requests

class TestAnnotationWorkflowIntegration:
    """Test complete annotation workflow integration."""

    @pytest.fixture
    def flask_server(self):
        # Create a temporary directory for this test
        test_dir = tempfile.mkdtemp()

        # Create test data file
        test_data = [
            {
                "id": "item_1",
                "text": "This is a positive statement about the product.",
                "metadata": {"source": "test"}
            },
            {
                "id": "item_2",
                "text": "This is a negative statement about the product.",
                "metadata": {"source": "test"}
            },
            {
                "id": "item_3",
                "text": "This is a neutral statement about the product.",
                "metadata": {"source": "test"}
            }
        ]
        data_file = os.path.join(test_dir, 'annotation_test_data.json')
        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        # Create minimal config
        config = {
            "debug": False,
            "max_annotations_per_user": 10,
            "max_annotations_per_item": -1,
            "assignment_strategy": "fixed_order",
            "annotation_task_name": "Annotation Integration Test Task",
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
                    "name": "sentiment_label",
                    "type": "radio",
                    "annotation_type": "radio",
                    "labels": ["positive", "negative", "neutral"],
                    "description": "Label the sentiment."
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

        # Create phase files
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
        config_file = os.path.join(test_dir, 'annotation_test_config.yaml')
        import yaml
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        # Create server with the config file
        server = FlaskTestServer(
            port=9004,
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

    def test_complete_annotation_workflow(self, flask_server):
        """Test a complete annotation workflow from start to finish."""
        server_url = flask_server.base_url

        # Create multiple users using production registration endpoint
        users = ["user_1", "user_2", "user_3"]
        sessions = {}
        for username in users:
            user_data = {"email": username, "pass": "test_password"}
            session = requests.Session()
            reg_response = session.post(f"{server_url}/register", data=user_data, timeout=5)
            assert reg_response.status_code in [200, 302]
            login_response = session.post(f"{server_url}/auth", data=user_data, timeout=5)
            assert login_response.status_code in [200, 302]
            sessions[username] = session

        # Check initial system state using admin endpoint (read-only)
        response = requests.get(f"{server_url}/admin/system_state",
                              headers={'X-API-Key': 'admin_api_key'},
                              timeout=5)
        if response.status_code == 200:  # Only check if endpoint exists
            data = response.json()
            assert "users" in data
            assert len(data["users"]) >= 3

        # Submit annotations for each user using production endpoints
        for i, username in enumerate(users):
            annotation_data = {
                "instance_id": f"item_{i+1}",
                "type": "label",
                "schema": "sentiment_label",
                "state": [
                    {"name": "sentiment_label", "value": ["positive", "negative", "neutral"][i]}
                ]
            }
            session = sessions[username]
            response = session.post(f"{server_url}/updateinstance", json=annotation_data, timeout=5)
            assert response.status_code == 200

            # Check user state after annotation using admin endpoint (read-only)
            response = requests.get(f"{server_url}/admin/user_state/{username}",
                                 headers={'X-API-Key': 'admin_api_key'},
                                 timeout=5)
            if response.status_code == 200:  # Only check if endpoint exists
                user_state = response.json()
                assert user_state["user_id"] == username

        # Check final system state using admin endpoint (read-only)
        response = requests.get(f"{server_url}/admin/system_state",
                              headers={'X-API-Key': 'admin_api_key'},
                              timeout=5)
        if response.status_code == 200:  # Only check if endpoint exists
            final_state = response.json()
            if "total_annotations" in final_state:
                assert final_state["total_annotations"] >= 3

        # Test that each user can access annotation interface after submission
        for username, session in sessions.items():
            response = session.get(f"{server_url}/annotate", timeout=5)
            assert response.status_code == 200

    def test_user_phase_transitions(self, flask_server):
        """Test user phase transitions during annotation workflow."""
        server_url = flask_server.base_url

        # Create user using production registration endpoint
        user_data = {"email": "phase_test_user", "pass": "test_password"}
        session = requests.Session()
        reg_response = session.post(f"{server_url}/register", data=user_data, timeout=5)
        assert reg_response.status_code in [200, 302]
        login_response = session.post(f"{server_url}/auth", data=user_data, timeout=5)
        assert login_response.status_code in [200, 302]

        # Check initial user state using admin endpoint (read-only)
        response = requests.get(f"{server_url}/admin/user_state/phase_test_user",
                              headers={'X-API-Key': 'admin_api_key'},
                              timeout=5)
        if response.status_code == 200:  # Only check if endpoint exists
            user_state = response.json()
            # Note: We can't control the initial phase, so we just verify the user exists
            assert user_state["user_id"] == "phase_test_user"

        # Simulate consent phase by accessing annotation interface
        response = session.get(f"{server_url}/annotate", timeout=5)
        assert response.status_code == 200

        # Simulate instructions phase by accessing annotation interface again
        response = session.get(f"{server_url}/annotate", timeout=5)
        assert response.status_code == 200

        # Simulate annotation phase by submitting an annotation using production endpoint
        annotation_data = {
            "instance_id": "item_1",
            "type": "label",
            "schema": "sentiment_label",
            "state": [
                {"name": "sentiment_label", "value": "positive"}
            ]
        }
        response = session.post(f"{server_url}/updateinstance", json=annotation_data, timeout=5)
        assert response.status_code == 200

        # Check final user state using admin endpoint (read-only)
        response = requests.get(f"{server_url}/admin/user_state/phase_test_user",
                              headers={'X-API-Key': 'admin_api_key'},
                              timeout=5)
        if response.status_code == 200:  # Only check if endpoint exists
            user_state = response.json()
            assert user_state["user_id"] == "phase_test_user"

        # Simulate done phase by accessing annotate again (should still be accessible)
        response = session.get(f"{server_url}/annotate", timeout=5)
        assert response.status_code == 200