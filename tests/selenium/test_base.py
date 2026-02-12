#!/usr/bin/env python3
"""
Base class for Selenium tests with consistent authentication.

This module provides a base class that handles user registration and authentication
for all Selenium tests. Each test will create a unique user account to ensure
test isolation and avoid conflicts between concurrent test runs.

Usage:
    class TestMyFeature(BaseSeleniumTest):
        def test_something(self):
            # User is already registered and logged in
            self.driver.get(f"{self.server.base_url}/annotate")
            # ... test logic ...
"""

import time
import unittest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port


class BaseSeleniumTest(unittest.TestCase):
    """
    Base class for Selenium tests with automatic user authentication.

    This class provides:
    1. Automatic Flask server setup and teardown
    2. Unique user registration for each test
    3. Automatic login before each test
    4. Proper cleanup after each test

    All Selenium tests should inherit from this class to ensure consistent
    authentication and test isolation.
    """

    @classmethod
    def setUpClass(cls):
        """Set up the Flask server for all tests in this class."""
        # Import FlaskTestServer for proper session handling
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.test_utils import create_span_annotation_config

        # Create a secure test configuration using test utilities
        import os
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        test_dir = os.path.join(tests_dir, "output", "selenium_base_test")

        # Ensure the test directory exists
        os.makedirs(test_dir, exist_ok=True)

        # Create span annotation config for Selenium tests
        config_file, data_file = create_span_annotation_config(
            test_dir,
            annotation_task_name="Selenium Base Test",
            require_password=False
        )

        # Store for cleanup
        cls.test_dir = test_dir

        # Use dynamic port allocation to avoid conflicts with concurrent tests
        port = find_free_port(preferred_port=9008)
        cls.server = FlaskTestServer(port=port, debug=False, config_file=config_file)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"

        # Wait for server to be ready
        cls.server._wait_for_server_ready(timeout=10)

        # Set up Chrome options for headless testing
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")  # Use new headless mode
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-plugins")
        chrome_options.add_argument("--disable-images")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)

        # Set up Firefox options for headless testing
        firefox_options = FirefoxOptions()
        firefox_options.add_argument("--headless")
        firefox_options.add_argument("--width=1920")
        firefox_options.add_argument("--height=1080")
        firefox_options.set_preference("dom.webdriver.enabled", False)
        firefox_options.set_preference("useAutomationExtension", False)
        firefox_options.set_preference("general.useragent.override", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:120.0) Gecko/20100101 Firefox/120.0")

        cls.chrome_options = chrome_options
        cls.firefox_options = firefox_options

    @classmethod
    def tearDownClass(cls):
        """Clean up the Flask server after all tests."""
        if hasattr(cls, 'server'):
            cls.server.stop_server()

        # Clean up test directory
        if hasattr(cls, 'test_dir'):
            from tests.helpers.test_utils import cleanup_test_directory
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        """
        Set up for each test: create WebDriver and authenticate user.

        This method:
        1. Creates a new WebDriver instance (Chrome or Firefox based on self.browser_type)
        2. Registers a unique test user
        3. Logs in the user
        4. Ensures the user is ready for testing

        Each test gets a fresh WebDriver and unique user account for isolation.
        """
        # Create a new WebDriver instance for each test
        if hasattr(self, 'browser_type') and self.browser_type == 'firefox':
            self.driver = webdriver.Firefox(options=self.firefox_options)
        else:
            self.driver = webdriver.Chrome(options=self.chrome_options)

        # Generate unique test user credentials
        timestamp = int(time.time())
        self.test_user = f"test_user_{self.__class__.__name__}_{timestamp}"
        self.test_password = "test_password_123"

        # Register and login the user
        self.register_user()
        self.login_user()

        # Verify authentication worked
        self.verify_authentication()

    def tearDown(self):
        """Clean up after each test: close WebDriver."""
        if hasattr(self, 'driver'):
            self.driver.quit()

    def register_user(self):
        """
        Register a new test user via the web interface.

        This method handles two cases:
        1. require_password=True: Uses login-tab/register-tab to register with password
        2. require_password=False: Just enters username in the simple login form

        The user credentials are stored in self.test_user and self.test_password.
        """
        self.driver.get(f"{self.server.base_url}/")

        # Wait for page to load - look for login-email which is present in both modes
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )

        # Check if this is password mode (has login-tab) or simple mode (no tabs)
        try:
            login_tab = self.driver.find_element(By.ID, "login-tab")
            # Password mode - switch to registration tab
            register_tab = self.driver.find_element(By.ID, "register-tab")
            register_tab.click()

            # Wait for register form to be visible
            WebDriverWait(self.driver, 10).until(
                EC.visibility_of_element_located((By.ID, "register-content"))
            )

            # Fill registration form using correct field IDs
            username_field = self.driver.find_element(By.ID, "register-email")
            password_field = self.driver.find_element(By.ID, "register-pass")

            username_field.clear()
            password_field.clear()
            username_field.send_keys(self.test_user)
            password_field.send_keys(self.test_password)

            # Submit registration form
            register_form = self.driver.find_element(By.CSS_SELECTOR, "#register-content form")
            register_form.submit()
        except NoSuchElementException:
            # Simple mode (require_password=False) - just enter username
            username_field = self.driver.find_element(By.ID, "login-email")
            username_field.clear()
            username_field.send_keys(self.test_user)

            # Submit the login form
            submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit_btn.click()

        # Wait for redirect after registration/login
        time.sleep(0.5)

    def login_user(self):
        """
        Login the test user via the web interface.

        This method handles two cases:
        1. require_password=True: Uses login-tab with username and password
        2. require_password=False: Just enters username (user already registered)

        Uses the credentials from self.test_user and self.test_password.
        """
        # Check if already logged in by looking for annotation interface elements
        try:
            self.driver.find_element(By.ID, "task_layout")
            return  # Already logged in, no need to login again
        except:
            pass  # Not logged in, continue with login

        # If not already logged in, login
        if "/annotate" not in self.driver.current_url:
            self.driver.get(f"{self.server.base_url}/")

            # Wait for page to load - look for login-email
            try:
                WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((By.ID, "login-email"))
                )
            except:
                # If login-email not found, check if we're at annotation interface
                try:
                    self.driver.find_element(By.ID, "task_layout")
                    return  # Already logged in
                except:
                    raise Exception("Could not find login form or annotation interface")

            # Check if password mode (has login-tab) or simple mode
            try:
                login_tab = self.driver.find_element(By.ID, "login-tab")
                # Password mode - click login tab and fill with password
                login_tab.click()

                # Wait for login form to be visible
                WebDriverWait(self.driver, 10).until(
                    EC.visibility_of_element_located((By.ID, "login-content"))
                )

                # Fill login form using correct field IDs
                username_field = self.driver.find_element(By.ID, "login-email")
                password_field = self.driver.find_element(By.ID, "login-pass")

                username_field.clear()
                password_field.clear()
                username_field.send_keys(self.test_user)
                password_field.send_keys(self.test_password)

                # Submit login form
                login_form = self.driver.find_element(By.CSS_SELECTOR, "#login-content form")
                login_form.submit()
            except NoSuchElementException:
                # Simple mode - just enter username
                username_field = self.driver.find_element(By.ID, "login-email")
                username_field.clear()
                username_field.send_keys(self.test_user)

                # Submit the login form
                submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
                submit_btn.click()

            # Wait for redirect after login
            time.sleep(0.5)

    def verify_authentication(self):
        """
        Verify that the user is properly authenticated.

        This method:
        1. Checks that the user is on the annotation interface (not login page)
        2. Waits for JavaScript to load the content
        3. Verifies annotation content is visible

        Raises an assertion error if authentication failed.
        """
        # Check if we're still on the login page by looking for login-email
        # (which is present in both password and simple modes)
        try:
            login_email = self.driver.find_element(By.ID, "login-email")
            if login_email.is_displayed():
                # Still on login page - check if there's an error message
                try:
                    error = self.driver.find_element(By.CSS_SELECTOR, ".text-destructive, [style*='destructive']")
                    if error.is_displayed():
                        raise Exception(f"Login failed with error: {error.text}")
                except NoSuchElementException:
                    pass
                raise Exception("User is still on login page - authentication failed")
        except NoSuchElementException:
            pass  # login-email not found - good, we've moved past the login page

        # Wait for annotation interface to fully load
        # First check for the task layout structure
        try:
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "task_layout"))
            )
        except:
            raise Exception("Annotation interface did not load - task_layout not found")

        # Wait for JavaScript to initialize and show main content
        # Give extra time for async API calls to complete
        time.sleep(0.05)  # Allow time for API calls to complete

        try:
            WebDriverWait(self.driver, 15).until(
                EC.visibility_of_element_located((By.ID, "main-content"))
            )
        except:
            # Check if we got an error state
            try:
                error_state = self.driver.find_element(By.ID, "error-state")
                if error_state.is_displayed():
                    error_text = self.driver.find_element(By.ID, "error-message-text").text
                    raise Exception(f"Page showed error state: {error_text}")
            except Exception as e:
                if "error state" in str(e):
                    raise
            # Check if loading state is still showing
            try:
                loading_state = self.driver.find_element(By.ID, "loading-state")
                if loading_state.is_displayed():
                    raise Exception("Page is stuck in loading state")
            except:
                pass
            raise Exception("Main content did not become visible within timeout")

        # Verify annotation content is present
        page_source = self.driver.page_source
        assert "annotation" in page_source.lower(), "Page should contain annotation content"

    def get_session_cookies(self):
        """
        Get session cookies for API requests.

        Returns:
            dict: Session cookies that can be used with requests library
        """
        cookies = self.driver.get_cookies()
        return {cookie['name']: cookie['value'] for cookie in cookies}

    def wait_for_element(self, by, value, timeout=10):
        """
        Wait for an element to be present and return it.

        Args:
            by: Selenium locator strategy (e.g., By.ID, By.CLASS_NAME)
            value: Locator value
            timeout: Maximum time to wait in seconds

        Returns:
            WebElement: The found element

        Raises:
            TimeoutException: If element is not found within timeout
        """
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((by, value))
        )

    def wait_for_element_visible(self, by, value, timeout=10):
        """
        Wait for an element to be visible and return it.

        Args:
            by: Selenium locator strategy (e.g., By.ID, By.CLASS_NAME)
            value: Locator value
            timeout: Maximum time to wait in seconds

        Returns:
            WebElement: The found element

        Raises:
            TimeoutException: If element is not visible within timeout
        """
        return WebDriverWait(self.driver, timeout).until(
            EC.visibility_of_element_located((by, value))
        )

    def execute_script_safe(self, script, *args):
        """
        Execute JavaScript safely with error handling.

        Args:
            script: JavaScript code to execute
            *args: Arguments to pass to the script

        Returns:
            The result of the JavaScript execution

        Raises:
            Exception: If JavaScript execution fails
        """
        try:
            return self.driver.execute_script(script, *args)
        except Exception as e:
            print(f"JavaScript execution failed: {e}")
            print(f"Script: {script}")
            print(f"Args: {args}")
            raise

    def create_firefox_driver(self):
        """
        Create a Firefox WebDriver instance with appropriate options.

        Returns:
            webdriver.Firefox: Configured Firefox WebDriver instance
        """
        return webdriver.Firefox(options=self.firefox_options)

    def create_chrome_driver(self):
        """
        Create a Chrome WebDriver instance with appropriate options.

        Returns:
            webdriver.Chrome: Configured Chrome WebDriver instance
        """
        return webdriver.Chrome(options=self.chrome_options)