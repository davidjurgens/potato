"""
Text-annotation importer base.

Potato registered fifteen importers and every one of them was computer vision,
so a CV team could migrate in from five named competitors while an NLP team --
our closest market -- had no door at all. This package is the text half.

It is deliberately NOT built on :mod:`potato.importers.base`. That contract is
image-shaped all the way down: :class:`~potato.importers.base.ImportedImage`
requires ``width``/``height``, ``ImportResult.num_objects`` counts drawn
regions, and ``test_importer_contract.py`` requires every ``*_importer.py``
beside it to call ``apply_url_prefix``. A text document has no pixels and no
image URL to prefix, so forcing one into that hierarchy would mean filling
three fields with lies to satisfy a guard written for a different problem.

The two shapes share their *ideas* instead: an importer parses one source into
a result, the result knows how to summarize itself for the CLI, and a registry
detects the format so the user does not have to name it.

Offsets
-------
Every offset in this package is a **Python string index**: a 0-based Unicode
code-point offset, with ``end`` **exclusive**, matching
:class:`potato.item_state_management.SpanAnnotation`. Source formats that count
differently are converted at their own boundary and nowhere else -- REFI-QDA
counts the last character inclusively, brat counts code points like we do, and
CoNLL has no character offsets at all until we rebuild the text. Each importer
documents its own conversion; by the time a span reaches
:class:`ImportedSpan` the question is already settled.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ImportedSpan:
    """One labelled stretch of text, in Potato's own offset convention."""

    #: 0-based code-point index of the first character
    start: int
    #: 0-based code-point index one past the last character
    end: int
    #: The code / entity type applied to it
    label: str
    #: The covered text. Carried for verification, not as the source of truth:
    #: a mismatch against ``text[start:end]`` is how an offset convention bug
    #: announces itself, and importers warn rather than silently shifting.
    text: str = ""
    #: Who coded it, when the source records that. QDA exports do; CoNLL cannot.
    annotator: Optional[str] = None
    #: The source's own identifier, preserved so a re-export can be diffed.
    span_id: Optional[str] = None
    #: Further ``{"start", "end", "text"}`` ranges of a discontinuous mention,
    #: in the shape ``SpanAnnotation.additional_parts`` expects. brat writes
    #: these as ``0 3;8 12``; most other formats cannot express them at all.
    additional_parts: List[dict] = field(default_factory=list)

    def as_client_span(self, schema: str) -> dict:
        """
        The dict shape ``SpanAnnotation.to_dict()`` produces.

        Going through the same keys the server writes means an imported span
        and a human-drawn one are indistinguishable downstream, which is the
        only way export-import-export converges.
        """
        span = {
            "schema": schema,
            "name": self.label,
            "title": self.label,
            "start": self.start,
            "end": self.end,
        }
        if self.span_id:
            span["id"] = self.span_id
        if self.additional_parts:
            span["additional_parts"] = list(self.additional_parts)
        return span


@dataclass
class ImportedDocument:
    """One text document and everything coded on it."""

    instance_id: str
    text: str
    spans: List[ImportedSpan] = field(default_factory=list)
    #: Document-level codes, ``schema_name -> label`` or ``-> [labels]``.
    #: QDA tools code whole documents as well as selections; span-only formats
    #: leave this empty.
    labels: Dict[str, Any] = field(default_factory=dict)
    #: Extra per-item fields to carry into the generated data file.
    extra: Dict[str, Any] = field(default_factory=dict)

    def verify_offsets(self) -> List[str]:
        """
        Report spans whose recorded text disagrees with their offsets.

        An off-by-one in an offset convention does not raise -- it silently
        shifts every coding in the project by one character, which a human
        only notices span by span. Where the source gave us the covered text
        we can catch it at import time instead.
        """
        problems = []
        for span in self.spans:
            if not span.text:
                continue
            actual = self.text[span.start:span.end]
            if actual != span.text:
                problems.append(
                    f"{self.instance_id}: span [{span.start},{span.end}) reads "
                    f"{actual!r} but the source recorded {span.text!r}"
                )
        return problems


@dataclass
class TextImportResult:
    """Everything an importer recovered from one text-annotation source."""

    documents: List[ImportedDocument] = field(default_factory=list)
    #: Span/code definitions for the generated schema, each with at least
    #: ``name``; QDA sources also supply ``description``, ``color`` and
    #: ``parent`` so a nested codebook survives.
    labels: List[dict] = field(default_factory=list)
    #: Document-level schemes to generate, as full annotation_scheme dicts.
    document_schemes: List[dict] = field(default_factory=list)
    #: Annotator names the source named, if any.
    annotators: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)

    @property
    def num_spans(self) -> int:
        return sum(len(doc.spans) for doc in self.documents)

    def summarize(self, **extra: Any) -> Dict[str, Any]:
        """
        Fill :attr:`stats` with the keys the CLI prints, plus any extras.

        The image side learned this the hard way: when each importer built its
        own stats dict the key names drifted twice, and both times the symptom
        was a ``KeyError`` at the very end of an otherwise successful import.
        """
        self.stats = {
            "num_documents": len(self.documents),
            "num_spans": self.num_spans,
            "num_codes": len(self.labels),
            **extra,
        }
        return self.stats

    def verify(self) -> None:
        """Append every offset mismatch to :attr:`warnings`."""
        for doc in self.documents:
            self.warnings.extend(doc.verify_offsets())


#: The keys :mod:`potato.importers.text.cli_support` prints for every format.
REQUIRED_STATS = ("num_documents", "num_spans", "num_codes")


class BaseTextImporter(ABC):
    """
    Base class for text-annotation format importers.

    Detection is by **path**, not by parsed document. Text formats do not share
    a container the way the CV JSON formats do: brat is a directory of file
    pairs, CoNLL is a tab-separated text file, doccano is JSONL and QDPX is a
    ZIP. Handing all four to ``json.load`` first, purely so ``detect(data)``
    could keep the CV signature, would fail on three of them before any
    importer got a look.
    """

    #: Short name used on the CLI and in the registry, e.g. "brat"
    format_name: str = ""
    #: Human-readable description shown by --list-formats
    description: str = ""
    #: File extensions this format typically uses
    file_extensions: List[str] = []

    @abstractmethod
    def parse_path(self, path: Path,
                   options: Optional[dict] = None) -> TextImportResult:
        """
        Read ``path`` -- a file or a directory, per the format -- into a result.

        Raises:
            ValueError: If the source is malformed in a way the caller must fix
        """
        raise NotImplementedError

    @abstractmethod
    def detect_path(self, path: Path) -> bool:
        """
        Return True if ``path`` looks like this format.

        Must be cheap and side-effect free; the registry calls it against every
        registered importer in turn, so one that raises on an unfamiliar file
        breaks auto-detection for all the others.
        """
        raise NotImplementedError

    def get_format_info(self) -> Dict[str, Any]:
        """Metadata for --list-formats."""
        return {
            "name": self.format_name,
            "description": self.description,
            "file_extensions": list(self.file_extensions),
        }
