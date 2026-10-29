"""
Praat TextGrid and ELAN EAF files as a tiered-annotation project.

Input is one ``.TextGrid`` / ``.eaf`` file or a directory of them. Each file
becomes one item; an audio or video file beside it with the same stem
(``interview01.TextGrid`` + ``interview01.wav``) is copied into the project's
``media/`` and played by the tiered annotation scheme. Each tier of the
source becomes a tier of one ``tiered_annotation`` scheme, and every
non-empty interval becomes a pre-annotation on that tier, so annotators open
the item with the existing segmentation and correct it. A TextGrid point tier
(``TextTier``) becomes a ``point: true`` tier whose marks are instants. The
TextGrid and EAF exporters write it back out.

A tier whose intervals use few distinct values (phone labels, speaker codes:
at most ``MAX_LABELS``) gets those values as its label set. A tier of free
text (words, transcription) gets one label named after the tier, with the
text kept as each segment's value.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import _dh
from .base import ProjectImportResult, ProjectItem

MEDIA_EXTENSIONS = (".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".webm", ".mp4")
MAX_LABELS = 30
SCHEME_NAME = "tiers"


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for bom, enc in ((b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be"),
                     (b"\xef\xbb\xbf", "utf-8-sig")):
        if raw.startswith(bom):
            return raw[len(bom):].decode(enc, errors="replace")
    if raw[:2].count(0) or raw[1:2] == b"\x00":
        return raw.decode("utf-16-le", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


class _TierFileImporter:
    format_name = ""
    description = ""
    file_extensions: List[str] = []
    media_type_by_ext = {".mp4": "video", ".webm": "video"}

    def _looks_like(self, text: str) -> bool:
        raise NotImplementedError

    def _tier_of(self, seg: Dict[str, Any]) -> str:
        return seg.get("speaker") or "tier"

    def _tiers(self, text: str, f: Path, result) -> List[tuple]:
        """(tier, parent) for every tier the file declares."""
        return []

    def _point_tiers(self, text: str) -> List[str]:
        """Tiers that mark instants rather than intervals."""
        return []

    def _tier_details(self, text: str) -> Dict[str, Dict[str, Any]]:
        """Per tier: linguistic_type, constraint and participant (EAF)."""
        return {}

    def _duration(self, text: str) -> Optional[float]:
        """The recording length the file declares, in seconds."""
        return None

    def _parse(self, text: str) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def _files(self, path: Path) -> List[Path]:
        exts = tuple(e.lower() for e in self.file_extensions)
        if path.is_dir():
            return sorted(p for p in path.iterdir() if p.suffix.lower() in exts)
        return [path] if path.suffix.lower() in exts else []

    def detect_path(self, path: Path) -> bool:
        files = self._files(Path(path))
        if not files:
            return False
        try:
            return self._looks_like(_read_text(files[0]))
        except OSError:
            return False

    def parse_path(self, path: Path, options: Optional[dict] = None) -> ProjectImportResult:
        path = Path(path)
        files = self._files(path)
        if not files:
            raise ValueError(f"no {' / '.join(self.file_extensions)} files at {path}")
        result = ProjectImportResult(source_format=self.description, text_key="text")
        tier_order: List[str] = []
        tier_values: Dict[str, set] = {}
        parents: Dict[str, str] = {}
        point_tiers: set = set()
        details: Dict[str, Dict[str, Any]] = {}
        media_type = "audio"
        parsed = []
        # A link inside the input folder that points out of it (a downloaded
        # archive can carry one) is not read, and its media is not copied.
        root = path if path.is_dir() else path.parent
        for f in files:
            if path.is_dir() and not _dh.within(f, [root]):
                result.warn(f"{f.name} links to a file outside the input folder; left out")
                result.skipped["files outside the input folder"] += 1
                continue
            text = _read_text(f)
            if not self._looks_like(text):
                result.warn(f"{f.name} is not a {self.format_name} file; left out")
                result.skipped["unreadable files"] += 1
                continue
            segments = self._parse(text)
            # Every tier the file declares, empty ones included, and (EAF)
            # which tier each depends on.
            for tier, parent in self._tiers(text, f, result):
                if tier not in tier_values:
                    tier_order.append(tier)
                    tier_values[tier] = set()
                if parent and tier not in parents:
                    parents[tier] = parent
            point_tiers.update(self._point_tiers(text))
            for tier, info in self._tier_details(text).items():
                details.setdefault(tier, info)
            for seg in segments:
                tier = self._tier_of(seg)
                if tier not in tier_values:
                    tier_order.append(tier)
                    tier_values[tier] = set()
                tier_values[tier].add(seg.get("text", ""))
            _report_overlaps(f, segments, self._tier_of, result)
            media = next((f.with_suffix(ext) for ext in MEDIA_EXTENSIONS
                          if f.with_suffix(ext).exists()), None)
            if media is not None and not _dh.within(media, [root]):
                result.warn(f"{media.name} links to a file outside the input folder; not copied")
                result.skipped["files outside the input folder"] += 1
                media = None
            if media is not None and media.suffix.lower() in self.media_type_by_ext:
                media_type = "video"
            parsed.append((f, segments, media, self._duration(text)))
        if not parsed:
            raise ValueError(f"no readable {self.format_name} files at {path}")

        tiers = []
        categorical = {}
        for tier in tier_order:
            values = sorted(v for v in tier_values[tier] if v)
            categorical[tier] = 0 < len(values) <= MAX_LABELS
            labels = values if categorical[tier] else [tier]
            entry = {"name": tier, "tier_type": "independent", "labels": labels}
            if tier in point_tiers:
                # Praat TextTier: ToBI tones, break indices. Imported as a
                # point tier, so the marks stay instants and export as points.
                entry["point"] = True
            elif parents.get(tier) in tier_values:
                entry.update(tier_type="dependent", parent_tier=parents[tier])
                constraint = _CONSTRAINTS.get((details.get(tier) or {}).get("constraint") or "")
                entry["constraint_type"] = constraint or "included_in"
            info = details.get(tier) or {}
            if info.get("participant"):
                entry["participant"] = info["participant"]
            if info.get("linguistic_type"):
                entry["linguistic_type"] = info["linguistic_type"]
            tiers.append(entry)
        result.schemes = [{
            "annotation_type": "tiered_annotation",
            "name": SCHEME_NAME,
            "description": f"Check and correct the segmentation imported from {self.format_name}.",
            "source_field": "audio_url",
            "media_type": media_type,
            "tiers": tiers,
        }]

        dependent = {t["name"]: t["parent_tier"] for t in tiers if t.get("parent_tier")}
        for f, segments, media, duration in parsed:
            stem = f.stem
            fields: Dict[str, Any] = {"text": f.name, "source_file": f.name}
            if media is not None:
                rel = f"media/{media.name}"
                result.media_files[rel] = str(media)
                fields["audio_url"] = f"/{rel}"
            else:
                result.warn(f"{f.name}: no audio or video file named {stem}.* beside it")
                fields["audio_url"] = ""
            by_tier: Dict[str, list] = {t: [] for t in tier_order}
            for i, seg in enumerate(segments):
                tier = self._tier_of(seg)
                text = seg.get("text", "")
                by_tier[tier].append({
                    "id": f"imp-{i}",
                    "tier": tier,
                    "start_time": round(float(seg["start"]) * 1000, 3),
                    "end_time": round(float(seg.get("end", seg["start"])) * 1000, 3),
                    "label": text if categorical[tier] else tier,
                    "value": "" if categorical[tier] else text,
                    "parent_id": None,
                    "_source_id": seg.get("annotation_id"),
                    "_source_parent": seg.get("parent_annotation_id"),
                })
            _link_parents(by_tier, segments, dependent)
            if duration is not None:
                # The grid's own length; the last label usually ends before it.
                fields["duration"] = duration
            item = ProjectItem(instance_id=stem, fields=fields)
            item.predictions[SCHEME_NAME] = {"annotations": by_tier}
            item.prediction_sources[SCHEME_NAME] = {"model": f"imported {self.format_name}"}
            result.items.append(item)
        return result


#: ELAN constraint stereotypes, as tiered_annotation's constraint_type.
_CONSTRAINTS = {
    "Time_Subdivision": "time_subdivision",
    "Included_In": "included_in",
    "Symbolic_Association": "symbolic_association",
    "Symbolic_Subdivision": "symbolic_subdivision",
}


def _link_parents(by_tier: Dict[str, list], segments, dependent: Dict[str, str]) -> None:
    """Give each annotation on a dependent tier its parent's id.

    A REF_ANNOTATION names its parent; a time-aligned child is the one inside
    the parent's span. Without the link an EAF export writes children that
    point at nothing, which ELAN's schema does not allow.
    """
    by_source = {ann["_source_id"]: ann for anns in by_tier.values() for ann in anns
                 if ann.get("_source_id")}
    for tier, parent_tier in dependent.items():
        parents = by_tier.get(parent_tier) or []
        for ann in by_tier.get(tier) or []:
            parent = by_source.get(ann.get("_source_parent") or "")
            if parent is None:
                parent = next((p for p in parents
                               if p["start_time"] <= ann["start_time"]
                               and ann["end_time"] <= p["end_time"]), None)
            if parent is not None:
                ann["parent_id"] = parent["id"]
    for anns in by_tier.values():
        for ann in anns:
            ann.pop("_source_id", None)
            ann.pop("_source_parent", None)


def _report_overlaps(f: Path, segments, tier_of, result) -> None:
    """Segments that overlap within one tier, which a tiered task does not
    expect; they are kept, and counted in the report."""
    by_tier: Dict[str, list] = {}
    for seg in segments:
        by_tier.setdefault(tier_of(seg), []).append(seg)
    for tier, segs in by_tier.items():
        segs = sorted(segs, key=lambda s: (float(s["start"]), float(s.get("end", s["start"]))))
        n = sum(1 for a, b in zip(segs, segs[1:]) if float(b["start"]) < float(a.get("end", a["start"])))
        if n:
            result.warn(f"{f.name}: {n} overlapping segment(s) in tier '{tier}'")


class TextGridImporter(_TierFileImporter):
    format_name = "textgrid"
    description = "Praat TextGrid files (with their audio) as tiered annotations"
    file_extensions = [".TextGrid", ".textgrid"]

    def _looks_like(self, text: str) -> bool:
        from potato.server_utils.transcripts.align import looks_like_textgrid
        return looks_like_textgrid(text)

    def _parse(self, text: str):
        from potato.server_utils.transcripts.align import parse_textgrid
        return parse_textgrid(text)

    def _tiers(self, text: str, f: Path, result) -> List[tuple]:
        from potato.server_utils.transcripts.align import textgrid_tier_names
        return [(name, None) for name in textgrid_tier_names(text) if name]

    def _point_tiers(self, text: str) -> List[str]:
        from potato.server_utils.transcripts.align import textgrid_point_tiers
        return textgrid_point_tiers(text)

    def _duration(self, text: str) -> Optional[float]:
        from potato.server_utils.transcripts.align import textgrid_bounds
        bounds = textgrid_bounds(text)
        return bounds[1] if bounds else None


class EAFImporter(_TierFileImporter):
    format_name = "eaf"
    description = "ELAN .eaf files (with their media) as tiered annotations"
    file_extensions = [".eaf"]

    def _looks_like(self, text: str) -> bool:
        from potato.server_utils.transcripts.align import looks_like_eaf
        return looks_like_eaf(text)

    def _parse(self, text: str):
        from potato.server_utils.transcripts.align import parse_eaf
        return parse_eaf(text)

    def _tier_of(self, seg: Dict[str, Any]) -> str:
        # The tier, not its participant: an ELAN speaker has several tiers.
        return seg.get("tier_id") or seg.get("speaker") or "tier"

    def _tiers(self, text: str, f: Path, result) -> List[tuple]:
        from potato.server_utils.transcripts.align import eaf_tier_info
        info = eaf_tier_info(text)
        if info["unaligned_slots"]:
            result.warn(f"{f.name}: {info['unaligned_slots']} time slot(s) had no time; "
                        "placed between the aligned slots around them, as ELAN does")
        return info["tiers"]

    def _tier_details(self, text: str) -> Dict[str, Dict[str, Any]]:
        from potato.server_utils.transcripts.align import eaf_tier_info
        return eaf_tier_info(text).get("details", {})
