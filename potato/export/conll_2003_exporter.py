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
from .nlp_utils import tokenize_text, char_spans_to_bio_tags, group_sentences

logger = logging.getLogger(__name__)


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
        out_file = os.path.join(output_path, "annotations.conll")

        lines = []
        total_tokens = 0
        total_entities = 0

        # Get text key from config
        item_props = context.config.get("item_properties", {})
        text_key = item_props.get("text_key", "text")

        # Group annotations by instance to handle multiple annotators
        instance_annotations = {}
        for ann in context.annotations:
            iid = ann.get("instance_id", "")
            if iid not in instance_annotations:
                instance_annotations[iid] = ann
            # If multiple annotators, use first one (could be configurable)

        for instance_id, ann in instance_annotations.items():
            item = context.items.get(instance_id, {})
            text = item.get(text_key, "")
            if not text:
                # Try alternative text fields
                for alt_key in ("text", "sentence", "content"):
                    if alt_key in item:
                        text = item[alt_key]
                        break

            if not text:
                warnings.append(f"No text found for {instance_id}")
                continue

            # Handle text that's a list
            if isinstance(text, list):
                text = " ".join(str(t) for t in text)

            # Tokenize
            tokens = tokenize_text(text, method=tokenization)
            if not tokens:
                continue

            # Get spans for this instance
            spans = []
            for span_schema, span_list in ann.get("spans", {}).items():
                if schema_name and span_schema != schema_name:
                    continue
                for sp in span_list:
                    spans.append({
                        "start": sp.get("start", 0),
                        "end": sp.get("end", 0),
                        "label": sp.get("name") or sp.get("label", "ENTITY"),
                    })

            bio_tags = char_spans_to_bio_tags(tokens, spans)
            total_tokens += len(tokens)
            total_entities += sum(1 for t in bio_tags if t.startswith("B-"))

            # Doc separator
            lines.append("-DOCSTART- -X- -X- O")
            lines.append("")

            # Group into sentences
            sentences = group_sentences(tokens, text)

            for sentence_indices in sentences:
                for idx in sentence_indices:
                    tok = tokens[idx]
                    tag = bio_tags[idx]
                    lines.append(f"{tok['token']}\t{pos_column}\t{chunk_column}\t{tag}")
                lines.append("")  # Blank line between sentences

        with open(out_file, "w") as f:
            f.write("\n".join(lines))

        return ExportResult(
            success=True,
            format_name=self.format_name,
            files_written=[out_file],
            warnings=warnings,
            stats={
                "num_documents": len(instance_annotations),
                "num_tokens": total_tokens,
                "num_entities": total_entities,
            },
        )
