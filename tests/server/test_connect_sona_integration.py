"""
Integration tests for the Connect and SONA providers: arrival with each
platform's URL parameters and the done-page completion behavior (Connect
code display; SONA client-side fallback link when the server-side credit
grant cannot reach the SONA host).
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


def _write_config(test_dir, port, login_argument, crowdsourcing_block, task_name):
    test_data = [
        {"id": "item_1", "text": "First item."},
        {"id": "item_2", "text": "Second item."},
    ]
    data_file = os.path.join(test_dir, 'test_data.json')
    with open(data_file, 'w') as f:
        for item in test_data:
            f.write(json.dumps(item) + '\n')
    output_dir = os.path.join(test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    config = {
        "debug": False,
        "annotation_task_name": task_name,
        "login": {"type": "url_direct", "url_argument": login_argument},
        "crowdsourcing": crowdsourcing_block,
        "hide_navbar": True,
        "authentication": {"method": "in_memory"},
        "require_password": False,
        "data_files": [data_file],
        "item_properties": {"text_key": "text", "id_key": "id"},
        "annotation_schemes": [
            {"name": "sentiment", "annotation_type": "radio",
             "labels": ["positive", "negative"], "description": "Sentiment?"}
        ],
        "assignment_strategy": "random",
        "max_annotations_per_user": 2,
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


def _complete_all(server, session, item_ids):
    for item_id in item_ids:
        response = session.post(
            f"{server.base_url}/updateinstance",
            json={"instance_id": item_id,
                  "annotations": {"sentiment:positive": "true"},
                  "span_annotations": []},
            timeout=5)
        assert response.status_code == 200
        response = session.post(
            f"{server.base_url}/annotate",
            json={"action": "next_instance", "instance_id": item_id},
            allow_redirects=True, timeout=5)
        assert response.status_code == 200


class TestConnectIntegration:
    @pytest.fixture
    def connect_server(self):
        port = find_free_port(preferred_port=9820)
        test_dir = create_test_directory(f"connect_test_{port}")
        config_file = _write_config(
            test_dir, port, "participantId",
            {"provider": "connect",
             "connect": {"completion": {"code": "CR-DONE-55"}}},
            f"Connect Test {port}")
        server = SimpleTestServer(config_file, port)
        if not server.start():
            cleanup_test_directory(test_dir)
            pytest.skip("Could not start test server")
        yield server, test_dir
        server.stop()
        time.sleep(0.5)
        cleanup_test_directory(test_dir)

    def test_connect_flow(self, connect_server):
        server, test_dir = connect_server
        session = requests.Session()

        response = session.get(
            f"{server.base_url}/",
            params={"participantId": "cr_1", "assignmentId": "as_1", "projectId": "pr_1"},
            allow_redirects=True, timeout=5)
        assert response.status_code == 200
        assert "sentiment" in response.text.lower()

        _complete_all(server, session, ["item_1", "item_2"])
        response = session.get(f"{server.base_url}/done", allow_redirects=True, timeout=5)
        assert "CR-DONE-55" in response.text

        # Connect IDs are persisted with the output
        state_file = os.path.join(test_dir, "output", "cr_1", "user_state.json")
        with open(state_file) as f:
            metadata = json.load(f).get("crowd_metadata", {})
        assert metadata.get("provider") == "connect"
        assert metadata.get("session_id") == "as_1"
        assert metadata.get("study_id") == "pr_1"


class TestSonaIntegration:
    @pytest.fixture
    def sona_server(self):
        port = find_free_port(preferred_port=9840)
        test_dir = create_test_directory(f"sona_test_{port}")
        config_file = _write_config(
            test_dir, port, "sona_code",
            {"provider": "sona",
             "sona": {"hostname": "sona.invalid",  # .invalid TLD: guaranteed DNS failure
                      "experiment_id": 42,
                      "credit_token": "tok42"}},
            f"SONA Test {port}")
        server = SimpleTestServer(config_file, port)
        if not server.start():
            cleanup_test_directory(test_dir)
            pytest.skip("Could not start test server")
        yield server, test_dir
        server.stop()
        time.sleep(0.5)
        cleanup_test_directory(test_dir)

    def test_sona_flow_falls_back_to_client_credit_link(self, sona_server):
        server, _ = sona_server
        session = requests.Session()

        response = session.get(
            f"{server.base_url}/", params={"sona_code": "SC12345"},
            allow_redirects=True, timeout=5)
        assert response.status_code == 200

        _complete_all(server, session, ["item_1", "item_2"])
        response = session.get(f"{server.base_url}/done", allow_redirects=True, timeout=5)
        assert response.status_code == 200
        # Server-side grant fails (unresolvable host) -> client-side link shown
        assert "webstudy_credit.aspx" in response.text
        assert "survey_code=SC12345" in response.text
        assert "Return to SONA" in response.text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
