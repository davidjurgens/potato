"""
Integration tests for POST /webhooks/prolific: HMAC gatekeeping, duplicate
suppression, and the real-time assignment-reclaim path when a participant
returns their submission.
"""

import base64
import hashlib
import hmac
import json
import os
import time

import pytest
import requests
import yaml

from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory
from tests.server.test_prolific_server_integration import SimpleTestServer

SECRET = "whsec_server_test"


def sign(body_bytes, timestamp):
    digest = hmac.new(SECRET.encode(), timestamp.encode() + body_bytes,
                      hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def _write_config(test_dir, port, webhooks_enabled=True):
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
        "annotation_task_name": f"Webhook Test {port}",
        "login": {"type": "url_direct", "url_argument": "PROLIFIC_PID"},
        "completion_code": "WH-CODE",
        "crowdsourcing": {
            "provider": "prolific",
            "prolific": {
                "webhooks": {"enabled": webhooks_enabled, "secret": SECRET},
            },
        },
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


class TestProlificWebhookEndpoint:
    @pytest.fixture(scope="class")
    def webhook_server(self, request):
        from potato.crowdsourcing.webhooks import clear_seen_events
        clear_seen_events()
        port = find_free_port(preferred_port=9880)
        test_dir = create_test_directory(f"webhook_test_{port}")
        config_file = _write_config(test_dir, port)
        server = SimpleTestServer(config_file, port)
        if not server.start():
            cleanup_test_directory(test_dir)
            pytest.skip("Could not start test server")
        yield server
        server.stop()
        time.sleep(0.5)
        cleanup_test_directory(test_dir)

    def _post_event(self, server, payload, event_id=None, valid_signature=True):
        body = json.dumps(payload).encode()
        timestamp = "1752700000"
        headers = {
            "Content-Type": "application/json",
            "X-Prolific-Request-Timestamp": timestamp,
            "X-Prolific-Request-Signature":
                sign(body, timestamp) if valid_signature else "aW52YWxpZA==",
        }
        if event_id:
            headers["X-Event-Id"] = event_id
        return requests.post(f"{server.base_url}/webhooks/prolific",
                             data=body, headers=headers, timeout=5)

    def test_unsigned_delivery_rejected(self, webhook_server):
        response = self._post_event(
            webhook_server,
            {"event_type": "study.status.change", "status": "PAUSED"},
            valid_signature=False)
        assert response.status_code == 401

    def test_signed_study_event_accepted(self, webhook_server):
        response = self._post_event(
            webhook_server,
            {"event_type": "study.status.change", "resource_id": "st1",
             "status": "PAUSED"},
            event_id="evt_study_1")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_duplicate_event_suppressed(self, webhook_server):
        payload = {"event_type": "study.progress.change", "resource_id": "st1"}
        first = self._post_event(webhook_server, payload, event_id="evt_dup")
        second = self._post_event(webhook_server, payload, event_id="evt_dup")
        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["status"] == "duplicate"

    def test_returned_submission_reclaims_assignments(self, webhook_server):
        # A participant arrives and gets items assigned (but annotates nothing)
        session = requests.Session()
        response = session.get(
            f"{webhook_server.base_url}/",
            params={"PROLIFIC_PID": "returner_1", "SESSION_ID": "sess_r1"},
            allow_redirects=True, timeout=5)
        assert response.status_code == 200

        # Prolific tells us they returned the study
        response = self._post_event(
            webhook_server,
            {"event_type": "submission.status.change", "resource_id": "sess_r1",
             "participant_id": "returner_1", "status": "RETURNED"},
            event_id="evt_return_1")
        assert response.status_code == 200
        data = response.json()
        assert data["submission_status"] == "RETURNED"
        assert data["reclaimed"] == 2, \
            "both unannotated assignments should be reclaimed in real time"

    def test_unknown_event_type_acknowledged(self, webhook_server):
        response = self._post_event(
            webhook_server,
            {"event_type": "something.new", "resource_id": "x"},
            event_id="evt_unknown_1")
        assert response.status_code == 200
        assert response.json().get("ignored") is True


class TestWebhookDisabled:
    def test_disabled_returns_404(self):
        port = find_free_port(preferred_port=9895)
        test_dir = create_test_directory(f"webhook_off_test_{port}")
        config_file = _write_config(test_dir, port, webhooks_enabled=False)
        server = SimpleTestServer(config_file, port)
        if not server.start():
            cleanup_test_directory(test_dir)
            pytest.skip("Could not start test server")
        try:
            response = requests.post(
                f"{server.base_url}/webhooks/prolific", json={}, timeout=5)
            assert response.status_code == 404
        finally:
            server.stop()
            time.sleep(0.5)
            cleanup_test_directory(test_dir)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
