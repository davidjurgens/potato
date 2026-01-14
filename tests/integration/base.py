"""
Base class for integration tests with server startup validation.

This module provides infrastructure for integration tests that:
1. Start real Flask servers with actual configs
2. Capture and report server startup errors (the key gap in current tests)
3. Use real browsers via Selenium
4. Provide common utilities for user registration, login, and annotation
"""

import os
import sys
import time
import socket
import subprocess
import unittest
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, Tuple, List

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.common.exceptions import TimeoutException, WebDriverException


# Project root for imports
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class ServerStartupError(Exception):
    """Exception raised when server fails to start."""
    pass


class IntegrationTestServer:
    """
    Manages a Flask server instance for integration testing.

    Unlike FlaskTestServer, this class:
    1. Captures stdout/stderr to detect startup errors
    2. Reports helpful error messages when configs are invalid
    3. Validates server is actually responding before returning
    4. Runs from the appropriate working directory based on config location
    """

    def __init__(self, config_path: str, port: int = 9100, working_dir: str = None):
        self.config_path = Path(config_path).resolve()
        self.port = port
        self.process: Optional[subprocess.Popen] = None
        self.base_url = f"http://localhost:{port}"
        self.startup_output = ""
        self.startup_errors = ""

        # Determine working directory
        # For configs in project-hub/simple_examples/configs/, run from project-hub/simple_examples/
        # For configs elsewhere, use the config's parent directory
        if working_dir:
            self.working_dir = Path(working_dir).resolve()
        else:
            self.working_dir = self._determine_working_dir()

    def _determine_working_dir(self) -> Path:
        """
        Determine the appropriate working directory for the server.

        For configs in project-hub/simple_examples/configs/, the working dir
        should be project-hub/simple_examples/ (where the data folder is).

        For configs with task_dir: ., the working dir should be where the config
        can find its data files.
        """
        config_dir = self.config_path.parent

        # Check if this is an example config in project-hub structure
        if "project-hub" in str(config_dir):
            # Go up from configs/ to simple_examples/
            if config_dir.name == "configs":
                return config_dir.parent
            # Handle nested configs like all-phases-example/
            if config_dir.parent.name == "configs":
                return config_dir.parent.parent

        # Default: use the config's parent directory
        return config_dir

    def start(self, timeout: int = 30) -> Tuple[bool, str]:
        """
        Start the server and wait for it to be ready.

        Returns:
            Tuple of (success, error_message)
        """
        if not self.config_path.exists():
            return False, f"Config file not found: {self.config_path}"

        # Find an available port
        self.port = self._find_available_port(self.port)
        self.base_url = f"http://localhost:{self.port}"

        # Build the command - use relative path from working dir
        flask_server = PROJECT_ROOT / "potato" / "flask_server.py"

        # Calculate relative config path from working directory
        try:
            config_relative = self.config_path.relative_to(self.working_dir)
        except ValueError:
            # Config not under working dir, use absolute path
            config_relative = self.config_path

        cmd = [
            sys.executable,
            str(flask_server),
            "start",
            str(config_relative),
            "-p", str(self.port)
        ]

        # Start the server process
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"  # Ensure output is not buffered

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                cwd=str(self.working_dir)
            )
        except Exception as e:
            return False, f"Failed to start server process: {e}"

        # Wait for server to be ready or fail
        start_time = time.time()
        while time.time() - start_time < timeout:
            # Check if process has died
            if self.process.poll() is not None:
                # Process exited - get output
                stdout, stderr = self.process.communicate()
                self.startup_output = stdout.decode('utf-8', errors='replace')
                self.startup_errors = stderr.decode('utf-8', errors='replace')
                return False, self._format_startup_error()

            # Try to connect
            if self._is_server_ready():
                return True, ""

            time.sleep(0.5)

        # Timeout - server didn't become ready
        self.stop()
        return False, f"Server did not become ready within {timeout} seconds"

    def stop(self):
        """Stop the server process."""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None

    def _find_available_port(self, start_port: int) -> int:
        """Find an available port starting from start_port."""
        port = start_port
        while port < start_port + 100:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(('localhost', port)) != 0:
                    return port
            port += 1
        raise RuntimeError(f"No available ports found starting from {start_port}")

    def _is_server_ready(self) -> bool:
        """Check if server is accepting connections."""
        import urllib.request
        import urllib.error

        try:
            response = urllib.request.urlopen(self.base_url, timeout=2)
            return response.status == 200
        except (urllib.error.URLError, urllib.error.HTTPError, ConnectionRefusedError):
            return False
        except Exception:
            return False

    def _format_startup_error(self) -> str:
        """Format a helpful error message from server output."""
        lines = []
        lines.append(f"Server failed to start with config: {self.config_path.name}")

        # Look for Python exceptions in stderr
        if self.startup_errors:
            # Find the most relevant error
            error_lines = self.startup_errors.strip().split('\n')
            # Look for traceback
            for i, line in enumerate(error_lines):
                if 'Error' in line or 'Exception' in line or 'error' in line.lower():
                    lines.append(f"Error: {line.strip()}")
                    break
            else:
                # No clear error found, show last few lines
                lines.append("stderr output:")
                for line in error_lines[-5:]:
                    lines.append(f"  {line}")

        if self.startup_output:
            # Check stdout for errors too
            output_lines = self.startup_output.strip().split('\n')
            for line in output_lines:
                if 'error' in line.lower() or 'exception' in line.lower():
                    lines.append(f"Output: {line.strip()}")

        return '\n'.join(lines)


class BaseIntegrationTest(unittest.TestCase):
    """
    Base class for all integration tests.

    Provides:
    - Server lifecycle management with error capture
    - Browser setup (headless Chrome by default)
    - User registration and login helpers
    - Common annotation interaction utilities
    - Proper cleanup
    """

    # Override in subclasses to use a specific config
    config_path: Optional[str] = None

    # Port range for tests (each test class should use unique port)
    base_port: int = 9100

    @classmethod
    def setUpClass(cls):
        """Set up server and browser for all tests in this class."""
        cls.server = None
        cls.driver = None

        # Set up Chrome options
        cls.chrome_options = ChromeOptions()
        cls.chrome_options.add_argument("--headless=new")
        cls.chrome_options.add_argument("--no-sandbox")
        cls.chrome_options.add_argument("--disable-dev-shm-usage")
        cls.chrome_options.add_argument("--disable-gpu")
        cls.chrome_options.add_argument("--window-size=1920,1080")

        # Start server if config is specified
        if cls.config_path:
            cls._start_server_for_class()

    @classmethod
    def _start_server_for_class(cls):
        """Start server for the test class."""
        cls.server = IntegrationTestServer(cls.config_path, port=cls.base_port)
        success, error = cls.server.start()
        if not success:
            raise ServerStartupError(error)

    @classmethod
    def tearDownClass(cls):
        """Clean up server after all tests."""
        if cls.server:
            cls.server.stop()

    def setUp(self):
        """Set up browser for each test."""
        try:
            self.driver = webdriver.Chrome(options=self.chrome_options)
            self.driver.implicitly_wait(5)
        except WebDriverException as e:
            self.skipTest(f"Chrome WebDriver not available: {e}")

        # Generate unique test user
        timestamp = int(time.time() * 1000)
        self.test_user = f"test_user_{self.__class__.__name__}_{timestamp}"
        self.test_password = "test_password_123"

    def tearDown(self):
        """Clean up browser after each test."""
        if self.driver:
            # Capture screenshot on failure
            if hasattr(self, '_outcome') and self._outcome:
                for test, exc_info in self._outcome.errors:
                    if exc_info:
                        self._capture_failure_screenshot()
                        break
            self.driver.quit()

    def _capture_failure_screenshot(self):
        """Capture screenshot on test failure for debugging."""
        try:
            screenshot_dir = PROJECT_ROOT / "tests" / "output" / "screenshots"
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{self.__class__.__name__}_{self._testMethodName}_{int(time.time())}.png"
            self.driver.save_screenshot(str(screenshot_dir / filename))
        except Exception:
            pass  # Don't fail the test if screenshot fails

    # ==================== Navigation Helpers ====================

    def go_to_home(self):
        """Navigate to home page."""
        self.driver.get(self.server.base_url)
        self.wait_for_page_load()

    def wait_for_page_load(self, timeout: int = 10):
        """Wait for page to finish loading."""
        WebDriverWait(self.driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )

    def wait_for_element(self, by: By, value: str, timeout: int = 10):
        """Wait for element to be present."""
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((by, value))
        )

    def wait_for_element_visible(self, by: By, value: str, timeout: int = 10):
        """Wait for element to be visible."""
        return WebDriverWait(self.driver, timeout).until(
            EC.visibility_of_element_located((by, value))
        )

    def wait_for_element_clickable(self, by: By, value: str, timeout: int = 10):
        """Wait for element to be clickable."""
        return WebDriverWait(self.driver, timeout).until(
            EC.element_to_be_clickable((by, value))
        )

    # ==================== Authentication Helpers ====================

    def register_user(self, username: str = None, password: str = None):
        """Register a new user."""
        username = username or self.test_user
        password = password or self.test_password

        self.go_to_home()

        # Wait for and click register tab
        register_tab = self.wait_for_element_clickable(By.ID, "register-tab")
        register_tab.click()

        # Wait for register form
        self.wait_for_element_visible(By.ID, "register-content")

        # Fill form
        username_field = self.driver.find_element(By.ID, "register-email")
        password_field = self.driver.find_element(By.ID, "register-pass")

        username_field.clear()
        username_field.send_keys(username)
        password_field.clear()
        password_field.send_keys(password)

        # Submit
        form = self.driver.find_element(By.CSS_SELECTOR, "#register-content form")
        form.submit()

        # Wait for redirect
        time.sleep(1)
        self.wait_for_page_load()

    def login_user(self, username: str = None, password: str = None):
        """Login an existing user."""
        username = username or self.test_user
        password = password or self.test_password

        self.go_to_home()

        # Check if already logged in
        try:
            self.driver.find_element(By.ID, "main-content")
            return  # Already logged in
        except:
            pass

        # Wait for and click login tab
        login_tab = self.wait_for_element_clickable(By.ID, "login-tab")
        login_tab.click()

        # Wait for login form
        self.wait_for_element_visible(By.ID, "login-content")

        # Fill form
        username_field = self.driver.find_element(By.ID, "login-email")
        password_field = self.driver.find_element(By.ID, "login-pass")

        username_field.clear()
        username_field.send_keys(username)
        password_field.clear()
        password_field.send_keys(password)

        # Submit
        form = self.driver.find_element(By.CSS_SELECTOR, "#login-content form")
        form.submit()

        # Wait for redirect
        time.sleep(1)
        self.wait_for_page_load()

    def register_and_login(self):
        """Register a new user and ensure they're logged in."""
        self.register_user()
        # Registration should auto-login, but verify
        try:
            self.wait_for_element(By.ID, "main-content", timeout=5)
        except TimeoutException:
            self.login_user()

    # ==================== Annotation Helpers ====================

    def wait_for_annotation_page(self, timeout: int = 15):
        """Wait for annotation page to be ready."""
        self.wait_for_element(By.ID, "main-content", timeout=timeout)
        self.wait_for_element(By.ID, "annotation-forms", timeout=timeout)
        time.sleep(0.5)  # Allow JS to initialize

    def get_current_instance_id(self) -> str:
        """Get the current instance ID."""
        element = self.driver.find_element(By.ID, "instance_id")
        return element.get_attribute("value")

    def navigate_next(self):
        """Navigate to next instance using keyboard."""
        body = self.driver.find_element(By.TAG_NAME, "body")
        body.send_keys(Keys.ARROW_RIGHT)
        time.sleep(1)
        self.wait_for_page_load()

    def navigate_prev(self):
        """Navigate to previous instance using keyboard."""
        body = self.driver.find_element(By.TAG_NAME, "body")
        body.send_keys(Keys.ARROW_LEFT)
        time.sleep(1)
        self.wait_for_page_load()

    def click_checkbox(self, value: str):
        """Click a checkbox with the given value."""
        checkbox = self.driver.find_element(
            By.CSS_SELECTOR, f"input[type='checkbox'][value='{value}']"
        )
        self.driver.execute_script("arguments[0].scrollIntoView(true);", checkbox)
        time.sleep(0.1)
        checkbox.click()
        time.sleep(0.3)

    def click_radio(self, value: str):
        """Click a radio button with the given value."""
        radio = self.driver.find_element(
            By.CSS_SELECTOR, f"input[type='radio'][value='{value}']"
        )
        self.driver.execute_script("arguments[0].scrollIntoView(true);", radio)
        time.sleep(0.1)
        radio.click()
        time.sleep(0.3)

    def get_checkbox_states(self) -> dict:
        """Get checked state of all checkboxes."""
        checkboxes = self.driver.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        states = {}
        for cb in checkboxes:
            label = cb.get_attribute("label_name") or cb.get_attribute("value")
            states[label] = cb.is_selected()
        return states

    def get_selected_radio(self) -> Optional[str]:
        """Get the value of the selected radio button."""
        radios = self.driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
        for radio in radios:
            if radio.is_selected():
                return radio.get_attribute("label_name") or radio.get_attribute("value")
        return None

    def type_in_text_field(self, name: str, text: str):
        """Type text into a text field."""
        field = self.driver.find_element(By.CSS_SELECTOR, f"input[name*='{name}'], textarea[name*='{name}']")
        field.clear()
        field.send_keys(text)

    def get_text_field_value(self, name: str) -> str:
        """Get value from a text field."""
        field = self.driver.find_element(By.CSS_SELECTOR, f"input[name*='{name}'], textarea[name*='{name}']")
        return field.get_attribute("value")

    # ==================== Assertion Helpers ====================

    def assert_on_annotation_page(self):
        """Assert that we're on the annotation page."""
        self.assertTrue(
            self.driver.find_elements(By.ID, "main-content"),
            "Should be on annotation page (main-content present)"
        )

    def assert_on_login_page(self):
        """Assert that we're on the login page."""
        self.assertTrue(
            self.driver.find_elements(By.ID, "login-tab"),
            "Should be on login page (login-tab present)"
        )

    def assert_no_js_errors(self):
        """Assert no JavaScript errors in console."""
        logs = self.driver.get_log('browser')
        errors = [log for log in logs if log['level'] == 'SEVERE']
        self.assertEqual(len(errors), 0, f"JavaScript errors found: {errors}")


@contextmanager
def integration_server(config_path: str, port: int = 9100):
    """
    Context manager for running an integration test server.

    Usage:
        with integration_server("path/to/config.yaml") as server:
            # server.base_url is available
            response = requests.get(server.base_url)
    """
    server = IntegrationTestServer(config_path, port)
    success, error = server.start()
    if not success:
        raise ServerStartupError(error)
    try:
        yield server
    finally:
        server.stop()
