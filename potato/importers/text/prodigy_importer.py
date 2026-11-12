"""
Prodigy JSONL importer.

Prodigy's ``db-out`` writes one task per line. Structurally it is close to
doccano -- text plus a list of character-offset spans -- with three differences
that matter:

* spans live under ``spans`` with ``label``, ``start``, ``end``
* every task carries an ``answer`` of ``accept`` / ``reject`` / ``ignore``
* ``_view_id``, ``_input_hash`` and friends record how the task was presented

The ``answer`` field is the one worth care. A rejected task is a human saying
"these annotations are wrong", so importing its spans as though they were
approved work turns an explicit negative judgement into positive training
signal. Rejected and ignored tasks are therefore dropped by default and
counted in the warnings, with ``prodigy_keep_rejected`` to override.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

from ._jsonl import coerce_span, peek_jsonl, read_jsonl
from .base import BaseTextImporter, ImportedDocument, ImportedSpan, TextImportResult

logger = logging.getLogger(__name__)

#: Keys only Prodigy writes. Checked before doccano's shape because doccano's
#: own detector -- text plus a label list -- would happily claim a Prodigy file.
PRODIGY_MARKERS = ("_input_hash", "_task_hash", "_view_id", "_session_id")

#: The scheme name generated for Prodigy's accept/reject verdicts.
ANSWER_SCHEME = "prodigy_answer"


class ProdigyImporter(BaseTextImporter):
    format_name = "prodigy"
    description = "Prodigy db-out JSONL (spans, accept/reject answers)"
    file_extensions = [".jsonl"]

    def detect_path(self, path: Path) -> bool:
        path = Path(path)
        if not path.is_file() or path.suffix.lower() not in (".jsonl", ".json"):
            return False
        for record in peek_jsonl(path):
            if any(marker in record for marker in PRODIGY_MARKERS):
                return True
            # A hand-built Prodigy-style file may have none of the hashes, but
            # `answer` beside `spans` is still unmistakable.
            if "answer" in record and "spans" in record:
                return True
            return False
        return False

    def parse_path(self, path: Path,
                   options: Optional[dict] = None) -> TextImportResult:
        options = options or {}
        path = Path(path)
        if not path.is_file():
            raise ValueError(f"{path} is not a file")

        keep_rejected = bool(options.get("prodigy_keep_rejected", False))
        records = read_jsonl(path)
        if not records:
            raise ValueError(f"{path} contains no records")

        result = TextImportResult()
        span_labels: Dict[str, None] = {}
        answers: Dict[str, None] = {}
        dropped = 0

        for index, record in enumerate(records):
            text = record.get("text")
            if not isinstance(text, str):
                result.warnings.append(
                    f"record {index + 1} has no text field; skipped")
                continue

            answer = str(record.get("answer") or "").lower()
            if answer in ("reject", "ignore") and not keep_rejected:
                dropped += 1
                continue

            instance_id = str(
                record.get("id")
                or record.get("_task_hash")
                or record.get("_input_hash")
                or index + 1
            )

            spans: List[ImportedSpan] = []
            for entry in record.get("spans") or []:
                parsed = coerce_span(entry)
                if parsed is None:
                    continue
                start, end, label = parsed
                if not 0 <= start < end <= len(text):
                    result.warnings.append(
                        f"record {index + 1}: {label} span [{start},{end}) "
                        f"does not fit the {len(text)}-character text; skipped")
                    continue
                span_labels.setdefault(label, None)
                spans.append(ImportedSpan(start=start, end=end, label=label,
                                          text=text[start:end]))

            document = ImportedDocument(instance_id=instance_id, text=text,
                                        spans=spans)
            if answer:
                answers.setdefault(answer, None)
                document.labels[ANSWER_SCHEME] = answer
            if record.get("meta"):
                document.extra["meta"] = record["meta"]

            result.documents.append(document)

        if dropped:
            result.warnings.append(
                f"{dropped} task(s) with answer=reject/ignore were not "
                f"imported. Those are explicit human judgements that the "
                f"annotations are wrong; pass prodigy_keep_rejected to bring "
                f"them in anyway.")

        result.labels = [{"name": name} for name in span_labels]
        if answers:
            result.document_schemes.append({
                "annotation_type": "radio",
                "name": ANSWER_SCHEME,
                "description": "Prodigy accept/reject verdict",
                "labels": [{"name": name} for name in sorted(answers)],
            })

        result.verify()
        result.summarize(num_rejected=dropped)
        return result
