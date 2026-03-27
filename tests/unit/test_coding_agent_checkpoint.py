"""
Unit tests for CheckpointManager.
"""

import os
import pytest
import subprocess
import tempfile

from potato.coding_agent_checkpoint import CheckpointManager, Checkpoint


class TestCheckpointManager:
    @pytest.fixture
    def git_workspace(self):
        """Create a temporary git repo with an initial file."""
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", td], capture_output=True, check=True)
            subprocess.run(["git", "-C", td, "config", "user.email", "test@test.com"], capture_output=True)
            subprocess.run(["git", "-C", td, "config", "user.name", "Test"], capture_output=True)

            # Create initial file
            with open(os.path.join(td, "main.py"), "w") as f:
                f.write("x = 1\n")
            subprocess.run(["git", "-C", td, "add", "-A"], capture_output=True)
            subprocess.run(["git", "-C", td, "commit", "-m", "initial"], capture_output=True)
            yield td

    def test_init(self, git_workspace):
        cm = CheckpointManager(git_workspace, "test-session")
        assert cm.init()
        # Should have created the session branch
        result = subprocess.run(
            ["git", "-C", git_workspace, "branch", "--list"],
            capture_output=True, text=True,
        )
        assert "potato-agent-" in result.stdout

    def test_create_checkpoint(self, git_workspace):
        cm = CheckpointManager(git_workspace, "test-session")
        cm.init()

        # Modify a file
        with open(os.path.join(git_workspace, "main.py"), "w") as f:
            f.write("x = 2\n")

        cp = cm.create_checkpoint(0, "Edit", "Modified main.py")
        assert cp is not None
        assert len(cm.checkpoints) >= 2  # init + this one

    def test_create_checkpoint_no_changes(self, git_workspace):
        cm = CheckpointManager(git_workspace, "test-session")
        cm.init()

        # No changes made
        cp = cm.create_checkpoint(0, "Read", "Just read a file")
        assert cp is not None  # Still records the checkpoint
        assert len(cm.checkpoints) >= 2

    def test_rollback(self, git_workspace):
        cm = CheckpointManager(git_workspace, "test-session")
        cm.init()

        # Step 0: edit
        with open(os.path.join(git_workspace, "main.py"), "w") as f:
            f.write("x = 2\n")
        cm.create_checkpoint(0, "Edit")

        # Step 1: another edit
        with open(os.path.join(git_workspace, "main.py"), "w") as f:
            f.write("x = 3\n")
        cm.create_checkpoint(1, "Edit")

        # Rollback to step 0
        assert cm.rollback_to(0)

        with open(os.path.join(git_workspace, "main.py")) as f:
            content = f.read()
        assert content == "x = 2\n"

        # Checkpoints should be truncated
        assert all(cp.step_index <= 0 for cp in cm.checkpoints)

    def test_rollback_to_init(self, git_workspace):
        cm = CheckpointManager(git_workspace, "test-session")
        cm.init()

        # Make some changes
        with open(os.path.join(git_workspace, "main.py"), "w") as f:
            f.write("x = 99\n")
        cm.create_checkpoint(0, "Edit")

        # Rollback to init (step -1)
        assert cm.rollback_to(-1)

        with open(os.path.join(git_workspace, "main.py")) as f:
            content = f.read()
        assert content == "x = 1\n"

    def test_list_checkpoints(self, git_workspace):
        cm = CheckpointManager(git_workspace, "test-session")
        cm.init()

        with open(os.path.join(git_workspace, "main.py"), "w") as f:
            f.write("x = 2\n")
        cm.create_checkpoint(0, "Edit")

        cps = cm.list_checkpoints()
        assert isinstance(cps, list)
        assert len(cps) >= 2
        assert all("checkpoint_id" in cp for cp in cps)
        assert all("step_index" in cp for cp in cps)

    def test_get_file_at(self, git_workspace):
        cm = CheckpointManager(git_workspace, "test-session")
        cm.init()

        with open(os.path.join(git_workspace, "main.py"), "w") as f:
            f.write("x = 2\n")
        cm.create_checkpoint(0, "Edit")

        with open(os.path.join(git_workspace, "main.py"), "w") as f:
            f.write("x = 3\n")
        cm.create_checkpoint(1, "Edit")

        # Get file at step 0
        content = cm.get_file_at(0, "main.py")
        assert content is not None
        assert "x = 2" in content

    def test_cleanup(self, git_workspace):
        cm = CheckpointManager(git_workspace, "test-session")
        cm.init()
        cm.cleanup()

        # Session branch should be removed
        result = subprocess.run(
            ["git", "-C", git_workspace, "branch", "--list"],
            capture_output=True, text=True,
        )
        assert "potato-agent-test" not in result.stdout

    def test_non_git_dir(self):
        """CheckpointManager should handle non-git directories."""
        with tempfile.TemporaryDirectory() as td:
            cm = CheckpointManager(td, "test")
            # Should init a new git repo
            assert cm.init()


class TestCheckpointDataclass:
    def test_to_dict(self):
        cp = Checkpoint(
            checkpoint_id="abc123",
            step_index=0,
            tool_name="Edit",
            description="test",
            timestamp=1234.5,
            files_changed=["main.py"],
        )
        d = cp.to_dict()
        assert d["checkpoint_id"] == "abc123"
        assert d["step_index"] == 0
        assert d["files_changed"] == ["main.py"]
