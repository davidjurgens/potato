"""
brat standoff importer (``.ann`` + ``.txt`` pairs).

brat is still the lingua franca of academic NLP annotation, and a decade of
corpora ship in it. It is also the format most likely to arrive as a
*directory* -- one ``.ann`` beside each ``.txt`` -- rather than as one file.

What is read
------------
* ``T`` -- text-bound annotations, including brat's discontinuous form
  (``T1\tPER 0 3;8 12\tNew York``). The first fragment sets the span; the rest
  become ``additional_parts``, which is exactly how Potato stores a
  discontinuous span.
* ``A`` / ``M`` -- attributes, kept as extra fields so nothing is silently lost.
* ``#`` -- annotator notes, attached to the item.

What is not
-----------
``R`` (relations) and ``E`` (events) are recorded as warnings rather than
imported. Potato has span links, but brat relations point at ``T`` ids which
must first be resolved to Potato span ids, and a relation silently attached to
the wrong span is worse than a relation reported as skipped. This is the
honest limit of the first version, not a claim that it cannot be done.

Offsets are Unicode code points with an exclusive end, which is brat's own
convention and Potato's -- so unlike REFI-QDA, no conversion happens here.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .base import BaseTextImporter, ImportedDocument, ImportedSpan, TextImportResult

logger = logging.getLogger(__name__)


class BratImporter(BaseTextImporter):
    format_name = "brat"
    description = "brat standoff annotation (.ann files beside their .txt)"
    file_extensions = [".ann"]

    def detect_path(self, path: Path) -> bool:
        path = Path(path)
        if path.is_file():
            return path.suffix.lower() == ".ann"
        if not path.is_dir():
            return False
        return next(path.rglob("*.ann"), None) is not None

    def parse_path(self, path: Path,
                   options: Optional[dict] = None) -> TextImportResult:
        options = options or {}
        path = Path(path)

        if path.is_file():
            ann_files = [path]
        elif path.is_dir():
            ann_files = sorted(path.rglob("*.ann"))
        else:
            raise ValueError(f"{path} is not a file or directory")

        if not ann_files:
            raise ValueError(f"No .ann files found under {path}")

        result = TextImportResult()
        seen_labels: Dict[str, None] = {}

        for ann_path in ann_files:
            txt_path = ann_path.with_suffix(".txt")
            if not txt_path.is_file():
                result.warnings.append(
                    f"{ann_path.name} has no matching .txt, so its offsets "
                    f"refer to text we do not have; skipped")
                continue

            text = txt_path.read_text(encoding="utf-8")
            document = self._parse_pair(ann_path, text, result.warnings)
            for span in document.spans:
                seen_labels.setdefault(span.label, None)
            result.documents.append(document)

        result.labels = [{"name": name} for name in seen_labels]
        result.verify()
        result.summarize(num_files=len(result.documents))
        return result

    # -------------------------------------------------------------- internals

    @staticmethod
    def _parse_pair(ann_path: Path, text: str,
                    warnings: List[str]) -> ImportedDocument:
        spans: List[ImportedSpan] = []
        attributes: Dict[str, List[str]] = {}
        notes: List[str] = []
        relations = 0
        events = 0

        for lineno, raw in enumerate(
                ann_path.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw.rstrip("\n")
            if not line.strip():
                continue

            kind = line[0]
            if kind == "T":
                span = BratImporter._parse_text_bound(
                    line, text, ann_path.name, lineno, warnings)
                if span is not None:
                    spans.append(span)
            elif kind in ("A", "M"):
                parts = line.split("\t", 1)
                if len(parts) == 2:
                    attributes.setdefault("brat_attributes", []).append(parts[1])
            elif kind == "#":
                parts = line.split("\t")
                if len(parts) >= 3:
                    notes.append(parts[2])
            elif kind == "R":
                relations += 1
            elif kind == "E":
                events += 1

        if relations:
            warnings.append(
                f"{ann_path.name}: {relations} relation(s) were not imported. "
                f"brat relations reference T ids, which have to be resolved to "
                f"Potato span ids before they can be reattached.")
        if events:
            warnings.append(
                f"{ann_path.name}: {events} event(s) were not imported.")

        extra: Dict[str, object] = {"source_file": ann_path.name}
        if attributes:
            extra.update(attributes)
        if notes:
            extra["brat_notes"] = notes

        return ImportedDocument(
            instance_id=ann_path.stem,
            text=text,
            spans=spans,
            extra=extra,
        )

    @staticmethod
    def _parse_text_bound(line: str, text: str, filename: str, lineno: int,
                          warnings: List[str]) -> Optional[ImportedSpan]:
        # T1 <TAB> LABEL start end[;start end]* <TAB> covered text
        parts = line.split("\t")
        if len(parts) < 2:
            warnings.append(f"{filename}:{lineno}: malformed T line")
            return None

        term_id = parts[0].strip()
        header = parts[1].split()
        if len(header) < 3:
            warnings.append(f"{filename}:{lineno}: T line has no offsets")
            return None

        label = header[0]
        fragments = BratImporter._parse_fragments(" ".join(header[1:]))
        if not fragments:
            warnings.append(
                f"{filename}:{lineno}: could not read offsets from "
                f"{' '.join(header[1:])!r}")
            return None

        start, end = fragments[0]
        covered = parts[2] if len(parts) > 2 else ""

        if max(e for _, e in fragments) > len(text):
            warnings.append(
                f"{filename}:{lineno}: offsets run past the end of the "
                f"{len(text)}-character .txt; skipped")
            return None

        additional = [{"start": s, "end": e, "text": text[s:e]}
                      for s, e in fragments[1:]]
        if additional:
            # brat records the covered text of a discontinuous mention as all
            # its fragments joined by a space, which will never equal
            # text[start:end] for the first fragment alone. Recording that
            # joined string as this span's `text` would make verify_offsets()
            # report a mismatch on every correctly-parsed discontinuous entity.
            covered = text[start:end]

        return ImportedSpan(start=start, end=end, label=label,
                            text=covered, span_id=term_id,
                            additional_parts=additional)

    @staticmethod
    def _parse_fragments(spec: str) -> List[Tuple[int, int]]:
        """Read ``0 3;8 12`` into ``[(0, 3), (8, 12)]``."""
        fragments: List[Tuple[int, int]] = []
        for chunk in spec.split(";"):
            bits = chunk.split()
            if len(bits) != 2:
                return []
            try:
                fragments.append((int(bits[0]), int(bits[1])))
            except ValueError:
                return []
        return fragments
