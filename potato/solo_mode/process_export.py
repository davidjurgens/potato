"""
Organized process-data export for Solo Mode.

Separate from final_dataset.py (the lean, single "what's the data" file) —
this answers a different question, "did the process work," and is kept
in its own well-labeled files rather than merged into one blob so each
piece can be read (or handed to a collaborator) for what it actually is:

    metadata_behavioral.csv  — per-instance interaction/timing summary
    validation_human.csv     — your independent judgment on the final
                                validation sample
    validation_llm.csv       — the LLM's original prediction on that same
                                sample, in its own file so it isn't read
                                alongside your answer
    cooperative.csv          — instances where you and the LLM both
                                labeled during regular annotation (agreed
                                or resolved after disagreement) — this is
                                the main-annotation process, distinct from
                                the validation sample above
    codebook_versions.csv    — one row per codebook revision a
                                codebook-driven relabel sweep has run
                                against, with the agreement rate and
                                sample size measured under it — see
                                manager.codebook_version_history
    codebook_snapshots.json  — the full codebook (every code's fields) as
                                it read at each of those revisions, keyed
                                by revision — codebook_versions.csv's
                                numbers without this are numbers about an
                                unrecorded codebook

All six are bundled into one ZIP by ``build_zip()``.
"""

import csv
import io
import json
import zipfile
from typing import Any, Dict, List


def _rows_to_csv(rows: List[Dict[str, Any]], columns: List[str]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def build_behavioral_rows(manager: Any) -> List[Dict[str, Any]]:
    """One row per (user, instance) with a readable interaction summary —
    not the raw nested event log, which isn't something a person scans."""
    from potato.user_state_management import get_user_state_manager

    rows: List[Dict[str, Any]] = []
    try:
        usm = get_user_state_manager()
    except Exception:
        return rows

    for user_id in usm.get_user_ids():
        user_state = usm.get_user_state(user_id)
        if user_state is None:
            continue
        for instance_id, bd in user_state.instance_id_to_behavioral_data.items():
            rows.append({
                'user_id': user_id,
                'instance_id': instance_id,
                'time_on_instance_seconds': round((bd.total_time_ms or 0) / 1000, 1),
                'num_interactions': len(bd.interactions or []),
                'num_annotation_changes': len(bd.annotation_changes or []),
                'num_ai_assist_uses': len(bd.ai_usage or []),
            })

    rows.sort(key=lambda r: (r['user_id'], r['instance_id']))
    return rows


def build_validation_human_rows(manager: Any) -> List[Dict[str, Any]]:
    """Your own independent label for each validated instance — no LLM
    label in this file, by design (see module docstring)."""
    schemes = manager.app_config.get('annotation_schemes', [])
    schema_name = schemes[0].get('name', 'default') if schemes else 'default'

    rows: List[Dict[str, Any]] = []
    completed_ids = manager.validation_sample_ids & manager.validated_instance_ids
    for instance_id in sorted(completed_ids):
        prediction = manager.predictions.get(instance_id, {}).get(schema_name)
        if prediction is None or prediction.human_label is None:
            continue
        rows.append({
            'instance_id': instance_id,
            'text': manager._get_instance_text(instance_id),
            'human_label': prediction.human_label,
        })
    return rows


def build_validation_llm_rows(manager: Any) -> List[Dict[str, Any]]:
    """The LLM's original prediction for each validated instance — same
    instance_id set as validation_human.csv, joinable on that column, but
    kept as a separate file rather than one merged comparison table."""
    schemes = manager.app_config.get('annotation_schemes', [])
    schema_name = schemes[0].get('name', 'default') if schemes else 'default'

    rows: List[Dict[str, Any]] = []
    completed_ids = manager.validation_sample_ids & manager.validated_instance_ids
    for instance_id in sorted(completed_ids):
        prediction = manager.predictions.get(instance_id, {}).get(schema_name)
        if prediction is None or prediction.human_label is None:
            continue
        rows.append({
            'instance_id': instance_id,
            'text': manager._get_instance_text(instance_id),
            'llm_label': prediction.predicted_label,
            'llm_confidence': prediction.confidence_score,
        })
    return rows


def build_cooperative_rows(manager: Any) -> List[Dict[str, Any]]:
    """Instances both you and the LLM labeled during regular annotation
    (not the validation sample — see module docstring): where you
    agreed, and where you resolved a disagreement, with what each side
    said and how it was settled."""
    schemes = manager.app_config.get('annotation_schemes', [])
    schema_name = schemes[0].get('name', 'default') if schemes else 'default'

    rows: List[Dict[str, Any]] = []
    for instance_id, by_schema in manager.predictions.items():
        if instance_id in manager.validation_sample_ids:
            continue  # that's validation data, not cooperative annotation
        prediction = by_schema.get(schema_name)
        if prediction is None or prediction.human_label is None:
            continue

        if prediction.disagreement_resolved:
            outcome = 'resolved'
            final_label = prediction.resolution_label
        elif prediction.agrees_with_human:
            outcome = 'agreed'
            final_label = prediction.human_label
        else:
            outcome = 'pending'
            final_label = prediction.human_label

        rows.append({
            'instance_id': instance_id,
            'text': manager._get_instance_text(instance_id),
            'human_label': prediction.human_label,
            'llm_label': prediction.predicted_label,
            'outcome': outcome,
            'final_label': final_label,
        })

    rows.sort(key=lambda r: r['instance_id'])
    return rows


def build_codebook_version_rows(manager: Any) -> List[Dict[str, Any]]:
    """One row per codebook revision codebook_version_history has an
    entry for, oldest first. A small sample_size is flagged in its own
    column rather than silently folded into the agreement number, since
    a 100% rate over 3 examples and a 100% rate over 80 mean very
    different things."""
    rows: List[Dict[str, Any]] = []
    for revision, entry in sorted(manager.codebook_version_history.items()):
        agreement_rate = entry.get('agreement_rate')
        sample_size = entry.get('sample_size') or 0
        rows.append({
            'revision': revision,
            'agreement_rate': (
                round(agreement_rate * 100, 1)
                if agreement_rate is not None else ''),
            'sample_size': sample_size,
            'small_sample': 'yes' if 0 < sample_size < 10 else '',
            'started_at': entry.get('started_at') or '',
            'completed_at': entry.get('completed_at') or '',
        })
    return rows


def build_codebook_snapshots(manager: Any) -> str:
    """The full codebook as it read at each revision in
    codebook_version_history, as pretty-printed JSON keyed by revision —
    what codebook_versions.csv's agreement numbers actually describe."""
    return json.dumps(
        {
            str(revision): entry.get('snapshot', [])
            for revision, entry in sorted(
                manager.codebook_version_history.items())
        },
        indent=2, default=str,
    )


def build_zip(manager: Any) -> bytes:
    """Bundle all files into one ZIP for a single download."""
    files = {
        'metadata_behavioral.csv': _rows_to_csv(
            build_behavioral_rows(manager),
            ['user_id', 'instance_id', 'time_on_instance_seconds',
             'num_interactions', 'num_annotation_changes',
             'num_ai_assist_uses'],
        ),
        'validation_human.csv': _rows_to_csv(
            build_validation_human_rows(manager),
            ['instance_id', 'text', 'human_label'],
        ),
        'validation_llm.csv': _rows_to_csv(
            build_validation_llm_rows(manager),
            ['instance_id', 'text', 'llm_label', 'llm_confidence'],
        ),
        'cooperative.csv': _rows_to_csv(
            build_cooperative_rows(manager),
            ['instance_id', 'text', 'human_label', 'llm_label', 'outcome',
             'final_label'],
        ),
        'codebook_versions.csv': _rows_to_csv(
            build_codebook_version_rows(manager),
            ['revision', 'agreement_rate', 'sample_size', 'small_sample',
             'started_at', 'completed_at'],
        ),
        'codebook_snapshots.json': build_codebook_snapshots(manager),
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for filename, content in files.items():
            zf.writestr(filename, content)
    return buf.getvalue()
