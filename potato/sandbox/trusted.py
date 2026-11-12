"""
Trusted sandbox backend -- the escape hatch, with no isolation at all.

For an administrator running the live coding agent on a host they control, with
annotators they trust, where installing a container runtime is not worth it.
The name is deliberate: the previous ``direct`` and ``worktree`` modes read as
though they provided isolation. ``worktree`` in particular does not -- it is a
git worktree on the same host, as the same user, with the same network, and
``cd /`` leaves it.

Selecting this backend requires ``acknowledge_untrusted_code_execution: true``
alongside it; :mod:`potato.sandbox.settings` refuses to build it otherwise.
"""

import logging
import os
import shutil
import subprocess
from typing import List, Optional

from .base import ExecResult, SandboxBackend, SandboxError

logger = logging.getLogger(__name__)


class TrustedBackend(SandboxBackend):
    """Runs agent tools directly on the host, as the Potato user."""

    name = "trusted"
    is_isolated = False

    def __init__(self, base_dir: str, settings):
        super().__init__(base_dir)
        self._base_dir = os.path.abspath(base_dir)
        self._settings = settings
        self._worktree_branch = None  # type: Optional[str]
        self._owns_workspace = False

    def create(self, session_id: str) -> str:
        self._session_id = session_id
        logger.warning(
            "Live coding agent session %s is running in TRUSTED mode: agent "
            "tools execute directly on this host as user %s, with no "
            "isolation.", session_id, _current_user(),
        )

        # `use_worktree` keeps the agent's file edits off the main checkout.
        # That is a workflow convenience, not a security boundary, and it is
        # documented as such.
        if self._settings.use_worktree:
            workspace = self._try_worktree(session_id)
            if workspace:
                self._workspace = workspace
                return workspace

        self._workspace = self._base_dir
        return self._base_dir

    def _try_worktree(self, session_id: str) -> Optional[str]:
        try:
            subprocess.run(["git", "rev-parse", "--git-dir"],
                           cwd=self._base_dir, capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            logger.info("%s is not a git repo; trusted mode will work in place",
                        self._base_dir)
            return None

        branch = "potato-agent-%s" % session_id[:8]
        worktree_dir = os.path.join(os.path.dirname(self._base_dir),
                                    ".potato-sandbox-%s" % session_id[:8])
        try:
            subprocess.run(["git", "branch", branch, "HEAD"],
                           cwd=self._base_dir, capture_output=True, check=True)
            subprocess.run(["git", "worktree", "add", worktree_dir, branch],
                           cwd=self._base_dir, capture_output=True, check=True)
        except (subprocess.CalledProcessError, OSError) as e:
            logger.info("Could not create worktree (%s); working in place", e)
            return None

        self._worktree_branch = branch
        self._owns_workspace = True
        return worktree_dir

    def exec(self, argv: List[str], cwd: Optional[str] = None,
             timeout: int = 60) -> ExecResult:
        workdir = cwd or self._workspace
        real = os.path.realpath(workdir)
        root = os.path.realpath(self._workspace)
        if real != root and not real.startswith(root + os.sep):
            raise SandboxError("Path %r is outside the workspace" % workdir)

        try:
            result = subprocess.run(argv, capture_output=True, text=True,
                                    cwd=real, timeout=timeout)
        except FileNotFoundError as e:
            return ExecResult(127, stderr="Command not found: %s" % e)
        except subprocess.TimeoutExpired:
            return ExecResult(124, timed_out=True)

        return ExecResult(result.returncode, result.stdout or "",
                          result.stderr or "")

    def cleanup(self) -> None:
        if not self._owns_workspace:
            return
        if os.path.realpath(self._workspace) == os.path.realpath(self._base_dir):
            return

        try:
            subprocess.run(
                ["git", "worktree", "remove", self._workspace, "--force"],
                cwd=self._base_dir, capture_output=True,
            )
        except (OSError, subprocess.SubprocessError) as e:
            logger.warning("Failed to remove worktree: %s", e)
            shutil.rmtree(self._workspace, ignore_errors=True)

        if self._worktree_branch:
            try:
                subprocess.run(["git", "branch", "-D", self._worktree_branch],
                               cwd=self._base_dir, capture_output=True)
            except (OSError, subprocess.SubprocessError):
                pass
        self._owns_workspace = False

    def describe(self) -> str:
        detail = "git worktree" if self._worktree_branch else "in place"
        return "trusted -- NO ISOLATION (%s, runs as %s)" % (detail, _current_user())


def _current_user() -> str:
    try:
        import getpass
        return getpass.getuser()
    except Exception:
        return "unknown"
