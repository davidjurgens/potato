"""
Server integration test for the automation engine: a trace ingested via the
webhook triggers a matching rule whose actions queue the item, curate it into a
dataset (fast actions), and run an evaluator (heavy action via the worker).
"""

import time

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager


@pytest.fixture(scope="class", autouse=True)
def flask_server(request):
    annotation_schemes = [{
        "annotation_type": "radio", "name": "ok",
        "description": "ok?", "labels": ["yes", "no"],
    }]
    extra = {
        "trace_ingestion": {"enabled": True, "api_key": "", "notify_annotators": False},
        "datasets": {"enabled": True, "storage": "file"},
        "automation": {
            "enabled": True,
            "rules": [{
                "name": "curate-ingested",
                "when": {"field": "metadata.source", "equals": "webhook"},
                "actions": [
                    {"type": "add_to_queue", "priority": 95},
                    {"type": "add_to_dataset", "dataset": "auto-curated"},
                    {"type": "run_evaluator", "evaluator": "json_valid"},
                ],
            }],
        },
    }
    with TestConfigManager(
        "automation_engine", annotation_schemes,
        additional_config=extra, admin_api_key="test-admin-api-key",
    ) as test_config:
        server = FlaskTestServer(port=9064, config_file=test_config.config_path)
        if not server.start():
            pytest.fail("Failed to start server")
        request.cls.server = server
        yield server
        server.stop()


class TestAutomationEngine:
    def _admin(self):
        s = requests.Session()
        s.headers.update({"X-API-Key": self.server.admin_api_key})
        return s, self.server.base_url

    def test_ingested_trace_triggers_rule(self):
        base = self.server.base_url
        # Ingest a trace (generic webhook). It becomes an item -> automation fires.
        r = requests.post(f"{base}/api/traces/webhook", json={
            "id": "auto-1",
            "task_description": "do a thing",
            "steps": [{"action_type": "click", "thought": "go"}],
        })
        assert r.status_code == 200, r.text

        s, _ = self._admin()

        # Fast actions ran inline: the dataset got the item.
        ds = s.get(f"{base}/datasets/api/datasets/auto-curated")
        assert ds.status_code == 200, ds.text
        assert ds.json()["versions"], "dataset should have a version from add_to_dataset"

        # Status counters reflect the firing.
        st = s.get(f"{base}/admin/automation/status").json()
        assert st["enabled"] is True
        assert st["counters"]["items_processed"] >= 1
        assert st["counters"]["rules_fired"] >= 1

        # Heavy action (run_evaluator) is processed by the worker — poll outcomes.
        found_eval = False
        for _ in range(20):
            outs = s.get(f"{base}/admin/automation/outcomes").json()["outcomes"]
            if any(o["action"] == "run_evaluator" for o in outs):
                found_eval = True
                break
            time.sleep(0.5)
        assert found_eval, "run_evaluator outcome not recorded by worker"

    def test_status_requires_admin(self):
        base = self.server.base_url
        r = requests.get(f"{base}/admin/automation/status")
        assert r.status_code in (401, 403)
