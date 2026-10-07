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

from potato.export.origin_columns import origin_in_use
from potato.export.tabular_exporter import _flatten_annotation


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
    """One flat row per (instance, annotator), matching the tabular exporter.

    That includes the ``annotator_origin`` columns when any row is from a
    declared machine rater: a published dataset is where a reader most needs
    to tell a tool's labels from a person's.
    """
    with_origin = origin_in_use(annotations)
    return [_flatten_annotation(ann, with_origin=with_origin)
            for ann in annotations]


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


def build_gold_rows(annotations: List[dict],
                    aggregation: str = "majority",
                    schemas: Optional[List[dict]] = None,
                    instance_ids: Optional[set] = None) -> List[dict]:
    """One resolved row per instance, with a column per schema.

    Each annotator's stored labels are first collapsed to their answer (the
    same collapse the exporter and display logic use), and the vote is taken
    over annotators:

    - a single choice is the answer most annotators gave. A tie has no
      majority: the column is None and ``gold_notes`` says so.
    - a multiselect is the list of labels ticked by more than half of the
      annotators who answered it.
    - with ``aggregation="mean"``, an all-numeric schema is the mean.

    This used to vote inside each flattened ``schema.label`` column, where
    every value present was that column's own label. A radio voted pos, pos,
    neg came out with both ``sentiment.positive`` and ``sentiment.negative``
    set, a multiselect kept every label anyone ticked, and a tie went to
    whichever annotator was read first.

    ``instance_ids`` limits the rows to instances that survived the coverage
    filter. ``n_annotators`` counts the annotators who answered anything.
    """
    from potato.server_utils.answer_collapse import (MULTI_SELECT_TYPES,
                                                     collapse_entries)

    types = {s.get("name"): s.get("annotation_type")
             for s in (schemas or []) if isinstance(s, dict)}
    # instance -> user -> schema -> answer
    answers: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    for ann in annotations or []:
        iid = ann.get("instance_id", "")
        if instance_ids is not None and iid not in instance_ids:
            continue
        user = ann.get("user_id", "")
        for schema, labels in (ann.get("labels") or {}).items():
            if isinstance(labels, dict):
                answer, _w, _m = collapse_entries(
                    list(labels.items()), schema=schema,
                    annotation_type=types.get(schema), changes=ann.get("_changes"))
            else:
                answer = labels
            if answer is None or answer == "":
                continue
            answers[iid].setdefault(user, {})[schema] = answer

    gold = []
    for iid, by_user in answers.items():
        out: Dict[str, Any] = {"instance_id": iid, "n_annotators": len(by_user)}
        notes: List[str] = []
        schema_names = sorted({sc for per in by_user.values() for sc in per})
        for schema in schema_names:
            given = [per[schema] for per in by_user.values() if schema in per]
            if types.get(schema) in MULTI_SELECT_TYPES or any(isinstance(g, list) for g in given):
                ticks = Counter(label for g in given
                                for label in set(g if isinstance(g, list) else [g]))
                out[schema] = sorted(label for label, n in ticks.items()
                                     if n * 2 > len(given))
                continue
            if aggregation == "mean" and _looks_numeric(given):
                out[schema] = sum(float(v) for v in given) / len(given)
                continue
            ranked = Counter(str(g) for g in given).most_common()
            if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
                tied = sorted(v for v, n in ranked if n == ranked[0][1])
                out[schema] = None
                notes.append(f"{schema}: tie between {', '.join(tied)}")
                continue
            winner = ranked[0][0]
            out[schema] = next(g for g in given if str(g) == winner)
        if notes:
            out["gold_notes"] = notes
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
