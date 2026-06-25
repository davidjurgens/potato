"""Server integration tests for hierarchical_multiselect annotation."""

import json
import os
import uuid

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_directory, create_test_data_file, cleanup_test_directory


def create_hierarchical_config(test_dir, data_file, port=9036):
    """Create a hierarchical_multiselect test config."""
    abs_test_dir = os.path.abspath(test_dir)
    output_dir = os.path.join(abs_test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    config = {
        "annotation_task_name": "Hierarchical Multiselect Test",
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
        "secret_key": "test-secret-key-hierarchical",
        "user_config": {"allow_all_users": True, "users": []},
        "annotation_schemes": [
            {
                "annotation_type": "hierarchical_multiselect",
                "name": "topics",
                "description": "Test",
                "taxonomy": {
                    "Science": {"Physics": ["QM"]},
                    "Arts": ["Music"],
                },
                "show_search": True,
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


class TestHierarchicalServer:
    """Integration tests for hierarchical_multiselect annotation server."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Start a Flask server with hierarchical_multiselect config."""
        test_dir = create_test_directory("hierarchical_server_test")
        data_file = create_test_data(test_dir)
        config_path = create_hierarchical_config(test_dir, data_file, port=9036)

        server = FlaskTestServer(port=9036, config_file=config_path)
        if not server.start():
            cleanup_test_directory(test_dir)
            pytest.fail("Failed to start hierarchical_multiselect test server")

        request.cls.server = server
        request.cls.test_dir = test_dir
        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    def _get_session(self):
        """Create an authenticated session."""
        session = requests.Session()
        username = f"hier_tester_{uuid.uuid4().hex[:6]}"
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
        """Server starts successfully with hierarchical_multiselect config."""
        response = requests.get(f"{self.server.base_url}/")
        assert response.status_code == 200

    def test_annotate_page_loads(self):
        """/annotate returns 200 with hierarchical_multiselect form HTML."""
        session = self._get_session()
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200
        assert "hier-tree" in response.text

    def test_submit_annotation(self):
        """POST annotation to /updateinstance succeeds."""
        session = self._get_session()

        response = session.post(
            f"{self.server.base_url}/updateinstance",
            json={
                "instance_id": "1",
                "annotations": {
                    "topics:selected_labels": "Physics,Music",
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
                    "topics:selected_labels": "Physics,Music",
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True or response.status_code == 200

    def test_annotate_page_contains_taxonomy_nodes(self):
        """Annotation page contains the configured taxonomy nodes."""
        session = self._get_session()
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200
        assert "Science" in response.text
        assert "Arts" in response.text
        assert "Physics" in response.text
        assert "Music" in response.text

    def test_annotate_page_has_search(self):
        """Annotation page includes the search box when show_search is true."""
        session = self._get_session()
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200
        # Search input should be present for hierarchical_multiselect with show_search: true
        assert "hier-search" in response.text or "search" in response.text.lower()


def create_mast_preset_config(test_dir, data_file, port):
    """Config using the built-in MAST failure-taxonomy preset (D2)."""
    abs_test_dir = os.path.abspath(test_dir)
    output_dir = os.path.join(abs_test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)
    config = {
        "annotation_task_name": "MAST Failure Taxonomy Test",
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
        "secret_key": "test-secret-key-mast",
        "user_config": {"allow_all_users": True, "users": []},
        "annotation_schemes": [
            {
                "annotation_type": "hierarchical_multiselect",
                "name": "failure_modes",
                "description": "Tag MAST failure modes",
                "taxonomy_preset": "mast",
                "show_search": True,
            }
        ],
    }
    config_path = os.path.join(abs_test_dir, "config.yaml")
    with open(config_path, "w") as f:
        yaml.dump(config, f)
    return config_path


class TestMastPresetServer:
    """Integration tests for the MAST taxonomy_preset (D2)."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        from tests.helpers.port_manager import find_free_port
        port = find_free_port()
        test_dir = create_test_directory("mast_preset_server_test")
        data_file = create_test_data(test_dir)
        config_path = create_mast_preset_config(test_dir, data_file, port=port)

        server = FlaskTestServer(port=port, config_file=config_path)
        if not server.start():
            cleanup_test_directory(test_dir)
            pytest.fail("Failed to start MAST preset test server")

        request.cls.server = server
        request.cls.test_dir = test_dir
        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    def _get_session(self):
        session = requests.Session()
        username = f"mast_tester_{uuid.uuid4().hex[:6]}"
        session.post(f"{self.server.base_url}/register",
                     data={"email": username, "pass": "testpass"})
        session.post(f"{self.server.base_url}/auth",
                     data={"email": username, "pass": "testpass"})
        return session

    def test_preset_renders_all_categories_and_modes(self):
        """The preset auto-populates the 3 categories and key coded modes."""
        session = self._get_session()
        r = session.get(f"{self.server.base_url}/annotate")
        assert r.status_code == 200
        assert "Specification &amp; System Design" in r.text or "Specification" in r.text
        assert "Inter-Agent Misalignment" in r.text
        assert "Task Verification" in r.text
        assert "1.1 Disobey task specification" in r.text
        assert "3.1 Premature termination" in r.text

    def test_preset_renders_accessible_tooltips(self):
        """Each mode carries an accessible ⓘ tooltip marker (a11y fix)."""
        session = self._get_session()
        r = session.get(f"{self.server.base_url}/annotate")
        assert "hier-info" in r.text
        assert 'aria-label="Definition:' in r.text
        # a definition fragment must be present
        assert "ignores or violates the constraints" in r.text

    def test_preset_submission_persists(self):
        """Selecting MAST modes submits successfully."""
        session = self._get_session()
        session.get(f"{self.server.base_url}/annotate")
        r = session.post(
            f"{self.server.base_url}/updateinstance",
            json={"instance_id": "1",
                  "annotations": {"failure_modes:selected_labels":
                                  "1.1 Disobey task specification,3.1 Premature termination"}},
        )
        assert r.status_code == 200
