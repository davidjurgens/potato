"""
Selenium test configuration.

This module provides fixtures and configuration for Selenium tests.
Selenium tests require a browser (Chrome or Firefox) to be installed.
"""

import pytest
import os

# Skip all selenium tests in CI or when explicitly disabled
SKIP_SELENIUM = os.environ.get('SKIP_SELENIUM_TESTS', '').lower() in ('1', 'true', 'yes')

def pytest_collection_modifyitems(config, items):
    """Skip selenium tests if SKIP_SELENIUM_TESTS env var is set."""
    if SKIP_SELENIUM:
        skip_marker = pytest.mark.skip(reason="Selenium tests skipped via SKIP_SELENIUM_TESTS env var")
        for item in items:
            if "selenium" in item.nodeid:
                item.add_marker(skip_marker)


@pytest.fixture(scope="session")
def browser_available():
    """Check if a browser is available for Selenium tests."""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options as ChromeOptions

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
