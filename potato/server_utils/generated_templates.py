"""Where Potato writes the task templates it bakes at startup.

Potato compiles each task's annotation schemes into a Jinja template at boot and
writes it next to the shipped templates, at ``<package>/templates/generated``.
That works for a source checkout and for ``pip install -e .``, where the package
directory belongs to the person running the server.

It does not work for an ordinary install. ``pip install potato-annotation`` puts
the package in site-packages, which a non-root user cannot write to, and the
server dies during boot with ``PermissionError: .../templates/generated``. A
container running as a non-root user hits it every time — which is how this was
found, on the first run of the published image.

So the directory is resolved rather than assumed:

1. ``POTATO_GENERATED_TEMPLATES_DIR``, for callers that want to place it
   deliberately — a mounted volume, a tmpfs, a test fixture.
2. ``<package>/templates/generated``, when the package directory is writable.
   Unchanged behaviour for every existing checkout and editable install.
3. A per-user, per-install directory under the system temp dir.

Case 3 is safe to lose because these files are derived: the generator rewrites
one whenever the config or the schema code changes, so an empty directory costs
a rebuild and nothing else. The path is keyed on the user and the package
location, so two Potato installs on one machine do not overwrite each other's
templates, and it is stable across restarts, so a gunicorn worker respawn reuses
the cache.

Case 3 is not safe to share. The files are Jinja templates that the server
renders, and the system temp dir is writable by every local user, who can
compute the same name. A directory another user created first, or one they can
write into, would let them plant a template that runs as the Potato user. So
the directory is created mode 0700, and an existing one is used only when it is
a real directory (not a symlink) owned by this user that nobody else can write
to. Otherwise the server uses a fresh private
directory from ``tempfile.mkdtemp`` for the rest of the process and logs why.
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile

logger = logging.getLogger(__name__)

ENV_VAR = "POTATO_GENERATED_TEMPLATES_DIR"

# Resolution is logged once per process; boot logs are noisy enough already.
_logged = False

# A shared-temp fallback that could not be trusted is replaced by a mkdtemp
# directory, keyed by the fallback path, so that every caller in this process
# (the generator writes, the Flask loader reads) gets the same one.
_private_fallbacks: dict = {}


def _is_writable(path: str) -> bool:
    """Whether a new subdirectory can be created under ``path``.

    ``os.access(..., W_OK)`` is the obvious check and the wrong one: it consults
    the real uid rather than the effective one, and reports success on paths a
    read-only mount will still refuse. Try the actual operation instead.
    """
    probe = os.path.join(path, f".potato-write-probe-{os.getpid()}")
    try:
        os.makedirs(path, exist_ok=True)
        with open(probe, "w") as handle:
            handle.write("")
    except OSError:
        return False
    finally:
        try:
            os.unlink(probe)
        except OSError:
            pass
    return True


def _fallback_dir(package_templates_dir: str) -> str:
    digest = hashlib.sha256(
        os.path.abspath(package_templates_dir).encode("utf-8")).hexdigest()[:12]
    owner = os.geteuid() if hasattr(os, "geteuid") else "user"
    return os.path.join(tempfile.gettempdir(), f"potato-templates-{owner}-{digest}")


def _untrusted_reason(path: str):
    """Why an existing *path* must not hold templates this process renders, or
    None when it is a directory only this user can write to."""
    import stat
    try:
        info = os.lstat(path)
    except OSError as exc:
        return f"it cannot be inspected ({exc})"
    if stat.S_ISLNK(info.st_mode):
        return "it is a symbolic link"
    if not stat.S_ISDIR(info.st_mode):
        return "it is not a directory"
    if not hasattr(os, "geteuid"):
        # Windows: %TEMP% is per user, and stat reports every directory as
        # 0o777, so the owner and mode checks below would refuse them all.
        return None
    if info.st_uid != os.geteuid():
        return f"it belongs to uid {info.st_uid}, not this user ({os.geteuid()})"
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        return "other users can write to it"
    return None


def _unsafe_parent_reason(parent: str):
    """Why *parent* cannot hold a private directory: one every user can write
    to without the sticky bit lets any of them rename the directory away
    after it is checked and put their own in its place."""
    import stat
    if not hasattr(os, "geteuid"):
        return None
    try:
        info = os.stat(parent)
    except OSError:
        return None
    if info.st_mode & stat.S_IWOTH and not info.st_mode & stat.S_ISVTX:
        return (f"{parent} is writable by every user and has no sticky bit, so "
                "another user could replace the directory after it is checked")
    return None


def _private_fallback(path: str) -> str:
    """*path* as a directory only this user can use, or a fresh private one."""
    if path in _private_fallbacks:
        return _private_fallbacks[path]
    unsafe = _unsafe_parent_reason(os.path.dirname(path))
    if unsafe:
        raise RuntimeError(
            f"Cannot keep generated templates in the temp dir: {unsafe}. "
            f"Set {ENV_VAR} to a directory only this user can write to.")
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    except OSError as exc:
        raise RuntimeError(
            f"Cannot create the generated-template directory {path}: {exc}. "
            f"Set {ENV_VAR} to a writable path.") from exc
    reason = _untrusted_reason(path)
    if reason is None:
        # Potato creates it 0700, but this user may have loosened it since.
        # Nobody else can write to it (checked above), so close it to reading
        # again rather than replace it.
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass
        return path
    private = tempfile.mkdtemp(prefix="potato-templates-")
    logger.warning(
        "Not using %s for generated templates: %s. Using %s for this process "
        "instead; set %s to choose a directory.", path, reason, private, ENV_VAR)
    _private_fallbacks[path] = private
    return private


def resolve_generated_templates_dir(package_templates_dir: str,
                                    create: bool = True) -> str:
    """Return the directory baked task templates belong in.

    ``package_templates_dir`` is the shipped ``<package>/templates`` directory.
    Every caller must agree on the result, so they all route through here: the
    generator writes the files, the Flask loader reads them, and a mismatch
    between the two is a 500 on the annotation page with no other symptom.
    """
    global _logged

    override = os.environ.get(ENV_VAR)
    if override:
        chosen, reason = os.path.abspath(override), f"{ENV_VAR} is set"
    else:
        preferred = os.path.join(package_templates_dir, "generated")
        if _is_writable(package_templates_dir):
            chosen, reason = preferred, "the package directory is writable"
        else:
            # Always checked, create or not: the loader asks with
            # create=False, and it must not read from a directory another
            # user planted.
            chosen = _private_fallback(_fallback_dir(package_templates_dir))
            reason = (f"{package_templates_dir} is not writable "
                      "(a non-root install or a read-only filesystem)")

    if create:
        try:
            os.makedirs(chosen, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(
                f"Cannot create the generated-template directory {chosen}: {exc}. "
                f"Set {ENV_VAR} to a writable path.") from exc

    if not _logged:
        logger.info("Generated templates directory: %s (%s)", chosen, reason)
        _logged = True
    return chosen


def site_name_prefix(task_name: str, space: str = "-") -> str:
    """``annotation_task_name`` as the leading part of a generated filename.

    Three places build a template filename out of the task name and all three
    only ever replaced spaces, so any separator in the name became a directory
    boundary. ``annotation_task_name: "Pairwise left/right"`` crashed the
    server at boot with a ``FileNotFoundError`` naming a directory nobody had
    asked for, and a name containing ``..`` would have written the template
    outside the generated directory entirely.

    Spaces still become ``space`` -- ``-`` for the annotation template and
    ``_`` for phase pages -- because that is what the existing names look like
    and the two conventions are not worth unifying here. Everything else that
    a path can interpret is replaced.
    """
    name = (task_name or "task").replace(" ", space)
    for unsafe in (os.sep, os.altsep, "\0"):
        if unsafe:
            name = name.replace(unsafe, "-")
    # A name that is only dots would resolve to the directory itself, and one
    # that is only punctuation names a file nobody can recognise.
    name = name.strip(".")
    if not any(character.isalnum() for character in name):
        return "task"
    return name
