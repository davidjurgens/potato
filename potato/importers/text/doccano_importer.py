"""
doccano JSONL importer.

doccano is the open-source text annotation tool Potato is most often compared
against, so it is the single most likely place an existing project is sitting.

Its export is one JSON object per line. Sequence labelling puts spans under
``label`` (or ``entities`` in newer exports); document classification puts a
list of category names under the same ``label`` key, which is why the two are
told apart by the *shape* of the entries rather than by the key name -- a
reader that assumes one shape imports zero of the other and still reports
success.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

from ._jsonl import coerce_span, peek_jsonl, read_jsonl
from .base import BaseTextImporter, ImportedDocument, ImportedSpan, TextImportResult

logger = logging.getLogger(__name__)

#: Keys doccano has used for the text body across versions.
TEXT_KEYS = ("text", "data")
#: Keys doccano has used for annotations across versions.
LABEL_KEYS = ("label", "labels", "entities", "annotations")

#: The scheme name generated for document-level categories.
CATEGORY_SCHEME = "categories"


class DoccanoImporter(BaseTextImporter):
    format_name = "doccano"
    description = "doccano JSONL export (sequence labelling or classification)"
    file_extensions = [".jsonl", ".json"]

    def detect_path(self, path: Path) -> bool:
        path = Path(path)
        if not path.is_file() or path.suffix.lower() not in (".jsonl", ".json"):
            return False
        for record in peek_jsonl(path):
            if not any(k in record for k in TEXT_KEYS):
                return False
            if any(k in record for k in LABEL_KEYS):
                return True
            # A doccano export of an unlabelled project still has text and id.
            return "id" in record
        return False

    def parse_path(self, path: Path,
                   options: Optional[dict] = None) -> TextImportResult:
        options = options or {}
        path = Path(path)
        if not path.is_file():
            raise ValueError(f"{path} is not a file")

        records = read_jsonl(path)
        if not records:
            raise ValueError(f"{path} contains no records")

        result = TextImportResult()
        span_labels: Dict[str, None] = {}
        categories: Dict[str, None] = {}

        for index, record in enumerate(records):
            text = self._read_text(record)
            if text is None:
                result.warnings.append(
                    f"record {index + 1} has no text field "
                    f"({'/'.join(TEXT_KEYS)}); skipped")
                continue

            instance_id = str(record.get("id", index + 1))
            spans, names = self._read_spans(record, text, index,
                                            result.warnings)
            for name in names:
                span_labels.setdefault(name, None)

            document = ImportedDocument(instance_id=instance_id, text=text,
                                        spans=spans)

            for category in self._read_categories(record):
                categories.setdefault(category, None)
                document.labels.setdefault(CATEGORY_SCHEME, []).append(category)

            for key in ("meta", "Comments", "comments"):
                if record.get(key):
                    document.extra[key] = record[key]

            result.documents.append(document)

        result.labels = [{"name": name} for name in span_labels]
        if categories:
            result.document_schemes.append({
                "annotation_type": "multiselect",
                "name": CATEGORY_SCHEME,
                "description": "Document categories imported from doccano",
                "labels": [{"name": name} for name in categories],
            })

        result.verify()
        result.summarize(num_categories=len(categories))
        return result

    # -------------------------------------------------------------- internals

    @staticmethod
    def _read_text(record: dict) -> Optional[str]:
        for key in TEXT_KEYS:
            value = record.get(key)
            if isinstance(value, str):
                return value
        return None

    @staticmethod
    def _read_spans(record: dict, text: str, index: int,
                    warnings: List[str]) -> tuple:
        spans: List[ImportedSpan] = []
        names: List[str] = []

        for key in LABEL_KEYS:
            entries = record.get(key)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                # A bare string in `label` is a document category, not a span.
                if isinstance(entry, str):
                    continue
                parsed = coerce_span(entry)
                if parsed is None:
                    continue
                start, end, label = parsed
                if not 0 <= start < end <= len(text):
                    warnings.append(
                        f"record {index + 1}: {label} span [{start},{end}) "
                        f"does not fit the {len(text)}-character text; skipped")
                    continue
                spans.append(ImportedSpan(start=start, end=end, label=label,
                                          text=text[start:end]))
                names.append(label)

        return spans, names

    @staticmethod
    def _read_categories(record: dict) -> List[str]:
        found: List[str] = []
        for key in ("cats", "categories", *LABEL_KEYS):
            entries = record.get(key)
            if isinstance(entries, str):
                found.append(entries)
            elif isinstance(entries, list):
                found.extend(e for e in entries if isinstance(e, str))
        return found
