"""Selenium tests for OAuth login UI.

Tests that the login page renders SSO buttons correctly in the browser,
OAuth CSS loads, mixed mode shows both SSO and local login, and
OAuth-only mode hides the local login form.
"""

import os
import time
import unittest

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.common.exceptions import NoSuchElementException

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
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


def _create_oauth_test_config(test_name, providers, **kwargs):
    """Create test directory, data, and OAuth config. Returns (test_dir, config_path)."""
    test_dir = create_test_directory(test_name)
    data_file = create_test_data_file(test_dir, [
        {"id": "1", "text": "First item."},
        {"id": "2", "text": "Second item."},
    ])

    annotation_schemes = [
        {
            "annotation_type": "radio",
            "name": "sentiment",
            "description": "Rate sentiment",
            "labels": ["positive", "negative"],
        }
    ]

    auth_config = make_oauth_config(
        providers=providers,
        allow_local_login=kwargs.get("allow_local_login", False),
        auto_register=kwargs.get("auto_register", True),
    )

    config_path = create_test_config(
        test_dir,
        annotation_schemes,
        data_files=[data_file],
        authentication=auth_config,
        require_password=kwargs.get("require_password", False),
        secret_key="test-oauth-selenium-secret",
    )
    return test_dir, config_path


class TestOAuthLoginUI(unittest.TestCase):
    """Selenium tests for OAuth SSO login page rendering."""

    @classmethod
    def setUpClass(cls):
        """Start Flask server with Google OAuth config and set up Chrome."""
        cls.test_dir, config_path = _create_oauth_test_config(
            "selenium_oauth_login_ui",
            providers={"google": google_provider()},
            allow_local_login=False,
        )

        port = find_free_port()
        cls.server = FlaskTestServer(port=port, debug=False, config_file=config_path)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=10)

        cls.chrome_options = ChromeOptions()
        cls.chrome_options.add_argument("--headless=new")
        cls.chrome_options.add_argument("--no-sandbox")
        cls.chrome_options.add_argument("--disable-dev-shm-usage")
        cls.chrome_options.add_argument("--disable-gpu")
        cls.chrome_options.add_argument("--window-size=1920,1080")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop_server()
        if hasattr(cls, "test_dir"):
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def test_sso_button_displayed(self):
        """Login page renders a visible SSO button for Google."""
        self.driver.get(f"{self.server.base_url}/auth")
        btn = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".oauth-login-btn"))
        )
        assert btn.is_displayed()
        assert "Google" in btn.text

    def test_sso_button_links_to_oauth_route(self):
        """SSO button href points to /auth/login/google."""
        self.driver.get(f"{self.server.base_url}/auth")
        btn = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".oauth-login-btn"))
        )
        assert "/auth/login/google" in btn.get_attribute("href")

    def test_oauth_css_loaded(self):
        """OAuth CSS stylesheet is included in the page."""
        self.driver.get(f"{self.server.base_url}/auth")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".oauth-login-btn"))
        )
        links = self.driver.find_elements(By.CSS_SELECTOR, "link[rel='stylesheet']")
        oauth_css = [l for l in links if "oauth.css" in (l.get_attribute("href") or "")]
        assert len(oauth_css) == 1, "oauth.css stylesheet should be loaded"

    def test_oauth_only_hides_local_form(self):
        """With allow_local_login=false, no local username/password form is shown."""
        self.driver.get(f"{self.server.base_url}/auth")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".oauth-login-btn"))
        )
        # The tab bar for login/register should not exist
        tabs = self.driver.find_elements(By.CSS_SELECTOR, ".potato-tabs")
        assert len(tabs) == 0, "Local login tabs should not be shown in OAuth-only mode"

    def test_oauth_button_has_provider_icon(self):
        """SSO button includes a provider icon element."""
        self.driver.get(f"{self.server.base_url}/auth")
        btn = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".oauth-login-btn"))
        )
        icons = btn.find_elements(By.CSS_SELECTOR, "i")
        assert len(icons) >= 1, "SSO button should have an icon"


class TestOAuthMixedModeUI(unittest.TestCase):
    """Selenium tests for mixed OAuth + local login mode."""

    @classmethod
    def setUpClass(cls):
        """Start server with Google OAuth + local login."""
        import yaml

        cls.test_dir, config_path = _create_oauth_test_config(
            "selenium_oauth_mixed_ui",
            providers={"google": google_provider()},
            allow_local_login=True,
            require_password=True,
        )

        # Ensure require_password is set in the config for mixed mode
        with open(config_path, "r") as f:
            config_data = yaml.safe_load(f)
        config_data["require_password"] = True
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        port = find_free_port()
        cls.server = FlaskTestServer(port=port, debug=False, config_file=config_path)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=10)

        cls.chrome_options = ChromeOptions()
        cls.chrome_options.add_argument("--headless=new")
        cls.chrome_options.add_argument("--no-sandbox")
        cls.chrome_options.add_argument("--disable-dev-shm-usage")
        cls.chrome_options.add_argument("--disable-gpu")
        cls.chrome_options.add_argument("--window-size=1920,1080")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop_server()
        if hasattr(cls, "test_dir"):
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def test_shows_sso_and_local_form(self):
        """Mixed mode shows both SSO button and local login form."""
        self.driver.get(f"{self.server.base_url}/auth")
        # Wait for SSO button
        sso_btn = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".oauth-login-btn"))
        )
        assert sso_btn.is_displayed()
        # Local login form should also be present
        login_email = self.driver.find_element(By.ID, "login-email")
        assert login_email.is_displayed()

    def test_divider_shown(self):
        """Mixed mode shows an 'or' divider between SSO and local login."""
        self.driver.get(f"{self.server.base_url}/auth")
        divider = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".oauth-divider"))
        )
        assert divider.is_displayed()
        assert "or" in divider.text.lower()

    def test_local_login_works_alongside_sso(self):
        """Traditional username/password login still works in mixed mode."""
        self.driver.get(f"{self.server.base_url}/auth")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".oauth-login-btn"))
        )

        # Switch to register tab
        register_tab = self.driver.find_element(By.ID, "register-tab")
        register_tab.click()
        WebDriverWait(self.driver, 5).until(
            EC.visibility_of_element_located((By.ID, "register-content"))
        )

        # Register a new user — registration auto-logs-in and redirects
        ts = int(time.time())
        username = f"mixed_user_{ts}"
        self.driver.find_element(By.ID, "register-email").send_keys(username)
        self.driver.find_element(By.ID, "register-pass").send_keys("password123")
        self.driver.find_element(By.CSS_SELECTOR, "#register-content form").submit()

        # After registration, the user is logged in and can access annotation
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )


class TestOAuthMultiProviderUI(unittest.TestCase):
    """Selenium test for multiple OAuth providers."""

    @classmethod
    def setUpClass(cls):
        """Start server with Google + GitHub OAuth."""
        cls.test_dir, config_path = _create_oauth_test_config(
            "selenium_oauth_multi_ui",
            providers={
                "google": google_provider(),
                "github": github_provider(),
            },
            allow_local_login=False,
        )

        port = find_free_port()
        cls.server = FlaskTestServer(port=port, debug=False, config_file=config_path)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=10)

        cls.chrome_options = ChromeOptions()
        cls.chrome_options.add_argument("--headless=new")
        cls.chrome_options.add_argument("--no-sandbox")
        cls.chrome_options.add_argument("--disable-dev-shm-usage")
        cls.chrome_options.add_argument("--disable-gpu")
        cls.chrome_options.add_argument("--window-size=1920,1080")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop_server()
        if hasattr(cls, "test_dir"):
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def test_both_provider_buttons_displayed(self):
        """Login page shows buttons for both Google and GitHub."""
        self.driver.get(f"{self.server.base_url}/auth")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".oauth-providers"))
        )
        buttons = self.driver.find_elements(By.CSS_SELECTOR, ".oauth-login-btn")
        assert len(buttons) == 2, f"Expected 2 SSO buttons, got {len(buttons)}"
        texts = [b.text for b in buttons]
        assert any("Google" in t for t in texts)
        assert any("GitHub" in t for t in texts)

    def test_each_button_has_correct_link(self):
        """Each provider button links to the correct OAuth login route."""
        self.driver.get(f"{self.server.base_url}/auth")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".oauth-providers"))
        )
        buttons = self.driver.find_elements(By.CSS_SELECTOR, ".oauth-login-btn")
        hrefs = [b.get_attribute("href") for b in buttons]
        assert any("/auth/login/google" in h for h in hrefs)
        assert any("/auth/login/github" in h for h in hrefs)
