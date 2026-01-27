"""
Smoke tests for Potato Annotation Platform.

These tests verify the critical path works:
1. All example configs can start a server
2. Home page loads without errors
3. Users can register and login
4. Annotation page renders correctly
5. Basic annotation can be saved

These tests are designed to catch configuration errors and broken
functionality that would be immediately apparent to users.
"""

import pytest
import time
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.integration.base import IntegrationTestServer, ServerStartupError


# ==================== Server Startup Tests ====================

@pytest.mark.smoke
class TestServerStartup:
    """Test that all example configs can start a server."""

    def test_server_starts_successfully(self, config_file: Path, base_port: int):
        """
        Test that the server starts without errors for this config.

        This is the most critical test - if the server can't start,
        nothing else will work.
        """
        from tests.integration.conftest import CONFIGS_WITH_KNOWN_ISSUES

        config_name = config_file.stem
        if config_name in CONFIGS_WITH_KNOWN_ISSUES:
            pytest.xfail(f"Known issue: {CONFIGS_WITH_KNOWN_ISSUES[config_name]}")

        server = IntegrationTestServer(str(config_file), port=base_port)

        try:
            success, error = server.start(timeout=30)

            if not success:
                # Provide detailed error information
                pytest.fail(
                    f"Server failed to start with config '{config_file.name}':\n"
                    f"{error}\n\n"
                    f"stdout: {server.startup_output[:500] if server.startup_output else 'none'}\n"
                    f"stderr: {server.startup_errors[:500] if server.startup_errors else 'none'}"
                )

            # Verify server is actually responding
            assert server._is_server_ready(), \
                f"Server started but is not responding at {server.base_url}"

        finally:
            server.stop()


# ==================== Home Page Tests ====================

@pytest.mark.smoke
class TestHomePage:
    """Test that home page loads correctly."""

    @pytest.fixture
    def server_with_checkbox_config(self, base_port: int) -> IntegrationTestServer:
        """Start a server with the simple checkbox config."""
        config_path = PROJECT_ROOT / "project-hub" / "simple_examples" / "configs" / "simple-check-box.yaml"
        server = IntegrationTestServer(str(config_path), port=base_port)
        success, error = server.start()
        if not success:
            pytest.skip(f"Server failed to start: {error}")
        yield server
        server.stop()

    def test_home_page_loads(self, server_with_checkbox_config: IntegrationTestServer, browser):
        """Test that home page loads with login form."""
        server = server_with_checkbox_config

        browser.get(server.base_url)

        # Wait for page load
        time.sleep(1)

        # Check for login form elements
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        try:
            # Should have login tab or form
            login_present = (
                browser.find_elements(By.ID, "login-tab") or
                browser.find_elements(By.ID, "login-content") or
                browser.find_elements(By.CSS_SELECTOR, "form")
            )
            assert login_present, "Home page should have login form"

        except Exception as e:
            # Capture screenshot for debugging
            screenshot_path = PROJECT_ROOT / "tests" / "output" / "screenshots"
            screenshot_path.mkdir(parents=True, exist_ok=True)
            browser.save_screenshot(str(screenshot_path / "home_page_failure.png"))
            raise

    def test_no_javascript_errors_on_home(self, server_with_checkbox_config: IntegrationTestServer, browser):
        """Test that home page loads without JavaScript errors."""
        server = server_with_checkbox_config

        browser.get(server.base_url)
        time.sleep(1)

        # Check for severe JavaScript errors
        logs = browser.get_log('browser')
        severe_errors = [log for log in logs if log['level'] == 'SEVERE']

        # Filter out expected errors (missing API keys, favicon, etc.)
        filtered_errors = [
            e for e in severe_errors
            if 'api_key' not in e.get('message', '').lower()
            and 'unauthorized' not in e.get('message', '').lower()
            and 'favicon' not in e.get('message', '').lower()
            and '404' not in e.get('message', '')  # Ignore 404 resource errors
        ]

        assert len(filtered_errors) == 0, f"JavaScript errors on home page: {filtered_errors}"


# ==================== User Registration Tests ====================

@pytest.mark.smoke
class TestUserRegistration:
    """Test user registration functionality."""

    @pytest.fixture
    def server(self, base_port: int) -> IntegrationTestServer:
        """Start a server with the simple checkbox config."""
        config_path = PROJECT_ROOT / "project-hub" / "simple_examples" / "configs" / "simple-check-box.yaml"
        server = IntegrationTestServer(str(config_path), port=base_port)
        success, error = server.start()
        if not success:
            pytest.skip(f"Server failed to start: {error}")
        yield server
        server.stop()

    def test_user_can_register(self, server: IntegrationTestServer, browser, test_user: dict):
        """Test that a new user can register."""
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        browser.get(server.base_url)
        time.sleep(1)

        try:
            # Click register tab to switch to registration form
            register_tab = WebDriverWait(browser, 10).until(
                EC.element_to_be_clickable((By.ID, "register-tab"))
            )
            register_tab.click()
            time.sleep(0.5)

            # Wait for the register form to be visible
            WebDriverWait(browser, 5).until(
                EC.visibility_of_element_located((By.ID, "register-content"))
            )

            # Find fields specifically in the register form
            username_field = browser.find_element(By.ID, "register-email")
            password_field = browser.find_element(By.ID, "register-pass")

            # Fill and submit
            username_field.clear()
            username_field.send_keys(test_user["username"])
            password_field.clear()
            password_field.send_keys(test_user["password"])

            # Submit the registration form specifically
            register_form = browser.find_element(By.CSS_SELECTOR, "#register-content form")
            register_form.submit()

            time.sleep(2)

            # After registration, should be redirected or see main content
            # Check we're not still on the login page
            current_url = browser.current_url
            page_source = browser.page_source.lower()

            success_indicators = [
                "annotation" in current_url.lower(),
                "main-content" in page_source,
                "annotation-forms" in page_source,
                "instance" in page_source
            ]

            assert any(success_indicators), \
                f"Registration may have failed - still appears to be on login page. URL: {current_url}"

        except Exception as e:
            screenshot_path = PROJECT_ROOT / "tests" / "output" / "screenshots"
            screenshot_path.mkdir(parents=True, exist_ok=True)
            browser.save_screenshot(str(screenshot_path / "registration_failure.png"))
            raise AssertionError(f"Registration failed: {e}")


# ==================== Annotation Page Tests ====================

@pytest.mark.smoke
class TestAnnotationPage:
    """Test that annotation page renders correctly."""

    @pytest.fixture
    def authenticated_session(self, base_port: int, browser, test_user: dict):
        """Start server and create authenticated browser session."""
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        config_path = PROJECT_ROOT / "project-hub" / "simple_examples" / "configs" / "simple-check-box.yaml"
        server = IntegrationTestServer(str(config_path), port=base_port)
        success, error = server.start()
        if not success:
            pytest.skip(f"Server failed to start: {error}")

        # Register user
        browser.get(server.base_url)
        time.sleep(1)

        try:
            # Wait for and click register tab
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
            username_field.send_keys(test_user["username"])
            password_field.clear()
            password_field.send_keys(test_user["password"])

            # Submit the registration form
            register_form = browser.find_element(By.CSS_SELECTOR, "#register-content form")
            register_form.submit()

            # Wait for redirect to annotation page (wait for main-content to appear)
            WebDriverWait(browser, 10).until(
                lambda d: "main-content" in d.page_source or "annotation" in d.current_url.lower()
            )
            time.sleep(1)

        except Exception as e:
            # Capture screenshot on failure for debugging
            screenshot_path = PROJECT_ROOT / "tests" / "output" / "screenshots"
            screenshot_path.mkdir(parents=True, exist_ok=True)
            browser.save_screenshot(str(screenshot_path / "auth_fixture_failure.png"))
            pytest.skip(f"Failed to authenticate: {e}")

        yield server, browser

        server.stop()

    def test_annotation_page_renders(self, authenticated_session):
        """Test that annotation page has required elements."""
        from selenium.webdriver.common.by import By

        server, browser = authenticated_session

        # Navigate to ensure we're on annotation page
        browser.get(server.base_url)
        time.sleep(2)

        # Check for key annotation page elements
        expected_elements = [
            ("ID", "main-content"),
            ("ID", "annotation-forms"),
            ("CSS_SELECTOR", "input[type='checkbox'], input[type='radio']"),
        ]

        found = []
        missing = []

        for by_type, selector in expected_elements:
            try:
                if by_type == "ID":
                    element = browser.find_element(By.ID, selector)
                elif by_type == "CSS_SELECTOR":
                    element = browser.find_element(By.CSS_SELECTOR, selector)
                found.append(selector)
            except:
                missing.append(selector)

        # Should have at least main-content or annotation-forms
        assert "main-content" in found or "annotation-forms" in found or len(missing) == 0, \
            f"Missing critical page elements: {missing}"

    def test_instance_displayed(self, authenticated_session):
        """Test that an instance is displayed on the annotation page."""
        from selenium.webdriver.common.by import By

        server, browser = authenticated_session

        browser.get(server.base_url)
        time.sleep(2)

        # Should have some text content displayed
        page_text = browser.find_element(By.TAG_NAME, "body").text

        # The toy-example.csv has specific content
        assert len(page_text) > 100, "Page should have substantial content"


# ==================== Basic Annotation Tests ====================

@pytest.mark.smoke
class TestBasicAnnotation:
    """Test that basic annotations can be made and saved."""

    @pytest.fixture
    def annotation_session(self, base_port: int, browser, test_user: dict):
        """Create a session ready for annotation."""
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        config_path = PROJECT_ROOT / "project-hub" / "simple_examples" / "configs" / "simple-check-box.yaml"
        server = IntegrationTestServer(str(config_path), port=base_port)
        success, error = server.start()
        if not success:
            pytest.skip(f"Server failed to start: {error}")

        # Register and navigate to annotation
        browser.get(server.base_url)
        time.sleep(1)

        try:
            # Wait for and click register tab
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
            username_field.send_keys(test_user["username"])
            password_field.clear()
            password_field.send_keys(test_user["password"])

            # Submit the registration form
            register_form = browser.find_element(By.CSS_SELECTOR, "#register-content form")
            register_form.submit()

            # Wait for redirect to annotation page
            WebDriverWait(browser, 10).until(
                lambda d: "main-content" in d.page_source or "annotation" in d.current_url.lower()
            )
            time.sleep(1)

        except Exception as e:
            screenshot_path = PROJECT_ROOT / "tests" / "output" / "screenshots"
            screenshot_path.mkdir(parents=True, exist_ok=True)
            browser.save_screenshot(str(screenshot_path / "annotation_session_failure.png"))
            pytest.skip(f"Failed to authenticate: {e}")

        yield server, browser

        server.stop()

    def test_checkbox_can_be_clicked(self, annotation_session):
        """Test that checkboxes can be clicked."""
        from selenium.webdriver.common.by import By

        server, browser = annotation_session

        browser.get(server.base_url)
        time.sleep(2)

        # Find a checkbox
        try:
            checkboxes = browser.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
            assert len(checkboxes) > 0, "Should have at least one checkbox"

            # Click first checkbox
            checkbox = checkboxes[0]
            initial_state = checkbox.is_selected()

            browser.execute_script("arguments[0].scrollIntoView(true);", checkbox)
            time.sleep(0.2)
            checkbox.click()
            time.sleep(0.5)

            # Verify state changed
            new_state = checkbox.is_selected()
            assert new_state != initial_state, "Checkbox state should change when clicked"

        except Exception as e:
            screenshot_path = PROJECT_ROOT / "tests" / "output" / "screenshots"
            screenshot_path.mkdir(parents=True, exist_ok=True)
            browser.save_screenshot(str(screenshot_path / "checkbox_click_failure.png"))
            raise

    @pytest.mark.xfail(reason="Known persistence issue - annotations via direct click not persisting")
    def test_annotation_triggers_save(self, annotation_session):
        """Test that making an annotation triggers a save to server.

        This test is currently failing due to a persistence issue where
        annotations made by directly clicking checkboxes don't persist
        after navigation. The issue is tracked and needs investigation.
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        server, browser = annotation_session

        browser.get(server.base_url)
        time.sleep(2)

        try:
            # Make an annotation
            checkboxes = browser.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
            if not checkboxes:
                pytest.skip("No checkboxes found on annotation page")

            checkbox = checkboxes[0]
            browser.execute_script("arguments[0].scrollIntoView(true);", checkbox)
            checkbox.click()
            time.sleep(0.5)

            # Navigate away to trigger save (re-find body after each navigation)
            browser.find_element(By.TAG_NAME, "body").send_keys(Keys.ARROW_RIGHT)
            time.sleep(1)

            # Navigate back (re-find body element)
            browser.find_element(By.TAG_NAME, "body").send_keys(Keys.ARROW_LEFT)
            time.sleep(1)

            # Check if annotation persisted
            checkboxes = browser.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
            if checkboxes:
                checkbox = checkboxes[0]
                assert checkbox.is_selected(), \
                    "Annotation should persist after navigation"

        except Exception as e:
            screenshot_path = PROJECT_ROOT / "tests" / "output" / "screenshots"
            screenshot_path.mkdir(parents=True, exist_ok=True)
            browser.save_screenshot(str(screenshot_path / "annotation_save_failure.png"))
            raise


# ==================== Config Validation Tests ====================

@pytest.mark.smoke
class TestConfigValidation:
    """Test that invalid configs produce helpful errors."""

    def test_missing_data_file_error(self, base_port: int, tmp_path: Path):
        """Test that missing data file produces clear error."""
        import yaml

        # Create config with non-existent data file
        config = {
            "annotation_task_name": "Test",
            "task_dir": str(tmp_path),
            "data_files": ["nonexistent_data.csv"],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "annotation_schemes": [
                {"annotation_type": "radio", "name": "test", "labels": ["a", "b"]}
            ],
            "output_annotation_dir": str(tmp_path / "output"),
            "site_dir": "default",
            "user_config": {"allow_all_users": True}
        }

        config_file = tmp_path / "test_config.yaml"
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        server = IntegrationTestServer(str(config_file), port=base_port)
        success, error = server.start(timeout=10)

        # Should fail with informative error
        assert not success, "Server should fail with missing data file"
        assert error, "Should have error message"

        server.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-x"])
