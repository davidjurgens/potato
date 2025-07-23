#!/usr/bin/env python3
"""
Simple Selenium test for login functionality in production mode.
"""

import os
import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from tests.helpers.flask_test_setup import FlaskTestServer, create_chrome_options


@pytest.fixture(scope="module")
def flask_server():
    """Start the Flask server in production mode using a test config."""
    # Calculate path relative to this test file
    test_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(test_dir))
    config_file = os.path.join(project_root, "tests", "configs", "radio-annotation.yaml")

    server = FlaskTestServer(
        app_factory=None,
        config=config_file,
        debug=False  # Production mode
    )

    started = server.start()
    assert started, "Failed to start Flask server in production mode"

    yield server

    server.stop()


@pytest.fixture
def browser():
    """Create a headless Chrome browser for testing."""
    chrome_options = create_chrome_options(headless=True)
    driver = webdriver.Chrome(options=chrome_options)

    yield driver

    driver.quit()


def test_login_ui_loads(flask_server, browser):
    """Test that the login UI loads correctly in production mode."""
    base_url = flask_server.base_url

    print(f"=== Testing Login UI Load ===")
    print(f"Base URL: {base_url}")

    # Navigate to home page
    browser.get(f"{base_url}/")

    # Wait for page to load
    WebDriverWait(browser, 10).until(
        EC.presence_of_element_located((By.ID, "login-tab"))
    )

    print(f"   Current URL: {browser.current_url}")
    print(f"   Page title: {browser.title}")

    # Verify login form elements are present
    login_tab = browser.find_element(By.ID, "login-tab")
    login_email = browser.find_element(By.ID, "login-email")
    login_pass = browser.find_element(By.ID, "login-pass")

    assert login_tab.is_displayed(), "Login tab should be visible"
    assert login_email.is_displayed(), "Login email field should be visible"
    assert login_pass.is_displayed(), "Login password field should be visible"

    # Verify register tab is also present
    register_tab = browser.find_element(By.ID, "register-tab")
    assert register_tab.is_displayed(), "Register tab should be visible"

    print("✅ Login UI loaded successfully")


def test_register_ui_loads(flask_server, browser):
    """Test that the register UI loads correctly when switching tabs."""
    base_url = flask_server.base_url

    print(f"=== Testing Register UI Load ===")

    # Navigate to home page
    browser.get(f"{base_url}/")

    # Wait for page to load
    WebDriverWait(browser, 10).until(
        EC.presence_of_element_located((By.ID, "login-tab"))
    )

    # Click on register tab
    register_tab = browser.find_element(By.ID, "register-tab")
    register_tab.click()

    # Wait for register form to be visible
    WebDriverWait(browser, 10).until(
        EC.visibility_of_element_located((By.ID, "register-content"))
    )

    # Verify register form elements are present
    register_email = browser.find_element(By.ID, "register-email")
    register_pass = browser.find_element(By.ID, "register-pass")

    assert register_email.is_displayed(), "Register email field should be visible"
    assert register_pass.is_displayed(), "Register password field should be visible"

    print("✅ Register UI loaded successfully")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])