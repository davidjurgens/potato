"""Server integration tests for the /api/prm/prelabel route.

The critical guard here is that the route is reachable under a real
`python flask_server.py start` server (registered in configure_routes, not just
via @app.route) — see the dual-registration gotcha in CLAUDE.md. The example
config enables ai_prelabel but ships no ai_support endpoint, so a valid request
degrades to 503 rather than returning fabricated labels.
"""

import os
import requests
import pytest

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CONFIG_FILE = os.path.join(
    REPO_ROOT, "examples", "agent-traces", "cot-process-reward", "config.yaml"
)


class TestPrmPrelabelRoute:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        server = FlaskTestServer(port=find_free_port(), config_file=CONFIG_FILE, debug=True)
        if not server.start():
            pytest.fail("Failed to start Flask test server for cot-process-reward config")
        request.cls.server = server
        request.cls.base_url = server.base_url
        yield server
        server.stop()

    def _session(self):
        s = requests.Session()
        # Register + login a real user (config allows all users).
        s.post(f"{self.base_url}/register", data={"email": "prm_tester", "pass": "pass"})
        s.post(f"{self.base_url}/auth", data={"email": "prm_tester", "pass": "pass"})
        return s

    def _url(self, **params):
        q = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self.base_url}/api/prm/prelabel?{q}"

    def test_route_is_registered(self):
        # A registered route must NOT 404 (the dual-registration guard). It
        # returns a 4xx/5xx business error, never a routing 404.
        s = self._session()
        resp = s.get(self._url(instance_id="prm-001", schema="step_rewards"))
        assert resp.status_code != 404

    def test_missing_params_400(self):
        s = self._session()
        resp = s.get(self._url(instance_id="prm-001"))
        assert resp.status_code == 400

    def test_unknown_schema_404(self):
        s = self._session()
        resp = s.get(self._url(instance_id="prm-001", schema="does_not_exist"))
        assert resp.status_code == 404
        assert "process_reward" in resp.json().get("error", "")

    def test_unknown_instance_404(self):
        s = self._session()
        resp = s.get(self._url(instance_id="nope-999", schema="step_rewards"))
        assert resp.status_code == 404

    def test_valid_request_degrades_to_503_without_endpoint(self):
        # ai_prelabel is enabled but no ai_support endpoint is configured, so
        # JudgeService cannot produce suggestions -> 503, not a crash or 200.
        s = self._session()
        resp = s.get(self._url(instance_id="prm-001", schema="step_rewards"))
        assert resp.status_code == 503
        assert "error" in resp.json()

    def test_segmentation_ran_and_display_renders(self):
        # Sanity: segmentation ran and the cot_trace display renders the steps.
        s = self._session()
        resp = s.get(f"{self.base_url}/annotate")
        assert resp.status_code == 200
        assert "cot-trace-display" in resp.text
        assert "data-turn-index" in resp.text
