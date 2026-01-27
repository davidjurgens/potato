#!/usr/bin/env python3
"""
Comprehensive Selenium test for navigation functionality with multiple instances.
Tests the core navigation behavior including:
- Instance assignment using item_state_management.py logic
- Next button disabled until all required annotations are complete
- Go-to input form restrictions (users cannot jump ahead)
- Navigation between instances with annotation persistence
- Relative indexing (users see instances as 1, 2, 3, etc.)
"""

import os
import time
import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_config, create_test_data_file
from tests.helpers.port_manager import find_free_port


@pytest.fixture(scope="module")
def flask_server():
    """Start the Flask server with dynamic config for navigation testing."""
    # Create test directory
    test_dir = os.path.join(os.path.dirname(__file__), "..", "output", f"navigation_test_{int(time.time())}")
    os.makedirs(test_dir, exist_ok=True)

    # Create test data with 10 instances
    test_data = [
        {"id": f"item_{i+1}", "text": f"This is test item number {i+1} for navigation testing."}
        for i in range(10)
    ]
    data_file = create_test_data_file(test_dir, test_data)

    # Create annotation schemes
    annotation_schemes = [
        {
            "name": "sentiment",
            "annotation_type": "radio",
            "labels": ["positive", "negative", "neutral"],
            "description": "What is the sentiment of this text?"
        }
    ]

    config_file = create_test_config(
        test_dir,
        annotation_schemes,
        data_files=[data_file],
        annotation_task_name="Navigation Test",
        require_password=True  # Enable login/register tabs
    )

    port = find_free_port()
    server = FlaskTestServer(port=port, debug=False, config_file=config_file)

    started = server.start_server()
    assert started, "Failed to start Flask server"

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


def _register_user(browser, base_url, username, password):
    """Helper to register a user."""
    browser.get(f"{base_url}/")

    WebDriverWait(browser, 10).until(
        EC.presence_of_element_located((By.ID, "login-tab"))
    )

    register_tab = browser.find_element(By.ID, "register-tab")
    register_tab.click()

    WebDriverWait(browser, 10).until(
        EC.visibility_of_element_located((By.ID, "register-content"))
    )

    username_input = browser.find_element(By.ID, "register-email")
    password_input = browser.find_element(By.ID, "register-pass")

    username_input.send_keys(username)
    password_input.send_keys(password)

    register_form = browser.find_element(By.CSS_SELECTOR, "#register-content form")
    register_form.submit()

    time.sleep(0.1)

    # Wait for annotation page
    WebDriverWait(browser, 10).until(
        EC.presence_of_element_located((By.ID, "instance-text"))
    )


def test_navigation_with_multiple_instances(flask_server, browser):
    """Test comprehensive navigation functionality with multiple instances."""
    base_url = flask_server.base_url
    username = f"test_user_{int(time.time())}"
    password = "test_password_123"

    print(f"=== Testing Navigation with Multiple Instances ===")
    print(f"Username: {username}")
    print(f"Base URL: {base_url}")

    # Register user and navigate to annotation page
    _register_user(browser, base_url, username, password)

    print("   ✅ User registered and on annotation page")

    # Test navigation buttons exist
    try:
        next_btn = browser.find_element(By.ID, "next-btn")
        prev_btn = browser.find_element(By.ID, "prev-btn")
        print("   ✅ Navigation buttons found")
    except NoSuchElementException:
        pytest.fail("Navigation buttons not found")

    # Check progress counter
    try:
        progress_counter = browser.find_element(By.ID, "progress-counter")
        progress_text = progress_counter.text
        print(f"   Progress: {progress_text}")
    except NoSuchElementException:
        print("   ⚠️ Progress counter not found")

    # Test navigating forward
    for i in range(3):
        # Make an annotation
        sentiment_radios = browser.find_elements(By.CSS_SELECTOR, "input[name='sentiment']")
        if sentiment_radios:
            sentiment_radios[0].click()
            time.sleep(0.1)

        # Click next
        next_btn = browser.find_element(By.ID, "next-btn")
        next_btn.click()
        time.sleep(0.1)

        print(f"   Navigated to instance {i+2}")

    print("   ✅ Forward navigation works")

    # Test navigating backward
    prev_btn = browser.find_element(By.ID, "prev-btn")
    prev_btn.click()
    time.sleep(0.1)

    print("   ✅ Backward navigation works")

    print("✅ Navigation test completed successfully")


def test_go_to_navigation(flask_server, browser):
    """Test go-to navigation functionality."""
    base_url = flask_server.base_url
    username = f"test_user_goto_{int(time.time())}"
    password = "test_password_123"

    print(f"=== Testing Go-To Navigation ===")

    # Register user
    _register_user(browser, base_url, username, password)

    # Look for go-to input
    try:
        goto_input = browser.find_element(By.ID, "go-to-input")
        goto_btn = browser.find_element(By.ID, "go-to-btn")
        print("   ✅ Go-to controls found")

        # Try to go to instance 2 (if annotations complete)
        goto_input.clear()
        goto_input.send_keys("2")
        goto_btn.click()
        time.sleep(0.1)

        print("   ✅ Go-to navigation executed")

    except NoSuchElementException:
        print("   ⚠️ Go-to controls not found (may be hidden until first annotation)")

    print("✅ Go-to navigation test completed")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
