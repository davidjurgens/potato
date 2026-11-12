"""
Export episode annotations as a per-frame JSONL sidecar.

Registered in the export registry, so it appears in the admin export UI and
``/admin/api/export`` alongside every other format with no extra wiring — the
same reason the CV exporters went in there rather than growing their own
endpoint.

## Why a sidecar rather than a modified dataset

The dataset you annotated is usually read-only: a public HuggingFace repo, a
shared scratch mount, a tree nobody wants a second copy of. A sidecar keyed by
``(episode_id, frame_index)`` sits beside it, is a few kilobytes, and can be
regenerated whenever the annotations change. Appending columns to the source
parquet is available in :mod:`potato.episodes.export` for the case where the
dataset really is yours, and is deliberately not the default.

## Why frames rather than seconds

The timeline stores seconds because that is what an annotator reads. A training
pipeline joins on ``dataset[i]``, which is a frame. Converting once here, using
the fps the episode manifest actually carried, removes a conversion step the
consumer would otherwise have to do against an fps they have to go and find.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from potato.export.base import BaseExporter, ExportContext, ExportResult

logger = logging.getLogger(__name__)


class EpisodeJsonlExporter(BaseExporter):
    """Per-frame JSON Lines for every annotated episode."""

    format_name = "episode_jsonl"
    description = ("Per-frame JSONL sidecar for embodied episodes "
                   "(phase, progress reward, outcome), keyed by "
                   "(episode_id, frame_index)")
    file_extensions = [".jsonl"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        schemas = [s for s in (context.schemas or [])
                   if (s.get("annotation_type") or "") == "episode_annotation"]
        if not schemas:
            return False, ("no episode_annotation schema in this project; "
                           "this format only describes robot episodes")
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        from potato.episodes.export import annotation_rows, write_jsonl
        from potato.episodes.models import EpisodeError

        options = options or {}
        schemas = [s for s in (context.schemas or [])
                   if (s.get("annotation_type") or "") == "episode_annotation"]

        rows: List[Dict[str, Any]] = []
        missing_episode: List[str] = []
        for record in context.annotations or []:
            instance_id = record.get("instance_id")
            for scheme in schemas:
                blob = self._blob(record, scheme.get("name"))
                if not blob:
                    continue
                fps, num_frames = self._timing(context, scheme, instance_id,
                                               options)
                if not fps or not num_frames:
                    # Refuse rather than guess: a phase boundary converted with
                    # the wrong frame rate is wrong in a way nothing downstream
                    # can detect.
                    missing_episode.append(str(instance_id))
                    continue
                rows.extend(annotation_rows(
                    str(instance_id), blob, fps, num_frames))
                rows[-num_frames:] = [
                    dict(row, user_id=record.get("user_id"),
                         schema=scheme.get("name"))
                    for row in rows[-num_frames:]]

        target = output_path
        if os.path.isdir(output_path) or not output_path.endswith(".jsonl"):
            target = os.path.join(output_path, "episode_annotations.jsonl")

        try:
            written = write_jsonl(rows, target)
        except OSError as err:
            return ExportResult(success=False, format_name=self.format_name,
                                errors=[f"could not write {target}: {err}"])
        except EpisodeError as err:
            return ExportResult(success=False, format_name=self.format_name,
                                errors=[str(err)])

        warnings = []
        if missing_episode:
            # Surfaced, not swallowed: a sidecar that silently omits episodes
            # reads as complete and will be quoted as such.
            warnings.append(
                f"skipped {len(missing_episode)} annotation(s) whose episode "
                f"could not be read for fps and frame count: "
                + ", ".join(sorted(set(missing_episode))[:5]))

        return ExportResult(
            success=True,
            format_name=self.format_name,
            files_written=[str(written)],
            warnings=warnings,
            stats={"frame_rows": len(rows),
                   "annotations": len(context.annotations or []),
                   "skipped": len(missing_episode)},
        )

    def _blob(self, record: dict, schema_name: Optional[str]):
        """The parsed annotation blob for one schema of one record."""
        labels = (record.get("labels") or {}).get(schema_name) or {}
        raw = labels.get("_data") if isinstance(labels, dict) else None
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                return None
        return raw if isinstance(raw, dict) else None

    def _timing(self, context: ExportContext, scheme: dict,
                instance_id: Any, options: dict) -> Tuple[float, int]:
        """
        The fps and frame count of the episode an annotation was drawn on.

        Read from the episode itself rather than from a config default,
        because the two are routinely different — a config says 30 and the
        dataset was recorded at 20, and every exported frame index is then off
        by half.
        """
        from potato.episodes.models import EpisodeError
        from potato.episodes.registry import read_episode
        from potato.media.paths import resolve_media_path

        item = (context.items or {}).get(instance_id) or {}
        field = scheme.get("source_field") or "episode"
        path = item.get(field)
        if not path:
            return (0.0, 0)

        try:
            _media_dir, resolved = resolve_media_path(
                context.config or {}, str(path), context="Episode export")
            if resolved is None:
                return (0.0, 0)
            episode = read_episode(resolved,
                                   episode=item.get(
                                       scheme.get("episode_field")
                                       or "episode_index") or 0)
        except (EpisodeError, OSError, ValueError) as err:
            logger.info("episode export: cannot read %s: %s", path, err)
            return (0.0, 0)
        return (episode.fps, episode.num_frames)
