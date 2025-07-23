#!/usr/bin/env python3
"""
Simple Selenium test for annotation functionality in production mode.
"""

import os
import time
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


def test_annotation_ui_loads_after_login(flask_server, browser):
    """Test that the annotation UI loads correctly after user login."""
    base_url = flask_server.base_url
    username = f"test_user_{int(time.time())}"
    password = "test_password_123"

    print(f"=== Testing Annotation UI Load After Login ===")
    print(f"Username: {username}")
    print(f"Base URL: {base_url}")

    # Step 1: Navigate to home page and register user
    browser.get(f"{base_url}/")

    WebDriverWait(browser, 10).until(
        EC.presence_of_element_located((By.ID, "login-tab"))
    )

    # Register a new user
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

    # Wait for redirect after registration
    time.sleep(3)

    # Step 2: Verify we're on the annotation page
    print("2. Verifying annotation page elements...")

    try:
        WebDriverWait(browser, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )
        print("   ✅ Annotation page loaded successfully")
    except:
        print("   ❌ Annotation page elements not found")
        print(f"   Current URL: {browser.current_url}")
        print(f"   Page source: {browser.page_source[:1000]}...")
        raise

    # Step 3: Check for annotation form elements
    print("3. Checking annotation form elements...")

    # Look for sentiment radio buttons
    sentiment_radios = browser.find_elements(By.CSS_SELECTOR, "input[name='sentiment']")
    print(f"   Found {len(sentiment_radios)} sentiment radio buttons")

    if sentiment_radios:
        print("   ✅ Sentiment radio buttons found")
    else:
        print("   ⚠️ No sentiment radio buttons found")

    # Check for navigation buttons
    try:
        next_btn = browser.find_element(By.ID, "next-btn")
        prev_btn = browser.find_element(By.ID, "prev-btn")
        print("   ✅ Navigation buttons found")
    except:
        print("   ❌ Navigation buttons not found")
        raise

    # Check for progress counter
    try:
        progress_counter = browser.find_element(By.ID, "progress-counter")
        print("   ✅ Progress counter found")
    except:
        print("   ⚠️ Progress counter not found")

    print("✅ Annotation UI loaded successfully after login")


def test_annotation_form_interaction(flask_server, browser):
    """Test basic annotation form interaction."""
    base_url = flask_server.base_url
    username = f"test_user_{int(time.time())}"
    password = "test_password_123"

    print(f"=== Testing Annotation Form Interaction ===")
    print(f"Username: {username}")

    # Register and login user
    browser.get(f"{base_url}/")

    WebDriverWait(browser, 10).until(
        EC.presence_of_element_located((By.ID, "login-tab"))
    )

    # Register user
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

    time.sleep(3)

    # Wait for annotation page
    WebDriverWait(browser, 10).until(
        EC.presence_of_element_located((By.ID, "instance-text"))
    )

    # Test annotation form interaction
    sentiment_radios = browser.find_elements(By.CSS_SELECTOR, "input[name='sentiment']")

    if sentiment_radios:
        # Select the first option
        sentiment_radios[0].click()
        print("   ✅ Selected first sentiment option")
        time.sleep(1)

        # Verify it's selected
        assert sentiment_radios[0].is_selected(), "First sentiment option should be selected"
        print("   ✅ First sentiment option is selected")
    else:
        print("   ⚠️ No sentiment radio buttons found for interaction test")

    # Test navigation
    next_btn = browser.find_element(By.ID, "next-btn")
    next_btn.click()
    time.sleep(2)

    print(f"   After clicking next - URL: {browser.current_url}")

    print("✅ Annotation form interaction test completed")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])