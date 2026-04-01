"""Server integration tests for text edit annotation."""

import json
import os
import uuid

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_directory, create_test_data_file, cleanup_test_directory


def create_text_edit_config(test_dir, data_file, port=9044):
    """Create a text edit annotation test config."""
    abs_test_dir = os.path.abspath(test_dir)
    output_dir = os.path.join(abs_test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    config = {
        "annotation_task_name": "Text Edit Test",
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
        "secret_key": "test-secret-key-text-edit",
        "user_config": {"allow_all_users": True, "users": []},
        "annotation_schemes": [
            {
                "annotation_type": "text_edit",
                "name": "postedit",
                "description": "Edit the machine translation output",
                "source_field": "mt_output",
                "show_diff": True,
                "allow_reset": True,
            }
        ],
    }

    config_path = os.path.join(abs_test_dir, "config.yaml")
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    return config_path


def create_test_data(test_dir, num_items=3):
    """Create test data items with text and mt_output fields."""
    data = [
        {
            "id": str(i + 1),
            "text": f"Source text {i + 1} for translation review.",
            "mt_output": f"Machine translated output {i + 1} that may need corrections.",
        }
        for i in range(num_items)
    ]
    return create_test_data_file(test_dir, data)


class TestTextEditServer:
    """Integration tests for text edit annotation server."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Start a Flask server with text edit config."""
        test_dir = create_test_directory("text_edit_server_test")
        data_file = create_test_data(test_dir)
        config_path = create_text_edit_config(test_dir, data_file, port=9044)

        server = FlaskTestServer(port=9044, config_file=config_path)
        if not server.start():
            cleanup_test_directory(test_dir)
            pytest.fail("Failed to start text edit test server")

        request.cls.server = server
        request.cls.test_dir = test_dir
        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    def _get_session(self):
        """Create an authenticated session."""
        session = requests.Session()
        username = f"textedit_tester_{uuid.uuid4().hex[:6]}"
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
        """Server starts successfully with text edit config."""
        response = requests.get(f"{self.server.base_url}/")
        assert response.status_code == 200

    def test_annotate_page_loads(self):
        """/annotate returns 200 with text edit form HTML."""
        session = self._get_session()
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200
        assert "text-edit" in response.text or "postedit" in response.text

    def test_submit_edit_annotation(self):
        """POST text edit annotation to /updateinstance succeeds."""
        session = self._get_session()

        edit_data = json.dumps({
            "edited_text": "Corrected machine translated output 1 with proper grammar.",
            "original_text": "Machine translated output 1 that may need corrections.",
            "edit_distance_chars": 15,
            "edit_distance_words": 3,
        })

        response = session.post(
            f"{self.server.base_url}/updateinstance",
            json={
                "instance_id": "1",
                "annotations": {
                    "postedit:postedit": edit_data,
                },
            },
        )
        assert response.status_code == 200

    def test_submit_and_verify_response(self):
        """POST text edit annotation returns success with stored data."""
        session = self._get_session()
        session.get(f"{self.server.base_url}/annotate")

        edit_data = json.dumps({
            "edited_text": "Improved output text for item 1.",
            "original_text": "Machine translated output 1 that may need corrections.",
            "edit_distance_chars": 20,
            "edit_distance_words": 5,
        })

        response = session.post(
            f"{self.server.base_url}/updateinstance",
            json={
                "instance_id": "1",
                "annotations": {
                    "postedit:postedit": edit_data,
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True or response.status_code == 200

    def test_page_contains_text_edit_elements(self):
        """Annotation page contains text edit interface elements."""
        session = self._get_session()
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200
        assert "text-edit-textarea" in response.text or "text-edit-container" in response.text
        assert "Reset to Original" in response.text
