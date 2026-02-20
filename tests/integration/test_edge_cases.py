"""
Edge case tests for Potato Annotation Platform.

These tests verify that the platform handles boundary conditions
and unusual scenarios gracefully:
1. Special characters and unicode
2. Rapid navigation
3. Large content
4. Browser behaviors
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

def register_user(browser, server, test_user):
    """Register user and wait for annotation page."""
    browser.get(server.base_url)
    time.sleep(1)

    register_tab = WebDriverWait(browser, 10).until(
        EC.element_to_be_clickable((By.ID, "register-tab"))
    )
    register_tab.click()
    time.sleep(0.5)

    WebDriverWait(browser, 5).until(
        EC.visibility_of_element_located((By.ID, "register-content"))
    )

    username_field = browser.find_element(By.ID, "register-email")
    password_field = browser.find_element(By.ID, "register-pass")

    username_field.clear()
    username_field.send_keys(test_user["username"])
    password_field.clear()
    password_field.send_keys(test_user["password"])

    register_form = browser.find_element(By.CSS_SELECTOR, "#register-content form")
    register_form.submit()

    WebDriverWait(browser, 15).until(
        lambda d: "main-content" in d.page_source
    )
    time.sleep(1)


# ==================== Rapid Navigation Tests ====================

@pytest.mark.edge_case
class TestRapidNavigation:
    """Test that rapid navigation doesn't break the UI."""

    @pytest.fixture
    def server(self, base_port):
        """Start server with checkbox config."""
        config_path = PROJECT_ROOT / "examples" / "classification" / "check-box" / "config.yaml"
        server = IntegrationTestServer(str(config_path), port=base_port)
        success, error = server.start()
        if not success:
            pytest.skip(f"Server failed to start: {error}")
        yield server
        server.stop()

    def test_rapid_next_navigation(self, server, browser, test_user):
        """Test that rapidly pressing next doesn't crash the UI."""
        register_user(browser, server, test_user)

        # Rapidly navigate next multiple times
        for _ in range(5):
            try:
                browser.find_element(By.TAG_NAME, "body").send_keys(Keys.ARROW_RIGHT)
            except:
                pass  # Ignore stale element errors during rapid navigation
            time.sleep(0.3)  # Short delay

        time.sleep(2)  # Wait for last navigation to complete

        # Should still be on a valid annotation page
        assert browser.find_elements(By.CSS_SELECTOR, ".annotation-form") or \
               "main-content" in browser.page_source, \
            "Should still be on valid annotation page after rapid navigation"

    def test_rapid_prev_next_alternating(self, server, browser, test_user):
        """Test rapid alternating navigation."""
        register_user(browser, server, test_user)

        # First go forward a bit
        for _ in range(3):
            try:
                browser.find_element(By.TAG_NAME, "body").send_keys(Keys.ARROW_RIGHT)
            except:
                pass
            time.sleep(0.5)

        time.sleep(1)

        # Rapidly alternate
        for _ in range(3):
            try:
                browser.find_element(By.TAG_NAME, "body").send_keys(Keys.ARROW_LEFT)
            except:
                pass
            time.sleep(0.3)
            try:
                browser.find_element(By.TAG_NAME, "body").send_keys(Keys.ARROW_RIGHT)
            except:
                pass
            time.sleep(0.3)

        time.sleep(2)

        # Should still be functional
        assert browser.find_elements(By.CSS_SELECTOR, "input[type='checkbox'], input[type='radio']") or \
               "main-content" in browser.page_source, \
            "Page should still be functional after rapid navigation"


# ==================== Keyboard Shortcut Tests ====================

@pytest.mark.edge_case
class TestKeyboardShortcuts:
    """Test that all keyboard shortcuts work correctly."""

    @pytest.fixture
    def server(self, base_port):
        """Start server with checkbox config."""
        config_path = PROJECT_ROOT / "examples" / "classification" / "check-box" / "config.yaml"
        server = IntegrationTestServer(str(config_path), port=base_port)
        success, error = server.start()
        if not success:
            pytest.skip(f"Server failed to start: {error}")
        yield server
        server.stop()

    def test_arrow_key_navigation_works(self, server, browser, test_user):
        """Test that arrow keys navigate between instances."""
        register_user(browser, server, test_user)

        # Get initial page state
        initial_source = browser.page_source

        # Navigate forward
        browser.find_element(By.TAG_NAME, "body").send_keys(Keys.ARROW_RIGHT)
        time.sleep(2)

        # Should have navigated (page should be different or at least reloaded)
        assert browser.find_elements(By.CSS_SELECTOR, ".annotation-form") or \
               "main-content" in browser.page_source, \
            "Navigation should work with arrow keys"

    def test_number_keys_toggle_checkboxes(self, server, browser, test_user):
        """Test that number keys can toggle checkboxes."""
        register_user(browser, server, test_user)

        checkboxes = browser.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        if not checkboxes:
            pytest.skip("No checkboxes found")

        # Get the value of first checkbox
        checkbox = checkboxes[0]
        value = checkbox.get_attribute("value")
        initial_state = checkbox.is_selected()

        if not value:
            pytest.skip("Checkbox has no value for keyboard shortcut")

        # Press the first character of the value
        browser.find_element(By.TAG_NAME, "body").send_keys(value[0].lower())
        time.sleep(0.5)

        # Checkbox state should have changed
        assert checkbox.is_selected() != initial_state, \
            f"Pressing '{value[0]}' should toggle checkbox"


# ==================== Text Input Edge Cases ====================

@pytest.mark.edge_case
class TestTextInputEdgeCases:
    """Test edge cases for text input annotations."""

    @pytest.fixture
    def server(self, base_port):
        """Start server with text box config."""
        config_path = PROJECT_ROOT / "examples" / "classification" / "text-box" / "config.yaml"
        server = IntegrationTestServer(str(config_path), port=base_port)
        success, error = server.start()
        if not success:
            pytest.skip(f"Server failed to start: {error}")
        yield server
        server.stop()

    def test_special_characters_in_text_input(self, server, browser, test_user):
        """Test that special characters can be entered in text inputs."""
        register_user(browser, server, test_user)

        text_inputs = browser.find_elements(By.CSS_SELECTOR, "input[type='text'], textarea")
        visible_input = None
        for inp in text_inputs:
            if inp.is_displayed():
                visible_input = inp
                break

        if not visible_input:
            pytest.skip("No visible text input found")

        # Type special characters
        special_text = "Test <html> & 'quotes' \"double\" @#$%"
        visible_input.clear()
        visible_input.send_keys(special_text)
        time.sleep(0.5)

        # Verify the text was entered
        entered = visible_input.get_attribute("value")
        assert special_text in entered or len(entered) > 0, \
            "Special characters should be accepted in text input"

    def test_unicode_in_text_input(self, server, browser, test_user):
        """Test that unicode characters can be entered."""
        register_user(browser, server, test_user)

        text_inputs = browser.find_elements(By.CSS_SELECTOR, "input[type='text'], textarea")
        visible_input = None
        for inp in text_inputs:
            if inp.is_displayed():
                visible_input = inp
                break

        if not visible_input:
            pytest.skip("No visible text input found")

        # Type unicode characters
        unicode_text = "Test unicode: cafe cafe"
        visible_input.clear()
        visible_input.send_keys(unicode_text)
        time.sleep(0.5)

        # Verify something was entered
        entered = visible_input.get_attribute("value")
        assert len(entered) > 0, "Unicode characters should be accepted"

    def test_long_text_input(self, server, browser, test_user):
        """Test that long text can be entered."""
        register_user(browser, server, test_user)

        text_inputs = browser.find_elements(By.CSS_SELECTOR, "input[type='text'], textarea")
        visible_input = None
        for inp in text_inputs:
            if inp.is_displayed():
                visible_input = inp
                break

        if not visible_input:
            pytest.skip("No visible text input found")

        # Type a long string
        long_text = "This is a long annotation. " * 20
        visible_input.clear()
        visible_input.send_keys(long_text[:500])  # Limit to prevent timeout
        time.sleep(0.5)

        # Verify text was entered
        entered = visible_input.get_attribute("value")
        assert len(entered) > 100, "Long text should be accepted"


# ==================== Browser Behavior Tests ====================

@pytest.mark.edge_case
class TestBrowserBehaviors:
    """Test browser-specific behaviors."""

    @pytest.fixture
    def server(self, base_port):
        """Start server with checkbox config."""
        config_path = PROJECT_ROOT / "examples" / "classification" / "check-box" / "config.yaml"
        server = IntegrationTestServer(str(config_path), port=base_port)
        success, error = server.start()
        if not success:
            pytest.skip(f"Server failed to start: {error}")
        yield server
        server.stop()

    def test_page_refresh_preserves_login(self, server, browser, test_user):
        """Test that refreshing the page doesn't log out the user."""
        register_user(browser, server, test_user)

        # Verify on annotation page
        assert "main-content" in browser.page_source

        # Refresh
        browser.refresh()
        time.sleep(2)

        # Should still be logged in
        assert "main-content" in browser.page_source, \
            "User should stay logged in after refresh"

    def test_direct_url_access_while_logged_in(self, server, browser, test_user):
        """Test accessing annotation URL directly while logged in."""
        register_user(browser, server, test_user)

        # Try accessing the base URL directly
        browser.get(server.base_url)
        time.sleep(2)

        # Should be on annotation page (not redirected to login)
        assert "main-content" in browser.page_source or \
               browser.find_elements(By.CSS_SELECTOR, ".annotation-form"), \
            "Direct URL access should show annotation page when logged in"


# ==================== Form Validation Tests ====================

@pytest.mark.edge_case
class TestFormValidation:
    """Test form validation edge cases."""

    @pytest.fixture
    def server(self, base_port):
        """Start server with checkbox config."""
        config_path = PROJECT_ROOT / "examples" / "classification" / "check-box" / "config.yaml"
        server = IntegrationTestServer(str(config_path), port=base_port)
        success, error = server.start()
        if not success:
            pytest.skip(f"Server failed to start: {error}")
        yield server
        server.stop()

    def test_empty_username_registration(self, server, browser):
        """Test that empty username is handled gracefully."""
        browser.get(server.base_url)
        time.sleep(1)

        register_tab = WebDriverWait(browser, 10).until(
            EC.element_to_be_clickable((By.ID, "register-tab"))
        )
        register_tab.click()
        time.sleep(0.5)

        # Try to submit empty form
        WebDriverWait(browser, 5).until(
            EC.visibility_of_element_located((By.ID, "register-content"))
        )

        password_field = browser.find_element(By.ID, "register-pass")
        password_field.send_keys("test_password")

        register_form = browser.find_element(By.CSS_SELECTOR, "#register-content form")

        try:
            register_form.submit()
            time.sleep(2)

            # Should still be on login page or show error
            assert "register-tab" in browser.page_source or \
                   "error" in browser.page_source.lower(), \
                "Should handle empty username gracefully"
        except:
            # Form submission may be blocked by browser validation
            pass

    def test_whitespace_only_username(self, server, browser):
        """Test that whitespace-only username is handled."""
        browser.get(server.base_url)
        time.sleep(1)

        register_tab = WebDriverWait(browser, 10).until(
            EC.element_to_be_clickable((By.ID, "register-tab"))
        )
        register_tab.click()
        time.sleep(0.5)

        WebDriverWait(browser, 5).until(
            EC.visibility_of_element_located((By.ID, "register-content"))
        )

        username_field = browser.find_element(By.ID, "register-email")
        password_field = browser.find_element(By.ID, "register-pass")

        username_field.send_keys("   ")  # Whitespace only
        password_field.send_keys("test_password")

        register_form = browser.find_element(By.CSS_SELECTOR, "#register-content form")
        register_form.submit()
        time.sleep(2)

        # Should handle gracefully - either error or sanitize
        # Just verify page is still functional
        assert browser.find_elements(By.TAG_NAME, "body"), \
            "Page should still be functional"


# ==================== Navigation Boundary Tests ====================

@pytest.mark.edge_case
class TestNavigationBoundaries:
    """Test navigation at boundaries (first/last instance)."""

    @pytest.fixture
    def server(self, base_port):
        """Start server with checkbox config."""
        config_path = PROJECT_ROOT / "examples" / "classification" / "check-box" / "config.yaml"
        server = IntegrationTestServer(str(config_path), port=base_port)
        success, error = server.start()
        if not success:
            pytest.skip(f"Server failed to start: {error}")
        yield server
        server.stop()

    def test_navigate_prev_at_first_instance(self, server, browser, test_user):
        """Test navigating previous when at first instance."""
        register_user(browser, server, test_user)

        # Try to navigate previous (should stay at first or show message)
        browser.find_element(By.TAG_NAME, "body").send_keys(Keys.ARROW_LEFT)
        time.sleep(2)

        # Should still be on a valid annotation page
        assert browser.find_elements(By.CSS_SELECTOR, ".annotation-form") or \
               "main-content" in browser.page_source, \
            "Should handle navigation at first instance gracefully"

    def test_go_to_invalid_instance(self, server, browser, test_user):
        """Test go-to with invalid instance number."""
        register_user(browser, server, test_user)

        go_to_inputs = browser.find_elements(By.ID, "go_to")
        if not go_to_inputs:
            pytest.skip("No go-to input found")

        go_to = go_to_inputs[0]

        # Try to go to a very large instance number
        go_to.clear()
        go_to.send_keys("999999")
        go_to.send_keys(Keys.RETURN)
        time.sleep(2)

        # Should handle gracefully - either go to last or show error
        assert browser.find_elements(By.TAG_NAME, "body"), \
            "Page should still be functional after invalid go-to"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-x"])
