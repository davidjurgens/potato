"""
Bioacoustic detections and selections as a spectrogram-box project.

Input is one table or a directory of tables, with the recordings beside them.
Three formats:

``raven``            Raven Pro / Raven Lite selection tables (``.txt``,
                     tab-separated, ``Begin Time (s)`` ... ``High Freq (Hz)``)
``audacity_labels``  Audacity label tracks (``.txt``), including the spectral
                     form whose second line is ``\\<TAB>low<TAB>high``
``birdnet``          BirdNET-Analyzer output: its Raven-format selection
                     table or its CSV. Rows below ``--min-confidence``
                     (default 0.1) are left out. Potato reads these files
                     only; the BirdNET models (CC BY-NC-SA) are not bundled.

Each recording becomes one item, copied into the project's ``media/`` and
annotated with one ``spectrogram_annotation`` scheme. Every row becomes a box
pre-annotation, so annotators open the clip with the detections drawn and
correct them. A table is matched to its recording by name
(``site3_0612.Table.1.selections.txt`` -> ``site3_0612.wav``) or, in a
multi-file table, by its ``Begin File`` / ``Begin Path`` / ``File`` column.
The ``raven`` and ``audacity_labels`` exporters write the corrected boxes back.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from potato.server_utils import acoustic_tables as tables

from . import _dh
from .base import ProjectImportResult, ProjectItem
from .textgrid import _read_text

AUDIO_EXTENSIONS = (".wav", ".flac", ".mp3", ".ogg", ".m4a", ".aac", ".opus", ".webm")
SCHEME_NAME = "calls"
DEFAULT_BIRDNET_MIN_CONFIDENCE = 0.1


def _wav_sample_rate(path: Path) -> Optional[int]:
    if path.suffix.lower() != ".wav":
        return None
    import wave
    try:
        with wave.open(str(path), "rb") as handle:
            return handle.getframerate()
    except (wave.Error, OSError, EOFError):
        return None


class _AcousticTableImporter:
    format_name = ""
    description = ""
    file_extensions: List[str] = [".txt"]
    import_label = ""
    #: Provenance written on every imported box: "import" for a person's
    #: selections, "ai" for a detector's output.
    source = "import"
    ai_model: Optional[str] = None

    def _looks_like(self, text: str) -> bool:
        raise NotImplementedError

    def _parse(self, text: str, options: dict,
               problems: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def _why_not(self, text: str) -> Optional[str]:
        """Why a file of the right extension was not taken as this format,
        when it nearly is one (a reason worth more than "no files")."""
        return None

    def _min_confidence(self, options: dict) -> Optional[float]:
        value = options.get("min_confidence")
        return float(value) if value is not None else None

    def _tables(self, path: Path) -> List[Path]:
        exts = tuple(e.lower() for e in self.file_extensions)
        candidates = (sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() in exts)
                      if path.is_dir() else
                      ([path] if path.suffix.lower() in exts else []))
        found = []
        for candidate in candidates:
            try:
                if self._looks_like(_read_text(candidate)):
                    found.append(candidate)
            except OSError:
                continue
        return found

    def detect_path(self, path: Path) -> bool:
        path = Path(path)
        if not path.exists():
            return False
        return bool(self._tables(path))

    @staticmethod
    def _find_audio(folder: Path, name: str) -> Optional[Path]:
        direct = folder / name
        if Path(name).suffix.lower() in AUDIO_EXTENSIONS and direct.is_file():
            return direct
        stem = Path(name).stem if Path(name).suffix.lower() in AUDIO_EXTENSIONS else name
        for ext in AUDIO_EXTENSIONS:
            for candidate in (folder / f"{stem}{ext}", folder / f"{stem}{ext.upper()}"):
                if candidate.is_file():
                    return candidate
        return None

    def parse_path(self, path: Path, options: Optional[dict] = None) -> ProjectImportResult:
        options = dict(options or {})
        path = Path(path)
        found = self._tables(path)
        if not found:
            raise ValueError(self._not_found(path))
        threshold = self._min_confidence(options)
        result = ProjectImportResult(source_format=self.import_label, text_key="recording")
        # The recording's name above the spectrogram, rather than its URL as
        # "text to annotate".
        result.instance_display = {"fields": [{"key": "recording", "type": "text",
                                               "label": "Recording"}]}

        # recording key -> (audio path or None, [boxes], [table names])
        recordings: Dict[str, Tuple[Optional[Path], List[dict], List[str]]] = {}
        below = 0
        left_out = 0
        # A link inside the input folder that points out of it (a downloaded
        # archive can carry one) is not read, and its audio is not copied.
        root = path if path.is_dir() else path.parent
        for table in found:
            if path.is_dir() and not _dh.within(table, [root]):
                result.warn(f"{table.name} links to a file outside the input folder; left out")
                result.skipped["files outside the input folder"] += 1
                continue
            problems: List[str] = []
            try:
                boxes = self._parse(_read_text(table), options, problems)
            except ValueError as exc:
                raise ValueError(f"{table.name}: {exc}") from exc
            for problem in problems:
                result.warn(f"{table.name}, {problem}")
                if problem.endswith("left out"):
                    left_out += 1
            for box in boxes:
                if threshold is not None and box.get("confidence") is not None \
                        and box["confidence"] < threshold:
                    below += 1
                    continue
                name = box.pop("file", None) or tables.recording_stem(table.name)
                key = Path(name).stem if Path(name).suffix.lower() in AUDIO_EXTENSIONS else name
                if key not in recordings:
                    recordings[key] = (self._find_audio(table.parent, name), [], [])
                box["source"] = self.source
                box["import_format"] = self.format_name
                if self.ai_model:
                    box["ai_model"] = self.ai_model
                if not box.get("label"):
                    box["label"] = "call"
                recordings[key][1].append(box)
                if table.name not in recordings[key][2]:
                    recordings[key][2].append(table.name)
            # A table with no rows still names a recording someone listened to.
            if not boxes:
                key = tables.recording_stem(table.name)
                recordings.setdefault(key, (self._find_audio(table.parent, key), [], [table.name]))
        if left_out:
            result.skipped["rows that could not be read (see the warnings)"] = left_out
        if below:
            result.skipped[f"detections below confidence {threshold}"] = below
            result.warn(f"{below} detection(s) below --min-confidence {threshold} were left out")

        labels = sorted({b["label"] for _, boxes, _ in recordings.values() for b in boxes})
        for key, (audio, boxes, sources) in sorted(recordings.items()):
            if audio is not None and not _dh.within(audio, [root]):
                result.warn(f"{audio.name} links to a file outside the input folder; not copied")
                result.skipped["files outside the input folder"] += 1
                audio = None
            fields: Dict[str, Any] = {"recording": audio.name if audio is not None else key,
                                      "source_table": ", ".join(sources)}
            if audio is not None:
                rel = f"media/{audio.name}"
                result.media_files[rel] = str(audio)
                fields["audio_url"] = f"/{rel}"
                rate = _wav_sample_rate(audio)
                if rate:
                    fields["sample_rate"] = rate
            else:
                result.warn(f"{key}: no recording named {key}.* beside the table "
                            f"({', '.join(sources)}); the item has no audio")
                fields["audio_url"] = ""
            item = ProjectItem(instance_id=key, fields=fields)
            item.predictions[SCHEME_NAME] = boxes
            item.prediction_sources[SCHEME_NAME] = {
                "model": self.ai_model or f"imported {self.format_name}"}
            result.items.append(item)

        scheme: Dict[str, Any] = {
            "annotation_type": "spectrogram_annotation",
            "name": SCHEME_NAME,
            "description": f"Check the boxes imported from {self.import_label}: "
                           "move, resize, relabel or delete them, and draw any call that was missed.",
            "source_field": "audio_url",
            "labels": labels or ["call"],
        }
        result.schemes = [scheme]
        return result

    def _not_found(self, path: Path) -> str:
        exts = tuple(e.lower() for e in self.file_extensions)
        candidates = (sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() in exts)
                      if path.is_dir() else [path] if path.is_file() else [])
        for candidate in candidates:
            try:
                reason = self._why_not(_read_text(candidate))
            except (OSError, UnicodeDecodeError):
                reason = None
            if reason:
                return f"{candidate.name} looks like {self.import_label} but {reason}"
        return f"no {self.import_label} files at {path}"


class RavenImporter(_AcousticTableImporter):
    format_name = "raven"
    import_label = "Raven selection tables"
    description = "Raven selection tables (with their recordings) as spectrogram boxes"
    file_extensions = [".txt", ".tsv"]

    def _looks_like(self, text: str) -> bool:
        return tables.looks_like_raven(text) and not tables.looks_like_birdnet_raven(text)

    def _parse(self, text: str, options: dict,
               problems: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        return tables.parse_raven(text, options.get("label_column"), problems=problems)


class AudacityLabelsImporter(_AcousticTableImporter):
    format_name = "audacity_labels"
    import_label = "Audacity label tracks"
    description = "Audacity label tracks (time or spectral) as spectrogram boxes"
    file_extensions = [".txt"]

    def _looks_like(self, text: str) -> bool:
        return tables.looks_like_audacity(text)

    def _parse(self, text: str, options: dict,
               problems: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        return tables.parse_audacity(text, problems=problems)

    def _why_not(self, text: str) -> Optional[str]:
        return tables.audacity_problem(text)


class BirdNETImporter(_AcousticTableImporter):
    format_name = "birdnet"
    import_label = "BirdNET-Analyzer output"
    description = ("BirdNET-Analyzer detections (Raven table or CSV) as spectrogram boxes; "
                   "reads output only, no model is bundled")
    file_extensions = [".txt", ".csv"]
    source = "ai"
    ai_model = "BirdNET"

    def _min_confidence(self, options: dict) -> Optional[float]:
        value = options.get("min_confidence")
        return float(value) if value is not None else DEFAULT_BIRDNET_MIN_CONFIDENCE

    def _looks_like(self, text: str) -> bool:
        return tables.looks_like_birdnet_raven(text) or tables.looks_like_birdnet_csv(text)

    def _parse(self, text: str, options: dict,
               problems: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        if tables.looks_like_birdnet_csv(text):
            return tables.parse_birdnet_csv(text, options.get("label_column"), problems=problems)
        return tables.parse_raven(text, options.get("label_column"),
                                  prefer=tables.BIRDNET_LABEL_COLUMNS, problems=problems)
