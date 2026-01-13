"""
Shared pytest fixtures for server tests.

This module imports common fixtures for test isolation.
"""

import pytest
import os

# Import the reset_state_managers fixture from flask_test_setup
# This ensures state is properly cleared between tests
from tests.helpers.flask_test_setup import reset_state_managers


@pytest.fixture(autouse=True)
def ensure_cwd_restored():
    """Ensure working directory is restored after each test."""
    original_cwd = os.getcwd()
    yield
    try:
        os.chdir(original_cwd)
    except Exception:
        pass  # Directory might not exist
