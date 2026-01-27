"""
Integration tests for annotation persistence.

Tests verify that annotations persist correctly:
- When navigating between instances
- When using go-to navigation
- When refreshing the page
"""

import os
import time
import pytest
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from tests.helpers.test_utils import TestConfigManager


# Get project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent


# ==================== Fixtures ====================

class IntegrationTestServer:
    """Wrapper to start a Flask test server for integration tests."""

    def __init__(self, config_path: str, port: int = 9494):
        self.config_path = config_path
        self.port = port
        self.process = None
        self.base_url = f"http://localhost:{port}"

    def start(self):
        """Start the server in a subprocess."""
        import subprocess
        import sys

        env = os.environ.copy()
        env['PYTHONPATH'] = str(PROJECT_ROOT)

        # Use absolute path for config file
        # Run from parent of configs dir (e.g., simple_examples/) since data paths are relative to that
        abs_config_path = os.path.abspath(self.config_path)
        config_dir = os.path.dirname(abs_config_path)
        project_dir = os.path.dirname(config_dir)  # Go up one level from configs/
        rel_config_path = os.path.join('configs', os.path.basename(abs_config_path))

        self.process = subprocess.Popen(
            [sys.executable, "-m", "potato.flask_server", "start", rel_config_path, "-p", str(self.port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=project_dir  # Run from the project directory (parent of configs/)
        )

        # Wait for server to be ready
        import socket
        for _ in range(30):  # 30 seconds timeout
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.connect(("localhost", self.port))
                    return True, None
            except (ConnectionRefusedError, OSError):
                time.sleep(1)

        return False, "Server failed to start within 30 seconds"

    def stop(self):
        """Stop the server."""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except:
                self.process.kill()


@pytest.fixture
def base_port():
    """Get a unique port for this test run."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]


def register_user(browser, server, username):
    """Register a user and navigate to the annotation page."""
    url = f"{server.base_url}/?username={username}"
    print(f"\n[DEBUG] Navigating to: {url}")
    browser.get(url)
    time.sleep(2)  # Wait for page to load

    # Debug: print page title and URL
    print(f"[DEBUG] Page title: {browser.title}")
    print(f"[DEBUG] Current URL: {browser.current_url}")
    print(f"[DEBUG] Page source length: {len(browser.page_source)}")

    # Debug: print first 500 chars of page source
    page_src = browser.page_source[:1000]
    print(f"[DEBUG] Page source preview:\n{page_src}")

    # Check if we're on a login/register page
    login_forms = browser.find_elements(By.ID, "login-tab")
    register_forms = browser.find_elements(By.ID, "register-tab")
    if login_forms or register_forms:
        print("[DEBUG] Detected login/register page - need to login")
        # Try to register if there's a register tab
        if register_forms:
            register_tab = register_forms[0]
            register_tab.click()
            time.sleep(0.5)
            # Fill in registration form
            username_field = browser.find_element(By.ID, "register-email")
            password_field = browser.find_element(By.ID, "register-pass")
            username_field.clear()
            username_field.send_keys(username)
            password_field.clear()
            password_field.send_keys("test123")
            # Submit
            form = browser.find_element(By.CSS_SELECTOR, "#register-content form")
            form.submit()
            time.sleep(2)
            print(f"[DEBUG] After registration - URL: {browser.current_url}")

    # Check if we're on a consent page
    consent_buttons = browser.find_elements(By.CSS_SELECTOR, "button[type='submit'], input[type='submit']")
    for btn in consent_buttons:
        btn_text = btn.text.lower() if btn.text else ""
        print(f"[DEBUG] Found button: {btn_text}")
        if "agree" in btn_text or "continue" in btn_text:
            btn.click()
            time.sleep(1)
            break

    # Wait for the annotation interface (could be checkboxes, radios, or text inputs)
    try:
        WebDriverWait(browser, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='checkbox'], input[type='radio'], textarea, input.annotation-input"))
        )
        print("[DEBUG] Found annotation inputs!")
    except Exception as e:
        print(f"[DEBUG] Failed to find annotation inputs: {e}")
        print(f"[DEBUG] Current page source:\n{browser.page_source[:2000]}")
        raise


@pytest.fixture
def test_user():
    """Generate a unique test username."""
    import uuid
    return f"test_user_{uuid.uuid4().hex[:8]}"


# ==================== Go-To Navigation Persistence Tests ====================

@pytest.mark.persistence
class TestGoToNavigationPersistence:
    """Test that annotations persist when using go-to navigation."""

    @pytest.fixture
    def server(self, base_port):
        """Start server with checkbox config."""
        config_path = PROJECT_ROOT / "project-hub" / "simple_examples" / "configs" / "simple-check-box.yaml"
        server = IntegrationTestServer(str(config_path), port=base_port)
        success, error = server.start()
        if not success:
            pytest.skip(f"Server failed to start: {error}")
        yield server
        server.stop()

    def test_annotation_survives_go_to_navigation(self, server, browser, test_user):
        """Test that annotation persists when using go-to input."""
        register_user(browser, server, test_user)

        checkboxes = browser.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        if not checkboxes:
            pytest.skip("No checkboxes found")

        # Get the initial instance ID
        instance_id = browser.execute_script("return currentInstance?.id")
        print(f"\n[DEBUG] Initial instance ID: {instance_id}")

        # Make annotation
        checkbox = checkboxes[0]
        checkbox_label = checkbox.get_attribute("label_name") or checkbox.get_attribute("value")
        print(f"[DEBUG] Clicking checkbox: label={checkbox_label}")

        # Click and dispatch change event
        browser.execute_script("""
            arguments[0].click();
            var event = new Event('change', { bubbles: true });
            arguments[0].dispatchEvent(event);
        """, checkbox)
        time.sleep(0.5)

        # Verify checkbox is checked
        checkbox = browser.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")[0]
        assert checkbox.is_selected(), "Checkbox should be checked after click"

        # Verify annotation is recorded in currentAnnotations
        annotations = browser.execute_script("return currentAnnotations")
        print(f"[DEBUG] currentAnnotations after click: {annotations}")
        assert annotations, "currentAnnotations should have the annotation"

        # Manually save the annotation BEFORE navigating
        print(f"[DEBUG] Saving annotation before navigation...")
        save_success = browser.execute_script("""
            syncAnnotationsFromDOM();
            return saveAnnotations().then(function() {
                return true;
            }).catch(function(err) {
                console.error('Save error:', err);
                return false;
            });
        """)
        time.sleep(1.0)  # Wait for async save

        # Refresh to verify save worked
        browser.refresh()
        time.sleep(2)

        # Check if checkbox is still checked after refresh
        checkboxes = browser.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        checkbox = None
        for cb in checkboxes:
            label = cb.get_attribute("label_name") or cb.get_attribute("value")
            if label == checkbox_label:
                checkbox = cb
                break

        if not checkbox or not checkbox.is_selected():
            # Debug: Check what the server returned
            annotations_after_refresh = browser.execute_script("return currentAnnotations")
            print(f"[DEBUG] currentAnnotations after refresh: {annotations_after_refresh}")
            pytest.fail("Annotation not persisted after page refresh")

        print(f"[DEBUG] Annotation persisted after refresh - now testing go-to navigation")

        # Check currentAnnotations before go-to
        annotations_before_goto = browser.execute_script("return currentAnnotations")
        print(f"[DEBUG] currentAnnotations BEFORE go-to: {annotations_before_goto}")

        # Get browser console logs
        console_logs = browser.get_log('browser')
        for log in console_logs:
            if 'PERSISTENCE' in str(log):
                print(f"[CONSOLE] {log}")

        # Now test go-to navigation
        print(f"[DEBUG] Navigating to instance 3...")
        go_to = browser.find_element(By.ID, "go_to")
        go_to.clear()
        go_to.send_keys("3")
        go_to.send_keys(Keys.RETURN)
        time.sleep(2)

        # Check instance and console after first go-to
        current_instance = browser.execute_script("return currentInstance?.id")
        print(f"[DEBUG] After go-to 3: currentInstance={current_instance}")

        # Get console logs after navigation
        console_logs = browser.get_log('browser')
        for log in console_logs:
            if 'PERSISTENCE' in str(log):
                print(f"[CONSOLE] {log}")

        # Navigate back to instance 1
        print(f"[DEBUG] Navigating back to instance 1...")
        go_to = browser.find_element(By.ID, "go_to")
        go_to.clear()
        go_to.send_keys("1")
        go_to.send_keys(Keys.RETURN)
        time.sleep(2)

        # Check instance and annotations after returning
        current_instance_back = browser.execute_script("return currentInstance?.id")
        annotations_after_return = browser.execute_script("return currentAnnotations")
        print(f"[DEBUG] After go-to 1: currentInstance={current_instance_back}")
        print(f"[DEBUG] currentAnnotations AFTER returning: {annotations_after_return}")

        # Get console logs
        console_logs = browser.get_log('browser')
        for log in console_logs:
            if 'PERSISTENCE' in str(log):
                print(f"[CONSOLE] {log}")

        # Verify annotation persists
        checkboxes = browser.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        for cb in checkboxes:
            label = cb.get_attribute("label_name") or cb.get_attribute("value")
            if label == checkbox_label:
                print(f"[DEBUG] Final checkbox state: is_selected={cb.is_selected()}")
                assert cb.is_selected(), "Annotation should survive go-to navigation"
                return

        pytest.fail(f"Could not find checkbox {checkbox_label}")


# ==================== Annotation Modification Tests ====================

@pytest.mark.persistence
class TestAnnotationModification:
    """Test that annotation modifications are handled correctly."""

    @pytest.fixture
    def server(self, base_port):
        """Start server with checkbox config."""
        config_path = PROJECT_ROOT / "project-hub" / "simple_examples" / "configs" / "simple-check-box.yaml"
        server = IntegrationTestServer(str(config_path), port=base_port)
        success, error = server.start()
        if not success:
            pytest.skip(f"Server failed to start: {error}")
        yield server
        server.stop()

    def test_modified_annotation_overwrites_previous(self, server, browser, test_user):
        """Test that modifying an annotation overwrites the previous value."""
        register_user(browser, server, test_user)

        checkboxes = browser.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        if len(checkboxes) < 2:
            pytest.skip("Need at least 2 checkboxes")

        # Click first checkbox
        browser.execute_script("arguments[0].click();", checkboxes[0])
        time.sleep(0.5)

        # Click second checkbox
        browser.execute_script("arguments[0].click();", checkboxes[1])
        time.sleep(0.5)

        # Navigate away and back - re-find buttons after each navigation
        next_btn = browser.find_element(By.ID, "next-btn")
        next_btn.click()
        time.sleep(2)

        # Re-find prev button after page update
        prev_btn = browser.find_element(By.ID, "prev-btn")
        prev_btn.click()
        time.sleep(2)

        # Both checkboxes should be checked
        checkboxes = browser.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        assert checkboxes[0].is_selected(), "First checkbox should be checked"
        assert checkboxes[1].is_selected(), "Second checkbox should be checked"


# ==================== Text Input Persistence Tests ====================

@pytest.mark.persistence
class TestTextInputPersistence:
    """Test that text input annotations persist correctly."""

    @pytest.fixture
    def server(self, base_port):
        """Start server with textbox config."""
        config_path = PROJECT_ROOT / "project-hub" / "simple_examples" / "configs" / "simple-text-box.yaml"
        server = IntegrationTestServer(str(config_path), port=base_port)
        success, error = server.start()
        if not success:
            pytest.skip(f"Server failed to start: {error}")
        yield server
        server.stop()

    def test_text_input_persists(self, server, browser, test_user):
        """Test that text input annotations persist when navigating."""
        register_user(browser, server, test_user)

        text_inputs = browser.find_elements(By.CSS_SELECTOR, "textarea, input[type='text']")
        if not text_inputs:
            pytest.skip("No text inputs found")

        # Enter text
        test_text = "This is a test annotation"
        text_input = text_inputs[0]
        text_input.clear()
        text_input.send_keys(test_text)
        time.sleep(2)  # Allow debounced save to complete

        # Navigate away and back - re-find buttons after each navigation
        next_btn = browser.find_element(By.ID, "next-btn")
        next_btn.click()
        time.sleep(2)

        # Re-find prev button after page update
        prev_btn = browser.find_element(By.ID, "prev-btn")
        prev_btn.click()
        time.sleep(2)

        # Verify text persists
        text_inputs = browser.find_elements(By.CSS_SELECTOR, "textarea, input[type='text']")
        assert text_inputs[0].get_attribute("value") == test_text, "Text should persist after navigation"


# ==================== Next/Previous Navigation Tests ====================

@pytest.mark.persistence
class TestNextPrevNavigation:
    """Test that annotations persist when using next/previous navigation."""

    @pytest.fixture
    def server(self, base_port):
        """Start server with checkbox config."""
        config_path = PROJECT_ROOT / "project-hub" / "simple_examples" / "configs" / "simple-check-box.yaml"
        server = IntegrationTestServer(str(config_path), port=base_port)
        success, error = server.start()
        if not success:
            pytest.skip(f"Server failed to start: {error}")
        yield server
        server.stop()

    def test_annotation_survives_next_prev_navigation(self, server, browser, test_user):
        """Test that annotation persists when using next/previous buttons."""
        register_user(browser, server, test_user)

        checkboxes = browser.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        if not checkboxes:
            pytest.skip("No checkboxes found")

        # Make annotation
        checkbox = checkboxes[0]
        checkbox_label = checkbox.get_attribute("label_name") or checkbox.get_attribute("value")
        browser.execute_script("arguments[0].click();", checkbox)
        time.sleep(0.5)

        # Navigate next then back - re-find buttons after each navigation
        next_btn = browser.find_element(By.ID, "next-btn")
        next_btn.click()
        time.sleep(2)

        # Re-find prev button after page update
        prev_btn = browser.find_element(By.ID, "prev-btn")
        prev_btn.click()
        time.sleep(2)

        # Verify annotation persists
        checkboxes = browser.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        for cb in checkboxes:
            label = cb.get_attribute("label_name") or cb.get_attribute("value")
            if label == checkbox_label:
                assert cb.is_selected(), "Annotation should survive next/prev navigation"
                return

        pytest.fail(f"Could not find checkbox {checkbox_label}")

    def test_multiple_annotations_persist(self, server, browser, test_user):
        """Test that multiple annotations persist across navigation."""
        register_user(browser, server, test_user)

        checkboxes = browser.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        if len(checkboxes) < 2:
            pytest.skip("Need at least 2 checkboxes")

        # Click first two checkboxes
        labels_checked = []
        for i in range(2):
            browser.execute_script("arguments[0].click();", checkboxes[i])
            labels_checked.append(
                checkboxes[i].get_attribute("label_name") or checkboxes[i].get_attribute("value")
            )
        time.sleep(0.5)

        # Navigate away and back - re-find buttons after each navigation
        next_btn = browser.find_element(By.ID, "next-btn")
        next_btn.click()
        time.sleep(2)

        # Re-find prev button after page update
        prev_btn = browser.find_element(By.ID, "prev-btn")
        prev_btn.click()
        time.sleep(2)

        # Verify both annotations persist
        checkboxes = browser.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        for cb in checkboxes:
            label = cb.get_attribute("label_name") or cb.get_attribute("value")
            if label in labels_checked:
                assert cb.is_selected(), f"Checkbox {label} should be checked"
