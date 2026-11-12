"""
Server-side transcript binding for schemas that read the instance record.

The ``audio_dialogue`` *display* receives its field value server-side and can
normalize it during render. The transcript-shaped *schemas* cannot: schema HTML
is generated once from the config, not per instance, so they read the record
client-side out of the ``[data-instance-json]`` element.

That left them accepting narrower input than the display did — ``speech_transcript``
handled ``{start, end, speaker, text}`` rows and nothing else, so an SRT file or a
Deepgram response worked in one place and not the other.

This module closes that gap by normalizing on the server anyway. For every key a
transcript-consuming scheme is configured to read, the normalized result is
attached to the record under :data:`INDEX_KEY` before it is serialized into the
page::

    {"segments": <original, untouched>,
     "_transcripts": {"segments": {"audio": ..., "turns": [...]}}}

The client prefers the normalized entry and falls back to its original ad-hoc
parsing, so configs and data files that already worked keep working — including
any custom scheme that reads the record itself.

The original field is never replaced. Annotations and exports must continue to
see exactly the data the user supplied.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from . import normalize_transcript
from .core import TranscriptError

logger = logging.getLogger(__name__)

#: Record key holding the normalized transcripts, keyed by source field name.
INDEX_KEY = "_transcripts"

#: Schemes that consume a transcript, mapped to the config key naming their
#: source field and the default when it is not set. A ``None`` default means the
#: feature is opt-in — nothing is bound unless the config names a field, which is
#: the case for tiered annotation's transcript seeding.
_SCHEME_SOURCES = {
    "speech_transcript": ("segments_key", "segments"),
    "voice_interaction": ("turns_key", "turns"),
    "tiered_annotation": ("transcript_field", None),
}

#: Display types that consume a transcript. These normalize during render too,
#: but indexing them as well means a page mixing a display and a scheme over the
#: same field parses it once and agrees with itself.
_DISPLAY_TYPES = {"audio_dialogue"}


def collect_bindings(config: Dict[str, Any]) -> List[Dict[str, str]]:
    """Find every record key that some configured scheme or display reads.

    Returns one binding per source key, each carrying the key names to hand the
    normalizer so a scheme's custom ``speaker_key``/``text_key`` is honored.
    Duplicate keys collapse to the first binding — normalizing the same field
    twice would only produce the same answer.
    """
    bindings: Dict[str, Dict[str, str]] = {}

    for scheme in config.get("annotation_schemes") or []:
        if not isinstance(scheme, dict):
            continue
        source = _SCHEME_SOURCES.get(scheme.get("annotation_type"))
        if not source:
            continue
        config_key, default = source
        field = scheme.get(config_key) or default
        if not field:
            continue
        bindings.setdefault(field, {
            "field": field,
            "audio_key": scheme.get("audio_key", "audio"),
            "turns_key": scheme.get("turns_key", "turns"),
            "speaker_key": scheme.get("speaker_key", "speaker"),
            "text_key": scheme.get("text_key", "text"),
        })

    display = config.get("instance_display")
    if isinstance(display, dict):
        for field_config in display.get("fields") or []:
            if not isinstance(field_config, dict):
                continue
            if field_config.get("type") not in _DISPLAY_TYPES:
                continue
            field = field_config.get("key")
            if not field:
                continue
            options = field_config.get("display_options") or {}
            bindings.setdefault(field, {
                "field": field,
                "audio_key": options.get("audio_key", "audio"),
                "turns_key": options.get("turns_key", "turns"),
                "speaker_key": options.get("speaker_key", "speaker"),
                "text_key": options.get("text_key", "text"),
                "is_path": str(options.get("transcript_is_path", "auto")),
            })

    return list(bindings.values())


def build_index(
    record: Dict[str, Any],
    bindings: List[Dict[str, str]],
    *,
    base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Normalize each bound field of ``record``, returning the index.

    Fields the record does not have are skipped, and a field that cannot be
    interpreted is left out rather than raising — one malformed row must not
    take down the annotation page.
    """
    index: Dict[str, Any] = {}

    for binding in bindings:
        field = binding["field"]
        if field not in record:
            continue
        try:
            index[field] = normalize_transcript(
                record[field],
                audio_key=binding.get("audio_key", "audio"),
                turns_key=binding.get("turns_key", "turns"),
                speaker_key=binding.get("speaker_key", "speaker"),
                text_key=binding.get("text_key", "text"),
                base_dir=base_dir,
                is_path=binding.get("is_path", "auto"),
            )
        except (TranscriptError, TypeError, ValueError) as exc:
            logger.warning("Could not normalize transcript field %r: %s", field, exc)

    return index


def enrich_record(
    record: Any,
    config: Dict[str, Any],
    *,
    base_dir: Optional[str] = None,
) -> Any:
    """Return ``record`` with a ``_transcripts`` index attached.

    A **shallow copy** is returned so the item's stored data is never mutated —
    the index is a rendering concern and must not leak into annotations or
    exports. Returns the record untouched when nothing is bound, which is the
    common case for tasks that have no transcript schemes at all.
    """
    if not isinstance(record, dict):
        return record

    bindings = collect_bindings(config)
    if not bindings:
        return record

    index = build_index(record, bindings, base_dir=base_dir)
    if not index:
        return record

    enriched = dict(record)
    enriched[INDEX_KEY] = index
    return enriched
