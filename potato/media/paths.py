"""
Where ``/media/<path>`` actually lives on disk, and the guard that keeps it there.

This resolution had been written out three times -- in ``routes.serve_media``,
in ``potato.media.routes._resolve_media_path``, and again the moment the
critique service needed to read the same file the browser is showing. Two of
those already carried a comment promising they matched "exactly", which is the
usual sign that the third copy is the one that will not.

The guard is not incidental. Every caller takes a path that originated in a
project's data file and hands the result to something that reads bytes off
disk -- a decoder, a transcoder, or an outbound request to a vision model. A
weaker check in any one of them turns that caller into an arbitrary-file-read
primitive, and in the critique service's case into an exfiltration path,
since the bytes leave the machine.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

#: Config key holding the media directory, relative to ``task_dir`` unless
#: absolute.
MEDIA_DIRECTORY_KEY = "media_directory"
DEFAULT_MEDIA_DIRECTORY = "media"


def media_root(config: Any) -> str:
    """The absolute, symlink-resolved media directory for a project."""
    task_dir = config.get("task_dir", ".")
    media_subdir = config.get(MEDIA_DIRECTORY_KEY, DEFAULT_MEDIA_DIRECTORY)
    root = (media_subdir if os.path.isabs(media_subdir)
            else os.path.join(task_dir, media_subdir))
    return os.path.realpath(root)


def resolve_media_path(config: Any, filepath: str,
                       context: str = "media") -> Tuple[Optional[str], Optional[str]]:
    """
    Resolve ``filepath`` inside the project's media directory.

    Returns ``(media_dir, absolute_path)``, or ``(None, None)`` when the path
    escapes the media directory. Existence is deliberately NOT checked here --
    callers differ on whether a missing file is a 404, a fallback, or an error,
    and folding that in would make the traversal result ambiguous.

    An absolute ``filepath`` is refused rather than reinterpreted as relative.
    It has to be handled explicitly because ``os.path.join(root, "/etc/passwd")``
    returns ``/etc/passwd`` -- the join silently discards the root -- and
    quietly rewriting it to ``<root>/etc/passwd`` would turn a caller's
    programming error into a confusing 404 instead of a clear refusal.
    """
    raw = str(filepath)
    root = media_root(config)
    if os.path.isabs(raw):
        logger.warning("%s refused an absolute path: %s", context, filepath)
        return None, None
    requested = os.path.realpath(os.path.join(root, raw))
    if not requested.startswith(root + os.sep) and requested != root:
        logger.warning("%s path traversal blocked: %s", context, filepath)
        return None, None
    return root, requested


def resolve_media_url(config: Any, reference: str,
                      context: str = "media") -> Optional[str]:
    """
    Resolve a stored item reference such as ``/media/scene_1.png`` to a file.

    Returns ``None`` for anything that is not a local media reference --
    remote URLs, data URIs, and paths outside the media directory -- so a
    caller can tell "not a local file" from "a local file I refused to serve"
    only by asking :func:`resolve_media_path` directly. That is intentional:
    callers that fetch remote images need to make that decision explicitly.
    """
    ref = str(reference or "").strip()
    if not ref or ref.startswith(("http://", "https://", "data:")):
        return None
    prefix = "/media/"
    if ref.startswith(prefix):
        ref = ref[len(prefix):]
    elif ref.startswith("media/"):
        ref = ref[len("media/"):]
    _, path = resolve_media_path(config, ref, context=context)
    if path and os.path.isfile(path):
        return path
    return None
