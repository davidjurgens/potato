"""
RTTM speaker diarization files as a speaker-turn correction project.

Input is one ``.rttm`` file or a folder of them. An RTTM line is

    SPEAKER <file id> <channel> <onset> <duration> <NA> <NA> <speaker> <NA> <NA>

and one file can hold several recordings (several file ids), as pyannote,
NeMo, dscore and md-eval write it. Each recording becomes one item; its audio
is the file named after the file id (``<id>.wav``, ``.flac``, ...) beside the
RTTM or in ``media_dir``, copied into the project's ``media/``. Only
``SPEAKER`` lines are read; ``SPKR-INFO``, ``LEXEME`` and the rest are
counted and skipped.

The turns become pre-annotations on one scheme, which annotators correct:

- ``rttm_scheme: audio`` (the default): an ``audio_annotation`` scheme named
  ``speakers`` whose labels are the speakers. The ``segments`` exporter writes
  the same RTTM back out, one file per annotator, with the item ids as file
  ids, so a corrected diarization goes back into scoring tools unchanged.
- ``rttm_scheme: tiered``: a ``tiered_annotation`` scheme with one
  ``speaker`` tier, for studies that transcribe turn by turn after.

``speaker_map`` renames speakers (``{"SPEAKER_00": "Interviewer"}``, or
``"SPEAKER_00=Interviewer,SPEAKER_01=Guest"`` on the command line); a speaker
it does not name keeps its RTTM name.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import _dh
from .base import ProjectImportResult, ProjectItem

MEDIA_EXTENSIONS = (".wav", ".flac", ".mp3", ".ogg", ".m4a", ".aac", ".webm", ".mp4")
AUDIO_SCHEME = "speakers"
TIERED_SCHEME = "tiers"
SCHEMES = ("audio", "tiered")


def parse_speaker_map(value: Any, problems: Optional[List[str]] = None) -> Dict[str, str]:
    """``{"A": "Interviewer"}`` from a mapping or ``"A=Interviewer,B=Guest"``.
    An entry that is not ``name=new name`` goes to *problems*."""
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    out: Dict[str, str] = {}
    for part in str(value or "").split(","):
        if not part.strip():
            continue
        key, _, name = part.partition("=")
        if key.strip() and name.strip():
            out[key.strip()] = name.strip()
        elif problems is not None:
            problems.append(part.strip())
    return out


def parse_rttm(text: str, long_lines: Optional[List[str]] = None
               ) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """``(turns, skipped)``: ``{file, channel, start, end, speaker}`` per
    SPEAKER line, and counts of the lines left out by reason. The speaker of
    each line with more than the ten RTTM fields goes to *long_lines*."""
    turns: List[Dict[str, Any]] = []
    skipped: Dict[str, int] = {}
    for line in text.splitlines():
        fields = line.split()
        if not fields or fields[0].startswith(";"):
            continue
        if fields[0] != "SPEAKER":
            skipped["%s lines" % fields[0]] = skipped.get("%s lines" % fields[0], 0) + 1
            continue
        def skip(reason):
            skipped[reason] = skipped.get(reason, 0) + 1

        if len(fields) < 8:
            skip("malformed SPEAKER lines")
            continue
        try:
            start, duration = float(fields[3]), float(fields[4])
        except ValueError:
            skip("malformed SPEAKER lines")
            continue
        if not (math.isfinite(start) and math.isfinite(duration)):
            skip("turns with a non-finite onset or duration")
            continue
        if start < 0:
            skip("turns with a negative onset")
            continue
        if duration <= 0:
            skip("zero-length turns")
            continue
        if fields[7] in ("<NA>", "NA", "-"):
            skip("turns with no speaker name")
            continue
        if len(fields) > 10 and long_lines is not None:
            # RTTM is space-separated: "Dr Smith" puts "Smith" in the
            # confidence column. The first word is all the speaker field holds.
            long_lines.append(fields[7])
        turns.append({"file": fields[1], "channel": fields[2], "start": start,
                      "end": start + duration, "speaker": fields[7]})
    return turns, skipped


class RTTMImporter:
    format_name = "rttm"
    description = "RTTM speaker diarization"
    file_extensions = [".rttm"]

    def _files(self, path: Path) -> List[Path]:
        if path.is_dir():
            return sorted(p for p in path.rglob("*") if p.suffix.lower() == ".rttm")
        return [path] if path.suffix.lower() == ".rttm" else []

    def detect_path(self, path: Path) -> bool:
        files = self._files(Path(path))
        if not files:
            return False
        try:
            head = files[0].read_text(errors="replace")[:4000]
        except OSError:
            return False
        return any(line.split()[:1] == ["SPEAKER"] for line in head.splitlines())

    def parse_path(self, path: Path, options: Optional[dict] = None) -> ProjectImportResult:
        options = options or {}
        path = Path(path)
        files = self._files(path)
        if not files:
            raise ValueError(f"no .rttm files at {path}")
        scheme_kind = str(options.get("rttm_scheme") or "audio")
        if scheme_kind not in SCHEMES:
            raise ValueError(f"rttm_scheme must be one of {', '.join(SCHEMES)}, not {scheme_kind!r}")
        bad_map: List[str] = []
        names = parse_speaker_map(options.get("speaker_map"), bad_map)
        root = path if path.is_dir() else path.parent
        media_dir = Path(options["media_dir"]) if options.get("media_dir") else None
        result = ProjectImportResult(source_format=self.description, text_key="text")
        # The writer copies media only from these; --media-dir is one.
        result.media_roots = [str(root)] + ([str(media_dir)] if media_dir else [])
        if bad_map:
            result.warn("--speaker-map: ignored %s (each entry is name=new name)"
                        % ", ".join(repr(b) for b in bad_map))

        recordings: Dict[str, Dict[str, Any]] = {}
        long_lines: List[str] = []
        for f in files:
            if path.is_dir() and not _dh.within(f, [root]):
                result.warn(f"{f.name} is outside the input folder (through a link or ../); left out")
                result.skipped["files outside the input folder"] += 1
                continue
            turns, skipped = parse_rttm(f.read_text(errors="replace"), long_lines)
            for reason, count in skipped.items():
                result.skipped[reason] += count
            if not turns:
                result.warn(f"{f.name} has no SPEAKER lines; left out")
                continue
            for turn in turns:
                entry = recordings.setdefault(turn["file"], {"rttm": f, "files": [],
                                                             "dirs": [], "turns": []})
                if f.parent not in entry["dirs"]:
                    entry["dirs"].append(f.parent)
                if f.name not in entry["files"]:
                    entry["files"].append(f.name)
                entry["turns"].append(turn)
        if long_lines:
            result.warn(f"{len(long_lines)} SPEAKER line(s) have more than RTTM's ten fields, "
                        "as a speaker name with a space makes; the speaker is read up to the "
                        f"space ({', '.join(sorted(set(long_lines))[:5])})")

        in_files = {t["speaker"] for r in recordings.values() for t in r["turns"]}
        unknown = sorted(set(names) - in_files)
        if unknown:
            result.warn("--speaker-map names speaker(s) no RTTM line has: " + ", ".join(unknown))
        merged: Dict[str, List[str]] = {}
        for old, new in names.items():
            if old in in_files:
                merged.setdefault(new, []).append(old)
        for new, olds in sorted(merged.items()):
            if len(olds) > 1:
                result.warn(f"--speaker-map: {', '.join(sorted(olds))} all become {new!r}; "
                            "their turns share one label")

        speakers = sorted({names.get(t["speaker"], t["speaker"])
                           for r in recordings.values() for t in r["turns"]})
        if scheme_kind == "audio":
            result.schemes = [{
                "annotation_type": "audio_annotation", "name": AUDIO_SCHEME,
                "description": "Check and correct who speaks when.",
                "source_field": "audio_url", "mode": "label",
                "labels": [{"name": s} for s in speakers]}]
        else:
            result.schemes = [{
                "annotation_type": "tiered_annotation", "name": TIERED_SCHEME,
                "description": "Check and correct who speaks when.",
                "source_field": "audio_url", "media_type": "audio",
                "tiers": [{"name": "speaker", "tier_type": "independent", "labels": speakers}]}]

        seen: set = set()
        for file_id in sorted(recordings):
            entry = recordings[file_id]
            # Every RTTM file with this recording's turns, in reading order.
            fields: Dict[str, Any] = {"text": file_id, "source_file": ", ".join(entry["files"])}
            # Beside any RTTM file that has this recording's turns.
            media = self._media(file_id, entry["dirs"], media_dir)
            outside = media is not None and not _dh.within(
                media, [root] + ([media_dir] if media_dir else []))
            if outside:
                result.warn(f"{media.name} is outside the input folders (through a link or ../); "
                            "not copied")
                fields["audio_url"] = ""
            elif media is not None:
                rel = f"media/{media.name}"
                result.media_files[rel] = str(media)
                fields["audio_url"] = f"/{rel}"
            else:
                result.warn(f"{file_id}: no audio file named {file_id}.* beside "
                            f"{entry['rttm'].name}" + (" or in the media folder" if media_dir else ""))
                fields["audio_url"] = ""
            channels = sorted({t["channel"] for t in entry["turns"]})
            if len(channels) > 1:
                result.warn(f"{file_id}: turns on {len(channels)} channels ({', '.join(channels)}); "
                            "all are shown on one timeline")
            turns, repeated = [], 0
            for t in sorted(entry["turns"], key=lambda t: (t["start"], t["end"], t["speaker"])):
                # The same turn twice (two RTTM files, or a repeated line) is one turn.
                if turns and (t["start"], t["end"], t["speaker"]) == (
                        turns[-1]["start"], turns[-1]["end"], turns[-1]["speaker"]):
                    repeated += 1
                    continue
                turns.append(t)
            if repeated:
                result.skipped["repeated turns"] += repeated
            iid = _dh.unique_id(file_id, seen)
            item = ProjectItem(instance_id=iid, fields=fields)
            if scheme_kind == "audio":
                item.predictions[AUDIO_SCHEME] = {"segments": [
                    {"id": f"rttm-{n}", "start_time": round(t["start"], 3),
                     "end_time": round(t["end"], 3),
                     "label": names.get(t["speaker"], t["speaker"]),
                     "source": "import", "import_format": "rttm"}
                    for n, t in enumerate(turns)]}
                item.prediction_sources[AUDIO_SCHEME] = {"model": "imported rttm"}
            else:
                item.predictions[TIERED_SCHEME] = {"annotations": {"speaker": [
                    {"id": f"rttm-{n}", "tier": "speaker",
                     "start_time": round(t["start"] * 1000, 3),
                     "end_time": round(t["end"] * 1000, 3),
                     "label": names.get(t["speaker"], t["speaker"]), "value": "",
                     "parent_id": None}
                    for n, t in enumerate(turns)]}}
                item.prediction_sources[TIERED_SCHEME] = {"model": "imported rttm"}
            result.items.append(item)
        if not result.items:
            raise ValueError(f"no SPEAKER lines in {path}")
        return result

    @staticmethod
    def _media(file_id: str, beside: List[Path], media_dir: Optional[Path]) -> Optional[Path]:
        for folder in list(beside) + ([media_dir] if media_dir else []):
            for ext in MEDIA_EXTENSIONS:
                candidate = folder / f"{file_id}{ext}"
                if candidate.exists():
                    return candidate
        return None
