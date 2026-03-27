"""
Coding Agent Branch Manager

Manages alternative trajectory branches for coding agent sessions.
Each branch is backed by a git branch, enabling independent file states
and conversation histories.

Branch model:
    main ────○──○──○──○──○──○  (original trajectory)
                  │
                  └── branch-1 ──○──○──○  (replayed with new instructions)
                        │
                        └── branch-2 ──○──○  (edited action)
"""

import logging
import os
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TrajectoryBranch:
    """A single branch in the trajectory tree."""
    branch_id: str
    parent_branch_id: Optional[str]
    branch_point_step: Optional[int]  # step where this diverges from parent
    turns: List[Dict[str, Any]]
    git_branch: str
    status: str = "active"  # active, completed, abandoned
    created_at: float = 0.0
    instructions: Optional[str] = None
    edited_actions: Optional[List[Dict]] = None

    def to_dict(self) -> dict:
        return {
            "branch_id": self.branch_id,
            "parent_branch_id": self.parent_branch_id,
            "branch_point_step": self.branch_point_step,
            "turns": self.turns,
            "git_branch": self.git_branch,
            "status": self.status,
            "created_at": self.created_at,
            "instructions": self.instructions,
            "edited_actions": self.edited_actions,
            "turn_count": len(self.turns),
        }


class BranchManager:
    """Manages trajectory branches for a coding agent session."""

    def __init__(self, session_id: str, working_dir: str):
        self._session_id = session_id
        self._working_dir = os.path.abspath(working_dir)
        self._branches: Dict[str, TrajectoryBranch] = {}
        self._active_branch_id: Optional[str] = None

        # Create the main branch
        main = TrajectoryBranch(
            branch_id="main",
            parent_branch_id=None,
            branch_point_step=None,
            turns=[],
            git_branch=f"potato-agent-{session_id[:12]}",
            created_at=time.time(),
        )
        self._branches["main"] = main
        self._active_branch_id = "main"

    @property
    def active_branch(self) -> TrajectoryBranch:
        return self._branches[self._active_branch_id]

    @property
    def active_branch_id(self) -> str:
        return self._active_branch_id

    def create_branch(self, parent_branch_id: str, branch_point_step: int,
                      instructions: Optional[str] = None,
                      edited_actions: Optional[List[Dict]] = None) -> TrajectoryBranch:
        """Create a new branch from a parent at a given step.

        Args:
            parent_branch_id: ID of the parent branch
            branch_point_step: Step index where the branch diverges
            instructions: Optional user instructions for the new branch
            edited_actions: Optional modified tool calls to execute

        Returns:
            The new TrajectoryBranch
        """
        parent = self._branches.get(parent_branch_id)
        if not parent:
            raise ValueError(f"Parent branch '{parent_branch_id}' not found")

        branch_id = f"branch-{len(self._branches)}"
        git_branch = f"potato-agent-{self._session_id[:8]}-{branch_id}"

        # Create git branch from parent's state at branch_point_step
        try:
            # First, ensure we're on the parent branch
            self._run_git("checkout", parent.git_branch)

            # Find the commit at branch_point_step
            # We use git log to find commits with [potato] step=N
            log = self._run_git("log", "--oneline", "--all")
            target_commit = None
            for line in log.strip().split("\n"):
                if f"step={branch_point_step}" in line:
                    target_commit = line.split()[0]
                    break

            if target_commit:
                self._run_git("checkout", "-b", git_branch, target_commit)
            else:
                # Fallback: branch from current HEAD
                self._run_git("checkout", "-b", git_branch)
                logger.warning(f"Could not find commit for step {branch_point_step}, branching from HEAD")

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to create git branch: {e}")
            # Create branch without git backing
            git_branch = parent.git_branch

        # Copy turns up to branch point
        branch_turns = list(parent.turns[:branch_point_step + 1])

        branch = TrajectoryBranch(
            branch_id=branch_id,
            parent_branch_id=parent_branch_id,
            branch_point_step=branch_point_step,
            turns=branch_turns,
            git_branch=git_branch,
            created_at=time.time(),
            instructions=instructions,
            edited_actions=edited_actions,
        )
        self._branches[branch_id] = branch
        self._active_branch_id = branch_id

        logger.info(f"Created branch {branch_id} from {parent_branch_id} at step {branch_point_step}")
        return branch

    def switch_branch(self, branch_id: str) -> bool:
        """Switch to a different branch."""
        if branch_id not in self._branches:
            return False

        branch = self._branches[branch_id]

        try:
            self._run_git("checkout", branch.git_branch)
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to switch git branch: {e}")

        self._active_branch_id = branch_id
        logger.info(f"Switched to branch {branch_id}")
        return True

    def add_turn_to_active(self, turn: Dict[str, Any]) -> None:
        """Add a turn to the active branch."""
        self.active_branch.turns.append(turn)

    def get_branch(self, branch_id: str) -> Optional[TrajectoryBranch]:
        return self._branches.get(branch_id)

    def list_branches(self) -> List[dict]:
        return [b.to_dict() for b in self._branches.values()]

    def get_branch_tree(self) -> dict:
        """Return tree structure for UI rendering."""
        tree = {}
        for bid, branch in self._branches.items():
            tree[bid] = {
                "branch_id": bid,
                "parent": branch.parent_branch_id,
                "branch_point": branch.branch_point_step,
                "turns": len(branch.turns),
                "status": branch.status,
                "instructions": branch.instructions,
                "is_active": bid == self._active_branch_id,
            }
        return tree

    def save_all(self) -> dict:
        """Serialize all branches for trace export."""
        return {
            bid: branch.to_dict()
            for bid, branch in self._branches.items()
        }

    def _run_git(self, *args) -> str:
        result = subprocess.run(
            ["git"] + list(args),
            cwd=self._working_dir,
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, ["git"] + list(args),
                output=result.stdout, stderr=result.stderr,
            )
        return result.stdout
