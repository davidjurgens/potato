"""Unit tests for the RBAC role/permission layer (potato.server_utils.rbac)."""

import pytest

from potato.server_utils.rbac import (
    RBACManager,
    Permission,
    DEFAULT_ROLE_PERMISSIONS,
    clear_rbac_manager,
)


@pytest.fixture(autouse=True)
def _clear():
    clear_rbac_manager()
    yield
    clear_rbac_manager()


def test_default_roles_present():
    m = RBACManager({})
    assert m.role_permissions["admin"] == set(Permission.ALL)
    assert Permission.ADJUDICATE in m.role_permissions["adjudicator"]
    assert m.role_permissions["annotator"] == {Permission.ANNOTATE}


def test_config_roles_merge_over_defaults():
    m = RBACManager({"rbac": {"roles": {"lead": ["view_admin_dashboard", "annotate"]}}})
    assert m.role_permissions["lead"] == {
        Permission.VIEW_ADMIN_DASHBOARD,
        Permission.ANNOTATE,
    }
    # Built-in defaults still present after merge.
    assert m.role_permissions["admin"] == set(Permission.ALL)


def test_user_role_assignment_confers_permissions():
    m = RBACManager({"rbac": {"user_role_assignments": {"carol": "admin"}}})
    assert m.has_permission("carol", Permission.MANAGE_ASSIGNMENT)
    assert m.has_permission("carol", Permission.EXPORT_DATA)


def test_custom_role_limited_permissions():
    m = RBACManager(
        {
            "rbac": {
                "roles": {"lead": ["view_admin_dashboard", "annotate"]},
                "user_role_assignments": {"dave": "lead"},
            }
        }
    )
    assert m.has_permission("dave", Permission.VIEW_ADMIN_DASHBOARD)
    assert not m.has_permission("dave", Permission.MANAGE_ASSIGNMENT)


def test_quota_only_user_roles_confer_nothing():
    # user_roles is a quota label; "novice"/"expert" are not permissioned roles.
    m = RBACManager({"user_roles": {"alice": "expert", "bob": "novice"}})
    assert not m.has_permission("alice", Permission.ANNOTATE)
    assert not m.has_permission("bob", Permission.ANNOTATE)


def test_quota_role_that_names_a_permissioned_role_confers_it():
    # If a quota label coincides with a real role name, it grants that role.
    m = RBACManager(
        {
            "rbac": {"roles": {"annotator": ["annotate"]}},
            "user_roles": {"alice": "annotator"},
        }
    )
    assert m.has_permission("alice", Permission.ANNOTATE)


def test_legacy_adjudicator_users_folds_into_role():
    m = RBACManager({"adjudication": {"adjudicator_users": ["ed"]}})
    assert m.has_permission("ed", Permission.ADJUDICATE)
    assert not m.has_permission("ed", Permission.MANAGE_ASSIGNMENT)


def test_sso_role_mapping():
    m = RBACManager(
        {"rbac": {"sso_role_mapping": {"org:acme": "adjudicator"}}}
    )
    assert m.has_permission("x", Permission.ADJUDICATE, sso_claims=["org:acme"])
    assert not m.has_permission("x", Permission.ADJUDICATE, sso_claims=["org:other"])
    assert not m.has_permission("x", Permission.ADJUDICATE)


def test_unknown_user_has_no_permissions():
    m = RBACManager({"rbac": {"user_role_assignments": {"carol": "admin"}}})
    assert not m.has_permission("nobody", Permission.ANNOTATE)
    assert m.get_permissions_for_user("nobody") == set()


class _FakeRequest:
    def __init__(self, headers=None):
        self.headers = headers or {}


def test_superuser_shared_key_bypass(monkeypatch):
    cfg = {"admin_api_key": "secret"}
    m = RBACManager(cfg)
    req = _FakeRequest({"X-API-Key": "secret"})
    session = {}
    assert m.is_admin_superuser(req, session)
    # check() passes for any permission with a valid key, even with no username.
    assert m.check(Permission.MANAGE_ASSIGNMENT, req, session)


def test_check_denies_without_key_or_role():
    m = RBACManager({"admin_api_key": "secret"})
    req = _FakeRequest({})
    session = {"username": "annie"}
    assert not m.check(Permission.VIEW_ADMIN_DASHBOARD, req, session)


def test_check_allows_role_admin_without_key():
    m = RBACManager(
        {
            "admin_api_key": "secret",
            "rbac": {"user_role_assignments": {"carol": "admin"}},
        }
    )
    req = _FakeRequest({})
    session = {"username": "carol"}
    assert m.check(Permission.VIEW_ADMIN_DASHBOARD, req, session)
    assert m.check(Permission.MANAGE_ASSIGNMENT, req, session)


def test_debug_mode_is_superuser():
    m = RBACManager({"debug": True})
    req = _FakeRequest({})
    assert m.is_admin_superuser(req, {})


def test_debug_grants_admin_dashboard_but_not_adjudicate():
    """Debug mode opens the admin-dashboard tier for any logged-in user, but
    must NOT auto-confer the adjudicator role (which was gated separately
    before RBAC by the adjudicator_users allow-list)."""
    m = RBACManager({"debug": True})
    req = _FakeRequest({})
    session = {"username": "random_annotator"}
    # Admin-dashboard tier: still open under debug (pre-RBAC behavior).
    assert m.check(Permission.VIEW_ADMIN_DASHBOARD, req, session)
    assert m.check(Permission.MANAGE_ASSIGNMENT, req, session)
    assert m.check(Permission.EXPORT_DATA, req, session)
    # Adjudicator gate: debug alone does NOT grant it to a role-less user.
    assert not m.check(Permission.ADJUDICATE, req, session)


def test_debug_adjudicate_still_granted_via_role_or_key():
    """Under debug, a genuine adjudicator (role, legacy allow-list, or real
    key) still passes the ADJUDICATE gate."""
    # Real shared admin key -> full superuser, adjudicate included.
    m_key = RBACManager({"debug": True, "admin_api_key": "secret"})
    assert m_key.check(
        Permission.ADJUDICATE, _FakeRequest({"X-API-Key": "secret"}), {}
    )
    # Explicit adjudicator role still works under debug.
    m_role = RBACManager(
        {"debug": True, "rbac": {"user_role_assignments": {"ed": "adjudicator"}}}
    )
    assert m_role.check(Permission.ADJUDICATE, _FakeRequest({}), {"username": "ed"})
    # Legacy adjudicator_users allow-list still works under debug.
    m_legacy = RBACManager(
        {"debug": True, "adjudication": {"adjudicator_users": ["ed"]}}
    )
    assert m_legacy.check(Permission.ADJUDICATE, _FakeRequest({}), {"username": "ed"})


def test_check_reads_sso_claims_from_session():
    m = RBACManager({"rbac": {"sso_role_mapping": {"org:acme": "adjudicator"}}})
    req = _FakeRequest({})
    session = {"username": "gh", "sso_claims": ["org:acme"]}
    assert m.check(Permission.ADJUDICATE, req, session)
