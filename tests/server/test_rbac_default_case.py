"""Server integration tests for the DEFAULT case: NO ``rbac`` config block.

Proves the two backward-compatibility promises at the HTTP layer:

1. ``TestRBACNoConfigBackwardCompat`` (debug OFF): with no ``rbac`` block, gating
   is exactly the legacy behavior — the shared admin key is the only way into the
   admin dashboard, a quota ``user_roles`` label confers nothing, the legacy
   ``adjudicator_users`` allow-list still reaches ``/adjudicate``, and a plain
   user is redirected / 403'd from the adjudicator endpoints.

2. ``TestRBACDebugModeAdjudicatorGate`` (debug ON): regression guard for the
   scoped superuser bypass. Debug opens the admin-dashboard tier for anyone (as
   before RBAC), but must NOT turn every logged-in user into an adjudicator — a
   plain user is still blocked from ``/adjudicate`` and its APIs, while a real
   ``adjudicator_users`` member still gets through.

The debug-mode server must be started with ``FlaskTestServer(debug=True)`` because
the harness drives the runtime ``debug`` flag from that argument, overriding the
config file's value.
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager


ADMIN_KEY = "default-case-key-999"

ANNOTATION_SCHEMES = [
    {
        "name": "sentiment",
        "annotation_type": "radio",
        "description": "Sentiment",
        "labels": ["pos", "neg"],
    }
]

ADJUDICATION = {
    "enabled": True,
    "adjudicator_users": ["ed@example.com"],
    "min_annotations": 2,
    "error_taxonomy": ["ambiguous_text"],
}

# A quota-only label (NOT a permissioned role) and NO rbac block.
QUOTA_ONLY = {"user_roles": {"nate@example.com": "novice"}}


def _login(base_url, username):
    s = requests.Session()
    s.post(f"{base_url}/register", data={"email": username, "pass": "pass"})
    s.post(f"{base_url}/auth", data={"email": username, "pass": "pass"})
    return s


class TestRBACNoConfigBackwardCompat:
    """debug OFF, no rbac block -> pure legacy behavior."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        with TestConfigManager(
            "rbac_default_case",
            ANNOTATION_SCHEMES,
            num_instances=3,
            admin_api_key=ADMIN_KEY,
            adjudication=ADJUDICATION,
            additional_config=QUOTA_ONLY,
        ) as cfg:
            server = FlaskTestServer(port=9041, config_file=cfg.config_path)
            if not server.start():
                pytest.fail("Failed to start server")
            request.cls.server = server
            request.cls.base_url = server.base_url
            yield server
            server.stop()

    def test_shared_key_authorizes(self):
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

    def test_quota_label_confers_no_admin(self):
        # "novice" is a workload label, not a role -> no admin access.
        s = _login(self.base_url, "nate@example.com")
        r = s.get(f"{self.base_url}/admin/api/adjudication")
        assert r.status_code == 403

    def test_legacy_adjudicator_reaches_adjudicate(self):
        s = _login(self.base_url, "ed@example.com")
        r = s.get(f"{self.base_url}/adjudicate", allow_redirects=False)
        assert r.status_code == 200

    def test_legacy_adjudicator_reaches_queue_api(self):
        s = _login(self.base_url, "ed@example.com")
        r = s.get(f"{self.base_url}/adjudicate/api/queue")
        assert r.status_code == 200

    def test_plain_user_redirected_from_adjudicate(self):
        s = _login(self.base_url, "pat@example.com")
        r = s.get(f"{self.base_url}/adjudicate", allow_redirects=False)
        assert r.status_code == 302  # redirected to home, not authorized

    def test_plain_user_forbidden_from_queue_api(self):
        s = _login(self.base_url, "pat@example.com")
        r = s.get(f"{self.base_url}/adjudicate/api/queue")
        assert r.status_code == 403


class TestRBACDebugModeAdjudicatorGate:
    """debug ON -> admin tier open to all, but the adjudicator gate stays closed.

    Regression guard: before the scoping fix, debug mode made
    ``check(ADJUDICATE)`` return True for ANY logged-in user, so a plain user
    could reach ``/adjudicate`` and its APIs.
    """

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        with TestConfigManager(
            "rbac_debug_gate",
            ANNOTATION_SCHEMES,
            num_instances=3,
            admin_api_key=ADMIN_KEY,
            adjudication=ADJUDICATION,
        ) as cfg:
            # debug=True is applied to the RUNTIME config by the harness.
            server = FlaskTestServer(port=9042, config_file=cfg.config_path, debug=True)
            if not server.start():
                pytest.fail("Failed to start server")
            request.cls.server = server
            request.cls.base_url = server.base_url
            yield server
            server.stop()

    def test_debug_opens_admin_dashboard(self):
        # No key, no login: debug still opens the admin-dashboard tier.
        r = requests.get(f"{self.base_url}/admin/api/adjudication")
        assert r.status_code == 200

    def test_debug_does_not_open_adjudicate_page(self):
        s = _login(self.base_url, "plain@example.com")
        r = s.get(f"{self.base_url}/adjudicate", allow_redirects=False)
        assert r.status_code == 302  # still redirected despite debug

    def test_debug_does_not_open_queue_api(self):
        s = _login(self.base_url, "plain@example.com")
        r = s.get(f"{self.base_url}/adjudicate/api/queue")
        assert r.status_code == 403  # the regression this fix prevents

    def test_debug_adjudicator_still_works(self):
        s = _login(self.base_url, "ed@example.com")
        r = s.get(f"{self.base_url}/adjudicate/api/queue")
        assert r.status_code == 200
