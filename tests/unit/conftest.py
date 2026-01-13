"""
Shared pytest fixtures for unit tests.

This module provides common fixtures for test isolation.
"""

import pytest
import os


@pytest.fixture(autouse=True)
def skip_config_path_validation():
    """Skip config path validation in tests."""
    os.environ['POTATO_SKIP_CONFIG_PATH_VALIDATION'] = '1'
    yield
    os.environ.pop('POTATO_SKIP_CONFIG_PATH_VALIDATION', None)


@pytest.fixture(autouse=True)
def ensure_cwd_restored():
    """Ensure working directory is restored after each test."""
    original_cwd = os.getcwd()
    yield
    try:
        os.chdir(original_cwd)
    except Exception:
        pass  # Directory might not exist
