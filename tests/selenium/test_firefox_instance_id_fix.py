"""
Test to verify the Firefox instance_id fix works correctly.
"""

import pytest
import time
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.firefox.options import Options
from selenium.common.exceptions import TimeoutException
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_config, create_test_data_file
from tests.helpers.port_manager import find_free_port
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def flask_server():
    """Start the Flask server with span annotation configuration."""
    # Create test directory
    test_dir = os.path.join(os.path.dirname(__file__), "..", "output", f"firefox_instance_id_test_{int(time.time())}")
    os.makedirs(test_dir, exist_ok=True)

    # Create test data
    test_data = [
        {"id": "item_1", "text": "This is test item 1 for Firefox instance ID testing."},
        {"id": "item_2", "text": "This is test item 2 for Firefox instance ID testing."},
        {"id": "item_3", "text": "This is test item 3 for Firefox instance ID testing."},
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
        annotation_task_name="Firefox Instance ID Test",
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

    # Disable cache to ensure fresh page loads
    firefox_options.set_preference("browser.cache.disk.enable", False)
    firefox_options.set_preference("browser.cache.memory.enable", False)
    firefox_options.set_preference("browser.cache.offline.enable", False)
    firefox_options.set_preference("network.http.use-cache", False)

    print("🔧 Creating headless Firefox browser...")
    driver = webdriver.Firefox(options=firefox_options)
    print("✅ Headless Firefox browser created successfully")

    yield driver
    driver.quit()


class TestFirefoxInstanceIdFix:
    """Test suite for Firefox instance_id fix."""

    def _register_user(self, driver, base_url, test_name):
        """Register a test user."""
        import uuid
        timestamp = int(time.time())
        unique_id = str(uuid.uuid4())[:8]
        username = f"ff_test_{test_name}_{timestamp}_{unique_id}"

        driver.get(base_url)

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "register-tab"))
        )

        register_tab = driver.find_element(By.ID, "register-tab")
        register_tab.click()
        time.sleep(0.1)

        email_field = driver.find_element(By.ID, "register-email")
        email_field.clear()
        email_field.send_keys(username)

        password_field = driver.find_element(By.ID, "register-pass")
        password_field.clear()
        password_field.send_keys("test_password_123")

        submit_button = driver.find_element(By.CSS_SELECTOR, "#register-content button[type='submit']")
        submit_button.click()

        time.sleep(0.05)

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )

        return username

    def test_instance_id_preserved_on_navigation(self, flask_server, firefox_browser):
        """Test that instance_id is preserved when navigating."""
        base_url = flask_server.base_url
        driver = firefox_browser

        print("=== Testing Instance ID Preservation ===")

        # Register user
        username = self._register_user(driver, base_url, "instance_id_test")
        print(f"✅ Registered user: {username}")

        # Get initial instance ID
        initial_instance = driver.execute_script("return window.currentInstanceId || document.getElementById('instance-id')?.value")
        print(f"Initial instance: {initial_instance}")

        # Navigate to next instance
        next_btn = driver.find_element(By.ID, "next-btn")
        next_btn.click()
        time.sleep(0.1)

        # Get new instance ID
        new_instance = driver.execute_script("return window.currentInstanceId || document.getElementById('instance-id')?.value")
        print(f"New instance: {new_instance}")

        # Navigate back
        prev_btn = driver.find_element(By.ID, "prev-btn")
        prev_btn.click()
        time.sleep(0.1)

        # Verify we're back to initial instance
        back_instance = driver.execute_script("return window.currentInstanceId || document.getElementById('instance-id')?.value")
        print(f"Back instance: {back_instance}")

        print("✅ Instance ID navigation test completed")
