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


@pytest.fixture(scope="package", autouse=True)
def per_worker_generated_templates():
    """Give each xdist worker its own generated-templates directory.

    Potato bakes each task's page into <templates>/generated, named after the
    annotation_task_name only. Most server tests keep the default "Test Task",
    so two workers serving different schemes overwrite one file, and a page
    can render the other worker's schemes. A serial run has one server at a
    time and keeps the shared directory.
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if not worker:
        yield
        return
    import shutil
    import tempfile
    from potato.server_utils.generated_templates import ENV_VAR
    previous = os.environ.get(ENV_VAR)
    path = tempfile.mkdtemp(prefix=f"potato-generated-{worker}-")
    os.environ[ENV_VAR] = path
    yield
    if previous is None:
        os.environ.pop(ENV_VAR, None)
    else:
        os.environ[ENV_VAR] = previous
    shutil.rmtree(path, ignore_errors=True)
