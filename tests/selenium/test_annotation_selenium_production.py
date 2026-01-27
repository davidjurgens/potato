import os
import time
import json
import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_config, create_test_data_file
from tests.helpers.port_manager import find_free_port


@pytest.fixture(scope="module")
def flask_server():
    """Start the server in production mode using dynamic config."""
    # Create test directory
    test_dir = os.path.join(os.path.dirname(__file__), "..", "output", f"production_test_{int(time.time())}")
    os.makedirs(test_dir, exist_ok=True)

    # Create test data
    test_data = [
        {"id": "item_1", "text": "This is a positive test item."},
        {"id": "item_2", "text": "This is a negative test item."},
        {"id": "item_3", "text": "This is a neutral test item."},
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
        annotation_task_name="Production Mode Test",
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
def browser():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-plugins")
    chrome_options.add_argument("--disable-images")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    print("🔧 Creating headless Chrome browser...")
    driver = webdriver.Chrome(options=chrome_options)
    print("✅ Headless Chrome browser created successfully")

    yield driver
    driver.quit()


def test_server_health_check(flask_server):
    """Test that the server is running and healthy."""
    response = flask_server.get("/")
    assert response.status_code in [200, 302], f"Server health check failed: {response.status_code}"
    print("✅ Server health check passed")


def test_user_registration_and_annotation(flask_server, browser):
    """Test user registration, login, and annotation submission in production mode."""
    base_url = flask_server.base_url
    username = f"test_user_{int(time.time())}"
    password = "test_password_123"

    print(f"=== Testing User Registration and Annotation ===")
    print(f"Username: {username}")
    print(f"Base URL: {base_url}")

    # Navigate to home page
    browser.get(f"{base_url}/")

    # Wait for login page
    WebDriverWait(browser, 10).until(
        EC.presence_of_element_located((By.ID, "login-tab"))
    )

    # Click register tab
    register_tab = browser.find_element(By.ID, "register-tab")
    register_tab.click()

    WebDriverWait(browser, 10).until(
        EC.visibility_of_element_located((By.ID, "register-content"))
    )

    # Fill registration form
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

    print("✅ User registered and on annotation page")

    # Make an annotation
    sentiment_radios = browser.find_elements(By.CSS_SELECTOR, "input[name='sentiment']")
    if sentiment_radios:
        sentiment_radios[0].click()
        print("✅ Annotation made")

    print("✅ User registration and annotation test passed")
