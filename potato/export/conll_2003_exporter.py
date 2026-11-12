"""
CoNLL-2003 Exporter

Exports span annotations to CoNLL-2003 format:
- Tab-separated columns: WORD POS CHUNK NER
- Blank lines between sentences
- -DOCSTART- markers between documents
"""

import os
import logging
from typing import Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult
from .nlp_utils import annotator_groups, conll_documents

logger = logging.getLogger(__name__)


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name) or "_"


class CoNLL2003Exporter(BaseExporter):
    format_name = "conll_2003"
    description = "CoNLL-2003 NER format (WORD POS CHUNK NER)"
    file_extensions = [".conll", ".txt"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        has_span_schema = any(
            s.get("annotation_type") == "span"
            for s in context.schemas
        )
        if not has_span_schema:
            return False, "No span annotation schema found in config"
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        options = options or {}
        warnings = []

        tokenization = options.get("tokenization", "whitespace")
        pos_column = options.get("pos_column", "_")
        chunk_column = options.get("chunk_column", "_")
        # Which span schema to export (defaults to first span schema)
        schema_name = options.get("schema_name")
        if not schema_name:
            for s in context.schemas:
                if s.get("annotation_type") == "span":
                    schema_name = s.get("name")
                    break

        os.makedirs(output_path, exist_ok=True)

        files_written = []
        total_tokens = 0
        total_entities = 0
        total_documents = 0

        for suffix, records in annotator_groups(
                context.annotations, options.get("annotator"), warnings, "CoNLL"):
            lines = []
            for doc_id, text, tokens, bio_tags, sentences in conll_documents(
                    context, records, schema_name, tokenization, warnings):
                total_documents += 1
                total_tokens += len(tokens)
                total_entities += sum(1 for t in bio_tags if t.startswith("B-"))

                # Doc separator
                lines.append("-DOCSTART- -X- -X- O")
                lines.append("")

                for sentence_indices in sentences:
                    for idx in sentence_indices:
                        tok = tokens[idx]
                        tag = bio_tags[idx]
                        lines.append(f"{tok['token']}\t{pos_column}\t{chunk_column}\t{tag}")
                    lines.append("")  # Blank line between sentences

            name = f"annotations.{_safe(suffix)}.conll" if suffix else "annotations.conll"
            out_file = os.path.join(output_path, name)
            with open(out_file, "w") as f:
                f.write("\n".join(lines))
            files_written.append(out_file)

        return ExportResult(
            success=True,
            format_name=self.format_name,
            files_written=files_written,
            warnings=warnings,
            stats={
                "num_documents": total_documents,
                "num_tokens": total_tokens,
                "num_entities": total_entities,
            },
        )
