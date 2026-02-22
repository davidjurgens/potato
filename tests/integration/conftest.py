"""
Shared fixtures for integration tests.

This module provides:
1. Config file discovery for testing all example configs
2. Temporary directory management
3. Browser session fixtures
4. Server fixtures for different scenarios
"""

import pytest
import os
import sys
import tempfile
import shutil
from pathlib import Path
from typing import Generator, List

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.integration.base import IntegrationTestServer, integration_server


# ==================== Config Discovery ====================

def get_example_configs() -> List[Path]:
    """Get all example config files for testing."""
    examples_dir = PROJECT_ROOT / "examples"
    configs = []

    # Walk through examples/<category>/<name>/config.yaml structure
    for config_file in examples_dir.glob("*/*/config.yaml"):
        # Skip simulator configs and templates
        skip_patterns = [
            "simulator-configs",  # Simulator configs, not server configs
        ]

        if any(pattern in str(config_file) for pattern in skip_patterns):
            continue

        configs.append(config_file)

    return sorted(configs, key=lambda p: p.name)


# Configs with known issues that are expected to fail
# These should be fixed in the configs themselves, not the tests
# Configs with known issues that are expected to fail
# These need to be fixed in the example configs themselves
CONFIGS_WITH_KNOWN_ISSUES = {
    # All example configs now work - no known issues!
}


def get_config_ids() -> List[str]:
    """Get config names for test IDs."""
    return [c.stem for c in get_example_configs()]


# ==================== Pytest Fixtures ====================

@pytest.fixture(scope="session")
def project_root() -> Path:
    """Return the project root directory."""
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def example_configs() -> List[Path]:
    """Return list of all example config files."""
    return get_example_configs()


@pytest.fixture(scope="function")
def temp_output_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """
    Provide a temporary directory for test outputs.

    This fixture creates a fresh directory for each test and
    cleans it up afterward.
    """
    output_dir = tmp_path / "annotation_output"
    output_dir.mkdir(parents=True, exist_ok=True)
    yield output_dir
    # Cleanup happens automatically via tmp_path


@pytest.fixture(scope="function")
def clean_output_dir(project_root: Path) -> Generator[Path, None, None]:
    """
    Create a clean output directory for tests.

    Some tests need to write to actual project directories.
    This fixture manages that safely.
    """
    output_dir = project_root / "tests" / "output" / "integration"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    yield output_dir
    # Optionally clean up after (leave for debugging)


@pytest.fixture(scope="module")
def base_port() -> int:
    """
    Return a base port for tests.

    Each test module should use a different port range to avoid conflicts.
    """
    import random
    # Use a random port in a high range to avoid conflicts
    return random.randint(9100, 9900)


# ==================== Server Fixtures ====================

@pytest.fixture(scope="function")
def server_factory(base_port: int):
    """
    Factory fixture for creating test servers.

    Usage:
        def test_something(server_factory):
            server = server_factory("path/to/config.yaml")
            # server.base_url available
            # server auto-stopped after test
    """
    servers = []
    port_offset = 0

    def _create_server(config_path: str) -> IntegrationTestServer:
        nonlocal port_offset
        server = IntegrationTestServer(config_path, port=base_port + port_offset)
        port_offset += 1
        success, error = server.start()
        if not success:
            pytest.fail(f"Server failed to start: {error}")
        servers.append(server)
        return server

    yield _create_server

    # Cleanup all servers
    for server in servers:
        server.stop()


# ==================== Browser Fixtures ====================

@pytest.fixture(scope="function")
def chrome_options():
    """Return Chrome options configured for testing."""
    from selenium.webdriver.chrome.options import Options

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    return options


@pytest.fixture(scope="function")
def browser(chrome_options):
    """
    Provide a Chrome WebDriver instance.

    The browser is quit automatically after the test.
    """
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException

    try:
        driver = webdriver.Chrome(options=chrome_options)
        driver.implicitly_wait(5)
    except WebDriverException as e:
        pytest.skip(f"Chrome WebDriver not available: {e}")

    yield driver

    driver.quit()


# ==================== Test User Fixtures ====================

@pytest.fixture(scope="function")
def test_user() -> dict:
    """Generate unique test user credentials."""
    import time
    timestamp = int(time.time() * 1000)
    return {
        "username": f"test_user_{timestamp}",
        "password": "test_password_123"
    }


# ==================== Parametrized Config Fixture ====================

def pytest_generate_tests(metafunc):
    """
    Generate test cases for each config file.

    Tests that use the 'config_file' fixture will be parametrized
    to run once for each example config.
    """
    if "config_file" in metafunc.fixturenames:
        configs = get_example_configs()
        ids = [c.stem for c in configs]
        metafunc.parametrize("config_file", configs, ids=ids)


# ==================== Markers ====================

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "smoke: marks tests as smoke tests (fast, critical path)"
    )
    config.addinivalue_line(
        "markers", "workflow: marks tests as workflow tests (complete user journeys)"
    )
    config.addinivalue_line(
        "markers", "e2e: marks tests as end-to-end tests (full annotation cycle)"
    )
    config.addinivalue_line(
        "markers", "persistence: marks tests as persistence tests (state preservation)"
    )
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (may take >30s)"
    )
    config.addinivalue_line(
        "markers", "edge_case: marks tests as edge case tests (boundary conditions)"
    )


def pytest_collection_modifyitems(config, items):
    """
    Mark all integration tests as slow.

    Integration tests typically involve starting servers and browsers,
    which takes significant time.
    """
    slow_marker = pytest.mark.slow

    for item in items:
        if "integration" in item.nodeid:
            item.add_marker(slow_marker)
