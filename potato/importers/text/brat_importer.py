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
        root = path if path.is_dir() else path.parent
        ids = _instance_ids(ann_files, root)

        for ann_path in ann_files:
            txt_path = ann_path.with_suffix(".txt")
            if not txt_path.is_file():
                result.warnings.append(
                    f"{ann_path.name} has no matching .txt, so its offsets "
                    f"refer to text we do not have; skipped")
                continue

            # brat offsets count every character in the file as written, \r
            # included. Reading with universal newlines dropped the \r first,
            # which shifted each span one character left per line before it.
            # So: read verbatim, resolve offsets there, then normalise line
            # endings (the browser does the same to the text it measures) and
            # move the offsets with them.
            with txt_path.open(encoding="utf-8", newline="") as handle:
                text = handle.read()
            document = self._parse_pair(ann_path, text, result.warnings)
            document.instance_id = ids[ann_path]
            if "\r" in text:
                _normalise_line_endings(document)
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


def _instance_ids(ann_files: List[Path], root: Path) -> Dict[Path, str]:
    """An id per document: the file stem, qualified by its folder when two collide.

    ``train/doc1.ann`` and ``dev/doc1.ann`` both have stem ``doc1``, and two
    items with one id stop the generated project from starting.
    """
    from collections import Counter
    from potato.importers._common import safe_instance_id

    stems = Counter(p.stem for p in ann_files)
    ids = {}
    for p in ann_files:
        if stems[p.stem] == 1:
            ids[p] = p.stem
        else:
            try:
                rel = p.relative_to(root).with_suffix("")
            except ValueError:
                rel = p.with_suffix("")
            ids[p] = safe_instance_id(rel.as_posix())
    return ids


def _normalise_line_endings(document) -> None:
    """Rewrite ``\r\n`` and lone ``\r`` as ``\n`` and move every offset to match."""
    raw = document.text
    # shift[i] = characters removed before raw position i
    shift = [0] * (len(raw) + 1)
    removed = 0
    for i, ch in enumerate(raw):
        shift[i] = removed
        if ch == "\r" and raw[i + 1:i + 2] == "\n":
            removed += 1
    shift[len(raw)] = removed

    def moved(pos: int) -> int:
        return pos - shift[min(max(pos, 0), len(raw))]

    for span in document.spans:
        span.start, span.end = moved(span.start), moved(span.end)
        span.text = span.text.replace("\r\n", "\n").replace("\r", "\n")
        for part in span.additional_parts:
            part["start"], part["end"] = moved(part["start"]), moved(part["end"])
            part["text"] = part["text"].replace("\r\n", "\n").replace("\r", "\n")
    document.text = raw.replace("\r\n", "\n").replace("\r", "\n")
