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
import uuid
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from tests.helpers.flask_test_setup import FlaskTestServer, create_chrome_options


@pytest.fixture(scope="module")
def test_data_with_10_instances():
    """Test data with 10 instances for comprehensive navigation testing."""
    # This fixture is kept for compatibility but the actual data comes from the file
    return 10  # Number of instances


@pytest.fixture(scope="module")
def flask_server():
    """Start the Flask server in production mode using a test config."""
    # Calculate path relative to this test file
    test_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(test_dir))
    config_file = os.path.join(project_root, "tests", "configs", "radio-annotation.yaml")

    # Create a modified config that uses the navigation test data
    import yaml
    with open(config_file, 'r') as f:
        config_data = yaml.safe_load(f)

    # Update the data file path to use the navigation test data
    config_data['data_files'] = [os.path.join(project_root, "data", "navigation_test_data.json")]

    # Write the modified config to a temporary file
    import tempfile
    fd, temp_config_path = tempfile.mkstemp(suffix='.yaml', prefix='navigation_test_')
    with os.fdopen(fd, 'w') as f:
        yaml.dump(config_data, f)

    server = FlaskTestServer(
        app_factory=None,
        config=temp_config_path,
        debug=False  # Production mode
    )

    started = server.start()
    assert started, "Failed to start Flask server in production mode"

    yield server

    # Cleanup
    server.stop()
    os.remove(temp_config_path)


@pytest.fixture
def browser():
    """Create a headless Chrome browser for testing."""
    chrome_options = create_chrome_options(headless=True)
    driver = webdriver.Chrome(options=chrome_options)

    yield driver

    driver.quit()


def test_navigation_with_10_instances(flask_server, browser, test_data_with_10_instances):
    """Test comprehensive navigation functionality with 10 instances."""
    base_url = flask_server.base_url
    username = f"test_user_{int(time.time())}"
    password = "test_password_123"

    print(f"=== Testing Navigation with 10 Instances ===")
    print(f"Username: {username}")
    print(f"Base URL: {base_url}")
    print(f"Number of instances: {test_data_with_10_instances}")

    # Step 1: Register user and navigate to annotation page
    print("1. Registering user and navigating to annotation page...")

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

    # Step 2: Test initial state and next button behavior
    print("2. Testing initial state and next button behavior...")

    # Check that next button is initially disabled
    next_btn = browser.find_element(By.ID, "next-btn")
    initial_disabled = next_btn.get_attribute("disabled") is not None
    print(f"   Next button initially disabled: {initial_disabled}")
    assert initial_disabled, "Next button should be disabled when no annotation is provided"

    # Check current instance text
    instance_text = browser.find_element(By.ID, "instance-text").text
    print(f"   Current instance text: {instance_text[:100]}...")

    # Step 3: Test go-to functionality restrictions
    print("3. Testing go-to functionality restrictions...")

    # Try to go to instance 5 (should be restricted)
    try:
        go_to_input = browser.find_element(By.ID, "go_to")
        go_to_btn = browser.find_element(By.ID, "go-to-btn")

        # Try to jump ahead to instance 5
        go_to_input.clear()
        go_to_input.send_keys("5")
        go_to_btn.click()
        time.sleep(2)

        # Check if we're still on the same instance (should be restricted)
        new_instance_text = browser.find_element(By.ID, "instance-text").text
        print(f"   Instance text after trying to go to 5: {new_instance_text[:100]}...")

        # Should still be on the same instance (navigation restricted)
        assert new_instance_text == instance_text, "Navigation to future instance should be restricted"
        print("   ✅ Go-to restriction working: cannot jump ahead")

    except NoSuchElementException:
        print("   ⚠️ Go-to input not found, skipping go-to test")

    # Step 4: Complete annotation on first instance
    print("4. Completing annotation on first instance...")

    # Find and select a sentiment radio button
    sentiment_radios = browser.find_elements(By.CSS_SELECTOR, "input[name='sentiment']")
    print(f"   Found {len(sentiment_radios)} sentiment radio buttons")

    if sentiment_radios:
        # Select the first option
        sentiment_radios[0].click()
        time.sleep(1)

        # Check that next button is now enabled
        next_btn_disabled = next_btn.get_attribute("disabled") is not None
        print(f"   Next button disabled after annotation: {next_btn_disabled}")
        assert not next_btn_disabled, "Next button should be enabled after completing annotation"

        # Step 5: Navigate to next instance
        print("5. Navigating to next instance...")

        next_btn.click()
        time.sleep(2)

        # Check that we're on a different instance
        new_instance_text = browser.find_element(By.ID, "instance-text").text
        print(f"   New instance text: {new_instance_text[:100]}...")
        assert new_instance_text != instance_text, "Navigation failed - same text displayed"

        # Check that next button is disabled again (no annotation on new instance)
        next_btn = browser.find_element(By.ID, "next-btn")
        next_btn_disabled = next_btn.get_attribute("disabled") is not None
        print(f"   Next button disabled on new instance: {next_btn_disabled}")
        assert next_btn_disabled, "Next button should be disabled on new instance without annotation"

        # Step 6: Navigate back to previous instance
        print("6. Navigating back to previous instance...")

        prev_btn = browser.find_element(By.ID, "prev-btn")
        prev_btn.click()
        time.sleep(2)

        # Check that we're back to the original instance
        restored_text = browser.find_element(By.ID, "instance-text").text
        print(f"   Restored instance text: {restored_text[:100]}...")
        assert restored_text == instance_text, "Navigation back failed - different text displayed"

        # Check that annotation is restored
        selected_radio = browser.find_element(By.CSS_SELECTOR, "input[name='sentiment']:checked")
        assert selected_radio is not None, "Annotation not restored after navigation back"
        print("   ✅ Annotation restored after navigation back")

        # Check that next button is still enabled (annotation was restored)
        next_btn = browser.find_element(By.ID, "next-btn")
        next_btn_disabled = next_btn.get_attribute("disabled") is not None
        print(f"   Next button disabled after navigation back: {next_btn_disabled}")
        assert not next_btn_disabled, "Next button should still be enabled after navigation back"

        # Step 7: Test go-to functionality for completed instances
        print("7. Testing go-to functionality for completed instances...")

        try:
            go_to_input = browser.find_element(By.ID, "go_to")
            go_to_btn = browser.find_element(By.ID, "go-to-btn")

            # Try to go to instance 1 (current instance, should work)
            go_to_input.clear()
            go_to_input.send_keys("1")
            go_to_btn.click()
            time.sleep(2)

            # Should still be on the same instance
            current_text = browser.find_element(By.ID, "instance-text").text
            assert current_text == instance_text, "Go-to to current instance should work"
            print("   ✅ Go-to to current instance works")

        except NoSuchElementException:
            print("   ⚠️ Go-to input not found, skipping go-to test")

        # Step 8: Navigate through multiple instances
        print("8. Navigating through multiple instances...")

        # Go to next instance again
        next_btn = browser.find_element(By.ID, "next-btn")
        next_btn.click()
        time.sleep(2)

        # Complete annotation on second instance
        sentiment_radios = browser.find_elements(By.CSS_SELECTOR, "input[name='sentiment']")
        if sentiment_radios:
            sentiment_radios[1].click()  # Select second option
            time.sleep(1)

            # Navigate to next instance
            next_btn = browser.find_element(By.ID, "next-btn")
            next_btn.click()
            time.sleep(2)

            # Complete annotation on third instance
            sentiment_radios = browser.find_elements(By.CSS_SELECTOR, "input[name='sentiment']")
            if sentiment_radios:
                sentiment_radios[2].click()  # Select third option
                time.sleep(1)

                # Navigate to next instance
                next_btn = browser.find_element(By.ID, "next-btn")
                next_btn.click()
                time.sleep(2)

                # Check that we're on the fourth instance
                fourth_instance_text = browser.find_element(By.ID, "instance-text").text
                print(f"   Fourth instance text: {fourth_instance_text[:100]}...")

                # Step 9: Test go-to functionality for completed instances
                print("9. Testing go-to functionality for completed instances...")

                try:
                    go_to_input = browser.find_element(By.ID, "go_to")
                    go_to_btn = browser.find_element(By.ID, "go-to-btn")

                    # Try to go to instance 2 (should work since it's completed)
                    go_to_input.clear()
                    go_to_input.send_keys("2")
                    go_to_btn.click()
                    time.sleep(2)

                    # Should be on instance 2
                    instance_2_text = browser.find_element(By.ID, "instance-text").text
                    print(f"   Instance 2 text: {instance_2_text[:100]}...")

                    # Check that annotation is restored
                    selected_radio = browser.find_element(By.CSS_SELECTOR, "input[name='sentiment']:checked")
                    assert selected_radio is not None, "Annotation not restored when going to completed instance"
                    selected_value = selected_radio.get_attribute("value")
                    assert selected_value == "2", f"Wrong annotation restored, expected '2', got '{selected_value}'"
                    print("   ✅ Annotation restored when going to completed instance")

                    # Try to go to instance 6 (should be restricted - not yet completed)
                    go_to_input.clear()
                    go_to_input.send_keys("6")
                    go_to_btn.click()
                    time.sleep(2)

                    # Should still be on instance 2 (navigation restricted)
                    current_text = browser.find_element(By.ID, "instance-text").text
                    assert current_text == instance_2_text, "Navigation to future instance should be restricted"
                    print("   ✅ Go-to restriction working: cannot jump to future instance")

                except NoSuchElementException:
                    print("   ⚠️ Go-to input not found, skipping go-to test")

        print("✅ Navigation test with 10 instances completed successfully")

    else:
        pytest.fail("No sentiment radio buttons found")


def test_instance_assignment_and_relative_indexing(flask_server, browser, test_data_with_10_instances):
    """Test that users see instances with relative indexing (1, 2, 3, etc.) and proper assignment."""
    base_url = flask_server.base_url
    username = f"test_user_{int(time.time())}"
    password = "test_password_123"

    print(f"=== Testing Instance Assignment and Relative Indexing ===")
    print(f"Username: {username}")

    # Register user and navigate to annotation page
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

    # Check progress counter to verify relative indexing
    try:
        progress_counter = browser.find_element(By.ID, "progress-counter")
        progress_text = progress_counter.text
        print(f"   Progress counter: {progress_text}")

        # Should show something like "1 of 10" or similar
        assert "1" in progress_text, "Progress counter should show instance 1"
        print("   ✅ Progress counter shows relative indexing")

    except NoSuchElementException:
        print("   ⚠️ Progress counter not found")

    # Test that we can navigate through instances in order
    instance_texts = []

    for i in range(min(5, test_data_with_10_instances)):  # Test first 5 instances
        # Get current instance text
        current_text = browser.find_element(By.ID, "instance-text").text
        instance_texts.append(current_text)
        print(f"   Instance {i+1} text: {current_text[:50]}...")

        # Complete annotation
        sentiment_radios = browser.find_elements(By.CSS_SELECTOR, "input[name='sentiment']")
        if sentiment_radios:
            sentiment_radios[i % len(sentiment_radios)].click()  # Cycle through options
            time.sleep(1)

            # Navigate to next instance
            next_btn = browser.find_element(By.ID, "next-btn")
            next_btn.click()
            time.sleep(2)
        else:
            break

    # Verify we have different instance texts (different instances were shown)
    unique_texts = set(instance_texts)
    assert len(unique_texts) > 1, "Should have navigated through different instances"
    print(f"   ✅ Navigated through {len(unique_texts)} different instances")

    print("✅ Instance assignment and relative indexing test completed")


def test_next_button_behavior_with_required_fields(flask_server, browser, test_data_with_10_instances):
    """Test that next button is properly disabled until all required fields are completed."""
    base_url = flask_server.base_url
    username = f"test_user_{int(time.time())}"
    password = "test_password_123"

    print(f"=== Testing Next Button Behavior with Required Fields ===")
    print(f"Username: {username}")

    # Register user and navigate to annotation page
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

    # Check initial state - next button should be disabled
    next_btn = browser.find_element(By.ID, "next-btn")
    initial_disabled = next_btn.get_attribute("disabled") is not None
    print(f"   Next button initially disabled: {initial_disabled}")
    assert initial_disabled, "Next button should be disabled initially"

    # Complete annotation
    sentiment_radios = browser.find_elements(By.CSS_SELECTOR, "input[name='sentiment']")
    if sentiment_radios:
        sentiment_radios[0].click()
        time.sleep(1)

        # Check that next button is now enabled
        next_btn_disabled = next_btn.get_attribute("disabled") is not None
        print(f"   Next button disabled after annotation: {next_btn_disabled}")
        assert not next_btn_disabled, "Next button should be enabled after completing annotation"

        # Navigate to next instance
        next_btn.click()
        time.sleep(2)

        # Check that next button is disabled again on new instance
        next_btn = browser.find_element(By.ID, "next-btn")
        next_btn_disabled = next_btn.get_attribute("disabled") is not None
        print(f"   Next button disabled on new instance: {next_btn_disabled}")
        assert next_btn_disabled, "Next button should be disabled on new instance without annotation"

        print("✅ Next button behavior test completed")

    else:
        pytest.fail("No sentiment radio buttons found")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])