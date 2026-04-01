"""Selenium UI tests for Iterative BWS annotation."""

import os
import time
import uuid

import pytest
import yaml

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import create_test_directory, create_test_data_file, cleanup_test_directory


def create_ibws_config(test_dir, data_file, tuple_size=4, port=9012):
    """Create an IBWS test config for Selenium tests."""
    abs_test_dir = os.path.abspath(test_dir)
    output_dir = os.path.join(abs_test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    config = {
        "annotation_task_name": "IBWS Selenium Test",
        "task_dir": abs_test_dir,
        "data_files": [os.path.basename(data_file)],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "output_annotation_dir": output_dir,
        "require_password": False,
        "authentication": {"method": "in_memory"},
        "persist_sessions": False,
        "debug": False,
        "port": port,
        "host": "0.0.0.0",
        "secret_key": "test-secret-key-ibws-selenium",
        "user_config": {"allow_all_users": True, "users": []},
        "ibws_config": {
            "tuple_size": tuple_size,
            "seed": 42,
            "scoring_method": "counting",
            "tuples_per_item_per_round": 2,
            "max_rounds": 2,
        },
        "annotation_schemes": [
            {
                "annotation_type": "bws",
                "name": "test_ibws",
                "description": "Test IBWS",
                "best_description": "Which is best?",
                "worst_description": "Which is worst?",
                "tuple_size": tuple_size,
                "sequential_key_binding": True,
            }
        ],
    }

    config_path = os.path.join(abs_test_dir, "config.yaml")
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    return config_path


@pytest.fixture(scope="module")
def ibws_server():
    """Start a Flask server with IBWS config for Selenium tests."""
    test_dir = create_test_directory("ibws_selenium_test")

    data = [
        {"id": f"s{i:03d}", "text": f"Test item number {i} with sentiment content."}
        for i in range(1, 13)
    ]
    data_file = create_test_data_file(test_dir, data)

    port = find_free_port(preferred_port=9012)
    config_path = create_ibws_config(test_dir, data_file, tuple_size=4, port=port)

    server = FlaskTestServer(port=port, config_file=config_path)
    if not server.start():
        cleanup_test_directory(test_dir)
        pytest.fail("Failed to start IBWS Selenium test server")

    yield server

    server.stop()
    cleanup_test_directory(test_dir)


@pytest.fixture(scope="module")
def driver():
    """Create a headless Chrome WebDriver."""
    chrome_options = ChromeOptions()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")

    try:
        d = webdriver.Chrome(options=chrome_options)
    except Exception:
        pytest.skip("Chrome WebDriver not available")
        return

    yield d
    d.quit()


def register_and_login(driver, base_url):
    """Register and login a unique test user."""
    username = f"ibws_ui_{uuid.uuid4().hex[:6]}"
    driver.get(f"{base_url}/")

    # Wait for the page to load
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )

    # Register
    try:
        email_field = driver.find_element(By.NAME, "email")
        pass_field = driver.find_element(By.NAME, "pass")
        email_field.clear()
        email_field.send_keys(username)
        pass_field.clear()
        pass_field.send_keys("testpass")

        # Find and click submit
        submit = driver.find_element(By.CSS_SELECTOR, "button[type='submit'], input[type='submit']")
        submit.click()
        time.sleep(1)
    except Exception:
        pass

    return username


class TestIbwsUI:
    """Selenium UI tests for IBWS."""

    def test_annotate_page_loads(self, ibws_server, driver):
        """Annotation page loads with BWS tiles."""
        register_and_login(driver, ibws_server.base_url)
        driver.get(f"{ibws_server.base_url}/annotate")

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        # The page should load (200 response = no error page)
        assert "Error" not in driver.title

    def test_round_banner_visible(self, ibws_server, driver):
        """IBWS round banner is visible on annotation page."""
        driver.get(f"{ibws_server.base_url}/annotate")

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        # Check for the round banner
        banners = driver.find_elements(By.ID, "ibws-round-banner")
        assert len(banners) > 0, "IBWS round banner should be present"

    def test_bws_tiles_present(self, ibws_server, driver):
        """BWS tile selection UI is present."""
        driver.get(f"{ibws_server.base_url}/annotate")

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        # Check for BWS tiles
        tiles = driver.find_elements(By.CSS_SELECTOR, ".bws-tile")
        # Should have tiles for best and worst selections
        assert len(tiles) > 0, "BWS tiles should be present"

    def test_progress_counter_visible(self, ibws_server, driver):
        """Progress counter shows annotation progress."""
        driver.get(f"{ibws_server.base_url}/annotate")

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        counter = driver.find_elements(By.ID, "progress-counter")
        assert len(counter) > 0, "Progress counter should be present"
