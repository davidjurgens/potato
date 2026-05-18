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
