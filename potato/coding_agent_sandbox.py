"""
Coding Agent Sandbox Manager

Manages isolated working directories for coding agent sessions.
Supports three modes:
- worktree: git worktree (lightweight copy, requires git repo)
- docker: Docker container with mounted workspace
- direct: No isolation (works directly in working_dir)
"""

import logging
import os
import shutil
import subprocess
import uuid
from typing import Optional

logger = logging.getLogger(__name__)


class SandboxManager:
    """Manages sandboxed working directories for agent sessions."""

    def __init__(self, mode: str = "worktree", base_dir: str = "."):
        """Initialize the sandbox manager.

        Args:
            mode: Sandbox mode — "worktree", "docker", or "direct"
            base_dir: Base directory for creating sandboxes
        """
        if mode not in ("worktree", "docker", "direct"):
            raise ValueError(f"Invalid sandbox mode: {mode}. Must be worktree, docker, or direct.")
        self._mode = mode
        self._base_dir = os.path.abspath(base_dir)
        self._sandbox_dir: Optional[str] = None
        self._session_id: Optional[str] = None
        self._worktree_branch: Optional[str] = None

    @property
    def working_dir(self) -> str:
        """The working directory for the agent."""
        return self._sandbox_dir or self._base_dir

    @property
    def mode(self) -> str:
        return self._mode

    def create(self, session_id: str) -> str:
        """Create a sandbox for the given session.

        Returns:
            The working directory path.
        """
        self._session_id = session_id

        if self._mode == "worktree":
            return self._create_worktree(session_id)
        elif self._mode == "docker":
            return self._create_docker(session_id)
        else:  # direct
            self._sandbox_dir = self._base_dir
            return self._base_dir

    def cleanup(self) -> None:
        """Clean up the sandbox."""
        if self._mode == "worktree":
            self._cleanup_worktree()
        elif self._mode == "docker":
            self._cleanup_docker()
        # direct mode: nothing to clean up

    def _create_worktree(self, session_id: str) -> str:
        """Create a git worktree for isolation."""
        # Check if base_dir is a git repo
        try:
            subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=self._base_dir, capture_output=True, check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning(
                f"Directory {self._base_dir} is not a git repo. "
                f"Falling back to direct mode."
            )
            self._mode = "direct"
            self._sandbox_dir = self._base_dir
            return self._base_dir

        # Create worktree in a temp location
        branch_name = f"potato-agent-{session_id[:8]}"
        worktree_dir = os.path.join(
            os.path.dirname(self._base_dir),
            f".potato-sandbox-{session_id[:8]}",
        )

        try:
            # Create a new branch from HEAD
            subprocess.run(
                ["git", "branch", branch_name, "HEAD"],
                cwd=self._base_dir, capture_output=True, check=True,
            )

            # Create worktree
            subprocess.run(
                ["git", "worktree", "add", worktree_dir, branch_name],
                cwd=self._base_dir, capture_output=True, check=True,
            )

            self._sandbox_dir = worktree_dir
            self._worktree_branch = branch_name
            logger.info(f"Created git worktree sandbox at {worktree_dir}")
            return worktree_dir

        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to create worktree: {e}. Falling back to direct mode.")
            self._mode = "direct"
            self._sandbox_dir = self._base_dir
            return self._base_dir

    def _cleanup_worktree(self) -> None:
        """Remove the git worktree and branch."""
        if not self._sandbox_dir or self._sandbox_dir == self._base_dir:
            return

        try:
            # Remove worktree
            subprocess.run(
                ["git", "worktree", "remove", self._sandbox_dir, "--force"],
                cwd=self._base_dir, capture_output=True,
            )
            logger.info(f"Removed worktree at {self._sandbox_dir}")
        except Exception as e:
            logger.warning(f"Failed to remove worktree: {e}")
            # Manual cleanup
            if os.path.exists(self._sandbox_dir):
                shutil.rmtree(self._sandbox_dir, ignore_errors=True)

        # Clean up the branch
        if self._worktree_branch:
            try:
                subprocess.run(
                    ["git", "branch", "-D", self._worktree_branch],
                    cwd=self._base_dir, capture_output=True,
                )
            except Exception:
                pass

    def _create_docker(self, session_id: str) -> str:
        """Create a Docker container for maximum isolation."""
        # For Phase 4 — placeholder
        logger.warning("Docker sandbox not yet implemented. Using direct mode.")
        self._mode = "direct"
        self._sandbox_dir = self._base_dir
        return self._base_dir

    def _cleanup_docker(self) -> None:
        """Remove Docker container."""
        pass  # Phase 4
