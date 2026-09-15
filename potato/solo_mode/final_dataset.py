"""
Lean, readable final-dataset export for Solo Mode.

Deliberately narrow: one row per (instance, schema) with the label that
should actually be used downstream, plus where it came from. Nothing about
calibration, behavioral tracking, or raw event logs — those answer a
different question (did the process work?) than this one (what's the
data?), and belong elsewhere if exported at all.

Provenance per row (``source``):
    human       — only a human label exists (LLM hasn't reached it yet,
                  or LLM prediction disabled)
    llm         — only an LLM label exists (autonomous labeling phase)
    agreed      — human and LLM independently produced the same label
    resolved    — human and LLM disagreed; a human resolved it (the final
                  label may differ from both original guesses)
    pending     — human and LLM disagreed and it hasn't been resolved yet;
                  included so nothing silently vanishes, flagged clearly
"""

import csv
import io
from typing import Any, Dict, List, Optional


def _classify(prediction: Optional[Any], human_label: Optional[Any]):
    """Return (final_label, source, note) for one (instance, schema)."""
    if prediction is None:
        return human_label, 'human', ''

    if human_label is None:
        note = (
            f'LLM only (confidence {prediction.confidence_score:.2f})'
            if prediction.confidence_score is not None else 'LLM only'
        )
        return prediction.predicted_label, 'llm', note

    if prediction.disagreement_resolved:
        note = (
            f'human resolved disagreement '
            f'(LLM predicted "{prediction.predicted_label}")'
        )
        return prediction.resolution_label, 'resolved', note

    if str(prediction.predicted_label) == str(human_label):
        return human_label, 'agreed', ''

    note = f'unresolved disagreement (LLM predicted "{prediction.predicted_label}")'
    return human_label, 'pending', note


def build_rows(manager: Any) -> List[Dict[str, Any]]:
    """Build the flat, readable final-dataset rows for a Solo Mode manager.

    One row per (instance_id, schema_name) that has a human label, an LLM
    prediction, or both. A ``schema`` column is only included when the
    task has more than one annotation scheme — most Solo Mode tasks have
    exactly one, and a row-per-instance table reads more cleanly without
    a column that's the same value every row.
    """
    schema_names = [
        s.get('name') for s in manager.app_config.get('annotation_schemes', [])
        if s.get('name')
    ]
    multi_schema = len(schema_names) > 1

    instance_ids = set(manager.human_labeled_ids) | set(manager.predictions.keys())

    rows: List[Dict[str, Any]] = []
    for instance_id in sorted(instance_ids):
        predictions_for_instance = manager.predictions.get(instance_id, {})

        seen_schemas = set(predictions_for_instance.keys())
        human_labels: Dict[str, Any] = {}
        for schema_name in schema_names:
            label = manager._get_stored_human_label(instance_id, schema_name)
            if label is not None:
                human_labels[schema_name] = label
                seen_schemas.add(schema_name)
        if not seen_schemas:
            continue

        text = manager._get_instance_text(instance_id)
        for schema_name in sorted(seen_schemas):
            prediction = predictions_for_instance.get(schema_name)
            human_label = human_labels.get(schema_name)
            final_label, source, note = _classify(prediction, human_label)

            row: Dict[str, Any] = {
                'instance_id': instance_id,
                'text': text,
                'final_label': final_label,
                'source': source,
                'note': note,
            }
            if multi_schema:
                row['schema'] = schema_name
            rows.append(row)

    return rows


def to_csv(rows: List[Dict[str, Any]]) -> str:
    """Render rows to a CSV string, spreadsheet-ready."""
    if not rows:
        columns = ['instance_id', 'text', 'final_label', 'source', 'note']
    else:
        columns = list(rows[0].keys())

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()
