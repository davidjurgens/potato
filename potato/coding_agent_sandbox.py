"""
Deprecated shim for the coding agent sandbox.

The sandbox is now a ladder of backends in :mod:`potato.sandbox`, because the
three modes this module used to offer did not mean what they said: ``docker``
was never implemented and silently fell back to no isolation, and ``worktree``
is a git worktree on the same host as the same user, which stops nothing.

Kept so existing imports do not break. New code should use
``potato.sandbox.create_backend``.
"""

import warnings

from potato.sandbox import (  # noqa: F401  (re-exported for compatibility)
    SandboxBackend,
    SandboxError,
    SandboxSettings,
    create_backend,
)


class SandboxManager(object):
    """Removed. Use :func:`potato.sandbox.create_backend` instead."""

    def __init__(self, *args, **kwargs):
        raise SandboxError(
            "SandboxManager has been replaced by potato.sandbox. Build a "
            "backend with create_backend(base_dir, SandboxSettings.from_config"
            "(live_coding_agent_config)). The old 'docker' mode never "
            "implemented isolation and fell back to running tools on the host."
        )


__all__ = [
    "SandboxBackend", "SandboxError", "SandboxSettings", "SandboxManager",
    "create_backend",
]


def __getattr__(name):
    # Dunder probes (`__path__`, `__bases__`, ...) come from the import system
    # and pytest, not from user code; warning on those would fire on every
    # import of this module and train people to ignore the warning.
    if not name.startswith("__"):
        warnings.warn(
            "potato.coding_agent_sandbox is deprecated; use potato.sandbox",
            DeprecationWarning, stacklevel=2,
        )
    raise AttributeError(name)
