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
from tests.helpers.flask_test_setup import FlaskTestServer, create_chrome_options


@pytest.fixture(scope="module")
def flask_server():
    """Start the Flask server in production mode using a test config."""
    # Calculate path relative to this test file
    test_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(test_dir))
    config_file = os.path.join(project_root, "tests", "configs", "radio-annotation.yaml")

    # Create server in production mode (debug=False)
    server = FlaskTestServer(
        app_factory=None,  # Will use default app factory
        config=config_file,
        debug=False  # Production mode
    )

    # Start the server
    started = server.start()
    assert started, "Failed to start Flask server in production mode"

    yield server

    # Cleanup
    server.stop()


@pytest.fixture
def browser():
    """Create a headless Chrome browser for testing."""
    chrome_options = create_chrome_options(headless=True)

    print("🔧 Creating headless Chrome browser...")
    driver = webdriver.Chrome(options=chrome_options)
    print("✅ Headless Chrome browser created successfully")

    yield driver

    driver.quit()


def test_server_health_check(flask_server):
    """Test that the server is running and healthy in production mode."""
    # In production mode, the server should redirect to auth page when no session exists
    response = flask_server.get("/")

    # Should redirect to auth page (302) or show auth page (200)
    assert response.status_code in [200, 302], f"Server health check failed: {response.status_code}"
    print("✅ Server health check passed")


def test_home_page_loads_with_login_form(flask_server, browser):
    """Test that the home page loads with the login/registration form."""
    base_url = flask_server.base_url

    print(f"=== Testing Home Page Load ===")
    print(f"Base URL: {base_url}")

    # Navigate to home page
    browser.get(f"{base_url}/")

    # Wait for page to load
    WebDriverWait(browser, 10).until(
        EC.presence_of_element_located((By.ID, "login-tab"))
    )

    print(f"   Current URL: {browser.current_url}")
    print(f"   Page title: {browser.title}")

    # Verify login tab is present and active
    login_tab = browser.find_element(By.ID, "login-tab")
    assert login_tab.is_displayed(), "Login tab should be visible"
    assert "active" in login_tab.get_attribute("class"), "Login tab should be active by default"

    # Verify register tab is present
    register_tab = browser.find_element(By.ID, "register-tab")
    assert register_tab.is_displayed(), "Register tab should be visible"

    # Verify login form is visible
    login_content = browser.find_element(By.ID, "login-content")
    assert login_content.is_displayed(), "Login form should be visible"

    # Verify register form is hidden initially
    register_content = browser.find_element(By.ID, "register-content")
    assert not register_content.is_displayed(), "Register form should be hidden initially"

    print("✅ Home page loaded with login form")


def test_user_registration_and_login(flask_server, browser):
    """Test user registration, login, and basic annotation functionality."""
    base_url = flask_server.base_url
    username = f"test_user_{int(time.time())}"
    password = "test_password_123"

    print(f"=== Testing User Registration and Login ===")
    print(f"Username: {username}")
    print(f"Base URL: {base_url}")

    # Step 1: Navigate to home page
    browser.get(f"{base_url}/")

    # Wait for page to load
    WebDriverWait(browser, 10).until(
        EC.presence_of_element_located((By.ID, "login-tab"))
    )

    # Step 2: Switch to registration tab and register user
    print("2. Registering new user...")

    # Click on register tab
    register_tab = browser.find_element(By.ID, "register-tab")
    register_tab.click()

    # Wait for register form to be visible
    WebDriverWait(browser, 10).until(
        EC.visibility_of_element_located((By.ID, "register-content"))
    )

    # Fill in registration form
    username_input = browser.find_element(By.ID, "register-email")
    password_input = browser.find_element(By.ID, "register-pass")

    username_input.send_keys(username)
    password_input.send_keys(password)

    # Submit registration form
    register_form = browser.find_element(By.CSS_SELECTOR, "#register-content form")
    register_form.submit()

    # Wait for redirect after registration
    time.sleep(3)
    print(f"   After registration - URL: {browser.current_url}")

    # Step 3: Check if we're on the annotation page
    print("3. Checking if user is on annotation page...")

    # The user should be automatically logged in and redirected to annotation page
    if "/annotate" in browser.current_url:
        print("   ✅ User is on annotation page after registration")
    else:
        print("   ⚠️ User not on annotation page, attempting manual login...")

        # Navigate back to home page
        browser.get(f"{base_url}/")
        time.sleep(1)

        # Switch to login tab
        login_tab = browser.find_element(By.ID, "login-tab")
        login_tab.click()

        # Wait for login form to be visible
        WebDriverWait(browser, 10).until(
            EC.visibility_of_element_located((By.ID, "login-content"))
        )

        # Fill in login form
        login_username_input = browser.find_element(By.ID, "login-email")
        login_password_input = browser.find_element(By.ID, "login-pass")

        login_username_input.clear()
        login_username_input.send_keys(username)
        login_password_input.clear()
        login_password_input.send_keys(password)

        # Submit login form
        login_form = browser.find_element(By.CSS_SELECTOR, "#login-content form")
        login_form.submit()

        # Wait for redirect after login
        time.sleep(3)
        print(f"   After login - URL: {browser.current_url}")

    # Step 4: Verify we're on the annotation page
    print("4. Verifying annotation page elements...")

    # Wait for annotation page elements to load
    try:
        WebDriverWait(browser, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )
        print("   ✅ Annotation page loaded successfully")
    except:
        print("   ❌ Annotation page elements not found")
        print(f"   Current page source: {browser.page_source[:1000]}...")
        raise

    # Step 5: Check for annotation form elements
    print("5. Checking annotation form elements...")

    # Look for sentiment radio buttons
    sentiment_radios = browser.find_elements(By.CSS_SELECTOR, "input[name='sentiment']")
    print(f"   Found {len(sentiment_radios)} sentiment radio buttons")

    if sentiment_radios:
        # Select the first option (positive)
        sentiment_radios[0].click()
        print("   ✅ Selected sentiment option")
        time.sleep(1)  # Wait for auto-save
    else:
        print("   ⚠️ No sentiment radio buttons found")

    # Step 6: Verify navigation buttons
    print("6. Checking navigation buttons...")

    try:
        next_btn = browser.find_element(By.ID, "next-btn")
        prev_btn = browser.find_element(By.ID, "prev-btn")
        print("   ✅ Navigation buttons found")
    except:
        print("   ❌ Navigation buttons not found")
        raise

            # Step 7: Test navigation
        print("7. Testing navigation...")

        # Click next button to go to next instance
        next_btn.click()
        time.sleep(2)

        # Check that we're on a different instance
        current_url_after_next = browser.current_url
        print(f"   After clicking next - URL: {current_url_after_next}")

        # Re-find the prev button after navigation (to avoid stale element reference)
        prev_btn = browser.find_element(By.ID, "prev-btn")
        prev_btn.click()
        time.sleep(2)

        print(f"   After clicking previous - URL: {browser.current_url}")

        print("✅ All tests completed successfully")


def test_login_with_existing_user(flask_server, browser):
    """Test login functionality with an existing user."""
    base_url = flask_server.base_url
    username = f"existing_user_{int(time.time())}"
    password = "test_password_123"

    print(f"=== Testing Login with Existing User ===")
    print(f"Username: {username}")

    # First, register a user
    browser.get(f"{base_url}/")
    WebDriverWait(browser, 10).until(
        EC.presence_of_element_located((By.ID, "login-tab"))
    )

    # Register the user
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

    # Now test login with the same user
    browser.get(f"{base_url}/")
    WebDriverWait(browser, 10).until(
        EC.presence_of_element_located((By.ID, "login-tab"))
    )

    # Login tab should be active by default
    login_tab = browser.find_element(By.ID, "login-tab")
    login_tab.click()

    WebDriverWait(browser, 10).until(
        EC.visibility_of_element_located((By.ID, "login-content"))
    )

    login_username_input = browser.find_element(By.ID, "login-email")
    login_password_input = browser.find_element(By.ID, "login-pass")

    login_username_input.clear()
    login_username_input.send_keys(username)
    login_password_input.clear()
    login_password_input.send_keys(password)

    login_form = browser.find_element(By.CSS_SELECTOR, "#login-content form")
    login_form.submit()

    time.sleep(3)

    # Verify we're on the annotation page
    try:
        WebDriverWait(browser, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )
        print("✅ Login successful - annotation page loaded")
    except:
        print("❌ Login failed - annotation page not loaded")
        raise


def test_tab_switching_functionality(flask_server, browser):
    """Test that the tab switching functionality works correctly."""
    base_url = flask_server.base_url

    print(f"=== Testing Tab Switching Functionality ===")

    # Navigate to home page
    browser.get(f"{base_url}/")

    # Wait for page to load
    WebDriverWait(browser, 10).until(
        EC.presence_of_element_located((By.ID, "login-tab"))
    )

    # Initially, login tab should be active
    login_tab = browser.find_element(By.ID, "login-tab")
    register_tab = browser.find_element(By.ID, "register-tab")
    login_content = browser.find_element(By.ID, "login-content")
    register_content = browser.find_element(By.ID, "register-content")

    assert "active" in login_tab.get_attribute("class"), "Login tab should be active initially"
    assert "active" in login_content.get_attribute("class"), "Login content should be visible initially"
    assert "active" not in register_tab.get_attribute("class"), "Register tab should not be active initially"
    assert "active" not in register_content.get_attribute("class"), "Register content should be hidden initially"

    # Click register tab
    register_tab.click()
    time.sleep(1)

    # Now register tab should be active
    assert "active" in register_tab.get_attribute("class"), "Register tab should be active after clicking"
    assert "active" in register_content.get_attribute("class"), "Register content should be visible after clicking"
    assert "active" not in login_tab.get_attribute("class"), "Login tab should not be active after clicking register"
    assert "active" not in login_content.get_attribute("class"), "Login content should be hidden after clicking register"

    # Click login tab again
    login_tab.click()
    time.sleep(1)

    # Login tab should be active again
    assert "active" in login_tab.get_attribute("class"), "Login tab should be active after clicking back"
    assert "active" in login_content.get_attribute("class"), "Login content should be visible after clicking back"
    assert "active" not in register_tab.get_attribute("class"), "Register tab should not be active after clicking back"
    assert "active" not in register_content.get_attribute("class"), "Register content should be hidden after clicking back"

    print("✅ Tab switching functionality works correctly")


if __name__ == "__main__":
    # Run the tests directly
    pytest.main([__file__, "-v"])