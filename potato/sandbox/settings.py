"""
Sandbox configuration: parsing, validation and the deprecation ladder.

Every key here is read from the server's YAML only. None of them may be
overridden by a client request -- ``working_dir`` selects what gets mounted into
the sandbox and ``sandbox_mode`` selects whether there is one at all, so a
caller who could set either would be choosing their own boundary.
"""

import logging
import os
from typing import Optional

from .base import SandboxError

logger = logging.getLogger(__name__)

# The ladder, strongest first. `container` covers Docker and Podman, and picks
# up gVisor or Kata through `container_runtime` without further code.
VALID_MODES = ("container", "bubblewrap", "trusted")

# Modes that existed before the ladder. `docker` silently fell back to no
# isolation when Docker was missing; `worktree` and `direct` never provided any.
DEPRECATED_MODES = {
    "docker": ("container", False),
    "worktree": ("trusted", True),
    "direct": ("trusted", False),
}

ACK_KEY = "acknowledge_untrusted_code_execution"

# Default image. A tag rather than a digest: pinning a digest here would go
# stale and there is no honest way to pick one at authoring time. Operators who
# need reproducibility should set `sandbox_image` to a digest of their own.
DEFAULT_IMAGE = "python:3.12-slim"

SANDBOX_ROOT_NAME = ".potato-sandboxes"


class SandboxSettings(object):
    """Resolved sandbox configuration for one task."""

    def __init__(self, mode="container", container_cli="docker",
                 container_runtime=None, sandbox_image=DEFAULT_IMAGE,
                 sandbox_network="none", sandbox_user="65534:65534",
                 sandbox_memory="512m", sandbox_cpus=1,
                 sandbox_pids_limit=128, sandbox_root=None,
                 use_worktree=False, acknowledged=False):
        self.mode = mode
        self.container_cli = container_cli
        self.container_runtime = container_runtime
        self.sandbox_image = sandbox_image
        self.sandbox_network = sandbox_network
        self.sandbox_user = sandbox_user
        self.sandbox_memory = sandbox_memory
        self.sandbox_cpus = sandbox_cpus
        self.sandbox_pids_limit = sandbox_pids_limit
        self.sandbox_root = sandbox_root
        self.use_worktree = use_worktree
        self.acknowledged = acknowledged

    @classmethod
    def from_config(cls, live_config: dict) -> "SandboxSettings":
        """Build from the ``live_coding_agent`` block of a task config."""
        live_config = live_config or {}
        raw_mode = str(live_config.get("sandbox_mode", "container")).lower()
        acknowledged = bool(live_config.get(ACK_KEY, False))
        use_worktree = False

        if raw_mode in DEPRECATED_MODES:
            mode, use_worktree = DEPRECATED_MODES[raw_mode]
            logger.warning(
                "sandbox_mode: %s is deprecated and maps to '%s'. %s",
                raw_mode, mode,
                _deprecation_note(raw_mode),
            )
        elif raw_mode in VALID_MODES:
            mode = raw_mode
        else:
            raise SandboxError(
                "Invalid sandbox_mode %r. Valid modes are: %s."
                % (raw_mode, ", ".join(VALID_MODES))
            )

        cli = str(live_config.get("container_cli", "docker")).lower()
        if cli not in ("docker", "podman"):
            raise SandboxError(
                "Invalid container_cli %r. Use 'docker' or 'podman'." % cli
            )

        settings = cls(
            mode=mode,
            container_cli=cli,
            container_runtime=live_config.get("container_runtime") or None,
            sandbox_image=live_config.get("sandbox_image", DEFAULT_IMAGE),
            sandbox_network=str(live_config.get("sandbox_network", "none")),
            sandbox_user=str(live_config.get("sandbox_user", "65534:65534")),
            sandbox_memory=str(live_config.get("sandbox_memory", "512m")),
            sandbox_cpus=live_config.get("sandbox_cpus", 1),
            sandbox_pids_limit=live_config.get("sandbox_pids_limit", 128),
            sandbox_root=live_config.get("sandbox_root") or None,
            use_worktree=use_worktree,
            acknowledged=acknowledged,
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        """Refuse configurations that only look safe."""
        if self.mode == "trusted" and not self.acknowledged:
            raise SandboxError(
                "sandbox_mode: trusted runs annotator-editable tool calls -- "
                "including arbitrary shell commands -- directly on this host "
                "with no isolation. If that is what you intend, set "
                "`%s: true` in the live_coding_agent block alongside it. "
                "Otherwise use `sandbox_mode: container` (Docker or Podman), "
                "or `sandbox_mode: bubblewrap` on Linux hosts without a "
                "container runtime." % ACK_KEY
            )
        if self.mode == "container" and self.sandbox_network != "none":
            # Allowed, but never silently: an agent with network access can
            # exfiltrate whatever it reads.
            logger.warning(
                "sandbox_network is %r rather than 'none'. The sandboxed agent "
                "can reach the network from inside the container.",
                self.sandbox_network,
            )

    def resolve_sandbox_root(self, base_dir: str) -> str:
        """Directory that holds per-session workspace copies.

        Defaults to a sibling of the working directory, matching where the old
        worktree sandboxes went, so it stays on the same filesystem and inside
        whatever the container runtime is allowed to share.
        """
        if self.sandbox_root:
            return os.path.abspath(self.sandbox_root)
        base = os.path.abspath(base_dir)
        return os.path.join(os.path.dirname(base) or base, SANDBOX_ROOT_NAME)

    def is_isolated_mode(self) -> bool:
        """False only for `trusted`. Cheap enough to answer without a backend."""
        return self.mode != "trusted"

    def describe(self) -> str:
        if self.mode == "container":
            return "container (%s, runtime=%s)" % (
                self.container_cli, self.container_runtime or "default")
        return self.mode


def _deprecation_note(raw_mode: str) -> str:
    if raw_mode == "docker":
        return (
            "It previously fell back to no isolation when Docker was missing; "
            "'container' fails loudly instead."
        )
    return (
        "It never provided isolation: agent tools ran on the host as the "
        "Potato user. Set `%s: true` to keep that behaviour explicitly, or "
        "switch to `sandbox_mode: container`." % ACK_KEY
    )
