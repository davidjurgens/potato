"""
Quotation Report Exporter

Exports one row per coded text span ("quotation") with full provenance, suitable
for qualitative-research deliverables and audit trails.

Output columns:
    schema           annotation_scheme name
    code             label applied to the span
    text             quoted span text
    start            character offset (inclusive)
    end              character offset (exclusive)
    field            display field key (for multi-field instances)
    instance_id      source item id
    source_doc       text_key value or item id, for cross-reference
    coder            user id
"""

import csv
import logging
import os
from typing import Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

logger = logging.getLogger(__name__)


class QuotationReportExporter(BaseExporter):
    format_name = "quotation_report"
    description = "Per-span CSV report with code, text, offsets, source, and coder"
    file_extensions = [".csv"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        has_span_schema = any(
            s.get("annotation_type") == "span" for s in context.schemas
        )
        if not has_span_schema:
            return False, "No span annotation schema found in config"
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        options = options or {}
        os.makedirs(output_path, exist_ok=True)
        out_file = os.path.join(output_path, "quotations.csv")

        item_props = context.config.get("item_properties", {})
        default_text_key = item_props.get("text_key", "text")

        rows = []
        for ann in context.annotations:
            instance_id = ann.get("instance_id", "")
            coder = ann.get("user_id", "")
            item = context.items.get(instance_id, {}) or {}
            source_doc = item.get(default_text_key, "") or instance_id

            spans = ann.get("spans", {}) or {}
            for schema_name, span_list in spans.items():
                for span in span_list or []:
                    label = (
                        span.get("label")
                        or span.get("annotation")
                        or span.get("category")
                        or ""
                    )
                    text = span.get("text", "")
                    start = span.get("start") if span.get("start") is not None else span.get("start_offset", "")
                    end = span.get("end") if span.get("end") is not None else span.get("end_offset", "")
                    field = span.get("field") or span.get("target_field") or ""
                    rows.append({
                        "schema": schema_name,
                        "code": label,
                        "text": text,
                        "start": start,
                        "end": end,
                        "field": field,
                        "instance_id": instance_id,
                        "source_doc": (source_doc[:200] if isinstance(source_doc, str) else source_doc),
                        "coder": coder,
                    })

        fieldnames = [
            "schema", "code", "text", "start", "end", "field",
            "instance_id", "source_doc", "coder",
        ]
        with open(out_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in rows:
                writer.writerow(r)

        logger.info(f"Quotation report exported to {out_file}: {len(rows)} quotations")
        return ExportResult(
            success=True,
            format_name=self.format_name,
            files_written=[out_file],
            stats={"quotations_exported": len(rows)},
        )
