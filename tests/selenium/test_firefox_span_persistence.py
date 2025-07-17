"""
Firefox-Specific Selenium Test Suite for Span Persistence and Cross-Instance Bugs
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

@pytest.fixture(scope="module")
def flask_server():
    config_file = os.path.abspath("tests/configs/span-annotation.yaml")
    test_data_file = os.path.abspath("tests/data/test_data.json")
    server = FlaskTestServer(port=9009, debug=False, config_file=config_file, test_data_file=test_data_file)
    started = server.start_server()
    assert started, "Failed to start Flask server"
    yield server
    server.stop_server()

@pytest.fixture
def firefox_browser():
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
    def register_test_user(self, driver, base_url, test_name):
        import uuid
        import time
        timestamp = int(time.time())
        unique_id = str(uuid.uuid4())[:8]
        username = f"firefox_span_test_user_{test_name}_{timestamp}_{unique_id}"
        driver.get(base_url)
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "register-tab")))
        register_tab = driver.find_element(By.ID, "register-tab")
        driver.execute_script("arguments[0].click();", register_tab)
        time.sleep(1)
        email_field = driver.find_element(By.ID, "register-email")
        email_field.clear()
        email_field.send_keys(username)
        password_field = driver.find_element(By.ID, "register-pass")
        password_field.clear()
        password_field.send_keys("test_password_123")
        submit_button = driver.find_element(By.CSS_SELECTOR, "#register-content button[type='submit']")
        driver.execute_script("arguments[0].click();", submit_button)
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "instance-text")))
        return username

    def wait_for_span_overlays(self, driver, expected_count, timeout=5):
        for _ in range(timeout * 2):
            spans = driver.find_elements(By.CSS_SELECTOR, ".span-overlay")
            if len(spans) == expected_count:
                return spans
            time.sleep(0.5)
        return driver.find_elements(By.CSS_SELECTOR, ".span-overlay")

    def test_span_persistence_and_cross_instance(self, flask_server, firefox_browser):
        base_url = f"http://localhost:{flask_server.port}"
        username = self.register_test_user(firefox_browser, base_url, "persistence")
        # 1. Annotate a span on instance 1
        firefox_browser.get(f"{base_url}/annotate")
        WebDriverWait(firefox_browser, 10).until(EC.presence_of_element_located((By.ID, "instance-text")))
        time.sleep(2)
        # Select label
        label = firefox_browser.find_element(By.CSS_SELECTOR, "input[name='span_label:::emotion'][value='1']")
        firefox_browser.execute_script("arguments[0].click();", label)
        time.sleep(1)
        # Select text (first 10 chars)
        firefox_browser.execute_script("""
            const el = document.getElementById('instance-text');
            if (el && el.firstChild) {
                const range = document.createRange();
                range.setStart(el.firstChild, 0);
                range.setEnd(el.firstChild, 10);
                window.getSelection().removeAllRanges();
                window.getSelection().addRange(range);
            }
        """)
        time.sleep(1)
        # Create span
        firefox_browser.execute_script("""
            if (typeof surroundSelection === 'function') {
                surroundSelection('emotion', 'happy', 'happy', '(255, 230, 230)');
            }
        """)
        time.sleep(2)
        # Verify span present on instance 1
        spans = self.wait_for_span_overlays(firefox_browser, 1)
        assert len(spans) == 1, f"Expected 1 span on instance 1, found {len(spans)}"
        # 2. Navigate to instance 2 and verify no span is present
        next_btn = firefox_browser.find_element(By.ID, "next-btn")
        firefox_browser.execute_script("arguments[0].click();", next_btn)
        time.sleep(3)
        spans = self.wait_for_span_overlays(firefox_browser, 0)
        assert len(spans) == 0, f"Expected 0 spans on instance 2, found {len(spans)}"
        # 3. Navigate back to instance 1 and verify the span is still present
        prev_btn = firefox_browser.find_element(By.ID, "prev-btn")
        firefox_browser.execute_script("arguments[0].click();", prev_btn)
        time.sleep(3)
        spans = self.wait_for_span_overlays(firefox_browser, 1)
        assert len(spans) == 1, f"Expected 1 span on instance 1 after return, found {len(spans)}"
        # 4. Delete the span on instance 1
        close_btn = spans[0].find_element(By.CSS_SELECTOR, ".span-close")
        firefox_browser.execute_script("arguments[0].click();", close_btn)
        time.sleep(2)
        spans = self.wait_for_span_overlays(firefox_browser, 0)
        assert len(spans) == 0, f"Expected 0 spans after deletion on instance 1, found {len(spans)}"
        # 5. Navigate to instance 2 and verify no span is present
        next_btn = firefox_browser.find_element(By.ID, "next-btn")
        firefox_browser.execute_script("arguments[0].click();", next_btn)
        time.sleep(3)
        spans = self.wait_for_span_overlays(firefox_browser, 0)
        assert len(spans) == 0, f"Expected 0 spans on instance 2 after deletion, found {len(spans)}"
        # 6. Navigate back to instance 1 and verify the span is gone
        prev_btn = firefox_browser.find_element(By.ID, "prev-btn")
        firefox_browser.execute_script("arguments[0].click();", prev_btn)
        time.sleep(3)
        spans = self.wait_for_span_overlays(firefox_browser, 0)
        assert len(spans) == 0, f"Expected 0 spans on instance 1 after deletion and return, found {len(spans)}"
        print("✅ Firefox span persistence/cross-instance bug test passed.")