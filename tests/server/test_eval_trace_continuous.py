"""
Server test for the continuous-eval story behind the eval_trace display.

The continuous-eval example enables trace_ingestion so new agent traces can be
pushed at runtime and evaluated as they arrive. This test drives a trace through
the real generic webhook endpoint and asserts a fresh annotator is actually
assigned the ingested trace (i.e. it is not merely stored/admin-visible — it is
annotatable). This is the F-037 dynamic-quota guarantee that makes the
eval_trace continuous-eval example work.

Rendering of the three panes is covered by tests/unit/test_eval_trace_display.py
and tests/selenium/test_eval_trace_ui.py; directory-watch ingestion is covered
by tests/unit/test_directory_watcher.py.
"""

import time

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager

WEBHOOK_PORT = 9663

SCHEMES = [
    {"annotation_type": "radio", "name": "answer_helpfulness",
     "description": "Helpful?", "labels": ["yes", "no"]},
]


def _post_webhook_trace(base_url, trace_id):
    """Push a generic-format agent trace into the ingestion webhook."""
    payload = {
        "id": trace_id,
        "task_description": "Find the capital of France.",
        "steps": [
            {"type": "thought", "thought": "I should look this up.",
             "observation": ""},
            {"type": "action", "action_type": "search",
             "observation": "Paris is the capital of France."},
        ],
    }
    return requests.post(f"{base_url}/api/traces/webhook", json=payload, timeout=10)


def _drain_assigned_ids(base_url, user):
    s = requests.Session()
    s.post(f"{base_url}/register", data={"email": user, "pass": "x", "action": "signup"})
    s.post(f"{base_url}/auth", data={"email": user, "pass": "x", "action": "login"})
    s.get(f"{base_url}/annotate")
    ids = []
    for _ in range(15):
        j = s.get(f"{base_url}/api/current_instance").json()
        iid = j.get("instance_id")
        if not iid or iid in ids:
            break
        ids.append(iid)
        s.post(f"{base_url}/updateinstance",
               json={"instance_id": iid, "annotations": {"answer_helpfulness:::yes": "true"}})
        time.sleep(0.15)
        s.post(f"{base_url}/annotate", json={"action": "next_instance"})
    return ids


class TestWebhookTraceIsAnnotatable:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        with TestConfigManager(
            "eval_trace_webhook", SCHEMES, num_instances=2,
            additional_config={"trace_ingestion": {"enabled": True, "api_key": ""}},
        ) as cfg:
            server = FlaskTestServer(port=WEBHOOK_PORT, config_file=cfg.config_path)
            if not server.start():
                pytest.fail("Failed to start server")
            yield server
            server.stop()

    def test_webhook_accepts_trace(self, flask_server):
        resp = _post_webhook_trace(flask_server.base_url, "evt001")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "accepted"
        assert body["trace_id"] == "webhook_evt001"

    def test_ingested_trace_assignable_to_fresh_user(self, flask_server):
        _post_webhook_trace(flask_server.base_url, "evt002")
        time.sleep(1.0)
        ids = _drain_assigned_ids(flask_server.base_url, "eval_ingest_user")
        assert any(str(i).startswith("webhook_") for i in ids), (
            f"ingested trace must be assignable to a fresh user; got {ids}"
        )
