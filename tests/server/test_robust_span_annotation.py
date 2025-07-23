"""
Test suite for robust span annotation refactoring.

This module tests the new boundary-based span annotation system that replaces
the complex overlay approach with a simpler, more robust rendering method.
"""

import pytest
import requests
import os
import json
import tempfile
import yaml
from tests.helpers.flask_test_setup import FlaskTestServer


def get_config_path(config_name):
    return os.path.abspath(os.path.join(os.path.dirname(__file__), f'../configs/{config_name}'))


class TestRobustSpanAnnotation:
    """Test suite for robust span annotation system."""

    def create_test_config(self, test_data):
        """Create a test configuration for robust span annotation testing."""
        config = {
            "debug": False,
            "max_annotations_per_user": 5,
            "assignment_strategy": "fixed_order",
            "annotation_task_name": "Robust Span Annotation Test",
            "require_password": False,
            "authentication": {
                "method": "in_memory"
            },
            "data_files": ["test_data.json"],
            "item_properties": {"text_key": "text", "id_key": "id"},
            "annotation_schemes": [
                {
                    "annotation_type": "span",
                    "name": "emotion",
                    "description": "Highlight which phrases express different emotions in the text",
                    "labels": ["happy", "sad", "angry", "surprised", "neutral"],
                    "sequential_key_binding": True
                },
                {
                    "annotation_type": "radio",
                    "name": "overall_sentiment",
                    "description": "What is the overall sentiment of this text?",
                    "labels": ["positive", "neutral", "negative"]
                }
            ],
            "ui": {
                "spans": {
                    "span_colors": {
                        "emotion": {
                            "happy": "(255, 230, 230)",
                            "sad": "(230, 243, 255)",
                            "angry": "(255, 230, 204)",
                            "surprised": "(230, 255, 230)",
                            "neutral": "(240, 240, 240)"
                        }
                    }
                }
            },
            "site_file": "base_template_v2.html",
            "output_annotation_dir": "output",
            "task_dir": "task",
            "base_html_template": "default",
            "header_file": "default",
            "html_layout": "default",
            "site_dir": "templates",
            "alert_time_each_instance": 10000000
        }

        # Create temporary directory for test
        test_dir = tempfile.mkdtemp()

        # Create test data file in the test directory
        data_file = os.path.join(test_dir, "test_data.json")
        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        # Create output and task directories
        os.makedirs(os.path.join(test_dir, "output"), exist_ok=True)
        os.makedirs(os.path.join(test_dir, "task"), exist_ok=True)

        # Update config paths to use absolute paths
        config["output_annotation_dir"] = os.path.join(test_dir, "output")
        config["task_dir"] = os.path.join(test_dir, "task")
        config["site_dir"] = os.path.join(test_dir, "templates")
        config["data_files"] = [data_file]  # Use absolute path to the data file

        # Create config file
        config_path = os.path.join(test_dir, "test_config.yaml")
        with open(config_path, 'w') as f:
            yaml.dump(config, f)

        return config_path, test_dir

    def test_robust_span_annotation_creation(self):
        """Test that robust span annotations can be created and stored correctly."""
        test_data = [
            {
                "id": "1",
                "text": "I am so happy today! The weather is beautiful and everything is going well."
            },
            {
                "id": "2",
                "text": "This is a sad story about a lost puppy who couldn't find its way home."
            }
        ]

        config_path, test_dir = self.create_test_config(test_data)

        server = FlaskTestServer(lambda: create_app(), config_path, debug=False)
        server.start()
        server_url = server.base_url

        try:
            # Register a test user
            user_data = {"email": "test_user", "pass": "test_password"}
            response = requests.post(f"{server_url}/register", data=user_data, timeout=10)
            assert response.status_code == 200

            # Create a session to maintain login state
            session = requests.Session()
            session.post(f"{server_url}/auth", data=user_data)

            # Get user state to find assigned items
            response = session.get(f"{server_url}/admin/user_state/test_user",
                                 headers={"X-API-Key": "admin_api_key"}, timeout=10)
            assert response.status_code == 200
            user_state = response.json()

            # Get assigned items
            assigned_items = user_state["assignments"]["items"]
            assert len(assigned_items) > 0, "No items assigned to user"
            instance_id = assigned_items[0]["id"]

            # Create a span annotation
            span_data = {
                "type": "span",
                "schema": "emotion",
                "state": [
                    {
                        "name": "happy",
                        "start": 5,
                        "end": 9,
                        "title": "Happy",
                        "value": "happy"
                    }
                ],
                "instance_id": instance_id
            }

            response = session.post(f"{server_url}/updateinstance",
                                  json=span_data, timeout=10)
            assert response.status_code == 200
            result = response.json()
            assert result["status"] == "success"

            # Verify the span annotation was stored
            response = session.get(f"{server_url}/admin/user_state/test_user",
                                 headers={"X-API-Key": "admin_api_key"}, timeout=10)
            assert response.status_code == 200
            user_state = response.json()

            # Check that span annotations exist
            annotations = user_state["annotations"]["by_instance"]
            assert str(instance_id) in annotations, f"Annotations should exist for instance {instance_id}"

            # The span annotations should be stored in the user state
            instance_annotations = annotations[str(instance_id)]
            assert len(instance_annotations) > 0, "Span annotation should be stored"

        finally:
            server.stop()

    def test_robust_span_annotation_deletion(self):
        """Test that robust span annotations can be deleted correctly."""
        test_data = [
            {
                "id": "1",
                "text": "I am so happy today! The weather is beautiful."
            }
        ]

        config_path, test_dir = self.create_test_config(test_data)

        server = FlaskTestServer(lambda: create_app(), config_path, debug=False)
        server.start()
        server_url = server.base_url

        try:
            # Register a test user
            user_data = {"email": "test_user", "pass": "test_password"}
            response = requests.post(f"{server_url}/register", data=user_data, timeout=10)
            assert response.status_code == 200

            # Create a session
            session = requests.Session()
            session.post(f"{server_url}/auth", data=user_data)

            # Get user state
            response = session.get(f"{server_url}/admin/user_state/test_user",
                                 headers={"X-API-Key": "admin_api_key"}, timeout=10)
            assert response.status_code == 200
            user_state = response.json()
            instance_id = user_state["assignments"]["items"][0]["id"]

            # Create a span annotation
            span_data = {
                "type": "span",
                "schema": "emotion",
                "state": [
                    {
                        "name": "happy",
                        "start": 5,
                        "end": 9,
                        "title": "Happy",
                        "value": "happy"
                    }
                ],
                "instance_id": instance_id
            }

            response = session.post(f"{server_url}/updateinstance",
                                  json=span_data, timeout=10)
            assert response.status_code == 200

            # Verify span was created
            response = session.get(f"{server_url}/admin/user_state/test_user",
                                 headers={"X-API-Key": "admin_api_key"}, timeout=10)
            user_state = response.json()
            annotations = user_state["annotations"]["by_instance"]
            assert str(instance_id) in annotations
            assert len(annotations[str(instance_id)]) > 0

            # Delete the span annotation
            delete_data = {
                "type": "span",
                "schema": "emotion",
                "state": [
                    {
                        "name": "happy",
                        "start": 5,
                        "end": 9,
                        "title": "Happy",
                        "value": None  # This signals deletion
                    }
                ],
                "instance_id": instance_id
            }

            response = session.post(f"{server_url}/updateinstance",
                                  json=delete_data, timeout=10)
            assert response.status_code == 200

            # Verify span was deleted
            response = session.get(f"{server_url}/admin/user_state/test_user",
                                 headers={"X-API-Key": "admin_api_key"}, timeout=10)
            user_state = response.json()
            annotations = user_state["annotations"]["by_instance"]

            # The instance should either not exist or have no annotations
            if str(instance_id) in annotations:
                assert len(annotations[str(instance_id)]) == 0, "Span annotation should be deleted"

        finally:
            server.stop()

    def test_robust_span_annotation_overlapping(self):
        """Test that overlapping span annotations work correctly with the boundary-based system."""
        test_data = [
            {
                "id": "1",
                "text": "I am so happy today! The weather is beautiful and everything is going well."
            }
        ]

        config_path, test_dir = self.create_test_config(test_data)

        server = FlaskTestServer(lambda: create_app(), config_path, debug=False)
        server.start()
        server_url = server.base_url

        try:
            # Register a test user
            user_data = {"email": "test_user", "pass": "test_password"}
            response = requests.post(f"{server_url}/register", data=user_data, timeout=10)
            assert response.status_code == 200

            # Create a session
            session = requests.Session()
            session.post(f"{server_url}/auth", data=user_data)

            # Get user state
            response = session.get(f"{server_url}/admin/user_state/test_user",
                                 headers={"X-API-Key": "admin_api_key"}, timeout=10)
            assert response.status_code == 200
            user_state = response.json()
            instance_id = user_state["assignments"]["items"][0]["id"]

            # Create overlapping span annotations
            # First span: "so happy" (positions 5-13)
            # Second span: "happy today" (positions 8-18) - overlaps with first
            span_data = {
                "type": "span",
                "schema": "emotion",
                "state": [
                    {
                        "name": "happy",
                        "start": 5,
                        "end": 13,
                        "title": "Happy",
                        "value": "so happy"
                    },
                    {
                        "name": "happy",
                        "start": 8,
                        "end": 18,
                        "title": "Happy",
                        "value": "happy today"
                    }
                ],
                "instance_id": instance_id
            }

            response = session.post(f"{server_url}/updateinstance",
                                  json=span_data, timeout=10)
            assert response.status_code == 200

            # Verify both spans were stored
            response = session.get(f"{server_url}/admin/user_state/test_user",
                                 headers={"X-API-Key": "admin_api_key"}, timeout=10)
            user_state = response.json()
            annotations = user_state["annotations"]["by_instance"]
            assert str(instance_id) in annotations

            # Check that the displayed text contains proper HTML for overlapping spans
            current_instance = user_state["current_instance"]
            displayed_text = current_instance["displayed_text"]

            # The displayed text should contain span elements
            assert "<span" in displayed_text, "Displayed text should contain span elements"
            assert "span-highlight" in displayed_text, "Displayed text should contain span-highlight class"

        finally:
            server.stop()

    def test_robust_span_annotation_with_other_types(self):
        """Test that robust span annotations work alongside other annotation types."""
        test_data = [
            {
                "id": "1",
                "text": "I am so happy today! The weather is beautiful."
            }
        ]

        config_path, test_dir = self.create_test_config(test_data)

        server = FlaskTestServer(lambda: create_app(), config_path, debug=False)
        server.start()
        server_url = server.base_url

        try:
            # Register a test user
            user_data = {"email": "test_user", "pass": "test_password"}
            response = requests.post(f"{server_url}/register", data=user_data, timeout=10)
            assert response.status_code == 200

            # Create a session
            session = requests.Session()
            session.post(f"{server_url}/auth", data=user_data)

            # Get user state
            response = session.get(f"{server_url}/admin/user_state/test_user",
                                 headers={"X-API-Key": "admin_api_key"}, timeout=10)
            assert response.status_code == 200
            user_state = response.json()
            instance_id = user_state["assignments"]["items"][0]["id"]

            # Create a span annotation
            span_data = {
                "type": "span",
                "schema": "emotion",
                "state": [
                    {
                        "name": "happy",
                        "start": 5,
                        "end": 9,
                        "title": "Happy",
                        "value": "happy"
                    }
                ],
                "instance_id": instance_id
            }

            response = session.post(f"{server_url}/updateinstance",
                                  json=span_data, timeout=10)
            assert response.status_code == 200

            # Create a label annotation (radio button)
            label_data = {
                "type": "label",
                "schema": "overall_sentiment",
                "state": [
                    {
                        "name": "overall_sentiment",
                        "value": "positive"
                    }
                ],
                "instance_id": instance_id
            }

            response = session.post(f"{server_url}/updateinstance",
                                  json=label_data, timeout=10)
            assert response.status_code == 200

            # Verify both annotations were stored
            response = session.get(f"{server_url}/admin/user_state/test_user",
                                 headers={"X-API-Key": "admin_api_key"}, timeout=10)
            user_state = response.json()
            annotations = user_state["annotations"]["by_instance"]
            assert str(instance_id) in annotations

            # Should have both span and label annotations
            instance_annotations = annotations[str(instance_id)]
            assert len(instance_annotations) >= 2, "Should have both span and label annotations"

        finally:
            server.stop()


def create_app():
    from potato.flask_server import create_app
    return create_app()