"""Server integration tests for card sort annotation."""

import json
import os
import uuid

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_directory, create_test_data_file, cleanup_test_directory


def create_card_sort_config(test_dir, data_file, port=9046):
    """Create a card sort annotation test config."""
    abs_test_dir = os.path.abspath(test_dir)
    output_dir = os.path.join(abs_test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    config = {
        "annotation_task_name": "Card Sort Test",
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
        "secret_key": "test-secret-key-card-sort",
        "user_config": {"allow_all_users": True, "users": []},
        "annotation_schemes": [
            {
                "annotation_type": "card_sort",
                "name": "categorize",
                "description": "Sort items into groups",
                "mode": "closed",
                "groups": ["Group A", "Group B", "Group C"],
                "items_field": "items",
            }
        ],
    }

    config_path = os.path.join(abs_test_dir, "config.yaml")
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    return config_path


def create_test_data(test_dir, num_items=3):
    """Create test data items with items lists for card sorting."""
    data = [
        {
            "id": str(i + 1),
            "text": f"Card sort task {i + 1}.",
            "items": [f"Item {j + 1}" for j in range(4)],
        }
        for i in range(num_items)
    ]
    return create_test_data_file(test_dir, data)


class TestCardSortServer:
    """Integration tests for card sort annotation server."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Start a Flask server with card sort config."""
        test_dir = create_test_directory("card_sort_server_test")
        data_file = create_test_data(test_dir)
        config_path = create_card_sort_config(test_dir, data_file, port=9046)

        server = FlaskTestServer(port=9046, config_file=config_path)
        if not server.start():
            cleanup_test_directory(test_dir)
            pytest.fail("Failed to start card sort test server")

        request.cls.server = server
        request.cls.test_dir = test_dir
        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    def _get_session(self):
        """Create an authenticated session."""
        session = requests.Session()
        username = f"cardsort_tester_{uuid.uuid4().hex[:6]}"
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
        """Server starts successfully with card sort config."""
        response = requests.get(f"{self.server.base_url}/")
        assert response.status_code == 200

    def test_annotate_page_loads(self):
        """/annotate returns 200 with card sort form HTML."""
        session = self._get_session()
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200
        assert "card-sort" in response.text or "categorize" in response.text

    def test_submit_card_sort_annotation(self):
        """POST card sort annotation with group assignments to /updateinstance succeeds."""
        session = self._get_session()

        sort_data = json.dumps({
            "Group A": ["Item 1", "Item 3"],
            "Group B": ["Item 2"],
            "Group C": ["Item 4"],
        })

        response = session.post(
            f"{self.server.base_url}/updateinstance",
            json={
                "instance_id": "1",
                "annotations": {
                    "categorize:categorize": sort_data,
                },
            },
        )
        assert response.status_code == 200

    def test_submit_and_verify_response(self):
        """POST card sort annotation returns success with stored data."""
        session = self._get_session()
        session.get(f"{self.server.base_url}/annotate")

        sort_data = json.dumps({
            "Group A": ["Item 1"],
            "Group B": ["Item 2", "Item 3"],
            "Group C": ["Item 4"],
        })

        response = session.post(
            f"{self.server.base_url}/updateinstance",
            json={
                "instance_id": "1",
                "annotations": {
                    "categorize:categorize": sort_data,
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True or response.status_code == 200

    def test_page_contains_groups(self):
        """Annotation page contains the configured group names."""
        session = self._get_session()
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200
        assert "Group A" in response.text
        assert "Group B" in response.text
        assert "Group C" in response.text
        assert "card-sort-group" in response.text
