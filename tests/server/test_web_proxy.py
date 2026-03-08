"""
Web Proxy Security Tests

Tests for the web proxy endpoint security: SSRF protection,
authentication requirements, scheme validation, and error handling.

NOTE: Some tests verify security protections (e.g., 403 for private IPs).
If the fixes are not yet in place, the tests will fail -- that is
intentional, as they document the expected correct behavior.
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_config,
    create_test_data_file,
    cleanup_test_directory,
)


def _create_authenticated_session(base_url, username="proxyuser", password="test123"):
    """Create a requests.Session that is registered and logged in."""
    session = requests.Session()
    session.post(
        f"{base_url}/register",
        data={"email": username, "pass": password},
        timeout=5,
    )
    session.post(
        f"{base_url}/auth",
        data={"email": username, "pass": password},
        timeout=5,
    )
    return session


class TestWebProxy:
    """Server-side tests for web proxy security."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Start a Flask test server for proxy testing."""
        test_dir = create_test_directory("web_proxy_test")

        test_data = [
            {"id": "task_001", "text": "Browse a website and complete a task"},
            {"id": "task_002", "text": "Find information on a website"},
        ]
        data_file = create_test_data_file(test_dir, test_data)

        annotation_schemes = [
            {
                "name": "status",
                "annotation_type": "radio",
                "labels": ["done", "not_done"],
                "description": "Task completion status",
            }
        ]

        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Web Proxy Test",
        )

        server = FlaskTestServer(config=config_file)
        if not server.start():
            cleanup_test_directory(test_dir)
            pytest.fail("Failed to start Flask test server")

        request.cls.base_url = server.base_url
        request.cls.test_dir = test_dir
        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    # ------------------------------------------------------------------
    # Authentication tests
    # ------------------------------------------------------------------

    def test_proxy_requires_auth(self):
        """Unauthenticated GET to /api/web_agent/proxy/ should redirect to login."""
        raw_session = requests.Session()

        resp = raw_session.get(
            f"{self.base_url}/api/web_agent/proxy/https://example.com",
            timeout=5,
            allow_redirects=False,
        )

        # The _login_required decorator redirects unauthenticated users
        assert resp.status_code == 302

    def test_check_frameable_requires_auth(self):
        """Unauthenticated GET to /api/web_agent/check_frameable should redirect to login."""
        raw_session = requests.Session()

        resp = raw_session.get(
            f"{self.base_url}/api/web_agent/check_frameable",
            params={"url": "https://example.com"},
            timeout=5,
            allow_redirects=False,
        )

        assert resp.status_code == 302

    # ------------------------------------------------------------------
    # SSRF protection: private/internal IP blocking
    # ------------------------------------------------------------------

    def test_proxy_blocks_private_ip(self):
        """GET proxy for http://192.168.1.1 should return 403 (SSRF protection)."""
        session = _create_authenticated_session(
            self.base_url, username="ssrf_private"
        )

        resp = session.get(
            f"{self.base_url}/api/web_agent/proxy/http://192.168.1.1",
            timeout=5,
        )

        assert resp.status_code == 403
        assert "private" in resp.text.lower() or "blocked" in resp.text.lower()

    def test_proxy_blocks_localhost(self):
        """GET proxy for http://127.0.0.1 should return 403 (SSRF protection)."""
        session = _create_authenticated_session(
            self.base_url, username="ssrf_localhost"
        )

        resp = session.get(
            f"{self.base_url}/api/web_agent/proxy/http://127.0.0.1",
            timeout=5,
        )

        assert resp.status_code == 403
        assert "private" in resp.text.lower() or "blocked" in resp.text.lower()

    def test_proxy_blocks_metadata(self):
        """GET proxy for cloud metadata endpoint should return 403 (SSRF protection)."""
        session = _create_authenticated_session(
            self.base_url, username="ssrf_metadata"
        )

        resp = session.get(
            f"{self.base_url}/api/web_agent/proxy/http://169.254.169.254/latest/meta-data",
            timeout=5,
        )

        assert resp.status_code == 403

    def test_proxy_blocks_internal_10(self):
        """GET proxy for http://10.0.0.1 should return 403 (SSRF protection)."""
        session = _create_authenticated_session(
            self.base_url, username="ssrf_internal10"
        )

        resp = session.get(
            f"{self.base_url}/api/web_agent/proxy/http://10.0.0.1",
            timeout=5,
        )

        assert resp.status_code == 403

    # ------------------------------------------------------------------
    # Scheme validation
    # ------------------------------------------------------------------

    def test_proxy_blocks_non_http(self):
        """GET proxy for ftp://example.com should return 403 (only HTTP/HTTPS allowed)."""
        session = _create_authenticated_session(
            self.base_url, username="ssrf_ftp"
        )

        resp = session.get(
            f"{self.base_url}/api/web_agent/proxy/ftp://example.com",
            timeout=5,
        )

        assert resp.status_code == 403
        assert "scheme" in resp.text.lower() or "not allowed" in resp.text.lower()

    # ------------------------------------------------------------------
    # Valid proxy request
    # ------------------------------------------------------------------

    def test_proxy_valid_url(self):
        """GET proxy for https://example.com should succeed or return a handled error.

        We accept 200 (successful proxy), 502 (network error but handled),
        since the test environment may or may not have internet access.
        The key assertion is that it does NOT return 403 (not blocked).
        """
        session = _create_authenticated_session(
            self.base_url, username="proxy_valid"
        )

        resp = session.get(
            f"{self.base_url}/api/web_agent/proxy/https://example.com",
            timeout=20,
        )

        # Should not be blocked (not private, valid scheme)
        assert resp.status_code != 403
        # Should be a success or a handled proxy error
        assert resp.status_code in (200, 502)

    # ------------------------------------------------------------------
    # check_frameable endpoint
    # ------------------------------------------------------------------

    def test_check_frameable_returns_result(self):
        """POST /api/web_agent/check_frameable with a valid URL returns JSON with frameable boolean.

        Note: check_frameable is actually a GET endpoint, not POST.
        """
        session = _create_authenticated_session(
            self.base_url, username="frameable_user"
        )

        resp = session.get(
            f"{self.base_url}/api/web_agent/check_frameable",
            params={"url": "https://example.com"},
            timeout=10,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "frameable" in data
        assert isinstance(data["frameable"], bool)
        assert "reason" in data

    # ------------------------------------------------------------------
    # Error handling / XSS prevention
    # ------------------------------------------------------------------

    def test_proxy_escapes_error_url(self):
        """If proxy errors, the URL in the error response is HTML-escaped (no XSS).

        We request a URL containing HTML special characters and verify the
        error response does not include the raw unescaped characters.
        """
        session = _create_authenticated_session(
            self.base_url, username="xss_test_user"
        )

        # Use a URL with an unresolvable host containing HTML characters.
        # The angle brackets should be escaped in the error response.
        malicious_url = 'https://nonexistent-xss-test-host.invalid/<script>alert("xss")</script>'

        resp = session.get(
            f"{self.base_url}/api/web_agent/proxy/{malicious_url}",
            timeout=10,
        )

        # Should get a 502 proxy error (host doesn't resolve)
        # The important thing is the response body does NOT contain raw <script>
        body = resp.text
        assert '<script>alert("xss")</script>' not in body
        # Check that it was properly HTML-escaped
        assert "&lt;script&gt;" in body or "script" not in body
