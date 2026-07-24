"""RBAC migration guard for the previously shared-key-only admin blueprints.

`arena`, `automation`, and `judge_calibration` each used to define a LOCAL
`admin_required` decorator that validated the shared admin key directly and did
NOT honor RBAC role grants. They now bind
`require_permission(Permission.VIEW_ADMIN_DASHBOARD)` from `potato.server_utils.rbac`.

These tests mount each module's `admin_required` on a throwaway Flask route (via
`test_client`) so the decorator is exercised in isolation — no feature-enable or
blueprint-registration plumbing required. They verify the full contract:
  * unauthenticated  -> 403
  * wrong shared key -> 403
  * valid shared key -> 200 (backward compatible / superuser)
  * RBAC admin role, NO key -> 200 (the new capability)
  * RBAC annotator role -> 403
"""

import importlib

import pytest
from flask import Flask, jsonify

from potato.server_utils.rbac import init_rbac_manager, clear_rbac_manager


MIGRATED_MODULES = [
    "potato.arena.routes",
    "potato.automation.routes",
    "potato.judge_calibration.routes",
]

ADMIN_KEY = "migrated-key-abc"


def _probe_app(admin_required):
    app = Flask(__name__)
    app.secret_key = "test-secret"

    @app.route("/probe")
    @admin_required
    def probe():
        return jsonify({"ok": True})

    return app


def _admin_required(modpath):
    return importlib.import_module(modpath).admin_required


@pytest.fixture(autouse=True)
def _clear_rbac():
    clear_rbac_manager()
    yield
    clear_rbac_manager()


@pytest.mark.parametrize("modpath", MIGRATED_MODULES)
class TestMigratedModuleAuth:
    def test_unauthenticated_forbidden(self, modpath):
        init_rbac_manager({"admin_api_key": ADMIN_KEY})
        client = _probe_app(_admin_required(modpath)).test_client()
        assert client.get("/probe").status_code == 403

    def test_wrong_key_forbidden(self, modpath):
        init_rbac_manager({"admin_api_key": ADMIN_KEY})
        client = _probe_app(_admin_required(modpath)).test_client()
        r = client.get("/probe", headers={"X-API-Key": "nope"})
        assert r.status_code == 403

    def test_shared_key_authorizes(self, modpath):
        init_rbac_manager({"admin_api_key": ADMIN_KEY})
        client = _probe_app(_admin_required(modpath)).test_client()
        r = client.get("/probe", headers={"X-API-Key": ADMIN_KEY})
        assert r.status_code == 200

    def test_rbac_admin_role_without_key(self, modpath):
        init_rbac_manager(
            {
                "admin_api_key": ADMIN_KEY,
                "rbac": {"user_role_assignments": {"carol": "admin"}},
            }
        )
        client = _probe_app(_admin_required(modpath)).test_client()
        with client.session_transaction() as sess:
            sess["username"] = "carol"
        # No X-API-Key header: authorized purely by the RBAC admin role.
        assert client.get("/probe").status_code == 200

    def test_rbac_annotator_role_forbidden(self, modpath):
        init_rbac_manager(
            {
                "admin_api_key": ADMIN_KEY,
                "rbac": {"user_role_assignments": {"dan": "annotator"}},
            }
        )
        client = _probe_app(_admin_required(modpath)).test_client()
        with client.session_transaction() as sess:
            sess["username"] = "dan"
        assert client.get("/probe").status_code == 403
