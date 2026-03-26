"""
Tabular Exporters (CSV, TSV, JSONL)

Exports annotations to flat tabular formats suitable for analysis in
spreadsheets, pandas, or streaming pipelines.
"""

import csv
import json
import os
import logging
from typing import Optional, Tuple, List

from .base import BaseExporter, ExportContext, ExportResult

logger = logging.getLogger(__name__)


def _flatten_annotation(ann: dict) -> dict:
    """Flatten a single annotation record into a flat dict for tabular output."""
    row = {
        "instance_id": ann.get("instance_id", ""),
        "user_id": ann.get("user_id", ""),
    }
    # Flatten labels: schema_name.label_name = value
    for schema_name, labels in ann.get("labels", {}).items():
        if isinstance(labels, dict):
            for label_name, value in labels.items():
                col = f"{schema_name}.{label_name}" if label_name else schema_name
                row[col] = value if not isinstance(value, (dict, list)) else json.dumps(value)
        else:
            row[schema_name] = labels if not isinstance(labels, (dict, list)) else json.dumps(labels)

    # Flatten spans as JSON strings
    for schema_name, spans in ann.get("spans", {}).items():
        row[f"{schema_name}._spans"] = json.dumps(spans)

    return row


class CSVExporter(BaseExporter):
    """Export annotations to CSV format."""

    format_name = "csv"
    description = "Comma-separated values (one row per user-instance annotation)"
    file_extensions = [".csv"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not context.annotations:
            return False, "No annotations to export"
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        return _write_delimited(context, output_path, "csv", ",")


class TSVExporter(BaseExporter):
    """Export annotations to TSV format."""

    format_name = "tsv"
    description = "Tab-separated values (one row per user-instance annotation)"
    file_extensions = [".tsv"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not context.annotations:
            return False, "No annotations to export"
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        return _write_delimited(context, output_path, "tsv", "\t")


class JSONLExporter(BaseExporter):
    """Export annotations to JSONL format (one JSON object per line)."""

    format_name = "jsonl"
    description = "JSON Lines (one JSON object per user-instance annotation)"
    file_extensions = [".jsonl"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not context.annotations:
            return False, "No annotations to export"
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        os.makedirs(output_path, exist_ok=True)
        out_file = os.path.join(output_path, "annotations.jsonl")

        with open(out_file, "w", encoding="utf-8") as f:
            for ann in context.annotations:
                record = {
                    "instance_id": ann.get("instance_id", ""),
                    "user_id": ann.get("user_id", ""),
                    "labels": ann.get("labels", {}),
                    "spans": ann.get("spans", {}),
                    "links": ann.get("links", {}),
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        files_written = [out_file]
        phase_file = _write_phase_jsonl(context, output_path)
        if phase_file:
            files_written.append(phase_file)

        return ExportResult(
            success=True,
            format_name=self.format_name,
            files_written=files_written,
            stats={
                "num_records": len(context.annotations),
                "num_phase_responses": len(context.phase_responses) if phase_file else 0,
            },
        )


def _should_include_phase_data(context: ExportContext) -> bool:
    """Check if phase response export is enabled."""
    return (
        bool(context.phase_responses)
        and context.config.get("export_include_phase_data", False)
    )


def _write_phase_delimited(context: ExportContext, output_path: str,
                           fmt_name: str, delimiter: str) -> Optional[str]:
    """Write phase responses as a separate delimited file. Returns file path or None."""
    if not _should_include_phase_data(context):
        return None

    out_file = os.path.join(output_path, f"phase_responses.{fmt_name}")
    columns = ["user_id", "phase", "page", "schema", "label_name", "value"]

    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, delimiter=delimiter,
                                extrasaction="ignore")
        writer.writeheader()
        for row in context.phase_responses:
            writer.writerow(row)

    return out_file


def _write_phase_jsonl(context: ExportContext, output_path: str) -> Optional[str]:
    """Write phase responses as a JSONL file. Returns file path or None."""
    if not _should_include_phase_data(context):
        return None

    out_file = os.path.join(output_path, "phase_responses.jsonl")

    with open(out_file, "w", encoding="utf-8") as f:
        for row in context.phase_responses:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    return out_file


def _write_delimited(context: ExportContext, output_path: str,
                     fmt_name: str, delimiter: str) -> ExportResult:
    """Write annotations as a delimited file (CSV or TSV)."""
    os.makedirs(output_path, exist_ok=True)
    out_file = os.path.join(output_path, f"annotations.{fmt_name}")

    # Flatten all annotations to collect the full set of columns
    rows = [_flatten_annotation(ann) for ann in context.annotations]

    if not rows:
        return ExportResult(
            success=True,
            format_name=fmt_name,
            files_written=[out_file],
            stats={"num_records": 0},
        )

    # Collect all column names preserving order (instance_id, user_id first)
    columns = ["instance_id", "user_id"]
    seen = set(columns)
    for row in rows:
        for key in row:
            if key not in seen:
                columns.append(key)
                seen.add(key)

    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, delimiter=delimiter,
                                extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    files_written = [out_file]
    phase_file = _write_phase_delimited(context, output_path, fmt_name, delimiter)
    if phase_file:
        files_written.append(phase_file)

    return ExportResult(
        success=True,
        format_name=fmt_name,
        files_written=files_written,
        stats={
            "num_records": len(rows),
            "num_columns": len(columns),
            "num_phase_responses": len(context.phase_responses) if phase_file else 0,
        },
    )
