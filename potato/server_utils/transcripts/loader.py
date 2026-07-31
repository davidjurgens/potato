"""
Sidecar transcript loading.

Transcripts usually arrive as files sitting next to the media — ``interview_01.mp3``
and ``interview_01.srt`` — rather than inlined into a data file. This module lets
an item field hold a *path* to such a file, which is read and handed to the
normalizer as content.

The path/content distinction is decided by :func:`is_transcript_path`, which is
deliberately conservative: a real transcript pasted inline is many lines long and
does not end in ``.srt``, so requiring a single short line with a known extension
separates the two cases without a config flag. Callers that need certainty can
force either behavior.

Resolution always goes through ``validate_path_security``, so a data file cannot
be used to read arbitrary files off the server.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "TRANSCRIPT_EXTENSIONS",
    "is_transcript_path",
    "resolve_transcript_source",
    "read_transcript_file",
]

#: Extensions recognized as transcript sidecars. Lowercased for comparison; note
#: ``.TextGrid`` is conventionally capitalized on disk but matched case-insensitively.
TRANSCRIPT_EXTENSIONS = frozenset({
    ".srt", ".vtt", ".webvtt",
    ".json", ".json3", ".srv1", ".srv2", ".srv3",
    ".ttml", ".dfxp", ".xml",
    ".ass", ".ssa",
    ".tsv",
    ".ctm",
    ".textgrid",
    ".eaf",
    ".txt",
})

#: A path is a single line; anything longer than this is inline content that
#: happens to be short. 512 is comfortably past any realistic path length.
_MAX_PATH_LENGTH = 512


def is_transcript_path(value: Any) -> bool:
    """Does ``value`` look like a path to a transcript file rather than content?"""
    if not isinstance(value, str):
        return False
    candidate = value.strip()
    if not candidate or len(candidate) > _MAX_PATH_LENGTH:
        return False
    if "\n" in candidate or "\r" in candidate:
        return False
    # A URL is not a local sidecar; leave it for the caller to handle.
    if "://" in candidate:
        return False
    _stem, ext = os.path.splitext(candidate)
    return ext.lower() in TRANSCRIPT_EXTENSIONS


def resolve_transcript_source(
    value: Any,
    base_dir: Optional[str] = None,
    *,
    is_path: str = "auto",
    project_dir: Optional[str] = None,
) -> Any:
    """Return transcript *content* for ``value``, reading a sidecar if needed.

    Args:
        value: An item field value — either inline transcript content or a path.
        base_dir: Directory paths resolve against (normally the task dir). When
            omitted, no file is read and ``value`` is returned unchanged.
        is_path: ``"auto"`` (default) uses :func:`is_transcript_path`; ``"true"``
            forces a read; ``"false"`` disables sidecar loading entirely.
        project_dir: Passed through to the path-security check.

    Returns:
        The file's text when a sidecar was read, otherwise ``value`` untouched.
        A path that cannot be read returns unchanged too, so a typo degrades to
        "this instance shows no turns" rather than a 500.
    """
    mode = str(is_path).strip().lower()
    if mode in ("false", "no", "0"):
        return value
    if not isinstance(value, str) or not base_dir:
        return value

    forced = mode in ("true", "yes", "1")
    if not forced and not is_transcript_path(value):
        return value

    content = read_transcript_file(value.strip(), base_dir, project_dir=project_dir)
    return value if content is None else content


def read_transcript_file(
    path: str,
    base_dir: str,
    *,
    project_dir: Optional[str] = None,
) -> Optional[str]:
    """Read a transcript file, or return ``None`` if it can't be read safely.

    Every failure mode — traversal attempt, missing file, undecodable bytes — is
    logged and swallowed. Rendering an instance must never crash the page over a
    bad path in one data row.
    """
    try:
        from ..config_module import validate_path_security

        resolved = validate_path_security(path, base_dir, project_dir)
    except Exception as exc:  # ConfigSecurityError and anything else
        logger.warning("Refusing to load transcript %r: %s", path, exc)
        return None

    if not os.path.isfile(resolved):
        logger.warning("Transcript file not found: %s", resolved)
        return None

    try:
        with open(resolved, "r", encoding="utf-8-sig") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("Could not read transcript %s: %s", resolved, exc)
        return None
