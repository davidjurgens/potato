"""
Container CLI helpers.

A thin, dependency-free wrapper around the ``docker`` / ``podman`` command line
tools. Deliberately shells out rather than using a Python SDK: the subset of
functionality Potato needs is identical across both CLIs, so one implementation
covers Docker and Podman, and container runtimes that install as drop-in
replacements (gVisor's ``runsc``, Kata) become a ``--runtime`` flag rather than
new code.

``potato/deploy/providers/local.py`` predates this module and has its own
copies; ``_docker_available`` there now delegates here so there is one answer to
"is Docker usable" in the codebase.
"""

import logging
import shutil
import subprocess
from typing import List, Optional

logger = logging.getLogger(__name__)

# The container CLIs we know how to drive. Both accept the flags used by
# potato.sandbox.container for the subset of commands issued there.
SUPPORTED_CLIS = ("docker", "podman")


class ContainerError(Exception):
    """A container CLI command failed, timed out, or the CLI is missing."""


def container_cli_available(cli: str = "docker", timeout: int = 15) -> bool:
    """True when ``cli`` is installed *and* its daemon answers.

    Checking only for the binary reports success on a machine where Docker
    Desktop is installed but not started, which then surfaces later as a raw
    socket error instead of a usable message. Podman is daemonless, but
    ``podman info`` still fails usefully when the user has no configured
    storage, so the same probe works for both.
    """
    if shutil.which(cli) is None:
        return False
    try:
        result = subprocess.run(
            [cli, "info"], capture_output=True, text=True, timeout=timeout,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def unavailable_reason(cli: str = "docker") -> Optional[str]:
    """Why ``cli`` is unusable, or None when it is fine.

    Split from the boolean so startup errors can say which of the two failure
    modes happened; "not installed" and "installed but not running" need
    different fixes from the operator.
    """
    if shutil.which(cli) is None:
        return "%s is not installed or not on PATH" % cli
    if not container_cli_available(cli):
        return (
            "%s is installed but its daemon is not reachable "
            "(is it running?)" % cli
        )
    return None


def run(cli: str, args: List[str], check: bool = True, timeout: int = 120):
    """Run ``<cli> <args...>`` and return the CompletedProcess.

    Raises ContainerError on a missing binary, a timeout, or (when ``check``) a
    non-zero exit, folding stderr into the message since that is where the
    container CLIs put the reason.
    """
    argv = [cli] + list(args)
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        raise ContainerError("%s is not installed or not on PATH" % cli)
    except subprocess.TimeoutExpired:
        raise ContainerError(
            "%s command timed out after %ss: %s" % (cli, timeout, " ".join(args[:3]))
        )
    if check and result.returncode != 0:
        detail = (result.stderr or "").strip() or (result.stdout or "").strip()
        raise ContainerError(
            "%s command failed (%s): %s" % (cli, result.returncode, detail)
        )
    return result


def container_exists(cli: str, name: str) -> bool:
    """True when a container with this exact name exists, running or not."""
    result = run(
        cli,
        ["ps", "-a", "--filter", "name=^%s$" % name, "--format", "{{.Names}}"],
        check=False, timeout=30,
    )
    return name in (result.stdout or "").split()


def remove_container(cli: str, name: str) -> None:
    """Force-remove a container, tolerating one that is already gone."""
    run(cli, ["rm", "-f", name], check=False, timeout=60)


def list_containers_with_prefix(cli: str, prefix: str) -> List[str]:
    """Names of all containers whose name starts with ``prefix``.

    Used to sweep sandbox containers orphaned by a Potato crash, which would
    otherwise accumulate one per session with nothing left to clean them up.
    """
    result = run(
        cli, ["ps", "-a", "--filter", "name=^%s" % prefix, "--format", "{{.Names}}"],
        check=False, timeout=30,
    )
    return [n for n in (result.stdout or "").split() if n.startswith(prefix)]
