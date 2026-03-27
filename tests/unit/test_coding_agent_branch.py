"""
Unit tests for BranchManager.
"""

import os
import pytest
import subprocess
import tempfile

from potato.coding_agent_branch import BranchManager, TrajectoryBranch


class TestBranchManager:
    @pytest.fixture
    def git_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", td], capture_output=True, check=True)
            subprocess.run(["git", "-C", td, "config", "user.email", "test@test.com"], capture_output=True)
            subprocess.run(["git", "-C", td, "config", "user.name", "Test"], capture_output=True)
            subprocess.run(["git", "-C", td, "commit", "--allow-empty", "-m", "init"], capture_output=True)
            subprocess.run(["git", "-C", td, "checkout", "-b", "potato-agent-test12345"], capture_output=True)
            yield td

    def test_init_creates_main_branch(self, git_workspace):
        bm = BranchManager("test1234567890", git_workspace)
        assert bm.active_branch_id == "main"
        assert len(bm.list_branches()) == 1

    def test_main_branch_metadata(self, git_workspace):
        bm = BranchManager("test1234567890", git_workspace)
        main = bm.get_branch("main")
        assert main is not None
        assert main.parent_branch_id is None
        assert main.branch_point_step is None

    def test_create_branch(self, git_workspace):
        bm = BranchManager("test1234567890", git_workspace)
        bm.active_branch.turns = [{"role": "assistant", "content": "step 0"}, {"role": "assistant", "content": "step 1"}]

        branch = bm.create_branch("main", 0, instructions="Try differently")
        assert branch.branch_id == "branch-1"
        assert branch.parent_branch_id == "main"
        assert branch.branch_point_step == 0
        assert branch.instructions == "Try differently"
        assert len(branch.turns) == 1  # Only turns up to branch point

    def test_create_branch_switches_active(self, git_workspace):
        bm = BranchManager("test1234567890", git_workspace)
        bm.active_branch.turns = [{"role": "assistant", "content": "step 0"}]

        branch = bm.create_branch("main", 0)
        assert bm.active_branch_id == branch.branch_id

    def test_switch_branch(self, git_workspace):
        bm = BranchManager("test1234567890", git_workspace)
        bm.active_branch.turns = [{"role": "assistant", "content": "step 0"}]

        bm.create_branch("main", 0)
        assert bm.active_branch_id != "main"

        assert bm.switch_branch("main")
        assert bm.active_branch_id == "main"

    def test_switch_nonexistent(self, git_workspace):
        bm = BranchManager("test1234567890", git_workspace)
        assert not bm.switch_branch("nonexistent")

    def test_add_turn_to_active(self, git_workspace):
        bm = BranchManager("test1234567890", git_workspace)
        bm.add_turn_to_active({"role": "assistant", "content": "hello"})
        assert len(bm.active_branch.turns) == 1

    def test_list_branches(self, git_workspace):
        bm = BranchManager("test1234567890", git_workspace)
        bm.active_branch.turns = [{"role": "assistant", "content": "step 0"}]
        bm.create_branch("main", 0)

        branches = bm.list_branches()
        assert len(branches) == 2
        assert all("branch_id" in b for b in branches)

    def test_get_branch_tree(self, git_workspace):
        bm = BranchManager("test1234567890", git_workspace)
        bm.active_branch.turns = [{"role": "assistant", "content": "s0"}, {"role": "assistant", "content": "s1"}]
        bm.create_branch("main", 0, instructions="alt path")

        tree = bm.get_branch_tree()
        assert "main" in tree
        assert "branch-1" in tree
        assert tree["branch-1"]["parent"] == "main"
        assert tree["branch-1"]["branch_point"] == 0

    def test_save_all(self, git_workspace):
        bm = BranchManager("test1234567890", git_workspace)
        bm.active_branch.turns = [{"role": "assistant", "content": "s0"}]
        bm.create_branch("main", 0)

        saved = bm.save_all()
        assert "main" in saved
        assert "branch-1" in saved
        assert "turns" in saved["main"]

    def test_create_branch_with_edited_actions(self, git_workspace):
        bm = BranchManager("test1234567890", git_workspace)
        bm.active_branch.turns = [{"role": "assistant", "content": "s0"}]

        edited = [{"tool": "Edit", "input": {"file_path": "x.py"}}]
        branch = bm.create_branch("main", 0, edited_actions=edited)
        assert branch.edited_actions == edited

    def test_invalid_parent(self, git_workspace):
        bm = BranchManager("test1234567890", git_workspace)
        with pytest.raises(ValueError, match="not found"):
            bm.create_branch("nonexistent", 0)


class TestTrajectoryBranch:
    def test_to_dict(self):
        branch = TrajectoryBranch(
            branch_id="b1",
            parent_branch_id="main",
            branch_point_step=3,
            turns=[{"role": "assistant"}],
            git_branch="potato-agent-x-b1",
            status="active",
            instructions="try again",
        )
        d = branch.to_dict()
        assert d["branch_id"] == "b1"
        assert d["parent_branch_id"] == "main"
        assert d["turn_count"] == 1
        assert d["instructions"] == "try again"
