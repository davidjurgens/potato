"""
Server integration tests for QDA Mode blueprint registration.

The unit tests in tests/unit/test_qda_mode_scaffolding.py register
qda_mode_bp on a bare Flask app, so they cannot catch the case where the
blueprint is missing from the *served* application. The served app is built
by create_app() and configured via potato.routes, not the module-level
`app` object — so the blueprint must be registered there too. These tests
boot a real server and hit /qda/status to lock that wiring in place.
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
    cleanup_test_directory,
)


_SCHEMES = [
    {
        "name": "sentiment",
        "annotation_type": "radio",
        "labels": ["Positive", "Negative"],
        "description": "Pick one.",
    }
]


class TestQDAModeEnabledServedApp:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("qda_mode_enabled_served")
        data_file = create_test_data_file(test_dir, [{"id": "1", "text": "hi"}])
        config_file = create_test_config(
            test_dir,
            _SCHEMES,
            data_files=[data_file],
            annotation_task_name="QDA Enabled Served",
            require_password=False,
            additional_config={
                "qda_mode": {
                    "enabled": True,
                    "codebook": {"enabled": True, "mode": "extensible"},
                }
            },
        )
        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("Failed to start Flask test server")
        request.cls.server = server
        request.cls.test_dir = test_dir
        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    def test_qda_status_reachable_on_served_app(self):
        """Regression: /qda/status must 200 on the real server, not 404."""
        resp = requests.get(f"{self.server.base_url}/qda/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["enabled"] is True
        assert body["codebook"] == {"enabled": True, "mode": "extensible"}
        assert body["memos"]["enabled"] is True

    def test_qda_codebook_route_200_when_enabled(self):
        """First real /qda/* route behind qda_mode_required: 200 here."""
        resp = requests.get(f"{self.server.base_url}/qda/codebook")
        assert resp.status_code == 200
        body = resp.json()
        assert "labels" in body and "tree" in body and "cases" in body

    def test_universal_codebook_api_registered_on_served_app(self):
        """/api/codebook must exist on the served app (not 404). Without
        a session it gates to 401 — proving the blueprint is wired."""
        resp = requests.get(f"{self.server.base_url}/api/codebook")
        assert resp.status_code != 404
        assert resp.status_code in (401, 200)


class TestQDAModeDisabledServedApp:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("qda_mode_disabled_served")
        data_file = create_test_data_file(test_dir, [{"id": "1", "text": "hi"}])
        config_file = create_test_config(
            test_dir,
            _SCHEMES,
            data_files=[data_file],
            annotation_task_name="QDA Disabled Served",
            require_password=False,
        )
        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("Failed to start Flask test server")
        request.cls.server = server
        request.cls.test_dir = test_dir
        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    def test_qda_status_endpoint_exists_but_reports_disabled(self):
        """When QDA Mode is off, /qda/status still exists and reports disabled."""
        resp = requests.get(f"{self.server.base_url}/qda/status")
        assert resp.status_code == 200
        assert resp.json() == {"enabled": False}

    def test_qda_codebook_route_503_when_disabled(self):
        """F5/T3: the first real /qda/* route behind qda_mode_required
        returns 503 (not 404, not 500) on a served app where QDA Mode is
        not enabled — the endpoint exists, the mode just isn't active."""
        resp = requests.get(f"{self.server.base_url}/qda/codebook")
        assert resp.status_code == 503
        body = resp.json()
        assert "QDA Mode not enabled" in body["error"]
