"""
Tests for the deprecated coding agent sandbox shim.

``SandboxManager`` and its three modes were replaced by the backend ladder in
:mod:`potato.sandbox`; the behaviour of the ladder itself lives in
``tests/unit/test_sandbox_ladder.py``. What is left to check here is that the
old entry point fails loudly rather than appearing to work, since the failure
it used to have was precisely "looks like it worked, provides no isolation".
"""

import pytest

from potato.coding_agent_sandbox import SandboxManager
from potato.sandbox import SandboxError


class TestDeprecatedSandboxManager:
    def test_constructing_it_raises(self):
        with pytest.raises(SandboxError):
            SandboxManager(mode="direct", base_dir="/tmp")

    def test_error_names_the_replacement(self):
        with pytest.raises(SandboxError) as exc:
            SandboxManager(mode="worktree", base_dir="/tmp")
        message = str(exc.value)
        assert "potato.sandbox" in message
        assert "create_backend" in message

    def test_error_explains_why_docker_mode_was_unsafe(self):
        # The old `docker` mode logged a warning and ran tools on the host.
        with pytest.raises(SandboxError) as exc:
            SandboxManager(mode="docker", base_dir="/tmp")
        assert "never implemented" in str(exc.value)


class TestShimReExports:
    """Existing imports keep resolving."""

    def test_re_exports_the_new_api(self):
        from potato.coding_agent_sandbox import (  # noqa: F401
            SandboxBackend, SandboxSettings, create_backend,
        )
