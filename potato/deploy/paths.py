"""Enumerate every filesystem path a config refers to.

Deploying a task means shipping the config *and everything it points at* to
another machine. That requires knowing the full set of referenced paths, which
until now existed only implicitly, spread across
``config_module.validate_file_paths`` (which checks paths but does not return
them) and ``publish.preprocessing._collect_media`` (which walks item media but
is bound to a publish context).

The key table below is the single declaration of "what a config can point at".
``tests/unit/test_deploy_path_keys.py`` asserts it covers everything the
validator touches, so the two cannot drift apart silently.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


# Media extensions recognised when walking item field values. Mirrors the set
# used by publish.preprocessing._collect_media.
MEDIA_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg",
    ".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac",
    ".mp4", ".webm", ".mov", ".avi", ".mkv",
    ".pdf",
)


@dataclass(frozen=True)
class PathKey:
    """One config key that names a path.

    Attributes:
        key: Dotted config key, e.g. ``training.data_file``.
        kind: ``file``, ``dir``, or ``list`` (a sequence of file paths).
        url_ok: True when an ``http(s)://`` value is legitimate and must not be
            treated as a local path.
        base: ``task_dir`` for paths resolved against the task directory, or
            ``project`` for the few resolved against the project directory.
        required: True when the config is invalid if the path is missing.
    """

    key: str
    kind: str = "file"
    url_ok: bool = False
    base: str = "task_dir"
    required: bool = False


# Every path-bearing config key. Ordering is cosmetic; grouping follows the
# structure of validate_file_paths so the two can be compared by eye.
CONFIG_PATH_KEYS: tuple = (
    # --- Core data, checked by validate_file_paths ---
    PathKey("data_files", kind="list", required=True),
    PathKey("data_directory", kind="dir", required=True),
    PathKey("output_annotation_dir", kind="dir", base="project"),
    PathKey("site_dir", kind="dir"),
    PathKey("custom_ds", kind="file"),
    PathKey("base_css", kind="file"),
    PathKey("header_logo", kind="file", url_ok=True),
    # --- Batch assignment, checked by validate_file_paths ---
    PathKey("batch_assignment.groups[].instances_file", kind="file"),
    PathKey("batch_assignment.groups[].items_file", kind="file"),
    PathKey("batch_assignment.groups[].instance_ids_file", kind="file"),
    PathKey("batch_assignment.groups[].data_file", kind="file"),
    PathKey("batch_assignment.groups[].input_data_file", kind="file"),
    PathKey("batch_assignment.groups[].input_file", kind="file"),
    # --- Training, checked by validate_training_config ---
    PathKey("training.data_file", kind="file"),
    # --- Not checked by any validator, but still shipped with the project ---
    PathKey("site_file", kind="file"),
    PathKey("header_file", kind="file"),
    PathKey("keyword_highlights_file", kind="file"),
    PathKey("gold_standards_file", kind="file"),
    PathKey("media_directory", kind="dir"),
    PathKey("ai_support.ai_config_file", kind="file"),
    PathKey("authentication.user_config_path", kind="file"),
    PathKey("surveyflow.pre_annotation", kind="list"),
    PathKey("surveyflow.post_annotation", kind="list"),
    PathKey("surveyflow.prestudy", kind="list"),
    PathKey("surveyflow.testing", kind="list"),
)

# Values that mean "unset" rather than a real path.
SENTINEL_VALUES = (None, "null", "default", "none", "None")


@dataclass
class ResolvedPath:
    """A single config-referenced path, resolved against its base directory."""

    config_key: str
    raw: str
    abspath: str
    kind: str
    exists: bool
    inside_task_dir: bool
    required: bool = False
    is_url: bool = False

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        state = "ok" if self.exists else "MISSING"
        return f"<ResolvedPath {self.config_key}={self.raw!r} {state}>"


@dataclass
class ConfigPaths:
    """Every path a config refers to, resolved and classified."""

    task_dir: str
    config_path: str
    paths: List[ResolvedPath] = field(default_factory=list)

    @property
    def files(self) -> List[ResolvedPath]:
        return [p for p in self.paths if p.kind == "file" and not p.is_url]

    @property
    def dirs(self) -> List[ResolvedPath]:
        return [p for p in self.paths if p.kind == "dir"]

    @property
    def missing(self) -> List[ResolvedPath]:
        return [p for p in self.paths if not p.exists and not p.is_url]

    @property
    def missing_required(self) -> List[ResolvedPath]:
        return [p for p in self.missing if p.required]

    @property
    def outside_task_dir(self) -> List[ResolvedPath]:
        return [p for p in self.paths
                if not p.inside_task_dir and not p.is_url and p.exists]

    def __len__(self) -> int:
        return len(self.paths)


def _is_sentinel(value: Any) -> bool:
    return value in SENTINEL_VALUES


def _is_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def _unwrap(entry: Any) -> Optional[str]:
    """Return the path string from a bare string or a ``{path: ...}`` mapping.

    ``data_files`` and the batch-assignment file keys both accept either form.
    """
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        candidate = entry.get("path")
        return candidate if isinstance(candidate, str) else None
    return None


def _lookup(config: Dict[str, Any], dotted_key: str) -> Iterable[Any]:
    """Yield the raw value(s) at a dotted key, expanding ``[]`` list segments.

    ``batch_assignment.groups[].data_file`` yields one value per group.
    """
    parts = dotted_key.split(".")
    current: List[Any] = [config]

    for part in parts:
        expand = part.endswith("[]")
        if expand:
            part = part[:-2]

        nxt: List[Any] = []
        for node in current:
            if not isinstance(node, dict):
                continue
            value = node.get(part)
            if value is None:
                continue
            if expand:
                if isinstance(value, list):
                    nxt.extend(value)
            else:
                nxt.append(value)
        current = nxt
        if not current:
            return []

    return current


def collect_config_paths(
    config: Dict[str, Any],
    config_path: str,
    task_dir: Optional[str] = None,
) -> ConfigPaths:
    """Resolve every path the config refers to.

    Args:
        config: Parsed config mapping.
        config_path: Path to the config file, used to resolve ``task_dir`` the
            same way ``init_config`` does (relative to the config file's
            directory, not the process working directory).
        task_dir: Override for the resolved task directory. Mostly for tests.

    Returns:
        A ConfigPaths holding one ResolvedPath per referenced path.
    """
    config_abspath = os.path.abspath(config_path)
    config_dir = os.path.dirname(config_abspath)

    if task_dir is None:
        raw_task_dir = config.get("task_dir", ".")
        if _is_sentinel(raw_task_dir):
            raw_task_dir = "."
        task_dir = (
            raw_task_dir if os.path.isabs(raw_task_dir)
            else os.path.normpath(os.path.join(config_dir, raw_task_dir))
        )
    task_dir = os.path.abspath(task_dir)

    result = ConfigPaths(task_dir=task_dir, config_path=config_abspath)

    for path_key in CONFIG_PATH_KEYS:
        base = task_dir if path_key.base == "task_dir" else config_dir

        for raw_value in _lookup(config, path_key.key):
            entries = raw_value if path_key.kind == "list" else [raw_value]
            if path_key.kind == "list" and not isinstance(raw_value, list):
                entries = [raw_value]

            for entry in entries:
                if _is_sentinel(entry):
                    continue
                raw = _unwrap(entry)
                if raw is None:
                    continue

                if _is_url(raw):
                    if not path_key.url_ok:
                        logger.debug(
                            "%s holds a URL (%s) but is not declared url_ok",
                            path_key.key, raw,
                        )
                    result.paths.append(ResolvedPath(
                        config_key=path_key.key, raw=raw, abspath=raw,
                        kind=path_key.kind, exists=True, inside_task_dir=True,
                        required=path_key.required, is_url=True,
                    ))
                    continue

                abspath = (
                    os.path.abspath(raw) if os.path.isabs(raw)
                    else os.path.abspath(os.path.join(base, raw))
                )
                # base_css and header_logo fall back to the config file's
                # directory, matching validate_file_paths.
                if not os.path.exists(abspath) and base != config_dir:
                    alternate = os.path.abspath(os.path.join(config_dir, raw))
                    if os.path.exists(alternate):
                        abspath = alternate

                kind = "list" if path_key.kind == "list" else path_key.kind
                result.paths.append(ResolvedPath(
                    config_key=path_key.key,
                    raw=raw,
                    abspath=abspath,
                    kind="file" if kind == "list" else kind,
                    exists=os.path.exists(abspath),
                    inside_task_dir=_is_inside(abspath, task_dir),
                    required=path_key.required,
                ))

    return result


def _is_inside(path: str, directory: str) -> bool:
    """True when ``path`` resolves inside ``directory``."""
    try:
        real_path = os.path.realpath(path)
        real_dir = os.path.realpath(directory)
        return os.path.commonpath([real_path, real_dir]) == real_dir
    except ValueError:
        # Different drives on Windows.
        return False


def collect_media_paths(
    config: Dict[str, Any],
    items: Iterable[Dict[str, Any]],
    task_root: str,
) -> List[str]:
    """Resolve media files referenced from item field values.

    Generalises ``publish.preprocessing._collect_media``: same ``/media/``
    prefix stripping and two-candidate resolution, without the publish context.

    Returns:
        Absolute paths of media files that exist on disk, de-duplicated.
    """
    media_dir = config.get("media_directory") or "media"
    found: List[str] = []
    seen = set()

    for item in items:
        if not isinstance(item, dict):
            continue
        for value in item.values():
            if not isinstance(value, str):
                continue
            if not value.lower().endswith(MEDIA_EXTENSIONS):
                continue
            if _is_url(value):
                continue

            relative = value[len("/media/"):] if value.startswith("/media/") else value
            candidates = (
                os.path.join(task_root, media_dir, relative),
                os.path.join(task_root, relative),
            )
            for candidate in candidates:
                abspath = os.path.abspath(candidate)
                if os.path.isfile(abspath) and abspath not in seen:
                    seen.add(abspath)
                    found.append(abspath)
                    break

    return found
