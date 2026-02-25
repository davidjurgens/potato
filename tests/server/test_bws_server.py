"""Server integration tests for BWS annotation."""

import json
import os
import re
import uuid

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_directory, create_test_data_file, cleanup_test_directory


def create_bws_config(test_dir, data_file, num_items=10, tuple_size=4, num_tuples=5, port=9010):
    """Create a BWS test config."""
    abs_test_dir = os.path.abspath(test_dir)
    output_dir = os.path.join(abs_test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    config = {
        "annotation_task_name": "BWS Test",
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
        "secret_key": "test-secret-key-bws",
        "user_config": {"allow_all_users": True, "users": []},
        "admin_api_key": "test-admin-key",
        "bws_config": {
            "tuple_size": tuple_size,
            "num_tuples": num_tuples,
            "seed": 42,
        },
        "annotation_schemes": [
            {
                "annotation_type": "bws",
                "name": "test_bws",
                "description": "Test BWS",
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


def create_bws_pool_data(test_dir, num_items=10):
    """Create pool data for BWS testing."""
    data = [
        {"id": f"s{i:03d}", "text": f"Test item number {i} with some text content."}
        for i in range(1, num_items + 1)
    ]
    return create_test_data_file(test_dir, data)


def extract_instance_id(html):
    """Extract the current instance ID from the annotation page HTML."""
    # Look for instance_id in the page's JavaScript config
    match = re.search(r'"instance_id"\s*:\s*"([^"]+)"', html)
    if match:
        return match.group(1)
    # Also try the data attribute
    match = re.search(r'data-instance-id="([^"]+)"', html)
    if match:
        return match.group(1)
    # Try the instance config
    match = re.search(r'"id"\s*:\s*"(bws_tuple_\d+)"', html)
    if match:
        return match.group(1)
    return None


class TestBwsServer:
    """Integration tests for BWS annotation server."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Start a Flask server with BWS config."""
        test_dir = create_test_directory("bws_server_test")
        data_file = create_bws_pool_data(test_dir, num_items=10)
        config_path = create_bws_config(
            test_dir, data_file, num_items=10, tuple_size=4, num_tuples=5, port=9010
        )

        server = FlaskTestServer(port=9010, config_file=config_path)
        if not server.start():
            cleanup_test_directory(test_dir)
            pytest.fail("Failed to start BWS test server")

        request.cls.server = server
        request.cls.test_dir = test_dir
        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    def _get_session(self):
        """Create an authenticated session."""
        session = requests.Session()
        username = f"bws_tester_{uuid.uuid4().hex[:6]}"
        session.post(
            f"{self.server.base_url}/register",
            data={"email": username, "pass": "testpass"},
        )
        session.post(
            f"{self.server.base_url}/auth",
            data={"email": username, "pass": "testpass"},
        )
        return session

    def _submit_annotation(self, session, instance_id, best="A", worst="D"):
        """Submit a BWS annotation in the correct format."""
        return session.post(
            f"{self.server.base_url}/updateinstance",
            json={
                "instance_id": instance_id,
                "annotations": {
                    "test_bws:best": best,
                    "test_bws:worst": worst,
                },
            },
        )

    def test_server_starts_with_bws_config(self):
        """Server starts successfully with BWS config."""
        response = requests.get(f"{self.server.base_url}/")
        assert response.status_code == 200

    def test_tuple_instances_created(self):
        """Admin overview shows correct number of tuple instances (not pool items)."""
        response = requests.get(
            f"{self.server.base_url}/admin/api/overview",
            headers={"X-API-Key": "test-admin-key"},
        )
        assert response.status_code == 200
        data = response.json()
        # Should have 5 tuples, not 10 pool items
        overview = data.get("overview", {})
        assert overview.get("total_items") == 5

    def test_annotate_page_loads(self):
        """/annotate returns 200 with BWS form HTML."""
        session = self._get_session()
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200
        assert "bws" in response.text.lower() or "annotation-form" in response.text

    def test_bws_items_in_var_elems(self):
        """Response HTML contains <script id="bws_items"> with JSON array."""
        session = self._get_session()
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200
        assert 'id="bws_items"' in response.text

    def test_submit_bws_annotation(self):
        """POST annotation with best and worst values succeeds."""
        session = self._get_session()

        # Load the annotation page first to get instance_id
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200
        instance_id = extract_instance_id(response.text)

        if instance_id:
            response = self._submit_annotation(session, instance_id, "B", "D")
            assert response.status_code == 200

    def test_annotate_page_reloads(self):
        """Annotation page can be reloaded after submission."""
        session = self._get_session()

        # Load page
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200
        instance_id = extract_instance_id(response.text)

        if instance_id:
            self._submit_annotation(session, instance_id, "A", "C")

        # Reload page
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200

    def test_navigate_between_tuples(self):
        """Can load annotation page multiple times (different tuples served)."""
        session = self._get_session()

        # Load first tuple
        response1 = session.get(f"{self.server.base_url}/annotate")
        assert response1.status_code == 200

        # Submit and go next via POST to /next_instance
        instance_id = extract_instance_id(response1.text)
        if instance_id:
            self._submit_annotation(session, instance_id, "A", "D")
            # Navigate forward
            session.post(f"{self.server.base_url}/next_instance")

        # Load next tuple
        response2 = session.get(f"{self.server.base_url}/annotate")
        assert response2.status_code == 200

    def test_bws_scoring_admin_api(self):
        """GET /admin/api/bws_scoring returns scoring status."""
        response = requests.get(
            f"{self.server.base_url}/admin/api/bws_scoring",
            headers={"X-API-Key": "test-admin-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "total_items" in data

    def test_bws_scoring_generate(self):
        """POST /admin/api/bws_scoring/generate computes scores."""
        response = requests.post(
            f"{self.server.base_url}/admin/api/bws_scoring/generate?method=counting",
            headers={"X-API-Key": "test-admin-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "success"
        assert "scores" in data
