"""
Container sandbox backend.

Drives the ``docker`` or ``podman`` CLI directly. One implementation covers
both, plus every drop-in container runtime: gVisor (``runtime: runsc``) and Kata
(``runtime: kata``) install as alternative runtimes, so upgrading from namespace
isolation to a userspace kernel or a hardware VM is a config key here rather
than new code.
"""

import logging
import os
import shutil
from typing import List, Optional

from potato.server_utils.container_utils import (
    ContainerError,
    remove_container,
    list_containers_with_prefix,
    run as run_cli,
    unavailable_reason,
)
from .base import ExecResult, SandboxBackend, SandboxError

logger = logging.getLogger(__name__)

CONTAINER_PREFIX = "potato-agent-"
MOUNT_POINT = "/workspace"

# Directories never worth copying into a sandbox: `.git` because the checkpoint
# manager runs `git init` itself and a fresh history keeps the agent's commits
# off the real repo, the rest because they are large and reconstructible.
COPY_IGNORE = (".git", "node_modules", "__pycache__", ".venv", "venv",
               ".mypy_cache", ".pytest_cache")


class ContainerBackend(SandboxBackend):
    """Runs agent tools inside a per-session container.

    The workspace is a *copy* of the configured working directory, bind-mounted
    into the container. Copying rather than mounting the live directory is
    deliberate: a previous provider mounted the real task directory and its
    cleanup deleted annotations.
    """

    name = "container"
    is_isolated = True

    def __init__(self, base_dir: str, settings):
        super().__init__(base_dir)
        self._base_dir = os.path.abspath(base_dir)
        self._settings = settings
        self._container = None  # type: Optional[str]
        self._created = False
        self._owns_workspace = False

    @classmethod
    def preflight(cls, settings) -> Optional[str]:
        reason = unavailable_reason(settings.container_cli)
        if reason:
            return (
                "%s. The live coding agent runs annotator-editable tool calls, "
                "so it needs a sandbox. Install it, switch to "
                "`container_cli: podman`, use `sandbox_mode: bubblewrap` on "
                "Linux, or -- only on a host you trust -- set "
                "`sandbox_mode: trusted` with "
                "`acknowledge_untrusted_code_execution: true`." % reason
            )
        return None

    # --- Lifecycle ---

    def create(self, session_id: str) -> str:
        self._session_id = session_id
        cli = self._settings.container_cli

        reason = unavailable_reason(cli)
        if reason:
            # Never degrade to a weaker backend. An operator who configured a
            # container sandbox and silently got none is the exact defect this
            # module replaces.
            raise SandboxError(
                "Cannot start a container sandbox: %s" % reason
            )

        self._workspace = self._prepare_workspace(session_id)
        self._container = CONTAINER_PREFIX + session_id[:12]

        # A leftover container from a previous crash would block the name.
        remove_container(cli, self._container)

        try:
            run_cli(cli, self._run_args(), timeout=180)
        except ContainerError as e:
            shutil.rmtree(self._workspace, ignore_errors=True)
            raise SandboxError("Failed to start container sandbox: %s" % e)

        self._created = True
        logger.info(
            "Container sandbox %s started (%s, runtime=%s, image=%s)",
            self._container, cli, self._settings.container_runtime or "default",
            self._settings.sandbox_image,
        )
        return self._workspace

    def _prepare_workspace(self, session_id: str) -> str:
        """Copy the working directory to a per-session sandbox directory."""
        root = self._settings.resolve_sandbox_root(self._base_dir)
        workspace = os.path.join(root, session_id[:12])

        if os.path.exists(workspace):
            shutil.rmtree(workspace, ignore_errors=True)
        os.makedirs(root, exist_ok=True)

        try:
            shutil.copytree(
                self._base_dir, workspace,
                ignore=shutil.ignore_patterns(*COPY_IGNORE),
                symlinks=False,
            )
        except OSError as e:
            raise SandboxError(
                "Failed to prepare sandbox workspace at %s: %s" % (workspace, e)
            )
        self._owns_workspace = True
        return workspace

    def _run_args(self) -> List[str]:
        s = self._settings
        args = ["run", "-d", "--name", self._container]

        if s.container_runtime:
            args += ["--runtime=%s" % s.container_runtime]

        args += [
            "--network", s.sandbox_network,
            "--read-only",
            "--user", s.sandbox_user,
            "--pids-limit", str(s.sandbox_pids_limit),
            "--memory", s.sandbox_memory,
            "--cpus", str(s.sandbox_cpus),
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            # The rootfs is read-only, so the agent needs somewhere to write
            # scratch files. noexec stops it being used to stage a binary.
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "-v", "%s:%s:rw" % (self._workspace, MOUNT_POINT),
            "-w", MOUNT_POINT,
            s.sandbox_image,
            # Idle process: tools arrive later via `exec`, so the container has
            # to outlive its entrypoint.
            "sleep", "infinity",
        ]
        return args

    def cleanup(self) -> None:
        if self._container and self._created:
            try:
                remove_container(self._settings.container_cli, self._container)
                logger.info("Removed container sandbox %s", self._container)
            except ContainerError as e:
                logger.warning("Failed to remove container %s: %s",
                               self._container, e)
        self._created = False

        # Only ever delete a workspace this backend created. `_owns_workspace`
        # is set once the copy succeeds, and the realpath comparison is a second
        # guard: a provider elsewhere in this codebase once rmtree'd what turned
        # out to be the live task directory.
        if self._owns_workspace and os.path.realpath(
                self._workspace) != os.path.realpath(self._base_dir):
            shutil.rmtree(self._workspace, ignore_errors=True)
            self._owns_workspace = False

    # --- Execution ---

    def exec(self, argv: List[str], cwd: Optional[str] = None,
             timeout: int = 60) -> ExecResult:
        if not self._created or not self._container:
            raise SandboxError("Container sandbox is not running")

        workdir = self._container_path(cwd) if cwd else MOUNT_POINT
        args = ["exec", "-w", workdir, self._container] + list(argv)

        try:
            result = run_cli(self._settings.container_cli, args,
                             check=False, timeout=timeout)
        except ContainerError as e:
            if "timed out" in str(e):
                return ExecResult(124, timed_out=True)
            raise SandboxError("Sandbox exec failed: %s" % e)

        return ExecResult(result.returncode, result.stdout or "",
                          result.stderr or "")

    def _container_path(self, host_path: str) -> str:
        """Translate a host workspace path to its path inside the container."""
        real = os.path.realpath(host_path)
        root = os.path.realpath(self._workspace)
        if real == root:
            return MOUNT_POINT
        if not real.startswith(root + os.sep):
            raise SandboxError(
                "Path %r is outside the sandbox workspace" % host_path
            )
        return MOUNT_POINT + "/" + os.path.relpath(real, root).replace(os.sep, "/")

    def describe(self) -> str:
        s = self._settings
        return "container (%s, runtime=%s, image=%s, network=%s)" % (
            s.container_cli, s.container_runtime or "default",
            s.sandbox_image, s.sandbox_network,
        )


def sweep_orphaned_containers(cli: str = "docker") -> int:
    """Remove sandbox containers left behind by a previous crash.

    Called once at startup. Without it a Potato process that dies mid-session
    leaks one container per session, with nothing left running to clean up.
    """
    try:
        names = list_containers_with_prefix(cli, CONTAINER_PREFIX)
    except ContainerError:
        return 0
    for name in names:
        try:
            remove_container(cli, name)
            logger.info("Swept orphaned sandbox container %s", name)
        except ContainerError:
            pass
    return len(names)
