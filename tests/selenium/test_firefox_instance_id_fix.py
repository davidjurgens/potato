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
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def flask_server():
    """Start the Flask server with span annotation configuration."""
    config_file = os.path.abspath("tests/configs/span-annotation.yaml")
    test_data_file = os.path.abspath("tests/data/test_data.json")
    # Force debug=False for Selenium tests
    server = FlaskTestServer(port=9008, debug=False, config_file=config_file, test_data_file=test_data_file)
    started = server.start_server()
    assert started, "Failed to start Flask server"
    yield server
    server.stop_server()


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

    def register_test_user(self, driver, base_url, test_name):
        """Register a unique test user for this test."""
        import uuid
        import time

        # Generate unique username
        timestamp = int(time.time())
        unique_id = str(uuid.uuid4())[:8]
        self.test_username = f"firefox_fix_test_user_{test_name}_{timestamp}_{unique_id}"

        print(f"🔐 Registering test user: {self.test_username}")

        # Navigate to home page
        driver.get(base_url)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "register-tab"))
        )

        # Click the Register tab
        register_tab = driver.find_element(By.ID, "register-tab")
        driver.execute_script("arguments[0].click();", register_tab)
        time.sleep(1)

        # Fill in registration form
        email_field = driver.find_element(By.ID, "register-email")
        email_field.clear()
        email_field.send_keys(self.test_username)

        password_field = driver.find_element(By.ID, "register-pass")
        password_field.clear()
        password_field.send_keys("test_password_123")

        # Submit registration form
        submit_button = driver.find_element(By.CSS_SELECTOR, "#register-content button[type='submit']")
        driver.execute_script("arguments[0].click();", submit_button)

        # Wait for redirect to annotation page
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )

        print(f"   ✅ Successfully registered and logged in as: {self.test_username}")
        return self.test_username

    def test_firefox_instance_id_fix(self, flask_server, firefox_browser):
        """Test that the Firefox instance_id fix works correctly."""
        print("\n=== Test Firefox Instance ID Fix ===")

        base_url = f"http://localhost:{flask_server.port}"
        username = self.register_test_user(firefox_browser, base_url, "instance_id_fix")

        try:
            # Navigate to annotation page
            print("1. Navigating to annotation page...")
            firefox_browser.get(f"{base_url}/annotate")
            WebDriverWait(firefox_browser, 10).until(
                EC.presence_of_element_located((By.ID, "instance-text"))
            )
            time.sleep(3)

            # Get initial instance details
            print("2. Getting initial instance details...")
            instance_id_input = firefox_browser.find_element(By.ID, "instance_id")
            initial_instance_id = instance_id_input.get_attribute("value")
            instance_text = firefox_browser.find_element(By.ID, "instance-text")
            initial_text = instance_text.text[:100]

            print(f"   📊 Initial instance_id: {initial_instance_id}")
            print(f"   📊 Initial text preview: {initial_text}...")

            # Test the Firefox fix function
            print("3. Testing Firefox instance_id fix function...")
            result = firefox_browser.execute_script("""
                if (typeof window.testFirefoxInstanceIdFix === 'function') {
                    window.testFirefoxInstanceIdFix();
                    return 'testFirefoxInstanceIdFix executed';
                } else {
                    return 'testFirefoxInstanceIdFix not available';
                }
            """)
            print(f"   📊 Fix test result: {result}")
            time.sleep(2)

            # Navigate to next instance
            print("4. Navigating to next instance...")
            next_button = firefox_browser.find_element(By.ID, "next-btn")
            firefox_browser.execute_script("arguments[0].click();", next_button)
            time.sleep(5)

            WebDriverWait(firefox_browser, 10).until(
                EC.presence_of_element_located((By.ID, "instance-text"))
            )

            # Get new instance details
            print("5. Getting new instance details...")
            instance_id_input = firefox_browser.find_element(By.ID, "instance_id")
            new_instance_id = instance_id_input.get_attribute("value")
            instance_text = firefox_browser.find_element(By.ID, "instance-text")
            new_text = instance_text.text[:100]

            print(f"   📊 New instance_id: {new_instance_id}")
            print(f"   📊 New text preview: {new_text}...")

            # Test the Firefox fix function again
            print("6. Testing Firefox instance_id fix function after navigation...")
            result = firefox_browser.execute_script("""
                if (typeof window.testFirefoxInstanceIdFix === 'function') {
                    window.testFirefoxInstanceIdFix();
                    return 'testFirefoxInstanceIdFix executed after navigation';
                } else {
                    return 'testFirefoxInstanceIdFix not available';
                }
            """)
            print(f"   📊 Fix test result after navigation: {result}")
            time.sleep(2)

            # Check if the fix worked
            print("7. Checking if the fix worked...")
            final_instance_id = firefox_browser.find_element(By.ID, "instance_id").get_attribute("value")
            print(f"   📊 Final instance_id: {final_instance_id}")

            # The fix should ensure that the instance_id changes when the text changes
            instance_id_changed = initial_instance_id != final_instance_id
            text_changed = initial_text != new_text

            print(f"   🔍 Instance ID changed: {instance_id_changed}")
            print(f"   🔍 Text changed: {text_changed}")

            if instance_id_changed and text_changed:
                print("   ✅ SUCCESS: Both instance_id and text changed correctly")
                assert True, "Firefox instance_id fix is working"
            elif not instance_id_changed and text_changed:
                print("   ❌ FAILURE: Text changed but instance_id did not - fix failed")
                assert False, "Firefox instance_id fix failed"
            elif not text_changed:
                print("   ⚠️ WARNING: Text did not change - navigation may have failed")
                assert False, "Navigation failed"
            else:
                print("   ⚠️ UNEXPECTED: Instance_id changed but text did not")
                assert False, "Unexpected behavior"

            print("✅ Firefox instance_id fix test completed successfully")

        except Exception as e:
            print(f"❌ Firefox instance_id fix test failed: {e}")
            raise

    def test_firefox_instance_id_fix_manual(self, flask_server, firefox_browser):
        """Test manual application of the Firefox instance_id fix."""
        print("\n=== Test Manual Firefox Instance ID Fix ===")

        base_url = f"http://localhost:{flask_server.port}"
        username = self.register_test_user(firefox_browser, base_url, "manual_fix")

        try:
            # Navigate to annotation page
            print("1. Navigating to annotation page...")
            firefox_browser.get(f"{base_url}/annotate")
            WebDriverWait(firefox_browser, 10).until(
                EC.presence_of_element_located((By.ID, "instance-text"))
            )
            time.sleep(3)

            # Get initial instance details
            print("2. Getting initial instance details...")
            instance_id_input = firefox_browser.find_element(By.ID, "instance_id")
            initial_instance_id = instance_id_input.get_attribute("value")
            print(f"   📊 Initial instance_id: {initial_instance_id}")

            # Navigate to next instance
            print("3. Navigating to next instance...")
            next_button = firefox_browser.find_element(By.ID, "next-btn")
            firefox_browser.execute_script("arguments[0].click();", next_button)
            time.sleep(5)

            WebDriverWait(firefox_browser, 10).until(
                EC.presence_of_element_located((By.ID, "instance-text"))
            )

            # Check if the bug is present (instance_id should be the same)
            print("4. Checking for the bug...")
            instance_id_input = firefox_browser.find_element(By.ID, "instance_id")
            buggy_instance_id = instance_id_input.get_attribute("value")
            print(f"   📊 Instance_id after navigation: {buggy_instance_id}")

            if buggy_instance_id == initial_instance_id:
                print("   ❌ BUG PRESENT: instance_id did not change")

                # Apply manual fix
                print("5. Applying manual fix...")
                result = firefox_browser.execute_script("""
                    if (typeof window.firefoxInstanceIdFix === 'function') {
                        window.firefoxInstanceIdFix();
                        return 'firefoxInstanceIdFix executed';
                    } else {
                        return 'firefoxInstanceIdFix not available';
                    }
                """)
                print(f"   📊 Manual fix result: {result}")
                time.sleep(2)

                # Check if fix worked
                print("6. Checking if manual fix worked...")
                fixed_instance_id = firefox_browser.find_element(By.ID, "instance_id").get_attribute("value")
                print(f"   📊 Instance_id after manual fix: {fixed_instance_id}")

                if fixed_instance_id != initial_instance_id:
                    print("   ✅ SUCCESS: Manual fix worked")
                    assert True, "Manual Firefox instance_id fix worked"
                else:
                    print("   ❌ FAILURE: Manual fix did not work")
                    assert False, "Manual Firefox instance_id fix failed"
            else:
                print("   ✅ No bug detected - instance_id changed correctly")
                assert True, "No bug detected"

            print("✅ Manual Firefox instance_id fix test completed successfully")

        except Exception as e:
            print(f"❌ Manual Firefox instance_id fix test failed: {e}")
            raise


if __name__ == "__main__":
    # Run the Firefox fix test suite
    pytest.main([__file__, "-v", "-s"])