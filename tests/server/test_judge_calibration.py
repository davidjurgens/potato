"""
Server integration tests for Judge Calibration mode.

Exercises the route lifecycle end-to-end against a real Flask instance:
admin gating, the generation run (with an unreachable Ollama endpoint so each
query fails fast and is recorded as a None sample — no real LLM needed),
phase advancement, report building, and a blindness check on /annotate.
"""

import time
import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager

ADMIN_KEY = "test-admin-key-jc"

ANNOTATION_SCHEMES = [
    {
        "annotation_type": "radio",
        "name": "sentiment",
        "description": "Overall sentiment",
        "labels": ["positive", "negative", "neutral"],
    }
]

JUDGE_CALIBRATION = {
    "enabled": True,
    "prompt": "Classify the sentiment.",
    # Unreachable port: endpoint construction succeeds, query() fails fast,
    # so generation completes quickly with None samples (no LLM required).
    "models": [
        {"endpoint_type": "ollama", "model": "nonexistent", "base_url": "http://127.0.0.1:1", "temperature": 0.7}
    ],
    "k_samples": 2,
    "sampling": {"strategy": "all", "sample_size": 5, "seed": 1},
    "human": {"num_raters": 1, "gold": "single"},
    "schemas": ["sentiment"],
    "calibration": {"n_bins": 5},
}


class TestJudgeCalibration:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self):
        with TestConfigManager(
            "judge_calibration",
            ANNOTATION_SCHEMES,
            num_instances=4,
            admin_api_key=ADMIN_KEY,
            additional_config={"judge_calibration": JUDGE_CALIBRATION},
        ) as test_config:
            server = FlaskTestServer(port=9043, config_file=test_config.config_path)
            if not server.start():
                pytest.fail("Failed to start server")
            yield server
            server.stop()

    def _key_headers(self):
        return {"X-API-Key": ADMIN_KEY}

    def test_status_requires_admin(self, flask_server):
        r = requests.get(f"{flask_server.base_url}/judge_calibration/status")
        assert r.status_code == 403

    def test_status_with_key(self, flask_server):
        r = requests.get(f"{flask_server.base_url}/judge_calibration/status",
                         headers=self._key_headers())
        assert r.status_code == 200
        data = r.json()
        assert data["enabled"] is True
        assert "nonexistent" in data["models"]

    def test_admin_page_renders(self, flask_server):
        r = requests.get(f"{flask_server.base_url}/judge_calibration/admin",
                         headers=self._key_headers())
        assert r.status_code == 200
        assert "Judge Calibration" in r.text

    def test_run_lifecycle_and_report(self, flask_server):
        # Kick off generation.
        r = requests.post(f"{flask_server.base_url}/judge_calibration/run",
                          headers=self._key_headers(), json={})
        assert r.status_code == 200, r.text
        assert r.json()["started"] is True

        # Poll to completion (all queries fail fast against the dead port).
        deadline = time.time() + 45
        phase = None
        while time.time() < deadline:
            p = requests.get(f"{flask_server.base_url}/judge_calibration/progress",
                             headers=self._key_headers()).json()
            phase = p["phase"]
            if not p["generating"] and phase == "human-calibration":
                break
            time.sleep(1)
        assert phase == "human-calibration", f"stuck in phase {phase}"

        # Build the report (no human labels yet -> empty metrics, but valid).
        r = requests.post(f"{flask_server.base_url}/judge_calibration/report",
                          headers=self._key_headers())
        assert r.status_code == 200, r.text
        report = r.json()["report"]
        assert "sentiment" in report["schemas"]

        # Report HTML is viewable.
        r = requests.get(f"{flask_server.base_url}/judge_calibration/report",
                         headers=self._key_headers())
        assert r.status_code == 200
        assert "Judge Calibration Report" in r.text

    def test_annotate_is_blind(self, flask_server):
        """The annotation page must never surface LLM verdicts."""
        session = requests.Session()
        session.post(f"{flask_server.base_url}/register",
                     data={"email": "blinduser", "pass": "pw", "action": "register"})
        session.post(f"{flask_server.base_url}/auth",
                     data={"email": "blinduser", "pass": "pw"})
        r = session.get(f"{flask_server.base_url}/annotate")
        # Page should load and not reference judge-calibration LLM result artifacts.
        assert r.status_code in (200, 302)
        if r.status_code == 200:
            assert "llm_labels" not in r.text
            assert "modal_label" not in r.text
