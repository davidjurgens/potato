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
3. A per-install directory under the system temp dir.

Case 3 is safe because these files are derived: the generator rewrites one
whenever the config or the schema code changes, so an empty directory costs a
rebuild and nothing else. The path is keyed on the package location, so two
Potato installs on one machine do not overwrite each other's templates, and it
is stable across restarts, so a gunicorn worker respawn reuses the cache.
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
    return os.path.join(tempfile.gettempdir(), f"potato-templates-{digest}")


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
            chosen = _fallback_dir(package_templates_dir)
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
