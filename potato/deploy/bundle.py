"""Assemble a self-contained, deployable copy of an annotation project.

This is the generalization of ``deployment/huggingface-spaces/build_space.py``,
which has built 40 HuggingFace Spaces but is maintainer-only tooling that lives
outside the installed package. Deploy providers run from a wheel, so the logic
has to live here; ``build_space.py`` becomes a caller.

Two differences from the original are deliberate:

* Copying is pure Python. ``build_space.py`` shells out to ``rsync``, which is
  fine for a maintainer script on a developer's Mac and wrong for a command a
  user runs on Windows or inside a minimal container.
* Paths referenced from outside ``task_dir`` are relocated into ``_bundled/``
  and the config is rewritten to match. The original silently omitted them,
  producing a bundle that booted locally and failed on the remote host.
"""

from __future__ import annotations

import fnmatch
import hashlib
import logging
import os
import shutil
import tarfile
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Mapping, Optional, Sequence

import yaml

from potato.deploy.paths import collect_config_paths

logger = logging.getLogger(__name__)


# Never copied out of a project directory. Kept byte-identical to the list in
# build_space.py so the Spaces pipeline produces the same tree as before.
SOURCE_EXCLUDES: List[str] = [
    "annotation_output",
    # Local deploy state. Holds secrets.json (admin key, session key) and the
    # build output; bundling either would publish the key and nest the bundle
    # inside itself.
    ".potato",
    "*.sqlite",
    "*.sqlite-shm",
    "*.sqlite-wal",
    "admin_api_key.txt",
    "__pycache__",
    "*.pyc",
    "*.log",
    ".DS_Store",
]

# Excludes when copying the potato package source.
POTATO_EXCLUDES: List[str] = ["__pycache__", "*.pyc", ".git", "node_modules"]

# Media extensions worth tracking with git-lfs on repo-backed targets.
LFS_PATTERNS: List[str] = [
    "*.mp4", "*.webm", "*.mov", "*.mkv",
    "*.wav", "*.mp3", "*.ogg", "*.flac", "*.m4a",
    "*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp",
    "*.pdf",
]

# Where out-of-tree files land inside the bundle.
BUNDLED_DIRNAME = "_bundled"


@dataclass
class BundleManifest:
    """The result of building a bundle."""

    bundle_dir: str
    config_rel_path: str
    files: List[str] = field(default_factory=list)
    total_bytes: int = 0
    rewritten_keys: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    @property
    def file_count(self) -> int:
        return len(self.files)

    def sha256(self) -> str:
        """Content hash over the bundle, stable across runs.

        Used to decide whether a redeploy needs to push anything. Hashes
        relative paths as well as contents, so a rename is a change.
        """
        digest = hashlib.sha256()
        for rel in sorted(self.files):
            digest.update(rel.encode("utf-8"))
            abspath = os.path.join(self.bundle_dir, rel)
            try:
                with open(abspath, "rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
            except OSError:  # pragma: no cover - race with external deletion
                digest.update(b"<unreadable>")
        return digest.hexdigest()

    def human_size(self) -> str:
        size = float(self.total_bytes)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}GB"


def _excluded(name: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def copy_tree(src: str, dst: str, excludes: Sequence[str] = SOURCE_EXCLUDES) -> List[str]:
    """Copy ``src`` into ``dst``, skipping anything matching ``excludes``.

    Returns bundle-relative paths of the files written. Patterns are matched
    against each path component, so ``annotation_output`` excludes the whole
    directory and ``*.pyc`` excludes individual files, matching rsync's
    behaviour for these patterns.
    """
    written: List[str] = []
    src = os.path.realpath(src)
    dst = os.path.realpath(dst)
    os.makedirs(dst, exist_ok=True)

    for root, dirnames, filenames in os.walk(src):
        dirnames[:] = [d for d in dirnames if not _excluded(d, excludes)]
        # Copying into a directory inside the source recurses until the path
        # length blows up. Skip the destination wherever it is encountered.
        dirnames[:] = [d for d in dirnames
                       if os.path.realpath(os.path.join(root, d)) != dst]
        relative_root = os.path.relpath(root, src)
        target_root = dst if relative_root == "." else os.path.join(dst, relative_root)
        os.makedirs(target_root, exist_ok=True)

        for filename in filenames:
            if _excluded(filename, excludes):
                continue
            source_file = os.path.join(root, filename)
            if os.path.islink(source_file) and not os.path.exists(source_file):
                logger.warning("Skipping broken symlink: %s", source_file)
                continue
            target_file = os.path.join(target_root, filename)
            shutil.copy2(source_file, target_file)
            written.append(os.path.relpath(target_file, dst))

    return written


def _tree_files(root: str) -> List[str]:
    found = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            found.append(os.path.relpath(os.path.join(dirpath, filename), root))
    return found


def _total_size(root: str, relative_paths: Sequence[str]) -> int:
    total = 0
    for rel in relative_paths:
        try:
            total += os.path.getsize(os.path.join(root, rel))
        except OSError:
            pass
    return total


def _set_by_dotted_key(config: dict, dotted_key: str, value) -> bool:
    """Set a dotted key, returning False when the path does not exist.

    Only handles plain nesting; list-expanding keys (``groups[]``) are skipped
    by the caller, since rewriting one element of a list needs its index.
    """
    parts = dotted_key.split(".")
    node = config
    for part in parts[:-1]:
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    if not isinstance(node, dict) or parts[-1] not in node:
        return False
    node[parts[-1]] = value
    return True


def _relocate_external_paths(config: dict, config_path: str, out_dir: str,
                             manifest: BundleManifest) -> None:
    """Copy referenced paths that live outside task_dir into the bundle.

    A config may point at a shared corpus elsewhere on disk. Copying only
    task_dir leaves those behind, and the failure appears on the remote host as
    a missing-data error rather than at build time.
    """
    paths = collect_config_paths(config, config_path)
    external = [p for p in paths.outside_task_dir]
    if not external:
        return

    bundled_root = os.path.join(out_dir, BUNDLED_DIRNAME)
    for resolved in external:
        if resolved.config_key.endswith("[]") or "[]" in resolved.config_key:
            manifest.warnings.append(
                f"{resolved.config_key} points outside task_dir ({resolved.raw}) and "
                "sits in a list; copy it into the project directory by hand"
            )
            continue

        basename = os.path.basename(resolved.abspath.rstrip(os.sep)) or "external"
        destination = os.path.join(bundled_root, basename)
        # Disambiguate collisions rather than overwriting.
        suffix = 1
        while os.path.exists(destination):
            stem, ext = os.path.splitext(basename)
            destination = os.path.join(bundled_root, f"{stem}_{suffix}{ext}")
            suffix += 1

        os.makedirs(bundled_root, exist_ok=True)
        if os.path.isdir(resolved.abspath):
            copy_tree(resolved.abspath, destination, SOURCE_EXCLUDES)
        else:
            shutil.copy2(resolved.abspath, destination)

        new_value = os.path.join(BUNDLED_DIRNAME, os.path.relpath(destination, bundled_root))
        if _set_by_dotted_key(config, resolved.config_key, new_value):
            manifest.rewritten_keys[resolved.config_key] = new_value
            logger.info("Relocated %s: %s -> %s", resolved.config_key,
                        resolved.raw, new_value)
        else:
            manifest.warnings.append(
                f"copied {resolved.raw} into {new_value} but could not rewrite "
                f"config key {resolved.config_key}"
            )


def potato_package_root() -> str:
    """Absolute path of the installed ``potato`` package.

    ``potato.__file__`` is the obvious answer and is ``None`` whenever Python
    resolved the name as a *namespace* package — which happens when a directory
    called ``potato`` with no ``__init__.py`` sits earlier on the path, the
    usual leftover from a previous non-editable install. Taking
    ``os.path.dirname`` of that raised a TypeError from inside the bundler,
    several frames from anything that named the cause.

    Fall back to ``__path__`` and then insist on seeing an ``__init__.py``, so a
    shadowed import fails with something a person can act on rather than
    silently bundling an empty directory.
    """
    import potato

    candidates = []
    if getattr(potato, "__file__", None):
        candidates.append(os.path.dirname(os.path.abspath(potato.__file__)))
    candidates.extend(os.path.abspath(p) for p in getattr(potato, "__path__", []))

    for candidate in candidates:
        if os.path.isfile(os.path.join(candidate, "__init__.py")):
            return candidate

    raise RuntimeError(
        "Could not locate the potato package source. Python resolved `potato` "
        f"to {candidates or 'nothing'}, none of which contains an __init__.py — "
        "usually a leftover directory from an earlier non-editable install "
        "shadowing the real package. Remove it, or reinstall with "
        "`pip install -e .`.")


def collected_data_names(config: Mapping) -> List[str]:
    """Top-level entries in a bundle directory that hold collected data.

    A bundle directory is normally write-once: build it, upload it, forget it.
    The ``local`` provider bind-mounts it as the running task's directory
    instead, so the server writes annotations and its databases straight back
    into it — and rebuilding the bundle with a plain rmtree deleted them.
    That made `potato deploy up`, the documented way to push a change, destroy
    every annotation collected since the first one.

    Nothing here can be regenerated from the source project, so nothing here is
    ever removed by a rebuild. For a provider that uploads the bundle rather
    than mounting it these entries do not exist, and the function returns
    names that simply are not present.
    """
    names = ["project.sqlite", "datasets.sqlite"]
    names += [f"{name}{suffix}" for name in list(names) for suffix in ("-wal", "-shm")]

    output = str(config.get("output_annotation_dir") or "annotation_output").strip()
    # The configured value is often nested ("annotation_output/study-1/"), but
    # what a rebuild deletes is the top-level entry, so that is what to keep.
    top = os.path.normpath(output).lstrip(os.sep).split(os.sep)[0]
    if top and top not in (".", ".."):
        names.append(top)
    return names


def _clean_out_dir(out_dir: str, config: Mapping) -> None:
    """Empty a bundle directory without touching what the server wrote into it."""
    keep = set(collected_data_names(config))
    for entry in os.listdir(out_dir):
        if entry in keep:
            continue
        target = os.path.join(out_dir, entry)
        if os.path.isdir(target) and not os.path.islink(target):
            shutil.rmtree(target)
        else:
            os.remove(target)


def build_bundle(
    config_path: str,
    out_dir: str,
    *,
    mode: str = "directory",
    include_source: bool = False,
    patch: Optional[Callable[[dict], dict]] = None,
    extra_files: Optional[Mapping[str, str]] = None,
    excludes: Sequence[str] = SOURCE_EXCLUDES,
    clean: bool = True,
    preserve_collected_data: bool = False,
) -> BundleManifest:
    """Build a self-contained deployable copy of the project holding ``config_path``.

    Args:
        config_path: Path to the project's ``config.yaml``.
        out_dir: Directory to build into. Replaced when ``clean`` is set.
        mode: ``directory`` copies the whole task directory minus ``excludes``,
            then relocates any out-of-tree referenced path. This is a strict
            superset of what build_space.py produced, which is what makes
            moving that pipeline onto this function safe. ``manifest`` copies
            only the config and the paths it names — smaller, but it drops
            files the config does not reference.
        include_source: Also copy the ``potato`` package. Needed by targets that
            build from source (HF Spaces); unnecessary once a target runs the
            published image.
        patch: Transform applied to the parsed config before it is written out.
        extra_files: ``{bundle_relative_name: source_path}`` written verbatim.
        excludes: Glob patterns skipped during the copy.
        clean: Remove ``out_dir`` first.
        preserve_collected_data: Keep the annotation output and the project
            databases already in ``out_dir`` when cleaning. Set this only for a
            provider that *mounts* the bundle directory as the live task
            directory, which today is ``local``. A provider that uploads the
            bundle must leave it off: the same directory is reused across
            providers, and carrying a stale local database into the tarball
            would overwrite the live one on the host.

    Returns:
        BundleManifest describing what was written.
    """
    if mode not in ("directory", "manifest"):
        raise ValueError(f"unknown bundle mode: {mode!r}")

    config_path = os.path.abspath(config_path)
    if not os.path.isfile(config_path):
        raise FileNotFoundError(f"config file not found: {config_path}")

    out_dir = os.path.abspath(out_dir)
    with open(config_path, "r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    if not isinstance(config, dict):
        raise ValueError(f"config did not parse to a mapping: {config_path}")

    paths = collect_config_paths(config, config_path)
    task_dir = paths.task_dir
    config_rel = os.path.relpath(config_path, task_dir)
    if config_rel.startswith(".."):
        # init_config requires the config to live inside task_dir; mirror that.
        raise ValueError(
            f"config file {config_path} is outside its task_dir {task_dir}; "
            "Potato requires the config to live inside the task directory"
        )

    if clean and os.path.exists(out_dir):
        if preserve_collected_data:
            _clean_out_dir(out_dir, config)
        else:
            shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    manifest = BundleManifest(bundle_dir=out_dir, config_rel_path=config_rel)

    if mode == "directory":
        copy_tree(task_dir, out_dir, excludes)
    else:
        for resolved in paths.paths:
            if resolved.is_url or not resolved.exists:
                continue
            if not resolved.inside_task_dir:
                continue
            relative = os.path.relpath(resolved.abspath, task_dir)
            destination = os.path.join(out_dir, relative)
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            if os.path.isdir(resolved.abspath):
                copy_tree(resolved.abspath, destination, excludes)
            else:
                shutil.copy2(resolved.abspath, destination)
        shutil.copy2(config_path, os.path.join(out_dir, config_rel))

    for resolved in paths.missing_required:
        manifest.warnings.append(
            f"{resolved.config_key} references a path that does not exist: {resolved.raw}"
        )

    # Out-of-tree files, then config rewrites, then write the config back.
    _relocate_external_paths(config, config_path, out_dir, manifest)
    if patch is not None:
        patched = patch(config)
        if patched is not None:
            config = patched

    bundled_config = os.path.join(out_dir, config_rel)
    os.makedirs(os.path.dirname(bundled_config), exist_ok=True)
    with open(bundled_config, "w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, default_flow_style=False,
                       allow_unicode=True, sort_keys=False)

    if include_source:
        copy_tree(potato_package_root(), os.path.join(out_dir, "potato"),
                  POTATO_EXCLUDES)

    for relative_name, source in (extra_files or {}).items():
        destination = os.path.join(out_dir, relative_name)
        os.makedirs(os.path.dirname(destination) or out_dir, exist_ok=True)
        shutil.copy2(source, destination)

    # The server writes here at runtime; ship it empty so the path exists.
    annotation_output = os.path.join(out_dir, "annotation_output")
    os.makedirs(annotation_output, exist_ok=True)
    keep = os.path.join(annotation_output, ".gitkeep")
    if not os.path.exists(keep):
        open(keep, "w").close()

    manifest.files = _tree_files(out_dir)
    manifest.total_bytes = _total_size(out_dir, manifest.files)
    return manifest


def write_lfs_attributes(bundle_dir: str, patterns: Sequence[str] = LFS_PATTERNS) -> str:
    """Write a ``.gitattributes`` marking media patterns for git-lfs."""
    destination = os.path.join(bundle_dir, ".gitattributes")
    body = "\n".join(f"{p} filter=lfs diff=lfs merge=lfs -text" for p in patterns)
    with open(destination, "w", encoding="utf-8") as handle:
        handle.write(body + "\n")
    return destination


def bundle_tarball(manifest: BundleManifest, dest_path: str) -> str:
    """Pack a built bundle into a gzipped tarball for upload.

    Entries are added in sorted order and stripped of uid/gid/mtime so the same
    bundle produces the same bytes, which is what lets a redeploy skip an
    unchanged upload.
    """
    dest_path = os.path.abspath(dest_path)
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)

    def _reset(info: tarfile.TarInfo) -> tarfile.TarInfo:
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        info.mtime = 0
        return info

    # tarfile.open(dest, "w:gz") writes the output filename and the current time
    # into the gzip header, so two archives of identical content differ. Drive
    # GzipFile directly with mtime=0 and no embedded name.
    import gzip

    with open(dest_path, "wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w") as archive:
                for relative in sorted(manifest.files):
                    archive.add(os.path.join(manifest.bundle_dir, relative),
                                arcname=relative, filter=_reset)
    return dest_path
