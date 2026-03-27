"""
Coding Agent Checkpoint Manager

Git-based checkpointing for coding agent sessions. Creates lightweight
commits after each file-modifying tool call, enabling rollback to any
previous step.

Uses a dedicated git branch (potato-agent-<session_id>) to avoid
interfering with the user's branches.
"""

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Checkpoint:
    """A snapshot of the working directory state."""
    checkpoint_id: str  # git commit hash
    step_index: int
    tool_name: str
    description: str
    timestamp: float
    files_changed: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "checkpoint_id": self.checkpoint_id,
            "step_index": self.step_index,
            "tool_name": self.tool_name,
            "description": self.description,
            "timestamp": self.timestamp,
            "files_changed": self.files_changed,
        }


class CheckpointManager:
    """Manages git-based checkpoints for a coding agent session."""

    def __init__(self, working_dir: str, session_id: str):
        self._working_dir = os.path.abspath(working_dir)
        self._session_id = session_id
        self._branch_name = f"potato-agent-{session_id[:12]}"
        self._checkpoints: List[Checkpoint] = []
        self._initialized = False

    @property
    def checkpoints(self) -> List[Checkpoint]:
        return list(self._checkpoints)

    def init(self) -> bool:
        """Initialize git repo and create session branch.

        Returns True if initialization succeeded.
        """
        if self._initialized:
            return True

        # Ensure git repo exists
        if not self._is_git_repo():
            try:
                self._run_git("init")
                self._run_git("add", "-A")
                self._run_git("commit", "--allow-empty", "-m", "[potato] init")
            except Exception as e:
                logger.warning(f"Failed to init git repo: {e}")
                return False

        # Create session branch from current HEAD
        try:
            current_branch = self._run_git("rev-parse", "--abbrev-ref", "HEAD").strip()
            self._run_git("checkout", "-b", self._branch_name)
        except subprocess.CalledProcessError:
            # Branch might already exist (session restart)
            try:
                self._run_git("checkout", self._branch_name)
            except subprocess.CalledProcessError as e:
                logger.warning(f"Failed to create/checkout session branch: {e}")
                return False

        # Create initial checkpoint
        try:
            self._run_git("add", "-A")
            self._run_git("commit", "--allow-empty", "-m",
                          f"[potato] session start {self._session_id[:8]}")
            commit_hash = self._get_head_hash()
            self._checkpoints.append(Checkpoint(
                checkpoint_id=commit_hash,
                step_index=-1,
                tool_name="init",
                description="Session start",
                timestamp=time.time(),
            ))
        except Exception as e:
            logger.warning(f"Failed to create initial checkpoint: {e}")

        self._initialized = True
        logger.info(f"CheckpointManager initialized on branch {self._branch_name}")
        return True

    def create_checkpoint(self, step_index: int, tool_name: str,
                          description: str = "") -> Optional[str]:
        """Create a checkpoint after a tool execution.

        Returns the commit hash, or None if no changes to commit.
        """
        if not self._initialized:
            if not self.init():
                return None

        try:
            # Stage all changes
            self._run_git("add", "-A")

            # Check if there are changes to commit
            status = self._run_git("status", "--porcelain")
            if not status.strip():
                # No changes, but still record the checkpoint for rollback
                commit_hash = self._get_head_hash()
                self._checkpoints.append(Checkpoint(
                    checkpoint_id=commit_hash,
                    step_index=step_index,
                    tool_name=tool_name,
                    description=description or f"Step {step_index}: {tool_name}",
                    timestamp=time.time(),
                ))
                return commit_hash

            # Get list of changed files
            changed = [
                line.split(None, 1)[-1].strip()
                for line in status.strip().split("\n")
                if line.strip()
            ]

            # Commit
            msg = f"[potato] step={step_index} tool={tool_name}"
            if description:
                msg += f" {description}"
            self._run_git("commit", "-m", msg)

            commit_hash = self._get_head_hash()
            checkpoint = Checkpoint(
                checkpoint_id=commit_hash,
                step_index=step_index,
                tool_name=tool_name,
                description=description or f"Step {step_index}: {tool_name}",
                timestamp=time.time(),
                files_changed=changed,
            )
            self._checkpoints.append(checkpoint)

            logger.debug(f"Created checkpoint {commit_hash[:8]} at step {step_index}")
            return commit_hash

        except Exception as e:
            logger.warning(f"Failed to create checkpoint: {e}")
            return None

    def rollback_to(self, step_index: int) -> bool:
        """Rollback to the checkpoint at the given step index.

        Returns True if rollback succeeded.
        """
        # Find the checkpoint
        target = None
        for cp in self._checkpoints:
            if cp.step_index == step_index:
                target = cp
                break
            if cp.step_index <= step_index:
                target = cp  # Use the latest checkpoint at or before step_index

        if not target:
            logger.warning(f"No checkpoint found at or before step {step_index}")
            return False

        try:
            self._run_git("reset", "--hard", target.checkpoint_id)

            # Truncate checkpoint list
            self._checkpoints = [
                cp for cp in self._checkpoints
                if cp.step_index <= step_index
            ]

            logger.info(f"Rolled back to step {step_index} (commit {target.checkpoint_id[:8]})")
            return True

        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            return False

    def get_diff_between(self, from_step: int, to_step: int) -> str:
        """Get the git diff between two checkpoints."""
        from_cp = self._find_checkpoint(from_step)
        to_cp = self._find_checkpoint(to_step)
        if not from_cp or not to_cp:
            return ""

        try:
            return self._run_git("diff", from_cp.checkpoint_id, to_cp.checkpoint_id)
        except Exception:
            return ""

    def get_diff_since(self, step_index: int) -> str:
        """Get the diff from a checkpoint to current HEAD."""
        cp = self._find_checkpoint(step_index)
        if not cp:
            return ""
        try:
            return self._run_git("diff", cp.checkpoint_id, "HEAD")
        except Exception:
            return ""

    def get_file_at(self, step_index: int, file_path: str) -> Optional[str]:
        """Get file contents at a specific checkpoint."""
        cp = self._find_checkpoint(step_index)
        if not cp:
            return None
        try:
            return self._run_git("show", f"{cp.checkpoint_id}:{file_path}")
        except Exception:
            return None

    def list_checkpoints(self) -> List[dict]:
        """Return checkpoint metadata as list of dicts."""
        return [cp.to_dict() for cp in self._checkpoints]

    def cleanup(self) -> None:
        """Clean up the session branch."""
        if not self._initialized:
            return

        try:
            # Switch back to the original branch
            branches = self._run_git("branch", "--list").strip().split("\n")
            main_branch = None
            for b in branches:
                name = b.strip().lstrip("* ")
                if name and name != self._branch_name:
                    main_branch = name
                    break

            if main_branch:
                self._run_git("checkout", main_branch)
                self._run_git("branch", "-D", self._branch_name)
                logger.info(f"Cleaned up session branch {self._branch_name}")
        except Exception as e:
            logger.warning(f"Failed to clean up session branch: {e}")

    def _find_checkpoint(self, step_index: int) -> Optional[Checkpoint]:
        for cp in self._checkpoints:
            if cp.step_index == step_index:
                return cp
        return None

    def _is_git_repo(self) -> bool:
        try:
            self._run_git("rev-parse", "--git-dir")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def _get_head_hash(self) -> str:
        return self._run_git("rev-parse", "HEAD").strip()

    def _run_git(self, *args) -> str:
        result = subprocess.run(
            ["git"] + list(args),
            cwd=self._working_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, ["git"] + list(args),
                output=result.stdout, stderr=result.stderr,
            )
        return result.stdout
