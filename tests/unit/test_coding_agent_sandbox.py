"""
Unit tests for SandboxManager.
"""

import os
import pytest
import subprocess
import tempfile

from potato.coding_agent_sandbox import SandboxManager


class TestSandboxManagerDirect:
    def test_direct_mode_returns_base_dir(self):
        sm = SandboxManager(mode="direct", base_dir="/tmp")
        path = sm.create("test-session")
        assert path == "/tmp"
        assert sm.working_dir == "/tmp"

    def test_direct_cleanup_is_noop(self):
        sm = SandboxManager(mode="direct", base_dir="/tmp")
        sm.create("test-session")
        sm.cleanup()  # Should not raise


class TestSandboxManagerWorktree:
    @pytest.fixture
    def git_repo(self):
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", td], capture_output=True, check=True)
            subprocess.run(["git", "-C", td, "config", "user.email", "test@test.com"], capture_output=True)
            subprocess.run(["git", "-C", td, "config", "user.name", "Test"], capture_output=True)
            # Create a file and commit
            with open(os.path.join(td, "test.py"), "w") as f:
                f.write("x = 1\n")
            subprocess.run(["git", "-C", td, "add", "-A"], capture_output=True)
            subprocess.run(["git", "-C", td, "commit", "-m", "init"], capture_output=True)
            yield td

    def test_worktree_creates_separate_dir(self, git_repo):
        sm = SandboxManager(mode="worktree", base_dir=git_repo)
        path = sm.create("test-wt-123")
        assert path != git_repo
        assert os.path.exists(path)
        # File should be in the worktree
        assert os.path.exists(os.path.join(path, "test.py"))
        sm.cleanup()

    def test_worktree_cleanup_removes_dir(self, git_repo):
        sm = SandboxManager(mode="worktree", base_dir=git_repo)
        path = sm.create("test-wt-456")
        assert os.path.exists(path)
        sm.cleanup()
        assert not os.path.exists(path)

    def test_worktree_fallback_non_git(self):
        with tempfile.TemporaryDirectory() as td:
            sm = SandboxManager(mode="worktree", base_dir=td)
            path = sm.create("test")
            # Should fall back to direct mode
            assert path == td
            assert sm.mode == "direct"


class TestSandboxManagerInvalid:
    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="Invalid sandbox mode"):
            SandboxManager(mode="invalid")
