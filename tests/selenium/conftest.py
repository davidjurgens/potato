"""
Selenium test configuration.

This module provides fixtures and configuration for Selenium tests.
Selenium tests require a browser (Chrome or Firefox) to be installed.
"""

import pytest
import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

# Skip all selenium tests in CI or when explicitly disabled
SKIP_SELENIUM = os.environ.get('SKIP_SELENIUM_TESTS', '').lower() in ('1', 'true', 'yes')

# Fast mode reduces wait times for local development
FAST_MODE = os.environ.get('FAST_TESTS', '').lower() in ('1', 'true', 'yes')
DEFAULT_WAIT = 5 if FAST_MODE else 10


def pytest_collection_modifyitems(config, items):
    """
    Modify test collection:
    - Skip selenium tests if SKIP_SELENIUM_TESTS env var is set
    - Mark all selenium tests as 'slow' for selective running
    """
    skip_marker = pytest.mark.skip(reason="Selenium tests skipped via SKIP_SELENIUM_TESTS env var")
    slow_marker = pytest.mark.slow

    for item in items:
        if "selenium" in item.nodeid:
            # Always mark selenium tests as slow
            item.add_marker(slow_marker)
            # Skip if env var is set
            if SKIP_SELENIUM:
                item.add_marker(skip_marker)


@pytest.fixture(scope="session")
def browser_available():
    """Check if a browser is available for Selenium tests."""
    try:
        options = ChromeOptions()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        driver = webdriver.Chrome(options=options)
        driver.quit()
        return True
    except Exception:
        return False


@pytest.fixture(autouse=True)
def skip_if_no_browser(request, browser_available):
    """Skip test if browser is not available."""
    if not browser_available and "selenium" in request.node.nodeid:
        pytest.skip("Browser not available for Selenium tests")


@pytest.fixture(scope="session")
def shared_flask_server():
    """
    Session-scoped Flask server for tests that don't need isolation.

    This server is created once and shared across all tests in the session,
    significantly reducing test runtime.

    Usage:
        def test_something(shared_flask_server, shared_chrome_browser):
            base_url = shared_flask_server.base_url
            # ... test code ...
    """
    from tests.helpers.flask_test_setup import FlaskTestServer
    from tests.helpers.test_utils import create_test_config, create_test_data_file
    from tests.helpers.port_manager import find_free_port
    import shutil

    # Create test directory
    test_dir = os.path.join(os.path.dirname(__file__), "..", "output", f"shared_server_{int(time.time())}")
    os.makedirs(test_dir, exist_ok=True)

    # Create test data with multiple items
    test_data = [
        {"id": f"item_{i+1}", "text": f"This is shared test item number {i+1} for testing."}
        for i in range(10)
    ]
    data_file = create_test_data_file(test_dir, test_data)

    # Create annotation schemes covering common types
    annotation_schemes = [
        {
            "annotation_type": "span",
            "name": "emotion",
            "description": "Highlight emotional phrases",
            "labels": ["happy", "sad", "angry", "neutral"],
        },
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
        annotation_task_name="Shared Test Server",
        require_password=False  # Simpler auth for shared server
    )

    port = find_free_port()
    server = FlaskTestServer(port=port, debug=False, config_file=config_file)
    started = server.start_server()

    if not started:
        shutil.rmtree(test_dir, ignore_errors=True)
        pytest.skip("Failed to start shared Flask server")

    yield server

    server.stop_server()
    shutil.rmtree(test_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def shared_chrome_options():
    """Session-scoped Chrome options for reuse."""
    options = ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-plugins")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    return options


@pytest.fixture(scope="module")
def shared_chrome_browser(shared_chrome_options):
    """
    Module-scoped Chrome browser for tests that can share a browser.

    The browser is created once per test module and reused across tests.
    Each test should clear cookies if needed for isolation.
    """
    driver = webdriver.Chrome(options=shared_chrome_options)
    yield driver
    driver.quit()


# Helper functions for replacing time.sleep() with explicit waits

def wait_for_page_load(driver, timeout=DEFAULT_WAIT):
    """Wait for page to finish loading."""
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )


def wait_for_element(driver, by, value, timeout=DEFAULT_WAIT):
    """Wait for element to be present and return it."""
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((by, value))
    )


def wait_for_element_clickable(driver, by, value, timeout=DEFAULT_WAIT):
    """Wait for element to be clickable and return it."""
    return WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((by, value))
    )


def wait_for_span_manager(driver, timeout=DEFAULT_WAIT):
    """Wait for span manager to be initialized."""
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return !!(window.spanManager && window.spanManager.isInitialized)")
    )


def wait_for_annotation_page(driver, timeout=DEFAULT_WAIT):
    """Wait for annotation page to load completely."""
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.ID, "instance-text"))
    )
    # Also wait for any JavaScript initialization
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )


def wait_for_ajax(driver, timeout=DEFAULT_WAIT):
    """Wait for any pending AJAX requests to complete."""
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return typeof jQuery === 'undefined' || jQuery.active === 0")
    )


def quick_sleep(seconds=0.3):
    """
    Short sleep for UI transitions. Use sparingly.
    In FAST_MODE, sleeps are reduced by 50%.
    """
    if FAST_MODE:
        time.sleep(seconds * 0.5)
    else:
        time.sleep(seconds)


# Additional domain-specific wait functions

def wait_for_annotation_saved(driver, timeout=DEFAULT_WAIT):
    """Wait for annotation save to complete (no pending AJAX)."""
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script(
            "return typeof jQuery === 'undefined' || jQuery.active === 0"
        )
    )


def wait_for_navigation_complete(driver, timeout=DEFAULT_WAIT):
    """Wait for page navigation to complete."""
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )
    # Also wait for any instance_id element if present
    try:
        WebDriverWait(driver, 2).until(
            EC.presence_of_element_located((By.ID, "instance_id"))
        )
    except:
        pass  # Not all pages have instance_id


def wait_for_form_ready(driver, timeout=DEFAULT_WAIT):
    """Wait for annotation form to be interactive."""
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )
    # Wait for any form elements to be present
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR,
                "input[type='checkbox'], input[type='radio'], textarea, input[type='text']")) > 0
        )
    except:
        pass  # Form may not have these elements


def wait_for_checkbox_state(driver, schema, label, checked, timeout=DEFAULT_WAIT):
    """Wait for a checkbox to reach a specific state."""
    selector = f'input[type="checkbox"][schema="{schema}"][label_name="{label}"]'
    WebDriverWait(driver, timeout).until(
        lambda d: d.find_element(By.CSS_SELECTOR, selector).is_selected() == checked
    )


def wait_for_instance_change(driver, old_instance_id, timeout=DEFAULT_WAIT):
    """Wait for instance ID to change from the old value."""
    WebDriverWait(driver, timeout).until(
        lambda d: d.find_element(By.ID, "instance_id").get_attribute("value") != old_instance_id
    )


# Session-scoped fixtures for different test types

@pytest.fixture(scope="session")
def shared_form_server():
    """
    Session-scoped Flask server for form-based annotation tests.

    Includes checkbox, radio, and text annotation types.
    """
    from tests.helpers.flask_test_setup import FlaskTestServer
    from tests.helpers.test_utils import create_test_config, create_test_data_file
    from tests.helpers.port_manager import find_free_port
    import shutil

    test_dir = os.path.join(os.path.dirname(__file__), "..", "output", f"shared_form_server_{int(time.time())}")
    os.makedirs(test_dir, exist_ok=True)

    test_data = [
        {"id": f"form_item_{i+1}", "text": f"Form test item {i+1} with content for checkbox, radio, and text annotations."}
        for i in range(10)
    ]
    data_file = create_test_data_file(test_dir, test_data)

    annotation_schemes = [
        {
            "name": "multiselect",
            "annotation_type": "multiselect",
            "labels": ["option_a", "option_b", "option_c"],
            "description": "Select all that apply"
        },
        {
            "name": "single_choice",
            "annotation_type": "radio",
            "labels": ["choice_1", "choice_2", "choice_3"],
            "description": "Choose one"
        },
        {
            "name": "freetext",
            "annotation_type": "text",
            "description": "Enter your response"
        }
    ]

    config_file = create_test_config(
        test_dir,
        annotation_schemes,
        data_files=[data_file],
        annotation_task_name="Shared Form Server",
        require_password=False
    )

    port = find_free_port()
    server = FlaskTestServer(port=port, debug=False, config_file=config_file)
    started = server.start_server()

    if not started:
        shutil.rmtree(test_dir, ignore_errors=True)
        pytest.skip("Failed to start shared form server")

    yield server

    server.stop_server()
    shutil.rmtree(test_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def shared_span_server():
    """
    Session-scoped Flask server for span annotation tests.

    Provides text with sufficient length for span selection.
    """
    from tests.helpers.flask_test_setup import FlaskTestServer
    from tests.helpers.test_utils import create_test_config, create_test_data_file
    from tests.helpers.port_manager import find_free_port
    import shutil

    test_dir = os.path.join(os.path.dirname(__file__), "..", "output", f"shared_span_server_{int(time.time())}")
    os.makedirs(test_dir, exist_ok=True)

    # Longer text content for span selection
    test_data = [
        {"id": f"span_item_{i+1}", "text": f"This is span test item {i+1} with enough text content to allow for span annotation selection and proper testing of text highlighting features."}
        for i in range(10)
    ]
    data_file = create_test_data_file(test_dir, test_data)

    annotation_schemes = [
        {
            "annotation_type": "span",
            "name": "highlight",
            "description": "Highlight text spans",
            "labels": ["important", "question", "example", "definition"],
        }
    ]

    config_file = create_test_config(
        test_dir,
        annotation_schemes,
        data_files=[data_file],
        annotation_task_name="Shared Span Server",
        require_password=False
    )

    port = find_free_port()
    server = FlaskTestServer(port=port, debug=False, config_file=config_file)
    started = server.start_server()

    if not started:
        shutil.rmtree(test_dir, ignore_errors=True)
        pytest.skip("Failed to start shared span server")

    yield server

    server.stop_server()
    shutil.rmtree(test_dir, ignore_errors=True)


@pytest.fixture
def clear_browser_state(request):
    """
    Fixture to clear browser state after each test.

    Usage:
        def test_something(shared_chrome_browser, clear_browser_state):
            # Test code here
            # Browser state will be cleared after test
    """
    yield
    # Get the browser from the test's fixtures if available
    if hasattr(request, 'fixturenames') and 'shared_chrome_browser' in request.fixturenames:
        driver = request.getfixturevalue('shared_chrome_browser')
        try:
            driver.delete_all_cookies()
            driver.execute_script("if(window.localStorage){localStorage.clear();}")
            driver.execute_script("if(window.sessionStorage){sessionStorage.clear();}")
        except:
            pass  # Browser may be closed or in error state
