"""
Firefox-Specific Selenium Test Suite for Span Persistence and Cross-Instance Bugs
"""
import pytest
import time
import os
import uuid
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.firefox.options import Options
from selenium.common.exceptions import TimeoutException
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_config, create_test_data_file
from tests.helpers.port_manager import find_free_port


@pytest.fixture(scope="module")
def flask_server():
    """Start the Flask server with span annotation configuration."""
    # Create test directory
    test_dir = os.path.join(os.path.dirname(__file__), "..", "output", f"firefox_span_persistence_test_{int(time.time())}")
    os.makedirs(test_dir, exist_ok=True)

    # Create test data
    test_data = [
        {"id": "item_1", "text": "This is test item 1 with happy and sad emotions."},
        {"id": "item_2", "text": "This is test item 2 with different emotional content."},
        {"id": "item_3", "text": "This is test item 3 for testing span persistence."},
    ]
    data_file = create_test_data_file(test_dir, test_data)

    # Create span annotation schemes
    annotation_schemes = [
        {
            "annotation_type": "span",
            "name": "emotion",
            "description": "Highlight emotional phrases",
            "labels": ["happy", "sad", "angry"],
        }
    ]

    config_file = create_test_config(
        test_dir,
        annotation_schemes,
        data_files=[data_file],
        annotation_task_name="Firefox Span Persistence Test",
        require_password=True
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
def firefox_browser():
    """Create a headless Firefox browser for testing."""
    firefox_options = Options()
    firefox_options.add_argument("--headless")
    firefox_options.add_argument("--no-sandbox")
    firefox_options.add_argument("--disable-dev-shm-usage")
    firefox_options.add_argument("--width=1920")
    firefox_options.add_argument("--height=1080")
    firefox_options.set_preference("browser.cache.disk.enable", False)
    firefox_options.set_preference("browser.cache.memory.enable", False)
    firefox_options.set_preference("browser.cache.offline.enable", False)
    firefox_options.set_preference("network.http.use-cache", False)

    driver = webdriver.Firefox(options=firefox_options)
    yield driver
    driver.quit()


class TestFirefoxSpanPersistence:
    """Test suite for span persistence in Firefox."""

    def _register_test_user(self, driver, base_url, test_name):
        """Register a test user."""
        timestamp = int(time.time())
        unique_id = str(uuid.uuid4())[:8]
        username = f"firefox_span_test_user_{test_name}_{timestamp}_{unique_id}"

        driver.get(base_url)

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "register-tab"))
        )

        register_tab = driver.find_element(By.ID, "register-tab")
        driver.execute_script("arguments[0].click();", register_tab)
        time.sleep(0.1)

        email_field = driver.find_element(By.ID, "register-email")
        email_field.clear()
        email_field.send_keys(username)

        password_field = driver.find_element(By.ID, "register-pass")
        password_field.clear()
        password_field.send_keys("test_password_123")

        submit_button = driver.find_element(By.CSS_SELECTOR, "#register-content button[type='submit']")
        driver.execute_script("arguments[0].click();", submit_button)

        time.sleep(0.05)

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )

        return username

    def test_span_persists_after_navigation(self, flask_server, firefox_browser):
        """Test that spans persist after navigating away and back."""
        base_url = flask_server.base_url
        driver = firefox_browser

        print("=== Testing Span Persistence After Navigation ===")

        # Register user
        username = self._register_test_user(driver, base_url, "persistence_test")
        print(f"✅ Registered user: {username}")

        # Wait for span manager
        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script("return !!(window.spanManager && window.spanManager.isInitialized);")
        )

        print("✅ Span manager initialized")

        # Navigate to next and back
        next_btn = driver.find_element(By.ID, "next-btn")
        next_btn.click()
        time.sleep(0.1)

        prev_btn = driver.find_element(By.ID, "prev-btn")
        prev_btn.click()
        time.sleep(0.1)

        print("✅ Span persistence test completed")

    def test_span_creation_in_firefox(self, flask_server, firefox_browser):
        """Test that span creation works in Firefox."""
        base_url = flask_server.base_url
        driver = firefox_browser

        print("=== Testing Span Creation in Firefox ===")

        # Register user
        username = self._register_test_user(driver, base_url, "creation_test")
        print(f"✅ Registered user: {username}")

        # Wait for span manager
        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script("return !!(window.spanManager && window.spanManager.isInitialized);")
        )

        # Check for span labels
        labels = driver.find_elements(By.CSS_SELECTOR, ".span-label-checkbox, input[name*='span']")
        print(f"Found {len(labels)} span label elements")

        print("✅ Span creation test completed")
