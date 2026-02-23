"""
Parquet Exporter

Exports annotations as Apache Parquet files via PyArrow, producing columnar
tables suitable for analysis with pandas, DuckDB, Spark, or HuggingFace Datasets.

Output files:
    annotations.parquet - One row per (instance_id, user_id) with flattened schema columns
    spans.parquet       - One row per span annotation (if span schemas exist)
    items.parquet       - One row per item with original data fields
"""

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

logger = logging.getLogger(__name__)


def _check_pyarrow():
    """Try to import pyarrow and return (pa, pq) or raise ImportError."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    return pa, pq


class ParquetExporter(BaseExporter):
    """
    Exports annotations as Parquet files.

    Produces up to three tables:
    - annotations.parquet: one row per (instance_id, user_id), flat columns per schema
    - spans.parquet: one row per span annotation
    - items.parquet: one row per item (original data)
    """

    format_name = "parquet"
    description = "Apache Parquet columnar format for large-scale analysis (pandas, DuckDB, Spark)"
    file_extensions = [".parquet"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        try:
            _check_pyarrow()
        except ImportError:
            return False, "pyarrow is required for Parquet export. Install with: pip install pyarrow>=12.0.0"

        if not context.annotations:
            return False, "No annotations to export"

        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        options = options or {}
        files_written = []
        warnings = []

        try:
            pa, pq = _check_pyarrow()
        except ImportError as e:
            return ExportResult(
                success=False,
                format_name=self.format_name,
                errors=[str(e)],
            )

        compression = options.get("compression", "snappy")
        include_items = options.get("include_items", True)
        include_spans = options.get("include_spans", True)
        row_group_size = options.get("row_group_size", None)

        # Normalize string booleans from CLI
        if isinstance(include_items, str):
            include_items = include_items.lower() not in ("false", "0", "no")
        if isinstance(include_spans, str):
            include_spans = include_spans.lower() not in ("false", "0", "no")

        try:
            os.makedirs(output_path, exist_ok=True)
            schema_map = {s["name"]: s for s in context.schemas}

            # 1. Write annotations.parquet
            ann_path = os.path.join(output_path, "annotations.parquet")
            ann_rows = self._build_annotation_rows(context.annotations, schema_map)
            if ann_rows:
                table = pa.Table.from_pylist(ann_rows)
                write_kwargs = {"compression": compression}
                if row_group_size is not None:
                    write_kwargs["row_group_size"] = int(row_group_size)
                pq.write_table(table, ann_path, **write_kwargs)
                files_written.append(ann_path)

            # 2. Write spans.parquet
            if include_spans:
                span_rows = self._build_span_rows(context.annotations)
                if span_rows:
                    span_path = os.path.join(output_path, "spans.parquet")
                    span_table = pa.Table.from_pylist(span_rows)
                    pq.write_table(span_table, span_path, compression=compression)
                    files_written.append(span_path)

            # 3. Write items.parquet
            if include_items and context.items:
                items_path = os.path.join(output_path, "items.parquet")
                item_rows = self._build_item_rows(context.items)
                if item_rows:
                    items_table = pa.Table.from_pylist(item_rows)
                    pq.write_table(items_table, items_path, compression=compression)
                    files_written.append(items_path)

            return ExportResult(
                success=True,
                format_name=self.format_name,
                files_written=files_written,
                warnings=warnings,
                stats={
                    "annotation_rows": len(ann_rows),
                    "span_rows": len(span_rows) if include_spans else 0,
                    "item_rows": len(item_rows) if include_items and context.items else 0,
                    "compression": compression,
                },
            )

        except Exception as e:
            logger.error(f"Parquet export failed: {e}")
            return ExportResult(
                success=False,
                format_name=self.format_name,
                files_written=files_written,
                errors=[str(e)],
            )

    def _build_annotation_rows(self, annotations: List[dict],
                                schema_map: Dict[str, dict]) -> List[dict]:
        """Build flat row dicts for the annotations table."""
        rows = []
        for ann in annotations:
            row = {
                "instance_id": ann.get("instance_id", ""),
                "user_id": ann.get("user_id", ""),
            }

            labels = ann.get("labels", {})
            for schema_name, value in labels.items():
                schema_config = schema_map.get(schema_name, {})
                schema_type = schema_config.get("annotation_type", "")
                row[schema_name] = self._flatten_value(value, schema_type)

            rows.append(row)
        return rows

    def _flatten_value(self, value: Any, schema_type: str) -> Any:
        """Flatten an annotation value to a Parquet-compatible type."""
        if schema_type in ("radio", "select"):
            return self._flatten_categorical(value)
        elif schema_type in ("likert", "slider", "number"):
            return self._flatten_numeric(value)
        elif schema_type == "multiselect":
            return self._flatten_multiselect(value)
        elif schema_type == "text":
            if isinstance(value, str):
                return value
            return str(value) if value is not None else None
        else:
            # Generic fallback
            if isinstance(value, dict):
                return self._flatten_categorical(value)
            return value

    def _flatten_categorical(self, value: Any) -> Optional[str]:
        """Extract the selected label from a categorical annotation."""
        if isinstance(value, dict):
            if not value:
                return None
            # Return the key with the highest value
            def _sort_key(k):
                try:
                    return float(value[k])
                except (ValueError, TypeError):
                    return 0
            return max(value.keys(), key=_sort_key)
        if isinstance(value, str):
            return value
        return str(value) if value is not None else None

    def _flatten_numeric(self, value: Any) -> Optional[float]:
        """Extract a numeric value."""
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        if isinstance(value, dict):
            # Try to extract numeric from dict values
            for v in value.values():
                try:
                    return float(v)
                except (ValueError, TypeError):
                    pass
        return None

    def _flatten_multiselect(self, value: Any) -> Optional[List[str]]:
        """Extract selected labels from a multiselect annotation."""
        if isinstance(value, dict):
            return [label for label, selected in value.items() if selected]
        if isinstance(value, list):
            return [str(v) for v in value]
        return None

    def _build_span_rows(self, annotations: List[dict]) -> List[dict]:
        """Build flat row dicts for the spans table."""
        rows = []
        for ann in annotations:
            instance_id = ann.get("instance_id", "")
            user_id = ann.get("user_id", "")
            spans = ann.get("spans", {})

            for schema_name, span_list in spans.items():
                if not isinstance(span_list, list):
                    continue
                for span in span_list:
                    if not isinstance(span, dict):
                        continue
                    rows.append({
                        "instance_id": instance_id,
                        "user_id": user_id,
                        "schema_name": schema_name,
                        "start": span.get("start"),
                        "end": span.get("end"),
                        "label": span.get("label", ""),
                        "text": span.get("text", ""),
                    })
        return rows

    def _build_item_rows(self, items: Dict[str, dict]) -> List[dict]:
        """Build flat row dicts for the items table."""
        rows = []
        for item_id, item_data in items.items():
            row = {"item_id": item_id}
            if isinstance(item_data, dict):
                for key, val in item_data.items():
                    # Convert non-primitive types to strings for Parquet compatibility
                    if isinstance(val, (dict, list)):
                        import json
                        row[key] = json.dumps(val, ensure_ascii=False)
                    else:
                        row[key] = val
            rows.append(row)
        return rows
