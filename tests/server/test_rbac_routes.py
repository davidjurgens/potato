"""Server integration tests for RBAC-gated admin access.

Verifies the role -> permission layer end to end:
  * shared admin API key still authorizes (backward compat / superuser),
  * a logged-in user with the ``admin`` role reaches admin endpoints WITHOUT
    the key,
  * an annotator-only user is forbidden from admin endpoints but can annotate,
  * an unauthenticated request is rejected.

Target endpoint: GET /admin/api/adjudication — gated by check_admin_access(),
returns 200 (with {"enabled": false}) when authorized even if adjudication is
off, and 403 otherwise.
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager


ADMIN_KEY = "test-admin-key-123"

ANNOTATION_SCHEMES = [
    {
        "name": "sentiment",
        "annotation_type": "radio",
        "description": "Sentiment",
        "labels": ["pos", "neg"],
    }
]

RBAC_CONFIG = {
    "rbac": {
        "enabled": True,
        "user_role_assignments": {
            "boss@example.com": "admin",
            "worker@example.com": "annotator",
        },
    }
}


class TestRBACRoutes:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        with TestConfigManager(
            "rbac_routes",
            ANNOTATION_SCHEMES,
            num_instances=3,
            admin_api_key=ADMIN_KEY,
            additional_config=RBAC_CONFIG,
        ) as test_config:
            server = FlaskTestServer(port=9037, config_file=test_config.config_path)
            if not server.start():
                pytest.fail("Failed to start server")
            request.cls.server = server
            request.cls.base_url = server.base_url
            yield server
            server.stop()

    def _login(self, username):
        s = requests.Session()
        s.post(f"{self.base_url}/register", data={"email": username, "pass": "pass"})
        s.post(f"{self.base_url}/auth", data={"email": username, "pass": "pass"})
        return s

    # --- backward compat: shared key ---------------------------------

    def test_shared_admin_key_authorizes(self):
        r = requests.get(
            f"{self.base_url}/admin/api/adjudication",
            headers={"X-API-Key": ADMIN_KEY},
        )
        assert r.status_code == 200

    def test_wrong_key_forbidden(self):
        r = requests.get(
            f"{self.base_url}/admin/api/adjudication",
            headers={"X-API-Key": "nope"},
        )
        assert r.status_code == 403

    def test_unauthenticated_forbidden(self):
        r = requests.get(f"{self.base_url}/admin/api/adjudication")
        assert r.status_code == 403

    # --- role-based access -------------------------------------------

    def test_admin_role_user_reaches_admin_without_key(self):
        s = self._login("boss@example.com")
        r = s.get(f"{self.base_url}/admin/api/adjudication")
        assert r.status_code == 200

    def test_annotator_role_user_forbidden_from_admin(self):
        s = self._login("worker@example.com")
        r = s.get(f"{self.base_url}/admin/api/adjudication")
        assert r.status_code == 403

    def test_annotator_role_user_can_annotate(self):
        s = self._login("worker@example.com")
        r = s.get(f"{self.base_url}/annotate")
        assert r.status_code == 200
