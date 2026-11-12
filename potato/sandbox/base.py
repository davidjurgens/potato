"""
Sandbox backend interface.

The live coding agent executes tool calls that annotators can edit freely, so
the boundary those tools run inside *is* the security control. This module
defines that boundary as an interface with one method that matters --
:meth:`SandboxBackend.exec` -- so the isolation strength becomes a
configuration choice rather than a branch in the tool executor.

See ``potato/sandbox/__init__.py`` for the ladder of available backends.
"""

import logging
import os
from abc import ABC, abstractmethod
from typing import List, Optional

logger = logging.getLogger(__name__)


class SandboxError(Exception):
    """A sandbox could not be created, or a tool could not be run inside it.

    Deliberately fatal. A sandbox that cannot be established must never quietly
    degrade to a weaker one: the previous implementation logged a warning and
    fell back to no isolation at all, which meant an operator who asked for
    Docker got nothing and was never told.
    """


class ExecResult(object):
    """The outcome of running one command inside a sandbox."""

    __slots__ = ("returncode", "stdout", "stderr", "timed_out")

    def __init__(self, returncode, stdout="", stderr="", timed_out=False):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out

    def as_tool_output(self) -> str:
        """Render for the agent transcript, the way the tools reported before."""
        if self.timed_out:
            return "Error: Command timed out"
        output = self.stdout or ""
        if self.stderr:
            output += "\n" + self.stderr
        if self.returncode != 0:
            output += "\n[exit code: %s]" % self.returncode
        return output.strip() or "(no output)"


def resolve_within(workspace: str, path: str) -> str:
    """Resolve ``path`` against ``workspace`` and refuse anything that escapes.

    Every backend routes file access through here, including the ones that
    provide real isolation. That is not redundant: the same tool executor also
    runs under the ``trusted`` backend, where this check is the *only* thing
    standing between an edited tool call and the host filesystem.

    Absolute paths are rejected rather than honoured. The previous behaviour --
    ``os.path.join(workspace, p) if not os.path.isabs(p) else p`` -- made an
    absolute path escape the workspace by construction.

    ``realpath`` is applied to the result, so a symlink planted inside the
    workspace that points outside it is caught too.
    """
    if os.path.isabs(path):
        raise SandboxError(
            "Absolute paths are not permitted inside the sandbox: %r" % path
        )

    workspace_real = os.path.realpath(workspace)
    candidate = os.path.realpath(os.path.join(workspace_real, path))

    if candidate != workspace_real and not candidate.startswith(
        workspace_real + os.sep
    ):
        raise SandboxError(
            "Path %r resolves outside the sandbox workspace" % path
        )
    return candidate


class SandboxBackend(ABC):
    """One rung of the isolation ladder.

    Subclasses own process execution. File reads and writes are concrete here
    because they are identical across backends: every backend's workspace is a
    real host directory (containers bind-mount it), so once
    :func:`resolve_within` has contained the path there is nothing per-backend
    left to do. Keeping them here also means the checkpoint and branch managers,
    which run git against the workspace on the host, work unchanged under every
    backend.
    """

    #: Human-readable name used in logs, errors and the admin dashboard.
    name = "base"

    #: False only for the trusted backend. Consulted when deciding whether to
    #: demand an explicit acknowledgement and when warning at startup.
    is_isolated = True

    def __init__(self, workspace: str):
        self._workspace = os.path.abspath(workspace)
        self._session_id = None  # type: Optional[str]

    @property
    def workspace(self) -> str:
        """Host path the agent works in. Valid after :meth:`create`."""
        return self._workspace

    @classmethod
    def preflight(cls, settings) -> Optional[str]:
        """Why this backend is unusable on this host, or None when it is fine.

        Called at server startup rather than at first tool call, so a
        misconfigured host fails before an annotator is halfway through a task.
        """
        return None

    @abstractmethod
    def create(self, session_id: str) -> str:
        """Establish the sandbox. Returns the workspace path."""

    @abstractmethod
    def exec(self, argv: List[str], cwd: Optional[str] = None,
             timeout: int = 60) -> ExecResult:
        """Run ``argv`` inside the boundary.

        ``argv`` is a list, never a shell string. The ``Bash`` tool passes
        ``["/bin/sh", "-c", command]`` -- a shell *inside* the sandbox is the
        tool's whole purpose, and in a network-less, read-only, unprivileged
        container it is the contained case. What must not survive is a shell on
        the host.
        """

    @abstractmethod
    def cleanup(self) -> None:
        """Tear the sandbox down. Must tolerate being called twice."""

    # --- File access, uniform across backends ---

    def read_file(self, path: str) -> str:
        target = resolve_within(self._workspace, path)
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    def write_file(self, path: str, content: str) -> None:
        target = resolve_within(self._workspace, path)
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)

    def describe(self) -> str:
        """One line for the startup banner and the admin dashboard."""
        return self.name
