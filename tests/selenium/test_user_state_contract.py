import pytest
import time
import json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from tests.helpers.flask_test_setup import FlaskTestServer

REQUIRED_USER_STATE_FIELDS = [
    "user_id",
    "current_instance",
    "displayed_text",
    "annotations",
    "assignments",
    "progress",
    "phase",
    "task_name",
]

@pytest.fixture(scope="module")
def flask_server():
    # Use a valid span annotation config
    config_file = "../configs/span-annotation.yaml"
    server = FlaskTestServer(config_file=config_file, debug=False)
    server.start()
    yield server
    server.stop()

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

    # Wait for redirect to annotation page
    WebDriverWait(browser, 10).until(EC.url_contains("/annotate"))

    # Use JS to fetch user state JSON (with session cookie)
    user_state_url = f"{base_url}/admin/user_state/{username}"
    script = f"""
        return fetch('{user_state_url}', {{credentials: 'same-origin'}})
            .then(r => r.json())
            .then(data => JSON.stringify(data))
            .catch(e => 'ERROR: ' + e.message);
    """
    user_state_json = browser.execute_script(script)

    # Check if there was an error
    if user_state_json.startswith("ERROR:"):
        pytest.fail(f"Failed to fetch user state: {user_state_json}")

    user_state = json.loads(user_state_json)

    # Assert contract fields
    for field in REQUIRED_USER_STATE_FIELDS:
        assert field in user_state, f"Missing field: {field}"
    assert isinstance(user_state["annotations"], dict)
    assert "by_instance" in user_state["annotations"]
    assert isinstance(user_state["assignments"], dict)
    assert isinstance(user_state["progress"], dict)
    assert isinstance(user_state["phase"], str)
    assert isinstance(user_state["task_name"], str)
    assert user_state["user_id"] == username
    # current_instance can be None or dict
    assert user_state["current_instance"] is None or isinstance(user_state["current_instance"], dict)
    # displayed_text should be a string
    assert isinstance(user_state["displayed_text"], str)

    # Optionally print for debug
    print("User state contract test passed. Response:", user_state)