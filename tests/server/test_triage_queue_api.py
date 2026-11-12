"""
Server tests for the signal-based triage queue.

Exercises the admin API auth gate, the ranked-queue JSON/HTML report, that
loaded items carry triage metadata, and that the PRIORITY strategy serves the
highest-priority item first. No LLM / external service — signals live in data.
"""

import os

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
)

PORT = 9671
ADMIN_KEY = "triage-test-key-123"

SCHEMES = [{"annotation_type": "radio", "name": "trace_quality",
            "description": "Rate", "labels": ["good", "needs_fix", "broken"]}]

DATA = [
    {"id": "t1", "text": "clean trace", "status": "ok", "score": 0.9},
    {"id": "t2", "text": "errored trace", "status": "error"},
    {"id": "t3", "text": "low score trace", "score": 0.3},
    {"id": "t4", "text": "thumbs down", "feedback": "thumbs_down"},
]


class TestTriageQueueAPI:
    @pytest.fixture(scope="class", autouse=True)
    def server(self, request):
        test_dir = create_test_directory("triage_queue_api")
        data_file = create_test_data_file(test_dir, DATA, filename="triage.jsonl")
        config_file = create_test_config(
            test_dir, SCHEMES, data_files=[data_file],
            additional_config={
                "admin_api_key": ADMIN_KEY,
                "item_properties": {"id_key": "id", "text_key": "text"},
                "assignment_strategy": "priority",
                "max_annotations_per_item": -1,
                "triage": {
                    "enabled": True,
                    "rules": [
                        {"name": "Agent errored", "badge": "Agent errored",
                         "priority": 100, "when": {"field": "status", "equals": "error"}},
                        {"name": "Negative feedback", "priority": 80,
                         "when": {"field": "feedback", "equals": "thumbs_down"}},
                        {"name": "Low score", "priority": 60,
                         "when": {"field": "score", "lt": 0.5}},
                    ],
                },
            },
        )
        srv = FlaskTestServer(port=PORT, config_file=config_file)
        if not srv.start():
            pytest.fail("server failed to start")
        request.cls.base = srv.base_url
        yield srv
        srv.stop()

    def test_requires_api_key(self):
        r = requests.get(f"{self.base}/admin/triage-queue")
        assert r.status_code == 403

    def test_queue_json_is_ranked(self):
        r = requests.get(f"{self.base}/admin/triage-queue",
                         headers={"X-API-Key": ADMIN_KEY})
        assert r.status_code == 200
        report = r.json()
        assert report["enabled"] is True
        assert report["n_items"] == 4
        assert report["n_flagged"] == 3
        ids = [it["id"] for it in report["items"]]
        # errored (100) > thumbs_down (80) > low score (60) > clean (0)
        assert ids == ["t2", "t4", "t3", "t1"]
        top = report["items"][0]
        assert top["priority"] == 100
        assert top["reason"] == "Agent errored"

    def test_html_report_renders(self):
        r = requests.get(f"{self.base}/admin/triage-queue?format=html",
                         headers={"X-API-Key": ADMIN_KEY})
        assert r.status_code == 200
        assert "Triage Queue" in r.text
        assert "Agent errored" in r.text

    def test_priority_strategy_serves_errored_first(self):
        s = requests.Session()
        s.post(f"{self.base}/register", data={"email": "tu", "pass": "x", "action": "signup"})
        s.post(f"{self.base}/auth", data={"email": "tu", "pass": "x", "action": "login"})
        s.get(f"{self.base}/annotate")
        j = s.get(f"{self.base}/api/current_instance").json()
        # Highest-priority item (the agent error) is served first.
        assert j.get("instance_id") == "t2"
