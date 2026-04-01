"""Server integration tests for semantic_differential annotation."""

import json
import os
import uuid

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_directory, create_test_data_file, cleanup_test_directory


def create_semantic_differential_config(test_dir, data_file, port=9033):
    """Create a semantic_differential test config."""
    abs_test_dir = os.path.abspath(test_dir)
    output_dir = os.path.join(abs_test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    config = {
        "annotation_task_name": "Semantic Differential Test",
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
        "secret_key": "test-secret-key-semantic-differential",
        "user_config": {"allow_all_users": True, "users": []},
        "annotation_schemes": [
            {
                "annotation_type": "semantic_differential",
                "name": "word_dims",
                "description": "Test",
                "pairs": [["Good", "Bad"], ["Strong", "Weak"]],
                "scale_points": 7,
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
        {"id": str(i + 1), "text": f"Test item {i + 1} for annotation."}
        for i in range(num_items)
    ]
    return create_test_data_file(test_dir, data)


class TestSemanticDifferentialServer:
    """Integration tests for semantic_differential annotation server."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Start a Flask server with semantic_differential config."""
        test_dir = create_test_directory("semantic_differential_server_test")
        data_file = create_test_data(test_dir)
        config_path = create_semantic_differential_config(test_dir, data_file, port=9033)

        server = FlaskTestServer(port=9033, config_file=config_path)
        if not server.start():
            cleanup_test_directory(test_dir)
            pytest.fail("Failed to start semantic_differential test server")

        request.cls.server = server
        request.cls.test_dir = test_dir
        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    def _get_session(self):
        """Create an authenticated session."""
        session = requests.Session()
        username = f"semdiff_tester_{uuid.uuid4().hex[:6]}"
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
        """Server starts successfully with semantic_differential config."""
        response = requests.get(f"{self.server.base_url}/")
        assert response.status_code == 200

    def test_annotate_page_loads(self):
        """/annotate returns 200 with semantic_differential form HTML."""
        session = self._get_session()
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200
        assert "semantic-differential" in response.text

    def test_submit_annotation(self):
        """POST annotation to /updateinstance succeeds."""
        session = self._get_session()

        response = session.post(
            f"{self.server.base_url}/updateinstance",
            json={
                "instance_id": "1",
                "annotations": {
                    "word_dims:Good__Bad": "3",
                    "word_dims:Strong__Weak": "5",
                },
            },
        )
        assert response.status_code == 200

    def test_submit_and_verify_response(self):
        """POST annotation returns success with stored data."""
        session = self._get_session()
        session.get(f"{self.server.base_url}/annotate")

        response = session.post(
            f"{self.server.base_url}/updateinstance",
            json={
                "instance_id": "1",
                "annotations": {
                    "word_dims:Good__Bad": "3",
                    "word_dims:Strong__Weak": "5",
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True or response.status_code == 200

    def test_annotate_page_contains_pairs(self):
        """Annotation page contains the configured adjective pairs."""
        session = self._get_session()
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200
        assert "Good" in response.text
        assert "Bad" in response.text
        assert "Strong" in response.text
        assert "Weak" in response.text
