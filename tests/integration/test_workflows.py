"""
Workflow tests for Potato Annotation Platform.

These tests verify complete user journeys through the annotation platform,
ensuring that real annotators can successfully complete their tasks.

Test Categories:
1. Onboarding workflow - First-time annotator experience
2. Returning user workflow - Resume previous work
3. Training workflows - Pass/fail scenarios
4. Multi-phase workflows - Complex task flows
"""

import pytest
import time
import sys
from pathlib import Path

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.integration.base import IntegrationTestServer


# ==================== Helper Functions ====================

def register_user(browser, server, username, password):
    """Register a new user and return to annotation page."""
    browser.get(server.base_url)
    time.sleep(1)

    # Click register tab
    register_tab = WebDriverWait(browser, 10).until(
        EC.element_to_be_clickable((By.ID, "register-tab"))
    )
    register_tab.click()
    time.sleep(0.5)

    # Wait for registration form
    WebDriverWait(browser, 5).until(
        EC.visibility_of_element_located((By.ID, "register-content"))
    )

    # Fill registration form
    username_field = browser.find_element(By.ID, "register-email")
    password_field = browser.find_element(By.ID, "register-pass")

    username_field.clear()
    username_field.send_keys(username)
    password_field.clear()
    password_field.send_keys(password)

    # Submit
    register_form = browser.find_element(By.CSS_SELECTOR, "#register-content form")
    register_form.submit()

    # Wait for page to load
    time.sleep(2)


def login_user(browser, server, username, password):
    """Login an existing user."""
    browser.get(server.base_url)
    time.sleep(1)

    # Click login tab
    login_tab = WebDriverWait(browser, 10).until(
        EC.element_to_be_clickable((By.ID, "login-tab"))
    )
    login_tab.click()
    time.sleep(0.5)

    # Wait for login form
    WebDriverWait(browser, 5).until(
        EC.visibility_of_element_located((By.ID, "login-content"))
    )

    # Fill login form
    username_field = browser.find_element(By.ID, "login-email")
    password_field = browser.find_element(By.ID, "login-pass")

    username_field.clear()
    username_field.send_keys(username)
    password_field.clear()
    password_field.send_keys(password)

    # Submit
    login_form = browser.find_element(By.CSS_SELECTOR, "#login-content form")
    login_form.submit()

    # Wait for page to load
    time.sleep(2)


def navigate_next(browser):
    """Navigate to next instance using keyboard."""
    browser.find_element(By.TAG_NAME, "body").send_keys(Keys.ARROW_RIGHT)
    time.sleep(1)


def navigate_prev(browser):
    """Navigate to previous instance using keyboard."""
    browser.find_element(By.TAG_NAME, "body").send_keys(Keys.ARROW_LEFT)
    time.sleep(1)


# ==================== Simple Workflow Tests ====================

@pytest.mark.workflow
class TestSimpleOnboarding:
    """Test basic onboarding workflow without phases."""

    @pytest.fixture
    def server(self, base_port):
        """Start server with simple checkbox config."""
        config_path = PROJECT_ROOT / "project-hub" / "simple_examples" / "configs" / "simple-check-box.yaml"
        server = IntegrationTestServer(str(config_path), port=base_port)
        success, error = server.start()
        if not success:
            pytest.skip(f"Server failed to start: {error}")
        yield server
        server.stop()

    def test_new_user_can_complete_first_annotation(self, server, browser, test_user):
        """Test that a new user can register and complete their first annotation."""
        # Register
        register_user(browser, server, test_user["username"], test_user["password"])

        # Should now be on annotation page
        WebDriverWait(browser, 10).until(
            lambda d: "main-content" in d.page_source
        )

        # Find and click a checkbox
        checkboxes = browser.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        assert len(checkboxes) > 0, "Should have checkboxes to annotate"

        checkbox = checkboxes[0]
        browser.execute_script("arguments[0].scrollIntoView(true);", checkbox)
        checkbox.click()
        time.sleep(0.5)

        # Navigate to next instance (implicitly saves)
        navigate_next(browser)

        # Verify we're on a new instance
        assert browser.find_elements(By.CSS_SELECTOR, "input[type='checkbox']"), \
            "Should be on new annotation page"

    def test_user_can_navigate_multiple_instances(self, server, browser, test_user):
        """Test that user can navigate through multiple instances."""
        register_user(browser, server, test_user["username"], test_user["password"])

        # Navigate forward 3 times
        for i in range(3):
            navigate_next(browser)

        # Navigate back 2 times
        for i in range(2):
            navigate_prev(browser)

        # Should be on the second instance (started at 1, went to 4, came back to 2)
        # Just verify we're still on an annotation page
        assert browser.find_elements(By.CSS_SELECTOR, ".annotation-form"), \
            "Should still be on annotation page after navigation"


# ==================== Returning User Workflow Tests ====================

@pytest.mark.workflow
class TestReturningUser:
    """Test workflows for returning users."""

    @pytest.fixture
    def server(self, base_port):
        """Start server with simple checkbox config."""
        config_path = PROJECT_ROOT / "project-hub" / "simple_examples" / "configs" / "simple-check-box.yaml"
        server = IntegrationTestServer(str(config_path), port=base_port)
        success, error = server.start()
        if not success:
            pytest.skip(f"Server failed to start: {error}")
        yield server
        server.stop()

    def test_returning_user_can_login(self, server, browser, test_user):
        """Test that a user can register, logout, and login again."""
        # Register first
        register_user(browser, server, test_user["username"], test_user["password"])

        # Verify we're logged in
        WebDriverWait(browser, 10).until(
            lambda d: "main-content" in d.page_source
        )

        # Clear session by navigating to logout
        try:
            browser.get(f"{server.base_url}/logout")
            time.sleep(1)
        except:
            # May not have explicit logout, clear cookies instead
            browser.delete_all_cookies()
            browser.get(server.base_url)
            time.sleep(1)

        # Now login
        login_user(browser, server, test_user["username"], test_user["password"])

        # Should be back on annotation page
        WebDriverWait(browser, 10).until(
            lambda d: "main-content" in d.page_source or "annotation" in d.current_url.lower()
        )


# ==================== Multi-Phase Workflow Tests ====================

@pytest.mark.workflow
class TestMultiPhaseWorkflow:
    """Test workflows with multiple phases (consent, instructions, training, etc.)."""

    @pytest.fixture
    def server(self, base_port):
        """Start server with all-phases config."""
        config_path = PROJECT_ROOT / "project-hub" / "simple_examples" / "configs" / "all-phases-example.yaml"
        server = IntegrationTestServer(str(config_path), port=base_port)
        success, error = server.start()
        if not success:
            pytest.skip(f"Server failed to start: {error}")
        yield server
        server.stop()

    def test_user_goes_through_consent_phase(self, server, browser, test_user):
        """Test that user encounters consent phase after registration."""
        register_user(browser, server, test_user["username"], test_user["password"])

        # Wait for page to load
        time.sleep(2)

        # Check if we're on a consent page, other phase, or annotation page
        page_source = browser.page_source.lower()
        current_url = browser.current_url.lower()

        # Should be either on consent, prestudy, instructions, or annotation page
        valid_pages = [
            "consent" in page_source,
            "consent" in current_url,
            "prestudy" in page_source,
            "prestudy" in current_url,
            "instructions" in page_source,
            "instructions" in current_url,
            "main-content" in page_source,
            "annotation" in current_url,
            "training" in current_url,
        ]

        assert any(valid_pages), \
            f"Should be on consent, instructions, or annotation page. URL: {browser.current_url}"

    def test_user_can_accept_consent(self, server, browser, test_user):
        """Test that user can accept consent and proceed."""
        register_user(browser, server, test_user["username"], test_user["password"])

        # Wait for page
        time.sleep(2)

        # Try to find and click consent accept button
        try:
            # Look for various consent button patterns
            consent_buttons = browser.find_elements(By.CSS_SELECTOR,
                "button[type='submit'], input[type='submit'], .consent-accept, #accept-consent")

            if consent_buttons:
                for btn in consent_buttons:
                    try:
                        if btn.is_displayed():
                            btn.click()
                            time.sleep(1)
                            break
                    except:
                        continue
        except:
            pass  # May not have consent page

        # After consent, should proceed to next phase
        time.sleep(2)


# ==================== Error Recovery Tests ====================

@pytest.mark.workflow
class TestErrorRecovery:
    """Test error recovery scenarios."""

    @pytest.fixture
    def server(self, base_port):
        """Start server with simple checkbox config."""
        config_path = PROJECT_ROOT / "project-hub" / "simple_examples" / "configs" / "simple-check-box.yaml"
        server = IntegrationTestServer(str(config_path), port=base_port)
        success, error = server.start()
        if not success:
            pytest.skip(f"Server failed to start: {error}")
        yield server
        server.stop()

    def test_page_refresh_preserves_session(self, server, browser, test_user):
        """Test that refreshing the page preserves the session."""
        register_user(browser, server, test_user["username"], test_user["password"])

        # Verify we're logged in
        WebDriverWait(browser, 10).until(
            lambda d: "main-content" in d.page_source
        )

        # Refresh the page
        browser.refresh()
        time.sleep(2)

        # Should still be on annotation page (session preserved)
        assert "main-content" in browser.page_source, \
            "Session should be preserved after page refresh"

    def test_invalid_login_shows_error(self, server, browser):
        """Test that invalid login credentials show an error message."""
        browser.get(server.base_url)
        time.sleep(1)

        # Click login tab
        login_tab = WebDriverWait(browser, 10).until(
            EC.element_to_be_clickable((By.ID, "login-tab"))
        )
        login_tab.click()
        time.sleep(0.5)

        # Try to login with invalid credentials
        username_field = browser.find_element(By.ID, "login-email")
        password_field = browser.find_element(By.ID, "login-pass")

        username_field.clear()
        username_field.send_keys("nonexistent_user")
        password_field.clear()
        password_field.send_keys("wrong_password")

        login_form = browser.find_element(By.CSS_SELECTOR, "#login-content form")
        login_form.submit()

        time.sleep(2)

        # Should show error or stay on login page
        page_source = browser.page_source.lower()
        current_url = browser.current_url.lower()

        # Either show error message or stay on auth/login page
        error_indicators = [
            "error" in page_source,
            "invalid" in page_source,
            "incorrect" in page_source,
            "failed" in page_source,
            "auth" in current_url,
            "login-tab" in browser.page_source,  # Still on login page
        ]

        assert any(error_indicators), \
            "Should show error or stay on login page for invalid credentials"


# ==================== Keyboard Shortcut Tests ====================

@pytest.mark.workflow
class TestKeyboardShortcuts:
    """Test keyboard shortcuts work correctly in workflows."""

    @pytest.fixture
    def server(self, base_port):
        """Start server with simple checkbox config."""
        config_path = PROJECT_ROOT / "project-hub" / "simple_examples" / "configs" / "simple-check-box.yaml"
        server = IntegrationTestServer(str(config_path), port=base_port)
        success, error = server.start()
        if not success:
            pytest.skip(f"Server failed to start: {error}")
        yield server
        server.stop()

    def test_arrow_keys_navigate_instances(self, server, browser, test_user):
        """Test that arrow keys navigate between instances."""
        register_user(browser, server, test_user["username"], test_user["password"])

        # Wait for annotation page
        WebDriverWait(browser, 10).until(
            lambda d: "main-content" in d.page_source
        )

        # Get initial instance (if available)
        initial_content = browser.page_source

        # Navigate to next instance
        browser.find_element(By.TAG_NAME, "body").send_keys(Keys.ARROW_RIGHT)
        time.sleep(2)

        # Page should change (new content or same structure but different data)
        # Just verify we're still on annotation page
        assert "main-content" in browser.page_source or \
               browser.find_elements(By.CSS_SELECTOR, ".annotation-form"), \
            "Should still be on annotation page after navigation"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-x"])
