"""
Role-Based Access Control (RBAC)

Generalizes Potato's historically ad-hoc authorization (a single shared admin
API key + an adjudicator allow-list + a quota-only ``user_roles`` map) into a
coherent role -> permission model.

Design goals
------------
* **Backward compatible.** With no ``rbac`` config block, behavior is identical
  to before: the shared ``admin_api_key`` is the only way to reach admin
  endpoints, ``adjudicator_users`` still authorizes adjudicators, and the
  ``user_roles`` map remains a pure workload-quota label. Nothing new is granted.
* **Superuser bypass preserved.** A valid ``admin_api_key`` (or debug mode)
  always passes every permission check, exactly as today.
* **Single entry point.** ``RBACManager.check(permission, request, session)`` is
  the one function every guard calls, and ``require_permission(...)`` is the one
  decorator that replaces the previously-duplicated ``admin_required`` copies.

The permission set is a small closed enum; roles map to sets of these
permissions. Roles come from (in precedence order) explicit
``rbac.user_role_assignments``, SSO/OAuth claim mappings, the legacy
``adjudicator_users`` allow-list, and finally the quota ``user_roles`` map (only
when the role name actually names a permissioned role -- otherwise a label like
``"novice"`` confers nothing, preserving existing semantics).
"""

import logging
import threading
from functools import wraps

logger = logging.getLogger(__name__)


class Permission:
    """Closed set of permission strings checked across the app."""

    VIEW_ADMIN_DASHBOARD = "view_admin_dashboard"
    MANAGE_ASSIGNMENT = "manage_assignment"
    ADJUDICATE = "adjudicate"
    EXPORT_DATA = "export_data"
    ANNOTATE = "annotate"

    ALL = frozenset(
        {
            VIEW_ADMIN_DASHBOARD,
            MANAGE_ASSIGNMENT,
            ADJUDICATE,
            EXPORT_DATA,
            ANNOTATE,
        }
    )


# Built-in role -> permissions. Config ``rbac.roles`` is merged over this.
DEFAULT_ROLE_PERMISSIONS = {
    "admin": set(Permission.ALL),
    "adjudicator": {
        Permission.ADJUDICATE,
        Permission.EXPORT_DATA,
        Permission.ANNOTATE,
    },
    "annotator": {Permission.ANNOTATE},
}


class RBACManager:
    """Resolves roles and permissions for users from config.

    The manager is immutable after construction; it holds a reference to the
    application config so it can consult the shared admin key for the superuser
    bypass.
    """

    def __init__(self, config):
        self.config = config or {}
        rbac = self.config.get("rbac") or {}
        if not isinstance(rbac, dict):
            logger.warning("rbac config is not a mapping; ignoring")
            rbac = {}

        self.enabled = bool(rbac.get("enabled", bool(rbac)))

        # role -> set(permissions), defaults merged with config overrides.
        self.role_permissions = {
            name: set(perms) for name, perms in DEFAULT_ROLE_PERMISSIONS.items()
        }
        for role, perms in (rbac.get("roles") or {}).items():
            if isinstance(perms, (list, tuple, set)):
                self.role_permissions[role] = {str(p) for p in perms}

        # Explicit user -> role assignments (highest-precedence role source).
        self._user_role_assignments = dict(rbac.get("user_role_assignments") or {})

        # SSO/OAuth claim -> role mapping (e.g. "org:my-org" -> "adjudicator").
        self._sso_role_mapping = dict(rbac.get("sso_role_mapping") or {})

        # Legacy quota-only roles: user -> role label. These confer permissions
        # ONLY when the label names a permissioned role; otherwise ignored here.
        self._quota_user_roles = dict(self.config.get("user_roles") or {})

        # Legacy adjudicator allow-list -> implicit "adjudicator" role.
        adj = self.config.get("adjudication") or {}
        self._adjudicator_users = set(adj.get("adjudicator_users") or [])

    # ------------------------------------------------------------------
    # Role / permission resolution
    # ------------------------------------------------------------------
    def get_roles_for_user(self, username, sso_claims=None):
        """Return the set of role names that apply to ``username``.

        Sources, unioned (an explicit assignment does not suppress others, but
        it guarantees at least that role):
          1. ``rbac.user_role_assignments``
          2. ``rbac.sso_role_mapping`` matched against ``sso_claims``
          3. legacy ``adjudicator_users`` -> ``adjudicator``
          4. quota ``user_roles`` -- only if the label names a permissioned role
        """
        roles = set()
        if not username:
            return roles

        assigned = self._user_role_assignments.get(username)
        if assigned:
            roles.add(assigned)

        for claim in sso_claims or []:
            mapped = self._sso_role_mapping.get(claim)
            if mapped:
                roles.add(mapped)

        if username in self._adjudicator_users:
            roles.add("adjudicator")

        quota_role = self._quota_user_roles.get(username)
        if quota_role and quota_role in self.role_permissions:
            roles.add(quota_role)

        return roles

    def get_permissions_for_user(self, username, sso_claims=None):
        """Union of permissions across all of the user's roles."""
        perms = set()
        for role in self.get_roles_for_user(username, sso_claims):
            perms |= self.role_permissions.get(role, set())
        return perms

    def has_permission(self, username, permission, sso_claims=None):
        return permission in self.get_permissions_for_user(username, sso_claims)

    # ------------------------------------------------------------------
    # Superuser (shared admin key) bypass
    # ------------------------------------------------------------------
    def _debug_enabled(self):
        return bool(self.config.get("debug", False))

    def _extract_api_key(self, request, session):
        api_key = None
        try:
            api_key = request.headers.get("X-API-Key")
        except Exception:
            api_key = None
        if not api_key and session is not None:
            api_key = session.get("admin_api_key")
        return api_key

    def has_valid_admin_key(self, request, session):
        """True only if a real shared admin key was provided and matches.

        Unlike ``admin_key.validate_admin_api_key`` this deliberately does NOT
        treat debug mode as a pass: debug is handled separately in ``check`` so
        that it opens the admin-dashboard tier without silently conferring the
        adjudicator role (which was gated independently before RBAC).
        """
        import hmac

        # Lazy import to avoid a circular dependency at module load.
        from potato.server_utils.admin_key import get_admin_api_key

        api_key = self._extract_api_key(request, session)
        if not api_key:
            return False
        expected_key = get_admin_api_key(self.config)
        if not expected_key:
            return False
        return hmac.compare_digest(str(api_key), str(expected_key))

    def is_admin_superuser(self, request, session):
        """True if the request carries a valid admin API key (or debug mode).

        Mirrors the pre-RBAC admin check so key-based admins keep full access.
        Retained for backward compatibility; note ``check`` does NOT use this
        blanket bypass for the ``ADJUDICATE`` permission (see below).
        """
        return self.has_valid_admin_key(request, session) or self._debug_enabled()

    # ------------------------------------------------------------------
    # Single authorization entry point
    # ------------------------------------------------------------------
    def check(self, permission, request, session):
        """Return True if this request is authorized for ``permission``.

        Order:
          1. A valid shared admin key is a full superuser (all permissions).
          2. Debug mode opens the admin-dashboard tier exactly as before RBAC,
             but NOT the ``ADJUDICATE`` role -- that gate was always separate
             (the legacy ``adjudicator_users`` allow-list), so debug must not
             turn every logged-in user into an adjudicator.
          3. Otherwise, the logged-in user's role-derived permissions.
        """
        if self.has_valid_admin_key(request, session):
            return True

        if self._debug_enabled() and permission != Permission.ADJUDICATE:
            return True

        username = session.get("username") if session is not None else None
        if not username:
            return False

        sso_claims = None
        if session is not None:
            sso_claims = session.get("sso_claims")
        return self.has_permission(username, permission, sso_claims)


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------
_RBAC_MANAGER = None
_RBAC_LOCK = threading.Lock()


def init_rbac_manager(config):
    """Initialize (or reinitialize) the singleton RBACManager."""
    global _RBAC_MANAGER
    with _RBAC_LOCK:
        _RBAC_MANAGER = RBACManager(config)
    return _RBAC_MANAGER


def get_rbac_manager():
    """Get the singleton RBACManager, lazily building it from the app config.

    Lazy construction keeps this safe for code paths (and tests) that reach a
    guard before startup has explicitly initialized the manager.
    """
    global _RBAC_MANAGER
    if _RBAC_MANAGER is None:
        with _RBAC_LOCK:
            if _RBAC_MANAGER is None:
                try:
                    from potato.flask_server import config as _config
                except Exception:
                    _config = {}
                _RBAC_MANAGER = RBACManager(_config)
    return _RBAC_MANAGER


def clear_rbac_manager():
    """Clear the singleton (for testing)."""
    global _RBAC_MANAGER
    with _RBAC_LOCK:
        _RBAC_MANAGER = None


# ---------------------------------------------------------------------------
# Reusable decorator (replaces the duplicated admin_required copies)
# ---------------------------------------------------------------------------
def require_permission(permission):
    """Decorator factory gating an endpoint on a single permission.

    Returns JSON 403 when the request lacks the permission (preserving the
    historical ``admin_required`` contract, which always returned 403). The
    shared admin key and debug mode always pass (handled inside
    ``RBACManager.check``).
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            from flask import request, session, jsonify

            mgr = get_rbac_manager()
            if mgr.check(permission, request, session):
                return f(*args, **kwargs)
            return jsonify({"error": "Admin authentication required"}), 403

        return decorated_function

    return decorator
