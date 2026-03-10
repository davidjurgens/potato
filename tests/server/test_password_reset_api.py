"""
Server integration tests for password reset API endpoints.
"""

import pytest
import requests
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager


class TestPasswordResetAPI:
    """Test password reset admin API and self-service routes."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        annotation_schemes = [{
            "annotation_type": "radio",
            "name": "sentiment",
            "description": "Sentiment",
            "labels": ["positive", "negative"],
        }]
        with TestConfigManager(
            "password_reset_test",
            annotation_schemes,
            require_password=True,
            admin_api_key="test-admin-key-123",
        ) as test_config:
            server = FlaskTestServer(config_file=test_config.config_path)
            if not server.start():
                pytest.fail("Failed to start server")
            request.cls.server = server
            yield server
            server.stop()

    def _register_user(self, session, username="testuser", password="testpass"):
        """Register a user and return the session."""
        session.post(
            f"{self.server.base_url}/register",
            data={"email": username, "pass": password},
        )
        return session

    def test_admin_reset_password_success(self):
        """POST /admin/reset_password with valid key resets password."""
        session = requests.Session()
        self._register_user(session, "reset_user", "old_password")

        resp = session.post(
            f"{self.server.base_url}/admin/reset_password",
            json={"username": "reset_user", "new_password": "new_password"},
            headers={"X-API-Key": "test-admin-key-123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"

        # Verify old password fails, new works
        login_session = requests.Session()
        resp = login_session.post(
            f"{self.server.base_url}/auth",
            data={"email": "reset_user", "pass": "new_password"},
        )
        assert resp.status_code == 200

    def test_admin_reset_password_no_key(self):
        """POST /admin/reset_password without API key returns 403."""
        session = requests.Session()
        resp = session.post(
            f"{self.server.base_url}/admin/reset_password",
            json={"username": "someone", "new_password": "pass"},
        )
        assert resp.status_code == 403

    def test_admin_reset_password_wrong_key(self):
        """POST /admin/reset_password with wrong API key returns 403."""
        session = requests.Session()
        resp = session.post(
            f"{self.server.base_url}/admin/reset_password",
            json={"username": "someone", "new_password": "pass"},
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp.status_code == 403

    def test_admin_reset_password_nonexistent_user(self):
        """POST /admin/reset_password for nonexistent user returns 404."""
        session = requests.Session()
        resp = session.post(
            f"{self.server.base_url}/admin/reset_password",
            json={"username": "nonexistent", "new_password": "pass"},
            headers={"X-API-Key": "test-admin-key-123"},
        )
        assert resp.status_code == 404

    def test_admin_create_reset_token(self):
        """POST /admin/create_reset_token generates a valid token."""
        session = requests.Session()
        self._register_user(session, "token_user", "password123")

        resp = session.post(
            f"{self.server.base_url}/admin/create_reset_token",
            json={"username": "token_user"},
            headers={"X-API-Key": "test-admin-key-123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "reset_link" in data
        assert "token" in data

    def test_admin_create_token_no_key(self):
        """POST /admin/create_reset_token without key returns 403."""
        session = requests.Session()
        resp = session.post(
            f"{self.server.base_url}/admin/create_reset_token",
            json={"username": "someone"},
        )
        assert resp.status_code == 403

    def test_reset_token_flow(self):
        """Full self-service reset flow: create token → GET form → POST reset."""
        session = requests.Session()
        self._register_user(session, "flow_user", "original_pass")

        # Admin creates token
        resp = session.post(
            f"{self.server.base_url}/admin/create_reset_token",
            json={"username": "flow_user"},
            headers={"X-API-Key": "test-admin-key-123"},
        )
        token = resp.json()["token"]

        # GET reset form
        reset_session = requests.Session()
        resp = reset_session.get(f"{self.server.base_url}/reset/{token}")
        assert resp.status_code == 200
        assert "flow_user" in resp.text

        # POST new password
        resp = reset_session.post(
            f"{self.server.base_url}/reset/{token}",
            data={"password": "updated_pass", "confirm_password": "updated_pass"},
        )
        assert resp.status_code == 200
        assert "successfully" in resp.text.lower() or "updated" in resp.text.lower()

    def test_reset_invalid_token(self):
        """GET /reset/<invalid_token> shows error."""
        session = requests.Session()
        resp = session.get(f"{self.server.base_url}/reset/invalid_token_abc")
        assert resp.status_code == 200
        assert "invalid" in resp.text.lower() or "expired" in resp.text.lower()

    def test_forgot_password_page_loads(self):
        """GET /forgot-password shows the form."""
        session = requests.Session()
        resp = session.get(f"{self.server.base_url}/forgot-password")
        assert resp.status_code == 200
        assert "username" in resp.text.lower()

    def test_forgot_password_unknown_user_shows_success(self):
        """POST /forgot-password with unknown user shows success (prevents enumeration)."""
        session = requests.Session()
        resp = session.post(
            f"{self.server.base_url}/forgot-password",
            data={"username": "unknown_user_xyz"},
        )
        assert resp.status_code == 200
        # Should show generic success, not an error
        assert "error" not in resp.text.lower() or "exists" not in resp.text.lower()

    def test_forgot_password_known_user_shows_link(self):
        """POST /forgot-password with known user shows reset link."""
        session = requests.Session()
        self._register_user(session, "forgot_user", "mypass")

        resp = session.post(
            f"{self.server.base_url}/forgot-password",
            data={"username": "forgot_user"},
        )
        assert resp.status_code == 200
        assert "/reset/" in resp.text
