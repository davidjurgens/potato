"""Server integration tests for OAuth authentication flow.

Uses FlaskTestServer to test OAuth routes. Tests login page rendering,
route behavior, error handling, and mixed mode — without real OAuth credentials.

Note: Full OAuth redirect flow (code exchange, token) requires `@responses.activate`
which intercepts all HTTP including local server calls. Those tests use separate
request sessions with passthrough configured for localhost.
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
from tests.helpers.oauth_test_utils import (
    make_oauth_config,
    google_provider,
    github_provider,
)


def _create_oauth_server(test_name, providers, **kwargs):
    """Helper to create a test directory, data, config with OAuth, and start server."""
    test_dir = create_test_directory(test_name)
    test_data = [
        {"id": "item_1", "text": "First test item."},
        {"id": "item_2", "text": "Second test item."},
    ]
    data_file = create_test_data_file(test_dir, test_data)

    annotation_schemes = [
        {
            "annotation_type": "radio",
            "name": "sentiment",
            "description": "Rate sentiment",
            "labels": ["positive", "negative"],
        }
    ]

    auth_config = make_oauth_config(providers=providers, **kwargs)

    config_path = create_test_config(
        test_dir,
        annotation_schemes,
        data_files=[data_file],
        authentication=auth_config,
        require_password=kwargs.pop("require_password", False) if "require_password" in kwargs else False,
        secret_key="test-oauth-secret",
    )
    return test_dir, config_path


class TestOAuthLoginPage:
    """Test that the login page shows OAuth buttons correctly."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir, config_path = _create_oauth_server(
            "oauth_login_page_test",
            providers={"google": google_provider()},
        )
        server = FlaskTestServer(config_file=config_path)
        if not server.start():
            pytest.fail("Failed to start server")
        request.cls.server = server
        request.cls.test_dir = test_dir
        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    def test_login_page_shows_sso_button(self):
        """Login page displays OAuth provider buttons."""
        session = requests.Session()
        response = session.get(f"{self.server.base_url}/auth")
        assert response.status_code == 200
        assert "Sign in with Google" in response.text

    def test_login_page_has_oauth_css(self):
        """Login page includes the OAuth stylesheet."""
        session = requests.Session()
        response = session.get(f"{self.server.base_url}/auth")
        assert "oauth.css" in response.text

    def test_login_page_has_oauth_link(self):
        """Login page has a link to the OAuth login route."""
        session = requests.Session()
        response = session.get(f"{self.server.base_url}/auth")
        assert "/auth/login/google" in response.text


class TestOAuthLoginPageMultiProvider:
    """Test login page with multiple providers."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir, config_path = _create_oauth_server(
            "oauth_multi_provider_page_test",
            providers={
                "google": google_provider(),
                "github": github_provider(),
            },
        )
        server = FlaskTestServer(config_file=config_path)
        if not server.start():
            pytest.fail("Failed to start server")
        request.cls.server = server
        request.cls.test_dir = test_dir
        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    def test_shows_both_provider_buttons(self):
        """Login page shows buttons for all configured providers."""
        session = requests.Session()
        response = session.get(f"{self.server.base_url}/auth")
        assert "Sign in with Google" in response.text
        assert "Sign in with GitHub" in response.text


class TestOAuthRoutes:
    """Test the OAuth route handlers."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir, config_path = _create_oauth_server(
            "oauth_routes_test",
            providers={"google": google_provider()},
        )
        server = FlaskTestServer(config_file=config_path)
        if not server.start():
            pytest.fail("Failed to start server")
        request.cls.server = server
        request.cls.test_dir = test_dir
        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    def test_unknown_provider_returns_404(self):
        """GET /auth/login/fakeprovider returns 404."""
        session = requests.Session()
        response = session.get(
            f"{self.server.base_url}/auth/login/fakeprovider",
            allow_redirects=False,
        )
        assert response.status_code == 404

    def test_callback_with_error_param_shows_message(self):
        """Provider returns ?error=access_denied — shows user-friendly message."""
        session = requests.Session()
        response = session.get(
            f"{self.server.base_url}/auth/callback/google",
            params={
                "error": "access_denied",
                "error_description": "User denied access",
            },
        )
        assert response.status_code == 200
        assert "cancelled" in response.text.lower() or "denied" in response.text.lower()

    def test_callback_with_error_shows_login_page(self):
        """Error callback still shows login page with SSO buttons."""
        session = requests.Session()
        response = session.get(
            f"{self.server.base_url}/auth/callback/google",
            params={"error": "access_denied"},
        )
        assert "Sign in with Google" in response.text

    def test_callback_without_code_fails_gracefully(self):
        """Callback without ?code= parameter fails gracefully."""
        session = requests.Session()
        response = session.get(
            f"{self.server.base_url}/auth/callback/google",
        )
        # Should show an error or redirect, not crash
        assert response.status_code in (200, 302)


class TestOAuthMixedMode:
    """Test OAuth + local login coexistence."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir, config_path = _create_oauth_server(
            "oauth_mixed_mode_test",
            providers={"google": google_provider()},
            allow_local_login=True,
        )
        # For mixed mode, require_password needs to be in the main config
        import yaml
        with open(config_path, 'r') as f:
            config_data = yaml.safe_load(f)
        config_data['require_password'] = True
        with open(config_path, 'w') as f:
            yaml.dump(config_data, f)

        server = FlaskTestServer(config_file=config_path)
        if not server.start():
            pytest.fail("Failed to start server")
        request.cls.server = server
        request.cls.test_dir = test_dir
        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    def test_login_page_shows_both_sso_and_local(self):
        """Login page shows SSO buttons AND local login form."""
        session = requests.Session()
        response = session.get(f"{self.server.base_url}/auth")
        html = response.text
        assert "Sign in with Google" in html
        assert 'name="pass"' in html  # Password field present

    def test_login_page_shows_divider(self):
        """Login page shows 'or' divider between SSO and local login."""
        session = requests.Session()
        response = session.get(f"{self.server.base_url}/auth")
        assert "oauth-divider" in response.text

    def test_local_login_still_works(self):
        """Traditional username/password login works alongside OAuth."""
        session = requests.Session()
        # Register
        session.post(
            f"{self.server.base_url}/register",
            data={"email": "localuser_mixed", "pass": "password123"},
        )
        # Login
        session.post(
            f"{self.server.base_url}/auth",
            data={"email": "localuser_mixed", "pass": "password123"},
        )
        # Verify access to annotation page
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200


class TestOAuthOnlyMode:
    """Test OAuth-only mode (no local login)."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir, config_path = _create_oauth_server(
            "oauth_only_mode_test",
            providers={"google": google_provider()},
            allow_local_login=False,
        )
        server = FlaskTestServer(config_file=config_path)
        if not server.start():
            pytest.fail("Failed to start server")
        request.cls.server = server
        request.cls.test_dir = test_dir
        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    def test_login_page_hides_local_form_when_oauth_only(self):
        """With allow_local_login=false, no password/username form shown."""
        session = requests.Session()
        response = session.get(f"{self.server.base_url}/auth")
        html = response.text
        assert "Sign in with Google" in html
        # The local login tabs should not be shown
        assert "potato-tabs" not in html
