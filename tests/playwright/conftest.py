"""
Pytest fixtures for Playwright-based browser tests.

Provides server lifecycle management and browser context isolation.
Each test gets a fresh browser context (cookies/storage cleared) while
sharing a single browser instance per session for speed.

Usage:
    @pytest.mark.playwright
    class TestMyFeature:
        def test_something(self, page, server):
            page.goto(f"{server.base_url}/annotate")
            # ... test logic ...
"""

import os
import time
import pytest

# Skip entire module if playwright is not installed
try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import create_test_directory, create_test_data_file, create_test_config


# ---------- marks ----------

def pytest_configure(config):
    config.addinivalue_line("markers", "playwright: mark test as requiring Playwright browser")


def pytest_collection_modifyitems(config, items):
    if not HAS_PLAYWRIGHT:
        skip_pw = pytest.mark.skip(reason="playwright not installed (pip install pytest-playwright)")
        for item in items:
            if "playwright" in item.keywords or "tests/playwright" in str(item.fspath):
                item.add_marker(skip_pw)


# ---------- browser fixtures ----------

@pytest.fixture(scope="session")
def browser_instance():
    """Session-scoped browser — launched once, shared across all tests."""
    if not HAS_PLAYWRIGHT:
        pytest.skip("playwright not installed")

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
    )
    yield browser
    browser.close()
    pw.stop()


@pytest.fixture
def context(browser_instance):
    """Fresh browser context per test — isolated cookies, storage, cache."""
    ctx = browser_instance.new_context(
        viewport={"width": 1920, "height": 1080},
        ignore_https_errors=True,
    )
    yield ctx
    ctx.close()


@pytest.fixture
def page(context):
    """Single page within the isolated context."""
    pg = context.new_page()
    yield pg
    pg.close()


# ---------- server fixtures ----------

def _make_server(annotation_schemes, port=None, extra_config=None):
    """Helper to build and start a FlaskTestServer with given schemes."""
    test_dir = create_test_directory("playwright")
    data_file = create_test_data_file(test_dir)
    config_file = create_test_config(
        test_dir,
        annotation_schemes=annotation_schemes,
        data_file=data_file,
        annotation_task_name="Playwright Test",
    )

    if port is None:
        port = find_free_port()

    srv = FlaskTestServer(port=port, debug=False, config_file=config_file)
    if not srv.start():
        raise RuntimeError("Failed to start Flask server for Playwright tests")
    return srv


@pytest.fixture(scope="session")
def _default_server():
    """Session-scoped default server with a simple radio schema."""
    schemes = [
        {
            "annotation_type": "radio",
            "name": "sentiment",
            "description": "Sentiment",
            "labels": ["positive", "negative", "neutral"],
        }
    ]
    srv = _make_server(schemes)
    yield srv
    srv.stop()


@pytest.fixture
def server(_default_server):
    """Per-test alias so tests can declare `server` as a fixture."""
    return _default_server


@pytest.fixture
def make_server():
    """Factory fixture — call to create a server with custom annotation schemes.

    Usage:
        def test_custom(make_server, page):
            srv = make_server([{"annotation_type": "pairwise", ...}])
            page.goto(f"{srv.base_url}/annotate")
    """
    servers = []

    def _factory(annotation_schemes, **kwargs):
        srv = _make_server(annotation_schemes, **kwargs)
        servers.append(srv)
        return srv

    yield _factory

    for s in servers:
        s.stop()
