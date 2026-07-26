"""
Backwards-compatible shim for transcript ingestion.

The implementation moved to the :mod:`potato.server_utils.transcripts` package
when support grew past subtitle files and Whisper JSON to cover cloud ASR
responses, YouTube caption formats, and forced-alignment files — one module was
no longer the right shape for it.

Import from the package for new code::

    from potato.server_utils.transcripts import normalize_transcript

This module re-exports the public API so existing imports keep working.
"""

from .transcripts import (  # noqa: F401
    TRANSCRIPT_EXTENSIONS,
    TranscriptError,
    detect_format,
    is_transcript_path,
    normalize_transcript,
    read_transcript_file,
    resolve_transcript_source,
)

__all__ = [
    "normalize_transcript",
    "TranscriptError",
    "resolve_transcript_source",
    "is_transcript_path",
    "read_transcript_file",
    "TRANSCRIPT_EXTENSIONS",
    "detect_format",
]
