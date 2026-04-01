"""Server integration tests for Iterative BWS annotation."""

import json
import os
import re
import uuid

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_directory, create_test_data_file, cleanup_test_directory


def create_ibws_config(test_dir, data_file, num_items=12, tuple_size=4, port=9011):
    """Create an IBWS test config."""
    abs_test_dir = os.path.abspath(test_dir)
    output_dir = os.path.join(abs_test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    config = {
        "annotation_task_name": "IBWS Test",
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
        "secret_key": "test-secret-key-ibws",
        "user_config": {"allow_all_users": True, "users": []},
        "admin_api_key": "test-admin-key",
        "ibws_config": {
            "tuple_size": tuple_size,
            "seed": 42,
            "scoring_method": "counting",
            "tuples_per_item_per_round": 2,
            "max_rounds": 3,
        },
        "annotation_schemes": [
            {
                "annotation_type": "bws",
                "name": "test_ibws",
                "description": "Test IBWS",
                "best_description": "Which is best?",
                "worst_description": "Which is worst?",
                "tuple_size": tuple_size,
                "sequential_key_binding": True,
            }
        ],
    }

    config_path = os.path.join(abs_test_dir, "config.yaml")
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    return config_path


def create_ibws_pool_data(test_dir, num_items=12):
    """Create pool data for IBWS testing."""
    data = [
        {"id": f"s{i:03d}", "text": f"Test item number {i} with some text content."}
        for i in range(1, num_items + 1)
    ]
    return create_test_data_file(test_dir, data)


def extract_instance_id(html):
    """Extract the current instance ID from the annotation page HTML."""
    match = re.search(r'"instance_id"\s*:\s*"([^"]+)"', html)
    if match:
        return match.group(1)
    match = re.search(r'data-instance-id="([^"]+)"', html)
    if match:
        return match.group(1)
    match = re.search(r'"id"\s*:\s*"(ibws_r\d+_b\d+_\d+)"', html)
    if match:
        return match.group(1)
    return None


class TestIbwsServer:
    """Integration tests for IBWS annotation server."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Start a Flask server with IBWS config."""
        test_dir = create_test_directory("ibws_server_test")
        data_file = create_ibws_pool_data(test_dir, num_items=12)
        config_path = create_ibws_config(
            test_dir, data_file, num_items=12, tuple_size=4, port=9011
        )

        server = FlaskTestServer(port=9011, config_file=config_path)
        if not server.start():
            cleanup_test_directory(test_dir)
            pytest.fail("Failed to start IBWS test server")

        request.cls.server = server
        request.cls.test_dir = test_dir
        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    def _get_session(self):
        """Create an authenticated session."""
        session = requests.Session()
        username = f"ibws_tester_{uuid.uuid4().hex[:6]}"
        session.post(
            f"{self.server.base_url}/register",
            data={"email": username, "pass": "testpass"},
        )
        session.post(
            f"{self.server.base_url}/auth",
            data={"email": username, "pass": "testpass"},
        )
        return session

    def test_server_starts_with_ibws_config(self):
        """Server starts successfully with IBWS config."""
        response = requests.get(f"{self.server.base_url}/")
        assert response.status_code == 200

    def test_round_1_tuples_created(self):
        """Admin overview shows round-1 tuples as items."""
        response = requests.get(
            f"{self.server.base_url}/admin/api/overview",
            headers={"X-API-Key": "test-admin-key"},
        )
        assert response.status_code == 200
        data = response.json()
        overview = data.get("overview", {})
        # Should have tuples, not the original 12 pool items
        total = overview.get("total_items", 0)
        assert total > 0

    def test_annotate_page_loads(self):
        """/annotate returns 200 with BWS form HTML."""
        session = self._get_session()
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200
        assert "bws" in response.text.lower() or "annotation-form" in response.text

    def test_bws_items_in_response(self):
        """Response HTML contains <script id="bws_items"> with JSON array."""
        session = self._get_session()
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200
        assert 'id="bws_items"' in response.text

    def test_ibws_round_banner_present(self):
        """Response HTML contains IBWS round banner."""
        session = self._get_session()
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200
        assert "ibws-round-banner" in response.text

    def test_ibws_status_admin_api(self):
        """GET /admin/api/ibws_status returns round info."""
        response = requests.get(
            f"{self.server.base_url}/admin/api/ibws_status",
            headers={"X-API-Key": "test-admin-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "current_round" in data
        assert data["current_round"] == 1
        assert data["total_items"] == 12
        assert data["completed"] is False

    def test_ibws_ranking_admin_api(self):
        """GET /admin/api/ibws_ranking returns ranking data."""
        response = requests.get(
            f"{self.server.base_url}/admin/api/ibws_ranking",
            headers={"X-API-Key": "test-admin-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "ranking" in data
        assert len(data["ranking"]) == 12  # All pool items in ranking
