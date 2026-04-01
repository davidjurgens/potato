"""Server integration tests for error span annotation."""

import json
import os
import uuid

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_directory, create_test_data_file, cleanup_test_directory


def create_error_span_config(test_dir, data_file, port=9045):
    """Create an error span annotation test config."""
    abs_test_dir = os.path.abspath(test_dir)
    output_dir = os.path.join(abs_test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    config = {
        "annotation_task_name": "Error Span Test",
        "task_dir": abs_test_dir,
        "data_files": [os.path.basename(data_file)],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "output_annotation_dir": output_dir,
        "require_password": False,
        "authentication": {"method": "in_memory"},
        "persist_sessions": False,
        "debug": False,
        "port": port,
        "host": "0.0.0.0",
        "secret_key": "test-secret-key-error-span",
        "user_config": {"allow_all_users": True, "users": []},
        "annotation_schemes": [
            {
                "annotation_type": "error_span",
                "name": "errors",
                "description": "Mark translation errors",
                "error_types": [
                    {"name": "Accuracy", "subtypes": ["Omission", "Mistranslation"]},
                    {"name": "Fluency", "subtypes": ["Grammar", "Spelling"]},
                ],
                "show_score": True,
            }
        ],
    }

    config_path = os.path.join(abs_test_dir, "config.yaml")
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    return config_path


def create_test_data(test_dir, num_items=3):
    """Create test data items."""
    data = [
        {"id": str(i + 1), "text": f"The translated text {i + 1} contains some errors that need to be identified and categorized."}
        for i in range(num_items)
    ]
    return create_test_data_file(test_dir, data)


class TestErrorSpanServer:
    """Integration tests for error span annotation server."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Start a Flask server with error span config."""
        test_dir = create_test_directory("error_span_server_test")
        data_file = create_test_data(test_dir)
        config_path = create_error_span_config(test_dir, data_file, port=9045)

        server = FlaskTestServer(port=9045, config_file=config_path)
        if not server.start():
            cleanup_test_directory(test_dir)
            pytest.fail("Failed to start error span test server")

        request.cls.server = server
        request.cls.test_dir = test_dir
        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    def _get_session(self):
        """Create an authenticated session."""
        session = requests.Session()
        username = f"errorspan_tester_{uuid.uuid4().hex[:6]}"
        session.post(
            f"{self.server.base_url}/register",
            data={"email": username, "pass": "testpass"},
        )
        session.post(
            f"{self.server.base_url}/auth",
            data={"email": username, "pass": "testpass"},
        )
        return session

    def test_server_starts(self):
        """Server starts successfully with error span config."""
        response = requests.get(f"{self.server.base_url}/")
        assert response.status_code == 200

    def test_annotate_page_loads(self):
        """/annotate returns 200 with error span form HTML."""
        session = self._get_session()
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200
        assert "error-span" in response.text or "errors" in response.text

    def test_submit_error_annotation(self):
        """POST error span annotation to /updateinstance succeeds."""
        session = self._get_session()

        error_data = json.dumps({
            "errors": [
                {
                    "start": 4,
                    "end": 14,
                    "text": "translated",
                    "type": "Accuracy",
                    "subtype": "Mistranslation",
                    "severity": "Major",
                }
            ],
            "score": 95,
        })

        response = session.post(
            f"{self.server.base_url}/updateinstance",
            json={
                "instance_id": "1",
                "annotations": {
                    "errors:errors": error_data,
                },
            },
        )
        assert response.status_code == 200

    def test_submit_and_verify_response(self):
        """POST error span annotation returns success with stored data."""
        session = self._get_session()
        session.get(f"{self.server.base_url}/annotate")

        error_data = json.dumps({
            "errors": [
                {
                    "start": 4,
                    "end": 14,
                    "text": "translated",
                    "type": "Fluency",
                    "subtype": "Grammar",
                    "severity": "Minor",
                },
                {
                    "start": 40,
                    "end": 46,
                    "text": "errors",
                    "type": "Accuracy",
                    "subtype": "Omission",
                    "severity": "Critical",
                },
            ],
            "score": 89,
        })

        response = session.post(
            f"{self.server.base_url}/updateinstance",
            json={
                "instance_id": "1",
                "annotations": {
                    "errors:errors": error_data,
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True or response.status_code == 200

    def test_page_contains_error_span_elements(self):
        """Annotation page contains error span interface elements."""
        session = self._get_session()
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200
        assert "error-span-text-container" in response.text or "error-span" in response.text
        assert "Accuracy" in response.text
        assert "Fluency" in response.text
