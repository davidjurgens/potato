#!/usr/bin/env python3
"""
Selenium tests for the annotation platform in production mode.

This test demonstrates the correct setup for running Selenium tests with a Flask server
in production mode (debug=False) using the proper home template and element selectors.
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
    """Start the Flask server in production mode using dynamic config."""
    # Create test directory
    test_dir = os.path.join(os.path.dirname(__file__), "..", "output", f"selenium_production_test_{int(time.time())}")
    os.makedirs(test_dir, exist_ok=True)

    # Create test data
    test_data = [
        {"id": "item_1", "text": "This is test item 1 for production mode testing."},
        {"id": "item_2", "text": "This is test item 2 for production mode testing."},
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
        annotation_task_name="Selenium Production Mode Test",
        require_password=True
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

    print("🔧 Creating headless Chrome browser...")
    driver = webdriver.Chrome(options=chrome_options)
    print("✅ Headless Chrome browser created successfully")

    yield driver

    driver.quit()


def test_server_health_check(flask_server):
    """Test that the server is running and healthy in production mode."""
    response = flask_server.get("/")
    assert response.status_code in [200, 302], f"Server health check failed: {response.status_code}"
    print("✅ Server health check passed in production mode")


def test_login_page_elements(flask_server, browser):
    """Test that the login page has all required elements."""
    base_url = flask_server.base_url

    print(f"=== Testing Login Page Elements ===")
    print(f"Base URL: {base_url}")

    browser.get(f"{base_url}/")

    # Wait for login page to load
    WebDriverWait(browser, 10).until(
        EC.presence_of_element_located((By.ID, "login-tab"))
    )

    # Verify all login elements are present
    login_tab = browser.find_element(By.ID, "login-tab")
    register_tab = browser.find_element(By.ID, "register-tab")
    login_email = browser.find_element(By.ID, "login-email")
    login_pass = browser.find_element(By.ID, "login-pass")

    assert login_tab.is_displayed(), "Login tab should be visible"
    assert register_tab.is_displayed(), "Register tab should be visible"
    assert login_email.is_displayed(), "Login email field should be visible"
    assert login_pass.is_displayed(), "Login password field should be visible"

    print("✅ All login page elements present")


def test_user_registration_flow(flask_server, browser):
    """Test user registration flow in production mode."""
    base_url = flask_server.base_url
    username = f"test_user_{int(time.time())}"
    password = "test_password_123"

    print(f"=== Testing User Registration Flow ===")
    print(f"Username: {username}")

    browser.get(f"{base_url}/")

    # Wait for page and switch to register tab
    WebDriverWait(browser, 10).until(
        EC.presence_of_element_located((By.ID, "login-tab"))
    )

    register_tab = browser.find_element(By.ID, "register-tab")
    register_tab.click()

    WebDriverWait(browser, 10).until(
        EC.visibility_of_element_located((By.ID, "register-content"))
    )

    # Fill and submit registration form
    username_input = browser.find_element(By.ID, "register-email")
    password_input = browser.find_element(By.ID, "register-pass")

    username_input.send_keys(username)
    password_input.send_keys(password)

    register_form = browser.find_element(By.CSS_SELECTOR, "#register-content form")
    register_form.submit()

    time.sleep(0.1)

    # Verify redirect to annotation page
    WebDriverWait(browser, 10).until(
        EC.presence_of_element_located((By.ID, "instance-text"))
    )

    print("✅ User registration flow completed successfully")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
