"""Timeline segments from audio and video annotation, as JSONL and RTTM.

``audio_annotation`` and ``video_annotation`` store an item's segments as one
JSON value, ``{"segments": [{start_time, end_time, label, ...}]}``. Before
this exporter they left Potato only as that string inside a CSV column. This
writes them out as rows:

``segments.jsonl``
    One line per segment: ``instance_id``, ``user_id``, ``schema``, ``start``,
    ``end``, ``duration`` (seconds), ``label``, and ``media`` when the item
    names its recording.

``rttm/<user_id>.rttm``
    NIST RTTM, the format diarization and sound-event tools read
    (pyannote.metrics, dscore, md-eval)::

        SPEAKER <file> 1 <onset> <duration> <NA> <NA> <label> <NA> <NA>

    One file per annotator, because each RTTM file is one reference: two
    annotators' segments in one file would read as overlapping speech. With
    more than one scheme, each scheme's files go under ``rttm/<schema>/``.
    ``<file>`` is the recording's file name without its extension, or the
    item id when the item names no file. When two items' recordings share a
    name, each is ``<name>__<item id>``. RTTM fields are separated by spaces,
    so whitespace inside a label becomes ``_``. Every row is a ``SPEAKER``
    row, the type these tools score, whatever the label names. Zero-length
    segments are left out of RTTM, and kept in the JSONL.
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

logger = logging.getLogger(__name__)

TIMELINE_TYPES = ("audio_annotation", "video_annotation")
_MEDIA_KEYS = ("audio_url", "audio", "audio_path", "video_url", "video",
               "video_path", "url", "path", "file_name")


def _schemes(context: ExportContext) -> List[dict]:
    return [s for s in context.schemas or []
            if s.get("annotation_type") in TIMELINE_TYPES and s.get("name")]


def _media_of(item: Any, scheme: dict, text_key: str = "") -> str:
    """The recording an item names: the scheme's source_field, a usual media
    key, or the item's text field, which is where the audio widget looks
    last (it plays the text when nothing else names a file)."""
    if not isinstance(item, dict):
        return ""
    source = scheme.get("source_field")
    for key in ((source,) if source else ()) + _MEDIA_KEYS + (
            (text_key,) if text_key else ()):
        if key and isinstance(item.get(key), str) and item[key]:
            return item[key]
    return ""


def _stem(media: str) -> str:
    name = os.path.basename(media.split("?", 1)[0].rstrip("/"))
    return re.sub(r"\s+", "_", os.path.splitext(name)[0])


def _file_ids(rows: List[Dict[str, Any]]) -> Dict[str, str]:
    """``{instance_id: RTTM file id}``.

    The recording's name without its extension, unless two items' recordings
    share it (talk3.mp3 on two hosts, talk3.mp3 and talk3.wav): then each of
    those items gets ``<stem>__<instance_id>``, or a scorer would read two
    recordings as one timeline.
    """
    stems: Dict[str, set] = {}
    for row in rows:
        stem = _stem(row["media"]) if row["media"] else ""
        if stem:
            stems.setdefault(stem, set()).add(row["instance_id"])
    out = {}
    for row in rows:
        iid = row["instance_id"]
        stem = _stem(row["media"]) if row["media"] else ""
        if not stem:
            out[iid] = re.sub(r"\s+", "_", iid) or "item"
        elif len(stems[stem]) > 1:
            out[iid] = "%s__%s" % (stem, re.sub(r"\s+", "_", iid))
        else:
            out[iid] = stem
    return out


def _safe_user(user: str) -> str:
    return re.sub(r"[^A-Za-z0-9._@-]+", "_", user) or "annotator"


class SegmentsExporter(BaseExporter):
    format_name = "segments"
    description = ("Audio and video timeline segments as JSONL, and as RTTM "
                   "for diarization and sound-event tools")
    file_extensions = [".jsonl", ".rttm"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not _schemes(context):
            return False, ("No audio_annotation or video_annotation scheme in "
                           "this project")
        return True, ""

    def rows(self, context: ExportContext) -> List[Dict[str, Any]]:
        from potato.server_utils.annotation_values import temporal_segments

        schemes = _schemes(context)
        text_key = str(((context.config or {}).get("item_properties") or {})
                       .get("text_key") or "")
        rows: List[Dict[str, Any]] = []
        for record in context.annotations or []:
            labels = record.get("labels") or {}
            iid = str(record.get("instance_id", ""))
            item = (context.items or {}).get(iid) or {}
            for scheme in schemes:
                name = scheme["name"]
                if name not in labels:
                    continue
                media = _media_of(item, scheme, text_key)
                for seg in temporal_segments(scheme, labels[name]):
                    rows.append({
                        "instance_id": iid,
                        "user_id": str(record.get("user_id", "")),
                        "schema": name,
                        "start": round(float(seg["start"]), 4),
                        "end": round(float(seg["end"]), 4),
                        "duration": round(float(seg["end"]) - float(seg["start"]), 4),
                        "label": "" if seg.get("label") is None else str(seg["label"]),
                        "media": media,
                    })
        rows.sort(key=lambda r: (r["schema"], r["instance_id"], r["user_id"],
                                 r["start"], r["label"]))
        return rows

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        rows = self.rows(context)
        if not rows:
            return ExportResult(success=False, format_name=self.format_name,
                                errors=["No audio or video segments to export"])

        os.makedirs(output_path, exist_ok=True)
        files = []
        jsonl_path = os.path.join(output_path, "segments.jsonl")
        with open(jsonl_path, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        files.append(jsonl_path)

        file_ids = _file_ids(rows)
        # RTTM has no schema column, so with several schemes each gets its
        # own directory: rttm/<schema>/<user>.rttm.
        groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for row in rows:
            groups.setdefault((row["schema"], row["user_id"]), []).append(row)
        several = len({schema for schema, _ in groups}) > 1
        written = set()
        instants = 0
        for (schema, user), user_rows in sorted(groups.items()):
            rttm_dir = os.path.join(output_path, "rttm",
                                    *([_safe_user(schema)] if several else []))
            os.makedirs(rttm_dir, exist_ok=True)
            path = os.path.join(rttm_dir, _safe_user(user) + ".rttm")
            while path in written:
                path = path[:-len(".rttm")] + "_.rttm"
            written.add(path)
            with open(path, "w", encoding="utf-8") as fh:
                for row in user_rows:
                    if row["duration"] <= 0:
                        # An instant has no extent to score; it stays in
                        # segments.jsonl.
                        instants += 1
                        continue
                    label = re.sub(r"\s+", "_", row["label"]) or "<NA>"
                    fh.write("SPEAKER %s 1 %.3f %.3f <NA> <NA> %s <NA> <NA>\n" % (
                        file_ids[row["instance_id"]],
                        row["start"], row["duration"], label))
            files.append(path)

        warnings = []
        if instants:
            warnings.append("%d zero-length segment(s) are in segments.jsonl "
                            "and not in the RTTM files" % instants)
        return ExportResult(
            success=True, format_name=self.format_name, files_written=files,
            warnings=warnings, stats={"num_segments": len(rows),
                   "num_annotators": len({r["user_id"] for r in rows}),
                   "num_items": len({r["instance_id"] for r in rows})})
