"""
Integration tests for the crowd-platform admin API blueprint
(/admin/api/crowd/...): RBAC enforcement, status overview, and input
validation. Prolific API calls themselves are unit-tested with mocks in
tests/unit/test_prolific_api_client.py — these tests never leave localhost.
"""

import json
import os
import time

import pytest
import requests
import yaml

from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory
from tests.server.test_prolific_server_integration import SimpleTestServer

API_KEY = "test-crowd-admin-key"


def _write_config(test_dir, port):
    test_data = [{"id": "item_1", "text": "One item."}]
    data_file = os.path.join(test_dir, 'test_data.json')
    with open(data_file, 'w') as f:
        for item in test_data:
            f.write(json.dumps(item) + '\n')
    output_dir = os.path.join(test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    config = {
        "debug": False,
        "annotation_task_name": f"Crowd Admin Test {port}",
        "admin_api_key": API_KEY,
        "login": {"type": "url_direct", "url_argument": "PROLIFIC_PID"},
        "completion_code": "ADMIN-TEST-CODE",
        "authentication": {"method": "in_memory"},
        "require_password": False,
        "data_files": [data_file],
        "item_properties": {"text_key": "text", "id_key": "id"},
        "annotation_schemes": [
            {"name": "sentiment", "annotation_type": "radio",
             "labels": ["positive", "negative"], "description": "Sentiment?"}
        ],
        "assignment_strategy": "random",
        "max_annotations_per_user": 1,
        "phases": {"order": ["annotation"], "annotation": {"type": "annotation"}},
        "site_file": "base_template.html",
        "site_dir": "default",
        "output_annotation_dir": output_dir,
        "task_dir": test_dir,
        "port": port,
        "host": "0.0.0.0",
        "secret_key": f"test-secret-{port}",
        "persist_sessions": False,
        "alert_time_each_instance": 0,
    }
    config_file = os.path.join(test_dir, 'config.yaml')
    with open(config_file, 'w') as f:
        yaml.dump(config, f)
    return config_file


class TestCrowdAdminAPI:
    @pytest.fixture(scope="class")
    def admin_server(self, request):
        port = find_free_port(preferred_port=9860)
        test_dir = create_test_directory(f"crowd_admin_test_{port}")
        config_file = _write_config(test_dir, port)
        server = SimpleTestServer(config_file, port)
        if not server.start():
            cleanup_test_directory(test_dir)
            pytest.skip("Could not start test server")
        yield server
        server.stop()
        time.sleep(0.5)
        cleanup_test_directory(test_dir)

    def test_status_requires_permission(self, admin_server):
        response = requests.get(
            f"{admin_server.base_url}/admin/api/crowd/status", timeout=5)
        assert response.status_code == 403

        response = requests.get(
            f"{admin_server.base_url}/admin/api/crowd/status",
            headers={"X-API-Key": "wrong-key"}, timeout=5)
        assert response.status_code == 403

    def test_status_with_admin_key(self, admin_server):
        response = requests.get(
            f"{admin_server.base_url}/admin/api/crowd/status",
            headers={"X-API-Key": API_KEY}, timeout=5)
        assert response.status_code == 200
        data = response.json()
        assert data["provider"] == "url_direct"
        assert data["api_configured"] is False

    def test_api_endpoints_need_token(self, admin_server):
        """Without a Prolific token, API-backed endpoints answer 400, not 500."""
        headers = {"X-API-Key": API_KEY}
        response = requests.get(
            f"{admin_server.base_url}/admin/api/crowd/study",
            headers=headers, timeout=5)
        assert response.status_code == 400
        assert "token" in response.json()["error"].lower()

        response = requests.post(
            f"{admin_server.base_url}/admin/api/crowd/submissions/sub1/approve",
            headers=headers, timeout=5)
        assert response.status_code == 400

    def test_mutating_endpoints_require_permission(self, admin_server):
        for path in ("/admin/api/crowd/study",
                     "/admin/api/crowd/study/s1/publish",
                     "/admin/api/crowd/submissions/sub1/approve",
                     "/admin/api/crowd/study/s1/bonus",
                     "/admin/api/crowd/qualification_sync"):
            response = requests.post(
                f"{admin_server.base_url}{path}", json={}, timeout=5)
            assert response.status_code == 403, f"{path} should 403 without key"

    def test_validation_errors(self, admin_server):
        headers = {"X-API-Key": API_KEY}
        # Bad study action
        response = requests.post(
            f"{admin_server.base_url}/admin/api/crowd/study/s1/explode",
            headers=headers, json={}, timeout=5)
        assert response.status_code == 400

        # qualification_sync with unknown source
        response = requests.post(
            f"{admin_server.base_url}/admin/api/crowd/qualification_sync",
            headers=headers, json={"source": "everything"}, timeout=5)
        assert response.status_code == 400


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
