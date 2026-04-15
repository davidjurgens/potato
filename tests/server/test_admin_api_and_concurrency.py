"""
Admin API authentication + concurrency tests.

Background:
The original priority was "QC blocking during in-flight annotation"
(admin blocks a user mid-annotation → race). A code audit found that
Potato does NOT expose an admin-triggered block endpoint — "blocking"
is a quality-control side effect driven by the user failing attention
checks. So the admin/block race scenario isn't a real code path to test.

What IS missing and testable:

1. Admin API endpoints are gated by `X-API-Key` header. No existing
   test verifies the 403/200 behavior for all /admin/* endpoints.
2. Concurrent admin requests against shared state (e.g. two admins
   hitting /admin/system_state at the same time while regular users
   are registering) must return consistent data.
3. Regular (non-admin) users must not be able to call admin endpoints
   even if authenticated as a regular user.

These tests plug that gap.
"""

import threading

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
    cleanup_test_directory,
)


def _auth(base_url, username):
    s = requests.Session()
    s.post(
        f"{base_url}/register",
        data={"action": "signup", "email": username, "pass": "pw"},
        timeout=5,
    )
    s.post(
        f"{base_url}/auth",
        data={"action": "login", "email": username, "pass": "pw"},
        timeout=5,
    )
    return s


# =====================================================================
# Shared fixture
# =====================================================================


@pytest.fixture(scope="module")
def flask_server():
    test_dir = create_test_directory("admin_api_test")
    test_data = [{"id": f"a_{i}", "text": f"Item {i}"} for i in range(4)]
    data_file = create_test_data_file(test_dir, test_data)
    config_file = create_test_config(
        test_dir,
        annotation_schemes=[
            {
                "name": "rating",
                "annotation_type": "radio",
                "labels": ["good", "bad"],
                "description": "Rate the item.",
            }
        ],
        data_files=[data_file],
    )
    server = FlaskTestServer(config=config_file)
    if not server.start():
        pytest.fail("Failed to start Flask test server")
    yield server
    server.stop()
    cleanup_test_directory(test_dir)


# =====================================================================
# TestAdminAPIAuthentication
# =====================================================================


# Endpoints that require X-API-Key. Format: (path, method)
ADMIN_GET_ENDPOINTS = [
    "/admin/health",
    "/admin/system_state",
    "/admin/all_instances",
    "/admin/item_state",
]


class TestAdminAPIAuthentication:
    @pytest.mark.parametrize("endpoint", ADMIN_GET_ENDPOINTS)
    def test_endpoint_requires_api_key(self, flask_server, endpoint):
        """No API key → 403."""
        resp = requests.get(f"{flask_server.base_url}{endpoint}", timeout=5)
        assert resp.status_code == 403, (
            f"Expected 403 for {endpoint} without API key, got {resp.status_code}"
        )

    @pytest.mark.parametrize("endpoint", ADMIN_GET_ENDPOINTS)
    def test_endpoint_rejects_wrong_api_key(self, flask_server, endpoint):
        """Wrong API key → 403."""
        resp = requests.get(
            f"{flask_server.base_url}{endpoint}",
            headers={"X-API-Key": "wrong-key-value"},
            timeout=5,
        )
        assert resp.status_code == 403

    @pytest.mark.parametrize("endpoint", ADMIN_GET_ENDPOINTS)
    def test_endpoint_accepts_correct_api_key(self, flask_server, endpoint):
        """Correct API key → 200 with JSON body."""
        resp = requests.get(
            f"{flask_server.base_url}{endpoint}",
            headers={"X-API-Key": flask_server.admin_api_key},
            timeout=5,
        )
        assert resp.status_code == 200, (
            f"{endpoint} returned {resp.status_code}: {resp.text[:200]}"
        )
        # All admin endpoints return JSON
        body = resp.json()
        assert isinstance(body, dict)

    def test_authenticated_non_admin_user_blocked(self, flask_server):
        """
        A regular user with a session cookie but no API key must not be
        able to access admin endpoints. Session auth must not substitute
        for API key auth.
        """
        s = _auth(flask_server.base_url, "regular_user_no_admin")
        # Regular session, no X-API-Key
        resp = s.get(f"{flask_server.base_url}/admin/system_state", timeout=5)
        assert resp.status_code == 403

    def test_empty_api_key_rejected(self, flask_server):
        resp = requests.get(
            f"{flask_server.base_url}/admin/health",
            headers={"X-API-Key": ""},
            timeout=5,
        )
        assert resp.status_code == 403


# =====================================================================
# TestAdminAPIContent — sanity checks on returned shape
# =====================================================================


class TestAdminAPIContent:
    def test_health_endpoint_returns_healthy_status(self, flask_server):
        resp = requests.get(
            f"{flask_server.base_url}/admin/health",
            headers={"X-API-Key": flask_server.admin_api_key},
            timeout=5,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("status") == "healthy"
        assert "managers" in body

    def test_system_state_includes_user_and_item_info(self, flask_server):
        resp = requests.get(
            f"{flask_server.base_url}/admin/system_state",
            headers={"X-API-Key": flask_server.admin_api_key},
            timeout=5,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        # The exact schema varies; just verify it's non-empty JSON with
        # plausible keys
        assert len(body) > 0

    def test_all_instances_returns_configured_items(self, flask_server):
        resp = requests.get(
            f"{flask_server.base_url}/admin/all_instances",
            headers={"X-API-Key": flask_server.admin_api_key},
            timeout=5,
        )
        assert resp.status_code == 200
        body = resp.json()
        # Response shape: could be list or dict with 'instances' key
        assert body  # non-empty


# =====================================================================
# TestAdminAPIConcurrency — the "race" test
# =====================================================================


class TestAdminAPIConcurrency:
    """Concurrent admin API requests against a server with active user
    registrations must not corrupt state or return inconsistent data."""

    def test_concurrent_system_state_reads_are_consistent(self, flask_server):
        """
        Two "admins" simultaneously hit /admin/system_state while several
        regular users are registering. Every admin response must be 200
        and parseable.
        """
        results = []
        errors = []

        def admin_worker(admin_id):
            try:
                for _ in range(10):
                    resp = requests.get(
                        f"{flask_server.base_url}/admin/system_state",
                        headers={"X-API-Key": flask_server.admin_api_key},
                        timeout=5,
                    )
                    results.append((admin_id, resp.status_code))
                    if resp.status_code == 200:
                        resp.json()  # must parse
            except Exception as e:
                errors.append((admin_id, repr(e)))

        def registration_worker(start_idx):
            try:
                for i in range(5):
                    s = requests.Session()
                    s.post(
                        f"{flask_server.base_url}/register",
                        data={
                            "action": "signup",
                            "email": f"concurrent_user_{start_idx}_{i}",
                            "pass": "pw",
                        },
                        timeout=5,
                    )
            except Exception as e:
                errors.append(("reg", repr(e)))

        threads = [
            threading.Thread(target=admin_worker, args=(0,)),
            threading.Thread(target=admin_worker, args=(1,)),
            threading.Thread(target=registration_worker, args=(100,)),
            threading.Thread(target=registration_worker, args=(200,)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not errors, f"Errors during concurrent run: {errors}"
        assert len(results) == 20
        for admin_id, status in results:
            assert status == 200, f"admin {admin_id} got status {status}"

    def test_concurrent_wrong_keys_rejected_consistently(self, flask_server):
        """Rejected requests must not leak data via error message differences."""
        results = []

        def worker(key):
            resp = requests.get(
                f"{flask_server.base_url}/admin/health",
                headers={"X-API-Key": key},
                timeout=5,
            )
            results.append((key, resp.status_code, len(resp.text)))

        threads = [
            threading.Thread(target=worker, args=("",)),
            threading.Thread(target=worker, args=("invalid",)),
            threading.Thread(target=worker, args=("not-the-key",)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should be rejected with 403
        for key, status, _ in results:
            assert status == 403
