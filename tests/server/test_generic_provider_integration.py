"""
Integration tests for the config-driven generic crowd provider.

Simulates a panel platform (e.g. Besample-style) participant: arrival with a
custom URL parameter, annotation, and a done page that shows the platform's
completion code and templated return link.
"""

import json
import os

import pytest
import requests
import yaml

from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory
from tests.server.test_prolific_server_integration import SimpleTestServer


def create_generic_provider_config(test_dir: str, port: int) -> str:
    test_data = [
        {"id": "item_1", "text": "First item to annotate."},
        {"id": "item_2", "text": "Second item to annotate."},
    ]
    data_file = os.path.join(test_dir, 'test_data.json')
    with open(data_file, 'w') as f:
        for item in test_data:
            f.write(json.dumps(item) + '\n')

    output_dir = os.path.join(test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    config = {
        "debug": False,
        "annotation_task_name": f"Generic Panel Test {port}",
        "login": {
            "type": "url_direct",
            "url_argument": "response_id",
        },
        "crowdsourcing": {
            "provider": "generic",
            "generic": {
                "platform_label": "TestPanel",
                "id_param": "response_id",
                "capture_params": ["batch"],
                "completion": {
                    "code": "PANEL-OK-77",
                    "redirect_url": "https://panel.example/complete?rid={worker_id}&code={code}",
                },
            },
        },
        "hide_navbar": True,
        "jumping_to_id_disabled": True,
        "authentication": {"method": "in_memory"},
        "require_password": False,
        "data_files": [data_file],
        "item_properties": {"text_key": "text", "id_key": "id"},
        "annotation_schemes": [
            {
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": ["positive", "negative", "neutral"],
                "description": "What is the sentiment?",
            }
        ],
        "assignment_strategy": "random",
        "max_annotations_per_user": 2,
        "max_annotations_per_item": 3,
        "phases": {
            "order": ["annotation"],
            "annotation": {"type": "annotation"},
        },
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


class TestGenericProviderFlow:
    @pytest.fixture
    def generic_server(self, request):
        port = find_free_port(preferred_port=9700)
        test_dir = create_test_directory(f"generic_provider_test_{port}")
        config_file = create_generic_provider_config(test_dir, port)

        server = SimpleTestServer(config_file, port)
        if not server.start():
            cleanup_test_directory(test_dir)
            pytest.skip("Could not start test server")

        yield server, test_dir

        server.stop()
        cleanup_test_directory(test_dir)

    def test_arrival_with_custom_param_logs_in(self, generic_server):
        server, _ = generic_server
        session = requests.Session()

        response = session.get(
            f"{server.base_url}/",
            params={"response_id": "panelist_1", "batch": "b7"},
            allow_redirects=True,
            timeout=5,
        )
        assert response.status_code == 200
        assert "sentiment" in response.text.lower()

    def test_missing_param_shows_error(self, generic_server):
        server, _ = generic_server
        response = requests.get(f"{server.base_url}/", allow_redirects=True, timeout=5)
        assert "response_id" in response.text

    def test_completion_shows_code_and_templated_redirect(self, generic_server):
        server, _ = generic_server
        session = requests.Session()

        response = session.get(
            f"{server.base_url}/",
            params={"response_id": "panelist_2"},
            allow_redirects=True,
            timeout=5,
        )
        assert response.status_code == 200

        for item_id in ["item_1", "item_2"]:
            response = session.post(
                f"{server.base_url}/updateinstance",
                json={
                    "instance_id": item_id,
                    "annotations": {"sentiment:positive": "true"},
                    "span_annotations": [],
                },
                timeout=5,
            )
            assert response.status_code == 200
            response = session.post(
                f"{server.base_url}/annotate",
                json={"action": "next_instance", "instance_id": item_id},
                allow_redirects=True,
                timeout=5,
            )
            assert response.status_code == 200

        response = session.get(f"{server.base_url}/done", allow_redirects=True, timeout=5)
        assert response.status_code == 200
        assert "PANEL-OK-77" in response.text
        assert "https://panel.example/complete?rid=panelist_2&amp;code=PANEL-OK-77" in response.text \
            or "https://panel.example/complete?rid=panelist_2&code=PANEL-OK-77" in response.text
        assert "Return to TestPanel" in response.text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
