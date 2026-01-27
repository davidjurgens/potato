#!/usr/bin/env python3
"""
Simple Selenium test for login functionality in production mode.
"""

import os
import time
import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_config, create_test_data_file
from tests.helpers.port_manager import find_free_port


@pytest.fixture(scope="module")
def flask_server():
    """Start the Flask server in production mode using a dynamically created config."""
    # Create test directory
    test_dir = os.path.join(os.path.dirname(__file__), "..", "output", f"frontend_login_test_{int(time.time())}")
    os.makedirs(test_dir, exist_ok=True)

    # Create test data
    test_data = [
        {"id": "item_1", "text": "This is test item 1 for login testing."},
        {"id": "item_2", "text": "This is test item 2 for login testing."},
    ]
    data_file = create_test_data_file(test_dir, test_data)

    # Create annotation schemes
    annotation_schemes = [
        {
            "name": "sentiment",
            "annotation_type": "radio",
            "labels": ["positive", "negative", "neutral"],
            "description": "What is the sentiment?"
        }
    ]

    config_file = create_test_config(
        test_dir,
        annotation_schemes,
        data_files=[data_file],
        annotation_task_name="Frontend Login Test",
        require_password=True  # Enable login/register tabs
    )

    port = find_free_port()
    server = FlaskTestServer(port=port, debug=False, config_file=config_file)

    started = server.start_server()
    assert started, "Failed to start Flask server in production mode"

    yield server

    server.stop_server()

    # Cleanup
    import shutil
    try:
        shutil.rmtree(test_dir, ignore_errors=True)
    except Exception:
        pass


@pytest.fixture
def browser():
    """Create a headless Chrome browser for testing."""
    chrome_options = ChromeOptions()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")

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
