"""
Parquet Exporter

Exports annotations as Apache Parquet files via PyArrow, producing columnar
tables suitable for analysis with pandas, DuckDB, Spark, or HuggingFace Datasets.

Output files:
    annotations.parquet - One row per (instance_id, user_id) with flattened schema columns
    spans.parquet       - One row per span annotation (if span schemas exist)
    items.parquet       - One row per item with original data fields
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

logger = logging.getLogger(__name__)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


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
                span_rows = self._build_span_rows(context.annotations, context)
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

            # 4. Write phase_responses.parquet
            #
            # csv and jsonl have written this since F-047; parquet did not, and
            # said nothing either way, so a study that collected consent and a
            # post-study survey handed over neither and the key that was meant
            # to control it read as honoured. Same predicate and same warning as
            # the delimited exporters, so the three cannot drift apart again.
            from potato.export.tabular_exporter import (
                _phase_exclusion_warning, _should_include_phase_data,
            )

            phase_rows = []
            if _should_include_phase_data(context):
                phase_rows = self._build_phase_rows(context.phase_responses)
                if phase_rows:
                    phase_path = os.path.join(output_path,
                                              "phase_responses.parquet")
                    phase_table = pa.Table.from_pylist(phase_rows)
                    pq.write_table(phase_table, phase_path,
                                   compression=compression)
                    files_written.append(phase_path)
            else:
                excluded = _phase_exclusion_warning(context)
                if excluded:
                    warnings.append(excluded)

            return ExportResult(
                success=True,
                format_name=self.format_name,
                files_written=files_written,
                warnings=warnings,
                stats={
                    "annotation_rows": len(ann_rows),
                    "span_rows": len(span_rows) if include_spans else 0,
                    "item_rows": len(item_rows) if include_items and context.items else 0,
                    "phase_response_rows": len(phase_rows),
                    "phase_responses_excluded": (
                        0 if phase_rows else len(context.phase_responses or [])),
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
                composite = self._composite_columns(value, schema_type)
                if composite is None:
                    row[schema_name] = self._flatten_value(value, schema_type)
                else:
                    for sub_name, sub_value in composite.items():
                        column = (f"{schema_name}.{sub_name}" if sub_name
                                  else schema_name)
                        row[column] = sub_value

            rows.append(row)

        self._unify_mixed_columns(rows)
        self._align_columns(rows)
        return rows

    @staticmethod
    def _align_columns(rows: List[dict]) -> None:
        """Give every row every column, in first-appearance order.

        ``pa.Table.from_pylist`` infers the schema from the **first row alone**
        and silently drops any key that row does not have. So a schema nobody
        answered on the first (instance, user) pair was missing from the entire
        file -- not null, absent -- however many later rows held it. An
        optional textbox, a conditional scheme behind ``display_logic``, or an
        item field only some items carry all hit it.

        Filling the union with None also makes the per-row sub-columns that
        ``_flatten_composite`` emits safe: a multirate row a given annotator
        skipped is a null in its column rather than a missing column.
        """
        columns: List[str] = []
        seen = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    columns.append(key)
        for row in rows:
            for key in columns:
                row.setdefault(key, None)

    @staticmethod
    def _unify_mixed_columns(rows: List[dict]) -> None:
        """Force any column holding both numbers and strings to strings.

        Parquet columns are typed, and `pa.Table.from_pylist` raises on the
        first value that does not fit the type it inferred -- which aborts the
        whole export, not just that column. A labelled scale can genuinely mix:
        `labels: [1, 2, 3, "Not applicable"]` flattens to three floats and a
        string. Choosing the shape per column rather than per value keeps the
        file writable and keeps every answer in it.
        """
        column_types: Dict[str, set] = {}
        for row in rows:
            for key, value in row.items():
                if value is None:
                    continue
                kind = ("number" if isinstance(value, (int, float))
                        and not isinstance(value, bool) else
                        "string" if isinstance(value, str) else None)
                if kind:
                    column_types.setdefault(key, set()).add(kind)

        mixed = {k for k, kinds in column_types.items() if len(kinds) > 1}
        if not mixed:
            return
        for row in rows:
            for key in mixed:
                value = row.get(key)
                if value is None:
                    continue
                # `3` came from a scale point, not a measurement: render it "3",
                # not "3.0", so the column reads the way the labels do.
                if isinstance(value, float) and value.is_integer():
                    row[key] = str(int(value))
                else:
                    row[key] = str(value)

    def _flatten_value(self, value: Any, schema_type: str) -> Any:
        """Flatten an annotation value to a Parquet-compatible type.

        Routing on the declared type alone is not enough, because one declared
        type has two stored shapes. A `likert` with an explicit `labels:` list
        renders as a radio group -- the generator says so at boot -- and stores
        its answer categorically, `{"Moderate": "Moderate"}`. Sent to
        `_flatten_numeric` that yields None on every row, and the column is
        present and entirely null, which reads as "nobody answered this" rather
        than "the exporter could not represent it". The shape the bundled
        full-study skeleton recommends is exactly this one.
        """
        if schema_type in ("radio", "select"):
            return self._flatten_categorical(value)
        elif schema_type in ("likert", "slider", "number"):
            numeric = self._flatten_numeric(value)
            if numeric is not None:
                return numeric
            # A labelled scale is stored as a label. Better the label than a
            # null; the CSV exporter and /admin/iaa both keep it.
            return self._flatten_categorical(value)
        elif schema_type == "multiselect":
            return self._flatten_multiselect(value)
        elif schema_type == "text":
            return self._flatten_text(value)
        else:
            # Generic fallback
            if isinstance(value, dict):
                return self._flatten_categorical(value)
            return value

    # The types whose stored shape this exporter knows how to reduce to one
    # scalar. Everything else reaches `_composite_columns` first.
    _SCALAR_TYPES = frozenset({
        "radio", "select", "likert", "slider", "number", "multiselect", "text",
    })

    @classmethod
    def _composite_columns(cls, value: Any,
                           schema_type: str) -> Optional[Dict[str, Any]]:
        """Sub-columns for an answer that is several answers, or None.

        `_flatten_categorical` reads a stored dict as "the selected label is
        one of the keys" and returns one of them. That is true for a radio
        (`{"positive": True}`) and for a labelled scale (`{"5": "5"}`), where
        the key *is* the answer. It is false for every scheme that stores
        several sub-answers keyed by row, option or step -- multirate keys by
        row name, constant_sum and soft_label by option, image_annotation by
        the `_data` blob, and the agent-trace schemes by step index. For those,
        the value carries the answer and the key merely names the question, so
        returning a key returned the *question* and dropped every answer:
        a three-row multirate exported as the string "Reproducibility".

        Fifty-four of the sixty-one registered types take that branch, and the
        ones that survived it did so by coincidence -- `confidence` stores
        `{"5": "5"}`, so the key happens to be the value.

        The test is therefore "do the keys carry the answer": a single key that
        equals its own value, or that holds a selection flag, is categorical.
        Anything else is expanded to `schema.key` columns, which is the shape
        the csv and jsonl exporters have always written for the same data.
        """
        if schema_type in cls._SCALAR_TYPES:
            return None
        if not isinstance(value, dict) or not value:
            return None
        if len(value) == 1:
            (key, only), = value.items()
            if isinstance(only, bool) or only is None:
                return None
            if isinstance(only, str):
                if only == str(key) or only.strip().lower() in (
                        "", "true", "false", "on", "off"):
                    return None
            elif str(only) == str(key):
                return None
        return {str(k): (v if not isinstance(v, (dict, list))
                         else _json_dumps(v))
                for k, v in value.items()}

    def _flatten_text(self, value: Any) -> Optional[str]:
        """The typed text, not the container it arrived in.

        A textbox stores `{"text_box": "what they wrote"}`; `str()` on that
        gives the repr of a dict, so every free-text column came out as
        `{'text_box': 'alice r06'}`.
        """
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            parts = [str(v) for v in value.values()
                     if v is not None and str(v) != ""]
            return "\n".join(parts) if parts else None
        if isinstance(value, (list, tuple)):
            parts = [str(v) for v in value if v is not None and str(v) != ""]
            return "\n".join(parts) if parts else None
        return str(value)

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

    def _build_phase_rows(self, phase_responses: List[dict]) -> List[dict]:
        """Phase/survey rows, columns matching the csv and jsonl files.

        Every row carries every column so the parquet schema is stable even
        when only some rows have `hidden` or `superseded`.
        """
        columns = ["user_id", "phase", "page", "sequence", "schema",
                   "label_name", "value"]
        for optional in ("hidden", "superseded"):
            if any(optional in row for row in phase_responses or []):
                columns.append(optional)

        rows = []
        for response in phase_responses or []:
            row = {}
            for column in columns:
                value = response.get(column)
                # `value` and `sequence` are the only ones that vary in type;
                # a typed column cannot hold both, so store them as text.
                row[column] = None if value is None else (
                    value if isinstance(value, (bool, int)) and column != "value"
                    else str(value))
            rows.append(row)
        return rows

    def _build_span_rows(self, annotations: List[dict],
                         context: Optional["ExportContext"] = None) -> List[dict]:
        """Build flat row dicts for the spans table.

        Both content columns were empty on every row: `label` read a `label`
        key the stored span does not have -- it is `name` -- and `text` read a
        key nothing ever writes. So a reader could not even tell which label
        had been applied without going back to the csv.
        """
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
                    text = span.get("text") or span.get("value")
                    if not isinstance(text, str) and context is not None:
                        text = context.covered_text(instance_id, span)
                    rows.append({
                        "instance_id": instance_id,
                        "user_id": user_id,
                        "schema_name": schema_name,
                        "start": span.get("start"),
                        "end": span.get("end"),
                        # The stored span calls it `name`; `label` was always "".
                        "label": (span.get("name")
                                  or span.get("label")
                                  or span.get("title") or ""),
                        "text": text if isinstance(text, str) else "",
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
                        row[key] = _json_dumps(val)
                    else:
                        row[key] = val
            rows.append(row)
        # Items are not required to carry identical fields, and the first one
        # decided the whole schema. See `_align_columns`.
        self._unify_mixed_columns(rows)
        self._align_columns(rows)
        return rows
