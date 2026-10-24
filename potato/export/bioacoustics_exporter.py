"""
Raven selection tables and Audacity label tracks from spectrogram boxes.

For ``spectrogram_annotation`` schemes. Both write one file per recording and
annotator, so a reviewed clip opens in Raven or Audacity beside its audio:

``raven``            ``<recording>.selections.txt``: Selection,
                     View, Channel, Begin Time (s), End Time (s), Low Freq
                     (Hz), High Freq (Hz) and the label under ``Annotation``
                     (``label_column=`` renames it), plus ``Confidence`` when
                     any box has one. A time-only box is written over the whole
                     band: 0 Hz to the recording's Nyquist frequency (from the
                     item's ``sample_rate``, or read from the header of a WAV
                     file in the media directory), else the scheme's
                     ``max_freq``. With none of these, High Freq is left empty
                     and the export warns.
``audacity_labels``  ``<recording>.labels.txt``: ``start<TAB>end<TAB>
                     label`` per box, followed by ``\\<TAB>low<TAB>high`` when
                     the box has a frequency range.

With more than one annotator the name carries theirs
(``<recording>.<annotator>.selections.txt``); ``annotator=<user>`` limits the
export to one person. Files go in one folder per scheme when a project has
more than one.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

from potato.server_utils import acoustic_tables as tables

from .base import BaseExporter, ExportContext, ExportResult


def _safe(name: Any) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(name)).strip("._") or "item"


class _BoxTableExporter(BaseExporter):
    suffix = ""

    def _schemes(self, context: ExportContext) -> Dict[str, dict]:
        return {s["name"]: s for s in context.schemas or []
                if s.get("annotation_type") == "spectrogram_annotation"}

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not self._schemes(context):
            return False, "No spectrogram_annotation scheme in this project"
        if not context.annotations:
            return False, "No annotations to export"
        return True, ""

    def _render(self, boxes: List[dict], scheme: dict, item: dict, options: dict,
                context: ExportContext, warnings: List[str]) -> str:
        raise NotImplementedError

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        options = options or {}
        schemes = self._schemes(context)
        only = options.get("annotator")
        files: List[str] = []
        warnings: List[str] = []
        boxes_written = 0
        os.makedirs(output_path, exist_ok=True)
        users = {str(r.get("user_id", "")) for r in context.annotations
                 if (not only or str(r.get("user_id", "")) == only)
                 and any(tables.decode_boxes((r.get("labels") or {}).get(n)) is not None
                         for n in schemes)}
        for record in context.annotations:
            user = str(record.get("user_id", ""))
            if only and user != only:
                continue
            iid = str(record.get("instance_id", ""))
            item = context.items.get(iid) or {}
            for name, scheme in schemes.items():
                boxes = tables.decode_boxes((record.get("labels") or {}).get(name))
                if boxes is None:
                    continue
                folder = output_path if len(schemes) == 1 else os.path.join(output_path, _safe(name))
                os.makedirs(folder, exist_ok=True)
                stem = os.path.splitext(str(item.get("recording") or ""))[0] or iid
                # The annotator goes in the name only when there is more than
                # one, so a single reviewer's tables re-import by recording name.
                tag = f".{_safe(user)}" if len(users) > 1 else ""
                path = os.path.join(folder, f"{_safe(stem)}{tag}{self.suffix}")
                with open(path, "w", encoding="utf-8", newline="") as handle:
                    handle.write(self._render(boxes, scheme, item, options, context, warnings))
                files.append(path)
                boxes_written += len(boxes)
        return ExportResult(success=True, format_name=self.format_name, files_written=files,
                            warnings=warnings,
                            stats={"num_files": len(files), "num_boxes": boxes_written})


class RavenExporter(_BoxTableExporter):
    format_name = "raven"
    description = "Raven selection tables (one per recording and annotator) from spectrogram boxes"
    file_extensions = [".txt"]
    suffix = ".selections.txt"

    def _render(self, boxes, scheme, item, options, context, warnings):
        high = nyquist(item, scheme, context.config)
        if high is None and any(b.get("low_hz") is None and b.get("high_hz") is None for b in boxes):
            message = (f"{item.get('recording') or 'an item'}: time-only boxes have no High Freq, "
                       f"because the item has no sample_rate, its audio is not a WAV file Potato "
                       f"can read, and the scheme has no max_freq. Set one of them.")
            if message not in warnings:
                warnings.append(message)
        return tables.write_raven(boxes, label_column=options.get("label_column", "Annotation"),
                                  default_high_hz=high)


def nyquist(item: dict, scheme: dict, config: Optional[dict] = None) -> Optional[float]:
    """The top of the band a time-only box covers: half the sample rate when
    it can be known, else the scheme's ``max_freq``, else None."""
    try:
        rate = float(item["sample_rate"])
        if rate > 0:
            return rate / 2
    except (KeyError, TypeError, ValueError):
        pass
    rate = _wav_rate(item.get(scheme.get("source_field") or "audio_url"), config or {})
    if rate:
        return rate / 2
    if scheme.get("max_freq") not in (None, ""):
        return float(scheme["max_freq"])
    return None


def _wav_rate(reference: Any, config: dict) -> Optional[int]:
    from potato.media.paths import resolve_media_url
    path = resolve_media_url(config, str(reference or ""), context="raven export")
    if not path or not path.lower().endswith(".wav"):
        return None
    import wave
    try:
        with wave.open(path, "rb") as handle:
            return handle.getframerate()
    except (wave.Error, OSError, EOFError):
        return None


class AudacityLabelsExporter(_BoxTableExporter):
    format_name = "audacity_labels"
    description = "Audacity label tracks (with spectral selections) from spectrogram boxes"
    file_extensions = [".txt"]
    suffix = ".labels.txt"

    def _render(self, boxes, scheme, item, options, context, warnings):
        return tables.write_audacity(boxes)
