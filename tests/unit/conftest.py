"""
Shared pytest fixtures for unit tests.

This module provides common fixtures for test isolation.
"""

import pytest
import os
from pathlib import Path

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


_ORIGINAL_CONFIG_SNAPSHOT = None


@pytest.fixture(autouse=True)
def ensure_global_state_available():
    """Restore global config and state managers if a previous test cleared them.

    Some tests (e.g., FlaskTestServer) call clear_config(),
    clear_user_state_manager(), and clear_item_state_manager() which
    destroy the shared state set up by the session-scoped ``app`` fixture.
    This fixture captures the original config once (when it's first
    populated by the ``app`` fixture) and restores it whenever a test
    leaves the config empty or corrupted.
    """
    global _ORIGINAL_CONFIG_SNAPSHOT
    from potato.server_utils.config_module import config

    # Capture the original config the first time we see a fully-populated one
    if _ORIGINAL_CONFIG_SNAPSHOT is None and config.get("annotation_task_name"):
        _ORIGINAL_CONFIG_SNAPSHOT = dict(config)

    # Before the test: restore config if it was cleared by a previous test
    if not config.get("annotation_task_name") and _ORIGINAL_CONFIG_SNAPSHOT:
        config.update(_ORIGINAL_CONFIG_SNAPSHOT)

    yield

    # After the test: restore config if the test cleared it
    if not config.get("annotation_task_name") and _ORIGINAL_CONFIG_SNAPSHOT:
        config.update(_ORIGINAL_CONFIG_SNAPSHOT)

    # Reinitialize state managers if they were cleared
    try:
        from potato.user_state_management import get_user_state_manager, init_user_state_manager
        from potato.item_state_management import get_item_state_manager, init_item_state_manager

        try:
            get_user_state_manager()
        except ValueError:
            init_user_state_manager(config)
        try:
            get_item_state_manager()
        except ValueError:
            init_item_state_manager(config)
    except Exception:
        pass
