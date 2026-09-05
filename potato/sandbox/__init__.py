"""
Sandbox backends for the live coding agent.

The live coding agent executes tool calls that annotators can edit freely, so
whatever boundary those tools run inside is the security control. This package
provides that boundary as a ladder, strongest first:

===============  ==========================================  ==================
Mode             Boundary                                     Needs
===============  ==========================================  ==================
``container``    namespaces + cgroups + seccomp               docker or podman
``container``    userspace kernel (``container_runtime:       gVisor installed
                 runsc``) or a hardware VM (``kata``)
``bubblewrap``   namespaces, no daemon, no root               ``bwrap``, Linux
``trusted``      **none** -- requires explicit acknowledgement
===============  ==========================================  ==================

Nothing here implements isolation from scratch; each backend drives a tool that
already does it. The upshot is that the strongest options are configuration
rather than code -- gVisor and Kata install as drop-in container runtimes, so
``container_runtime: runsc`` upgrades the boundary with no change on our side.

Backends never fall back. If the configured one is unavailable the session
fails with an error naming the alternatives, because an operator who asked for a
container and silently received none is the defect this package replaces.
"""

import logging
from typing import Optional

from .base import ExecResult, SandboxBackend, SandboxError, resolve_within
from .settings import (
    ACK_KEY, DEFAULT_IMAGE, DEPRECATED_MODES, VALID_MODES, SandboxSettings)

logger = logging.getLogger(__name__)

__all__ = [
    "ACK_KEY",
    "DEPRECATED_MODES",
    "ExecResult",
    "SandboxBackend",
    "SandboxError",
    "SandboxSettings",
    "VALID_MODES",
    "create_backend",
    "backend_class_for",
    "preflight",
    "resolve_within",
    "startup_report",
]


def backend_class_for(mode: str):
    """The backend class implementing ``mode``. Imported lazily by design.

    Boot must not pay for backends the task never uses; see
    ``project_boot_import_weight``.
    """
    if mode == "container":
        from .container import ContainerBackend
        return ContainerBackend
    if mode == "bubblewrap":
        from .bubblewrap import BubblewrapBackend
        return BubblewrapBackend
    if mode == "trusted":
        from .trusted import TrustedBackend
        return TrustedBackend
    raise SandboxError(
        "Invalid sandbox mode %r. Valid modes are: %s."
        % (mode, ", ".join(VALID_MODES))
    )


def create_backend(base_dir: str, settings: SandboxSettings) -> SandboxBackend:
    """Build the configured backend. Does not create the sandbox yet."""
    return backend_class_for(settings.mode)(base_dir, settings)


def preflight(settings: SandboxSettings) -> Optional[str]:
    """Why the configured backend is unusable on this host, or None.

    Call at server startup. Checking here rather than at the first tool call
    means a misconfigured host fails before an annotator is halfway through a
    task rather than after.
    """
    return backend_class_for(settings.mode).preflight(settings)


def startup_report(settings: SandboxSettings) -> str:
    """The banner logged when the live coding agent blueprint registers.

    Annotators can execute tool calls on this server; whoever starts it should
    see what contains them without reading the config.
    """
    lines = [
        "=" * 70,
        "Live coding agent enabled: annotators can execute tool calls.",
        "  Sandbox: %s" % settings.describe(),
    ]
    if not settings.is_isolated_mode():
        lines += [
            "",
            "  *** NO ISOLATION. Tool calls, including arbitrary shell",
            "  *** commands, run directly on this host as the Potato user.",
            "  *** Acknowledged via %s." % ACK_KEY,
        ]
    # Both defaults are right on their own and awkward together: a bare image
    # with no network cannot install anything, so an agent asked to run tests
    # spends its turns discovering that `pytest` is not there. Say so once, at
    # boot, rather than leaving it to be found a tool call at a time.
    if (settings.mode == "container"
            and settings.sandbox_network == "none"
            and settings.sandbox_image == DEFAULT_IMAGE):
        lines += [
            "",
            "  Note: %s with sandbox_network 'none' has no test runner and" % DEFAULT_IMAGE,
            "  no way to install one. Give the agent an image that already",
            "  carries what the task needs (sandbox_image), or loosen",
            "  sandbox_network -- which lets it reach the network.",
        ]
    lines.append("=" * 70)
    return "\n".join(lines)
