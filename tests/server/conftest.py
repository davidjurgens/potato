"""
Shared pytest fixtures for server tests.

This module imports common fixtures for test isolation.
"""

import pytest
import os
from pathlib import Path

# Import the reset_state_managers fixture from flask_test_setup
# This ensures state is properly cleared between tests
from tests.helpers.flask_test_setup import reset_state_managers

# Store the project root at module load time - this is the true project root
# before any tests have had a chance to change the cwd
_PROJECT_ROOT = str(Path(__file__).parent.parent.parent.resolve())


@pytest.fixture(autouse=True)
def skip_config_path_validation():
    """Skip config path validation in tests."""
    os.environ['POTATO_SKIP_CONFIG_PATH_VALIDATION'] = '1'
    yield
    os.environ.pop('POTATO_SKIP_CONFIG_PATH_VALIDATION', None)


@pytest.fixture(autouse=True)
def ensure_cwd_restored():
    """Ensure working directory is restored to project root after each test.

    Uses the project root captured at module load time to ensure we always
    restore to the correct directory, even if a previous test changed cwd.
    """
    yield
    try:
        os.chdir(_PROJECT_ROOT)
    except Exception:
        pass  # Directory might not exist
