"""The ``PublishBundle`` — a normalized, ready-to-ship dataset.

A bundle is the output of the preprocessing pipeline and the input to every target
adapter (HuggingFace / Zenodo / local archive). It holds the data splits (already
anonymized/aggregated/filtered), the schemas, resolved metadata, the report metrics,
the generated card, and any media files to ship alongside.

Row shapes reuse the canonical flattening from
``potato.export.tabular_exporter._flatten_annotation`` (``schema.label`` columns,
spans as ``schema._spans`` JSON) so a published dataset matches Potato's other
tabular exports column-for-column.
"""

import csv
import json
import os
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from potato.export.tabular_exporter import _flatten_annotation

_RESERVED_COLS = {"instance_id", "user_id", "n_annotators"}


@dataclass
class PublishBundle:
    """A packaged dataset ready to hand to a target adapter."""

    splits: Dict[str, List[dict]]
    schemas: List[dict]
    metadata: Any                       # publish.config.DatasetMetadata
    config: dict
    stats: Dict[str, Any] = field(default_factory=dict)   # paper.compute_metrics
    media_files: List[str] = field(default_factory=list)
    card_markdown: str = ""
    warnings: List[str] = field(default_factory=list)

    def split_row_counts(self) -> Dict[str, int]:
        return {name: len(rows) for name, rows in self.splits.items()}


# ------------------------------------------------------------- row builders --


def build_annotation_rows(annotations: List[dict]) -> List[dict]:
    """One flat row per (instance, annotator), matching the tabular exporter."""
    return [_flatten_annotation(ann) for ann in annotations]


def build_span_rows(annotations: List[dict]) -> List[dict]:
    """One row per span across all annotators (flat, join-friendly)."""
    rows = []
    for ann in annotations:
        instance_id = ann.get("instance_id", "")
        user_id = ann.get("user_id", "")
        for schema_name, span_list in (ann.get("spans", {}) or {}).items():
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
                    "label": span.get("label", span.get("name", "")),
                    "text": span.get("text", ""),
                })
    return rows


def build_item_rows(items: Dict[str, dict]) -> List[dict]:
    """One row per source instance (the raw data being annotated)."""
    rows = []
    for item_id, item_data in items.items():
        row = {"item_id": item_id}
        if isinstance(item_data, dict):
            for key, val in item_data.items():
                row[key] = val if not isinstance(val, (dict, list)) \
                    else json.dumps(val, ensure_ascii=False)
        rows.append(row)
    return rows


def _looks_numeric(values: List[Any]) -> bool:
    for v in values:
        try:
            float(v)
        except (TypeError, ValueError):
            return False
    return bool(values)


def build_gold_rows(annotation_rows: List[dict],
                    aggregation: str = "majority") -> List[dict]:
    """Aggregate per-annotator rows into one resolved row per instance.

    Categorical columns resolve by majority vote; with ``aggregation="mean"``,
    columns whose values are all numeric resolve to their mean instead. Each row
    carries ``n_annotators`` (distinct annotators who labeled the instance) so
    consumers can weight or filter by coverage.
    """
    by_instance: Dict[str, List[dict]] = defaultdict(list)
    for row in annotation_rows:
        by_instance[row.get("instance_id", "")].append(row)

    gold = []
    for instance_id, rows in by_instance.items():
        annotators = {r.get("user_id", "") for r in rows}
        out = {"instance_id": instance_id, "n_annotators": len(annotators)}
        columns = set()
        for r in rows:
            columns.update(k for k in r if k not in _RESERVED_COLS)
        for col in sorted(columns):
            values = [r[col] for r in rows
                      if col in r and r[col] not in (None, "")]
            if not values:
                continue
            if aggregation == "mean" and _looks_numeric(values):
                out[col] = sum(float(v) for v in values) / len(values)
            else:
                out[col] = Counter(values).most_common(1)[0][0]
        gold.append(out)
    gold.sort(key=lambda r: str(r["instance_id"]))
    return gold


# ----------------------------------------------------------------- writers --


def _all_columns(rows: List[dict]) -> List[str]:
    cols: List[str] = []
    seen = set()
    for row in rows:
        for k in row:
            if k not in seen:
                seen.add(k)
                cols.append(k)
    return cols


def _encode(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def write_split(rows: List[dict], path: str, fmt: str = "jsonl") -> str:
    """Write one split to ``path`` (extension added). Returns the file path."""
    fmt = (fmt or "jsonl").lower()
    if fmt == "jsonl":
        out = path + ".jsonl"
        with open(out, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return out
    if fmt == "csv":
        out = path + ".csv"
        cols = _all_columns(rows)
        with open(out, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=cols)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: _encode(row.get(k, "")) for k in cols})
        return out
    if fmt == "parquet":
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as e:
            raise ImportError(
                "parquet output needs pyarrow: pip install pyarrow>=12.0.0") from e
        cols = _all_columns(rows)
        table = pa.table({c: [_encode(row.get(c)) for row in rows] for c in cols})
        out = path + ".parquet"
        pq.write_table(table, out)
        return out
    raise ValueError(f"Unknown split format: {fmt!r} (use jsonl, csv, or parquet)")
