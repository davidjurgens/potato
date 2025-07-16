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
from selenium.webdriver.chrome.options import Options
from tests.helpers.flask_test_setup import FlaskTestServer


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

        # Start the Flask server using the proper test setup
        import os
        config_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "tests/configs/frontend-span-test.yaml")
        cls.server = FlaskTestServer(port=9008, debug=False, config_file=config_file)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"

        # Wait for server to be ready
        cls.server._wait_for_server_ready(timeout=10)

        # Set up Chrome options for headless testing
        chrome_options = Options()
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

        cls.chrome_options = chrome_options

    @classmethod
    def tearDownClass(cls):
        """Clean up the Flask server after all tests."""
        if hasattr(cls, 'server'):
            cls.server.stop_server()

    def setUp(self):
        """
        Set up for each test: create WebDriver and authenticate user.

        This method:
        1. Creates a new Chrome WebDriver instance
        2. Registers a unique test user
        3. Logs in the user
        4. Ensures the user is ready for testing

        Each test gets a fresh WebDriver and unique user account for isolation.
        """
        # Create a new WebDriver instance for each test
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

        This method:
        1. Navigates to the home page
        2. Switches to the registration tab
        3. Fills out the registration form
        4. Submits the form
        5. Waits for successful registration

        The user credentials are stored in self.test_user and self.test_password.
        """
        self.driver.get(f"{self.server.base_url}/")

        # Wait for page to load - should show login/register form
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-tab"))
        )

        # Switch to registration tab
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

        # Wait for redirect after registration
        time.sleep(2)

    def login_user(self):
        """
        Login the test user via the web interface.

        This method:
        1. Navigates to the home page (if not already there)
        2. Switches to the login tab
        3. Fills out the login form
        4. Submits the form
        5. Waits for successful login

        Uses the credentials from self.test_user and self.test_password.
        """
        # If not already logged in, login
        if "/annotate" not in self.driver.current_url:
            self.driver.get(f"{self.server.base_url}/")

            # Wait for page to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "login-tab"))
            )

            # Switch to login tab
            login_tab = self.driver.find_element(By.ID, "login-tab")
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

            # Wait for redirect after login
            time.sleep(2)

    def verify_authentication(self):
        """
        Verify that the user is properly authenticated.

        This method:
        1. Attempts to access the annotation page
        2. Verifies that the page loads successfully (not redirected to login)
        3. Checks that the user can see annotation content

        Raises an assertion error if authentication failed.
        """
        # Try to access the annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for the annotation page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )

        # Verify we're on the annotation page (not redirected to login)
        current_url = self.driver.current_url
        assert "/annotate" in current_url, f"Expected to be on annotation page, got: {current_url}"

        # Verify we can see annotation content
        instance_text = self.driver.find_element(By.ID, "instance-text")
        assert instance_text.is_displayed(), "Instance text should be visible"

        # Verify we have a valid session by checking for user-specific content
        # This could be checking for the username in the page or other user-specific elements
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