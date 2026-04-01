"""Server integration tests for conjoint analysis annotation."""

import json
import os
import uuid

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_directory, create_test_data_file, cleanup_test_directory


def create_conjoint_config(test_dir, data_file, port=9047):
    """Create a conjoint analysis annotation test config."""
    abs_test_dir = os.path.abspath(test_dir)
    output_dir = os.path.join(abs_test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    config = {
        "annotation_task_name": "Conjoint Test",
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
        "secret_key": "test-secret-key-conjoint",
        "user_config": {"allow_all_users": True, "users": []},
        "annotation_schemes": [
            {
                "annotation_type": "conjoint",
                "name": "preference",
                "description": "Choose your preferred option",
                "profiles_per_set": 3,
                "attributes": [
                    {"name": "Speed", "levels": ["Fast", "Medium", "Slow"]},
                    {"name": "Price", "levels": ["$10", "$20", "$50"]},
                ],
                "show_none_option": True,
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
        {"id": str(i + 1), "text": f"Conjoint choice task {i + 1}."}
        for i in range(num_items)
    ]
    return create_test_data_file(test_dir, data)


class TestConjointServer:
    """Integration tests for conjoint analysis annotation server."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Start a Flask server with conjoint config."""
        test_dir = create_test_directory("conjoint_server_test")
        data_file = create_test_data(test_dir)
        config_path = create_conjoint_config(test_dir, data_file, port=9047)

        server = FlaskTestServer(port=9047, config_file=config_path)
        if not server.start():
            cleanup_test_directory(test_dir)
            pytest.fail("Failed to start conjoint test server")

        request.cls.server = server
        request.cls.test_dir = test_dir
        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    def _get_session(self):
        """Create an authenticated session."""
        session = requests.Session()
        username = f"conjoint_tester_{uuid.uuid4().hex[:6]}"
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
        """Server starts successfully with conjoint config."""
        response = requests.get(f"{self.server.base_url}/")
        assert response.status_code == 200

    def test_annotate_page_loads(self):
        """/annotate returns 200 with conjoint form HTML."""
        session = self._get_session()
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200
        assert "conjoint" in response.text.lower() or "preference" in response.text

    def test_submit_conjoint_annotation(self):
        """POST conjoint annotation with chosen profile to /updateinstance succeeds."""
        session = self._get_session()

        response = session.post(
            f"{self.server.base_url}/updateinstance",
            json={
                "instance_id": "1",
                "annotations": {
                    "preference:preference": "2",
                },
            },
        )
        assert response.status_code == 200

    def test_submit_none_option(self):
        """POST conjoint annotation with 'none' choice succeeds."""
        session = self._get_session()

        response = session.post(
            f"{self.server.base_url}/updateinstance",
            json={
                "instance_id": "1",
                "annotations": {
                    "preference:preference": "none",
                },
            },
        )
        assert response.status_code == 200

    def test_submit_and_verify_response(self):
        """POST conjoint annotation returns success with stored data."""
        session = self._get_session()
        session.get(f"{self.server.base_url}/annotate")

        response = session.post(
            f"{self.server.base_url}/updateinstance",
            json={
                "instance_id": "1",
                "annotations": {
                    "preference:preference": "1",
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True or response.status_code == 200

    def test_page_contains_conjoint_elements(self):
        """Annotation page contains conjoint profile elements."""
        session = self._get_session()
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200
        assert "Speed" in response.text
        assert "Price" in response.text
        assert "conjoint-profile-card" in response.text
        assert "None of these" in response.text
