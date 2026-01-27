import os
import pytest
import time
import json
import shutil
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_span_annotation_config

REQUIRED_USER_STATE_FIELDS = [
    "user_id",
    "current_instance",
    "annotations",
    "assignments",
    "phase",
    "max_assignments",
    "hints",
]

@pytest.fixture(scope="module")
def flask_server():
    # Create test directory and config using proper test utilities
    tests_dir = os.path.dirname(os.path.dirname(__file__))
    test_dir = os.path.join(tests_dir, "output", "user_state_contract_test")
    os.makedirs(test_dir, exist_ok=True)

    # Create a span annotation config with admin API key
    config_file, data_file = create_span_annotation_config(
        test_dir,
        annotation_task_name="User State Contract Test",
        require_password=True,  # Test needs password mode for register-tab
        admin_api_key="admin_api_key"  # Required for admin endpoints
    )

    server = FlaskTestServer(config_file=config_file, debug=False)
    server.start()
    yield server
    server.stop()

    # Cleanup test directory
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir, ignore_errors=True)

@pytest.fixture(scope="module")
def browser():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1200,800")
    driver = webdriver.Chrome(options=options)
    yield driver
    driver.quit()

def test_user_state_contract(flask_server, browser):
    base_url = flask_server.base_url
    username = "contract_user"
    password = "contract_pass"

    # Go to login page
    browser.get(f"{base_url}/login")
    WebDriverWait(browser, 10).until(EC.presence_of_element_located((By.NAME, "email")))

    # Click on register tab
    register_tab = browser.find_element(By.ID, "register-tab")
    register_tab.click()

    # Wait for register form to be visible
    WebDriverWait(browser, 10).until(EC.visibility_of_element_located((By.ID, "register-content")))

    # Fill registration form
    browser.find_element(By.ID, "register-email").send_keys(username)
    browser.find_element(By.ID, "register-pass").send_keys(password)

    # Submit registration form
    register_button = browser.find_element(By.CSS_SELECTOR, "#register-content button[type='submit']")
    register_button.click()

    # Wait for page to load after registration (redirects to / which shows annotation interface)
    WebDriverWait(browser, 10).until(EC.presence_of_element_located((By.ID, "task_layout")))

    # Use the server's get method which automatically includes admin API key
    response = flask_server.get(f"/admin/user_state/{username}")

    if response.status_code != 200:
        pytest.fail(f"Failed to fetch user state: HTTP {response.status_code} - {response.text}")

    user_state = response.json()

    # Assert contract fields
    for field in REQUIRED_USER_STATE_FIELDS:
        assert field in user_state, f"Missing field: {field}"
    assert isinstance(user_state["annotations"], dict)
    assert "by_instance" in user_state["annotations"]
    assert "total_count" in user_state["annotations"]
    assert isinstance(user_state["assignments"], dict)
    assert "total" in user_state["assignments"]
    assert "annotated" in user_state["assignments"]
    assert "remaining" in user_state["assignments"]
    assert "items" in user_state["assignments"]
    assert isinstance(user_state["phase"], str)
    assert user_state["user_id"] == username
    # current_instance can be None or dict
    assert user_state["current_instance"] is None or isinstance(user_state["current_instance"], dict)
    # If current_instance exists, displayed_text should be present and a string
    if user_state["current_instance"]:
        assert "displayed_text" in user_state["current_instance"]
        assert isinstance(user_state["current_instance"]["displayed_text"], str)
    assert isinstance(user_state["hints"], dict)
    assert isinstance(user_state["max_assignments"], int)

    # Optionally print for debug
    print("User state contract test passed. Response:", user_state)