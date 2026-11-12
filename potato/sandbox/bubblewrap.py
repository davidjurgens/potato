"""
Bubblewrap sandbox backend.

For hosts where a container runtime is not an option. Potato's users are
frequently on shared university machines and HPC clusters where Docker is
unavailable and rootless Podman is impractical -- it wants ``/etc/subuid``
entries and struggles on NFS home directories. ``bwrap`` was built for exactly
that case: no daemon, no root, no setuid binary on modern kernels.

It is a weaker boundary than a container and sits below one on the ladder
accordingly: no cgroup limits, and it depends on unprivileged user namespaces,
which some hardened kernels disable. :meth:`preflight` checks for that rather
than letting it surface at the first tool call.
"""

import logging
import os
import shutil
import subprocess
from typing import List, Optional

from .base import ExecResult, SandboxBackend, SandboxError

logger = logging.getLogger(__name__)

USERNS_SYSCTL = "/proc/sys/kernel/unprivileged_userns_clone"


def _userns_available() -> Optional[str]:
    """Why unprivileged user namespaces are unusable, or None when fine."""
    # Debian-family kernels expose this toggle; its absence is not a problem,
    # since mainline enables unprivileged userns by default.
    try:
        if os.path.exists(USERNS_SYSCTL):
            with open(USERNS_SYSCTL, "r") as f:
                if f.read().strip() == "0":
                    return (
                        "unprivileged user namespaces are disabled on this "
                        "kernel (%s is 0)" % USERNS_SYSCTL
                    )
    except OSError:
        pass
    return None


class BubblewrapBackend(SandboxBackend):
    """Runs agent tools under ``bwrap`` with a minimal read-only root."""

    name = "bubblewrap"
    is_isolated = True

    def __init__(self, base_dir: str, settings):
        super().__init__(base_dir)
        self._base_dir = os.path.abspath(base_dir)
        self._settings = settings
        self._owns_workspace = False

    @classmethod
    def preflight(cls, settings) -> Optional[str]:
        if shutil.which("bwrap") is None:
            return (
                "bwrap is not installed or not on PATH. Install bubblewrap "
                "(package `bubblewrap` on most distributions), or use "
                "`sandbox_mode: container`."
            )
        userns = _userns_available()
        if userns:
            return (
                "%s, so bubblewrap cannot create a sandbox. Use "
                "`sandbox_mode: container` instead." % userns
            )
        return None

    def create(self, session_id: str) -> str:
        self._session_id = session_id

        reason = self.preflight(self._settings)
        if reason:
            raise SandboxError("Cannot start a bubblewrap sandbox: %s" % reason)

        from .container import COPY_IGNORE

        root = self._settings.resolve_sandbox_root(self._base_dir)
        workspace = os.path.join(root, session_id[:12])
        if os.path.exists(workspace):
            shutil.rmtree(workspace, ignore_errors=True)
        os.makedirs(root, exist_ok=True)
        try:
            shutil.copytree(self._base_dir, workspace,
                            ignore=shutil.ignore_patterns(*COPY_IGNORE),
                            symlinks=False)
        except OSError as e:
            raise SandboxError(
                "Failed to prepare sandbox workspace at %s: %s" % (workspace, e)
            )

        self._owns_workspace = True
        self._workspace = workspace
        logger.info("Bubblewrap sandbox workspace at %s", workspace)
        return workspace

    def _bwrap_args(self, workdir: str) -> List[str]:
        """Read-only system directories, writable workspace, nothing else."""
        args = [
            "bwrap",
            "--unshare-all",          # user, pid, net, ipc, uts, cgroup
            "--die-with-parent",
            "--new-session",          # no TIOCSTI terminal injection
            "--proc", "/proc",
            "--dev", "/dev",
            "--tmpfs", "/tmp",
        ]
        # Bind whatever of the usual read-only system tree actually exists;
        # distributions differ, and binding a missing path is a hard error.
        for path in ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc"):
            if os.path.exists(path):
                args += ["--ro-bind", path, path]

        args += [
            "--bind", self._workspace, self._workspace,
            "--chdir", workdir,
            "--setenv", "HOME", self._workspace,
            "--setenv", "PATH", "/usr/bin:/bin",
        ]
        return args

    def exec(self, argv: List[str], cwd: Optional[str] = None,
             timeout: int = 60) -> ExecResult:
        if not self._workspace:
            raise SandboxError("Bubblewrap sandbox is not prepared")

        workdir = cwd or self._workspace
        real = os.path.realpath(workdir)
        root = os.path.realpath(self._workspace)
        if real != root and not real.startswith(root + os.sep):
            raise SandboxError("Path %r is outside the sandbox workspace" % workdir)

        command = self._bwrap_args(real) + list(argv)
        try:
            result = subprocess.run(command, capture_output=True, text=True,
                                    timeout=timeout)
        except FileNotFoundError:
            raise SandboxError("bwrap is not installed or not on PATH")
        except subprocess.TimeoutExpired:
            return ExecResult(124, timed_out=True)

        return ExecResult(result.returncode, result.stdout or "",
                          result.stderr or "")

    def cleanup(self) -> None:
        if self._owns_workspace and os.path.realpath(
                self._workspace) != os.path.realpath(self._base_dir):
            shutil.rmtree(self._workspace, ignore_errors=True)
            self._owns_workspace = False

    def describe(self) -> str:
        return "bubblewrap (no network, read-only system dirs)"
