"""
Tests for logout behavior with url_direct (Prolific) login.

Issue #149: When using url_direct login, clicking Logout would redirect to
the home page which requires PROLIFIC_PID parameter, showing an error.
The fix renders a standalone logged-out page instead.
"""

import json
import os
import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_directory, cleanup_test_directory
from tests.helpers.port_manager import find_free_port


def create_url_direct_config(test_dir: str, port: int) -> str:
    """Create a config with url_direct login for testing logout."""
    test_data = [
        {"id": "item_1", "text": "Test item one."},
        {"id": "item_2", "text": "Test item two."},
    ]
    data_file = os.path.join(test_dir, "test_data.json")
    with open(data_file, "w") as f:
        for item in test_data:
            f.write(json.dumps(item) + "\n")

    output_dir = os.path.join(test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    config = {
        "annotation_task_name": f"URL-Direct Logout Test {port}",
        "login": {
            "type": "url_direct",
            "url_argument": "PROLIFIC_PID",
        },
        "completion_code": "TEST-LOGOUT-CODE",
        "output_annotation_dir": output_dir,
        "data_files": [data_file],
        "item_properties": {
            "id_key": "id",
            "text_key": "text",
        },
        "annotation_schemes": [
            {
                "annotation_type": "radio",
                "name": "sentiment",
                "description": "Sentiment",
                "labels": ["positive", "negative"],
            }
        ],
        "task_dir": test_dir,
        "port": port,
        "server_name": f"127.0.0.1:{port}",
    }

    config_file = os.path.join(test_dir, "config.yaml")
    with open(config_file, "w") as f:
        yaml.dump(config, f)
    return config_file


class TestUrlDirectLogout:
    """Test that logout works correctly for url_direct login users."""

    @pytest.fixture(scope="class")
    def url_direct_server(self):
        port = find_free_port()
        test_dir = create_test_directory(f"url_direct_logout_{port}")
        config_file = create_url_direct_config(test_dir, port)
        server = FlaskTestServer(port=port, config_file=config_file)
        if not server.start():
            cleanup_test_directory(test_dir)
            pytest.fail("Failed to start url_direct test server")
        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    def test_logout_renders_logged_out_page(self, url_direct_server):
        """Logout with url_direct login should render logged_out.html, not redirect to home."""
        server = url_direct_server
        session = requests.Session()

        # Login via URL parameter
        resp = session.get(f"{server.base_url}/?PROLIFIC_PID=test_worker_1", allow_redirects=True, timeout=5)
        assert resp.status_code == 200

        # Now logout
        resp = session.get(f"{server.base_url}/logout", allow_redirects=True, timeout=5)
        assert resp.status_code == 200

        # Should see the logged-out page, NOT a PROLIFIC_PID error
        assert "Logged Out" in resp.text
        assert "PROLIFIC_PID" not in resp.text

    def test_logout_does_not_require_url_parameter(self, url_direct_server):
        """After logout, the page should not demand a URL parameter."""
        server = url_direct_server
        session = requests.Session()

        # Login
        session.get(f"{server.base_url}/?PROLIFIC_PID=test_worker_2", allow_redirects=True, timeout=5)

        # Logout
        resp = session.get(f"{server.base_url}/logout", allow_redirects=True, timeout=5)

        # Page should be self-contained — no error about missing parameters
        assert "Missing required URL parameter" not in resp.text

    def test_logout_mentions_saved_responses(self, url_direct_server):
        """Logged-out page should reassure user that data was saved."""
        server = url_direct_server
        session = requests.Session()

        session.get(f"{server.base_url}/?PROLIFIC_PID=test_worker_3", allow_redirects=True, timeout=5)
        resp = session.get(f"{server.base_url}/logout", allow_redirects=True, timeout=5)

        assert "saved" in resp.text.lower()

    def test_logout_without_prior_login(self, url_direct_server):
        """Logout without prior login should still render the logged-out page (not crash)."""
        server = url_direct_server
        session = requests.Session()

        # Directly access logout without logging in first
        resp = session.get(f"{server.base_url}/logout", allow_redirects=True, timeout=5)
        assert resp.status_code == 200
        assert "Logged Out" in resp.text


class TestStandardLogout:
    """Test that standard login logout still redirects to home as before."""

    @pytest.fixture(scope="class")
    def standard_server(self):
        port = find_free_port()
        test_dir = create_test_directory(f"standard_logout_{port}")

        test_data = [{"id": "item_1", "text": "Test item one."}]
        data_file = os.path.join(test_dir, "test_data.json")
        with open(data_file, "w") as f:
            for item in test_data:
                f.write(json.dumps(item) + "\n")

        output_dir = os.path.join(test_dir, "output")
        os.makedirs(output_dir, exist_ok=True)

        config = {
            "annotation_task_name": f"Standard Logout Test {port}",
            "output_annotation_dir": output_dir,
            "data_files": [data_file],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "sentiment",
                    "description": "Sentiment",
                    "labels": ["positive", "negative"],
                }
            ],
            "task_dir": test_dir,
            "port": port,
            "server_name": f"127.0.0.1:{port}",
        }
        config_file = os.path.join(test_dir, "config.yaml")
        with open(config_file, "w") as f:
            yaml.dump(config, f)

        server = FlaskTestServer(port=port, config_file=config_file)
        if not server.start():
            cleanup_test_directory(test_dir)
            pytest.fail("Failed to start standard test server")
        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    def test_standard_logout_redirects_to_home(self, standard_server):
        """Standard login logout should redirect to home page (login form)."""
        server = standard_server
        session = requests.Session()

        # Register and login
        session.post(f"{server.base_url}/register",
                     data={"email": "testuser", "pass": "testpass"}, timeout=5)
        session.post(f"{server.base_url}/auth",
                     data={"email": "testuser", "pass": "testpass"}, timeout=5)

        # Logout — should redirect to home, not show logged_out.html
        resp = session.get(f"{server.base_url}/logout", allow_redirects=True, timeout=5)
        assert resp.status_code == 200
        # Should see the login page, not the logged_out template
        assert "Logged Out" not in resp.text
