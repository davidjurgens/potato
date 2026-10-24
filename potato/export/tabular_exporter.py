"""
Tabular Exporters (CSV, TSV, JSONL)

Exports annotations to flat tabular formats suitable for analysis in
spreadsheets, pandas, or streaming pipelines.
"""

import csv
import json
import os
import logging
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult
from .origin_columns import (engine_fields, engine_in_use, origin_fields, origin_in_use,
                             record_origin)
from .single_select import (
    EXEMPT_LABEL_NAMES,
    resolve_final_label,
    single_select_schema_names,
)

logger = logging.getLogger(__name__)


def _single_select_names(context: ExportContext) -> set:
    """Single-select schema names across annotation schemes and SurveyFlow questions."""
    names = single_select_schema_names(context.schemas or [])
    cfg = getattr(context, "config", None) or {}
    names |= single_select_schema_names(cfg.get("_surveyflow_schemes") or [])
    return names


def _spans_with_text(ann: dict,
                     context: Optional[ExportContext]) -> Dict[str, Any]:
    """This record's spans, each carrying the words it covers.

    A stored span is offsets and a label with no content, so every tabular
    export left the reader joining back to the data file and slicing on
    start/end to find out what was marked -- `conll` was the only format that
    showed the words, because it re-tokenises the source itself.
    `context.covered_text` does that slice once, against the item the span was
    drawn on, so the text can never disagree with the offsets.
    """
    spans_by_schema = ann.get("spans", {}) or {}
    if context is None:
        return spans_by_schema

    instance_id = ann.get("instance_id", "")
    out = {}
    for schema_name, spans in spans_by_schema.items():
        if not isinstance(spans, list):
            out[schema_name] = spans
            continue
        out[schema_name] = [
            ({**span, "text": context.covered_text(instance_id, span)}
             if isinstance(span, dict) and not span.get("text") else span)
            for span in spans
        ]
    return out


def _flatten_annotation(ann: dict, single_select: Optional[set] = None,
                        ambiguities: Optional[List[str]] = None,
                        context: Optional[ExportContext] = None,
                        with_origin: bool = False, with_engine: bool = False) -> dict:
    """Flatten a single annotation record into a flat dict for tabular output.

    ``single_select`` names the schemas that may hold at most one label. When such a
    schema arrives with several labels — data written before the GH #167 fix — the
    per-label columns are still emitted (nothing is hidden), but an additional
    ``{schema}`` column carries the resolved final answer so a consumer reading the CSV
    is never left guessing. Each collapse is appended to ``ambiguities``.

    ``with_origin`` adds the ``annotator_origin`` columns beside ``user_id``;
    the caller sets it when any record in the export is from a machine rater
    (see ``origin_columns``).
    """
    row = {
        "instance_id": ann.get("instance_id", ""),
        "user_id": ann.get("user_id", ""),
    }
    if with_origin:
        row.update(origin_fields(ann))
    if with_engine:
        row.update(engine_fields(ann))
    single_select = single_select or set()

    # Flatten labels: schema_name.label_name = value
    for schema_name, labels in ann.get("labels", {}).items():
        if isinstance(labels, dict):
            for label_name, value in labels.items():
                col = f"{schema_name}.{label_name}" if label_name else schema_name
                row[col] = value if not isinstance(value, (dict, list)) else json.dumps(value)

            if schema_name in single_select:
                non_exempt = [n for n in labels if n not in EXEMPT_LABEL_NAMES]
                if len(non_exempt) > 1:
                    winner, method = resolve_final_label(
                        schema_name, list(labels.keys()), ann.get("_changes"))
                    if winner is not None:
                        row[schema_name] = labels[winner]
                    if ambiguities is not None:
                        ambiguities.append(
                            f"{ann.get('user_id', '')}/{ann.get('instance_id', '')}"
                            f"/{schema_name}: {len(non_exempt)} stored labels "
                            f"({', '.join(map(str, non_exempt))}) -> '{winner}' "
                            f"[{method}]")
        else:
            row[schema_name] = labels if not isinstance(labels, (dict, list)) else json.dumps(labels)

    # Flatten spans as JSON strings.
    #
    # A stored span is offsets and a label with no content, so this column used
    # to leave the reader joining back to the data file and slicing on
    # start/end to find out what was actually marked. `context.covered_text`
    # does that slice here, once, against the item the span was drawn on.
    for schema_name, spans in _spans_with_text(ann, context).items():
        row[f"{schema_name}._spans"] = json.dumps(spans)

    # Which room produced the answer, when one did. The id gets its own column
    # because grouping by it is the whole point -- a reader who has to parse
    # JSON to find out which rows are non-independent will not do it.
    for schema_name, prov in (ann.get("_room") or {}).items():
        if not isinstance(prov, dict) or not prov:
            continue
        row[f"{schema_name}._room_id"] = prov.get("room_id", "")
        row[f"{schema_name}._room"] = json.dumps(prov)

    # Cloze answers scored against the key in the config, which never went to
    # the browser: one 0/1 column per keyed blank and a total.
    if context is not None:
        _add_cloze_scores(row, ann, context)

    return row


def _add_cloze_scores(row, ann, context) -> None:
    schemes = [s for s in (context.schemas or (context.config or {}).get("annotation_schemes") or [])
               if isinstance(s, dict) and s.get("annotation_type") == "cloze"]
    if not schemes:
        return
    from potato.server_utils.schemas.cloze import score_responses
    labels = ann.get("labels") or {}
    for scheme in schemes:
        given = labels.get(scheme.get("name"))
        if not isinstance(given, dict):
            # Left blank: scored as 0 rather than as a missing column.
            given = {}
        item = (context.items or {}).get(ann.get("instance_id")) if scheme.get("source_field") else None
        scored = score_responses(scheme, {k: v for k, v in given.items()}, item)
        if not scored:
            continue
        for key, value in scored.items():
            row[f"{scheme['name']}.{key}"] = value


def _ambiguity_warning(ambiguities: List[str], method_note: bool = True) -> Optional[str]:
    """One warning summarising every single-select group that had to be collapsed."""
    if not ambiguities:
        return None
    shown = ambiguities[:10]
    more = len(ambiguities) - len(shown)
    msg = (f"{len(ambiguities)} single-select schema(s) had more than one stored value "
           f"(pre-#167 data corruption). A canonical column holding the resolved final "
           f"answer was added alongside the per-label columns: " + "; ".join(shown))
    if more:
        msg += f"; and {more} more"
    if method_note:
        msg += (". Entries marked [order] were resolved by persisted order, which is "
                "first-write order rather than recency and can be wrong for A->B->A "
                "revisions. Run 'potato repair-annotations' to rewrite the stored state.")
    return msg


def _phase_only_gate(context: ExportContext) -> Tuple[bool, str]:
    """For a study with no item labels: its survey answers are exportable when
    export_include_phase_data is on; otherwise say how to turn them on."""
    if _should_include_phase_data(context):
        return True, ""
    if context.phase_responses:
        return False, (f"No item annotations to export, and {len(context.phase_responses)} "
                       "survey/phase answer(s) are left out: set "
                       "'export_include_phase_data: true' in the config to export them")
    return False, "No annotations to export"


def _can_export_tabular(context: ExportContext) -> Tuple[bool, str]:
    """Item annotations, a design record for the participants/trials sidecars,
    or survey answers (a survey-only study has no item labels at all)."""
    if context.annotations:
        return True, ""
    from .experiment_sidecars import has_design_records
    if has_design_records(context):
        return True, ""
    return _phase_only_gate(context)


class CSVExporter(BaseExporter):
    """Export annotations to CSV format."""

    format_name = "csv"
    description = "Comma-separated values (one row per user-instance annotation)"
    file_extensions = [".csv"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        return _can_export_tabular(context)

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        return _write_delimited(context, output_path, "csv", ",")


class TSVExporter(BaseExporter):
    """Export annotations to TSV format."""

    format_name = "tsv"
    description = "Tab-separated values (one row per user-instance annotation)"
    file_extensions = [".tsv"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        return _can_export_tabular(context)

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
            return _phase_only_gate(context)
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        os.makedirs(output_path, exist_ok=True)
        out_file = os.path.join(output_path, "annotations.jsonl")

        with_origin = origin_in_use(context.annotations)
        # A survey-only study has no item rows: write only the phase file.
        with (open(out_file, "w", encoding="utf-8") if context.annotations
              else open(os.devnull, "w")) as f:
            for ann in context.annotations:
                record = {
                    "instance_id": ann.get("instance_id", ""),
                    "user_id": ann.get("user_id", ""),
                }
                if with_origin:
                    # The whole declaration, not the flattened pair: JSON
                    # has room for the version fields as they are.
                    record["annotator_origin"] = record_origin(ann)
                if ann.get("_engine"):
                    record["engine_request"] = ann["_engine"]
                record.update({
                    "labels": ann.get("labels", {}),
                    # Same slice the csv column gets: a stored span is offsets
                    # and a label, and the words it covers are the point.
                    "spans": _spans_with_text(ann, context),
                    "links": ann.get("links", {}),
                })
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        files_written = [out_file] if context.annotations else []
        phase_file = _write_phase_jsonl(context, output_path)
        if phase_file:
            files_written.append(phase_file)

        warnings = []
        excl = _phase_exclusion_warning(context)
        if excl:
            warnings.append(excl)

        return ExportResult(
            success=True,
            format_name=self.format_name,
            files_written=files_written,
            warnings=warnings,
            stats={
                "num_records": len(context.annotations),
                "num_phase_responses": len(context.phase_responses) if phase_file else 0,
                "num_phase_responses_excluded": (
                    len(context.phase_responses) if not phase_file else 0),
            },
        )


def _should_include_phase_data(context: ExportContext) -> bool:
    """Check if phase response export is enabled."""
    return (
        bool(context.phase_responses)
        and context.config.get("export_include_phase_data", False)
    )


def _phase_exclusion_warning(context: ExportContext) -> Optional[str]:
    """Return a warning when phase/survey responses exist but are NOT exported.

    Phase-response export is opt-in via ``export_include_phase_data``. Without this
    warning a survey/consent/instrument study would export with all phase responses
    silently missing and the stats reporting ``num_phase_responses: 0`` (F-047),
    making it look like no survey data was ever collected.
    """
    if context.phase_responses and not context.config.get("export_include_phase_data", False):
        return (
            f"{len(context.phase_responses)} phase/survey responses were found but "
            f"NOT exported. Set 'export_include_phase_data: true' in your config to "
            f"write them to a phase_responses file."
        )
    return None


def _write_phase_delimited(context: ExportContext, output_path: str,
                           fmt_name: str, delimiter: str) -> Optional[str]:
    """Write phase responses as a separate delimited file. Returns file path or None."""
    if not _should_include_phase_data(context):
        return None

    out_file = os.path.join(output_path, f"phase_responses.{fmt_name}")
    # `sequence` documents the ordering the row layout previously only implied
    # (GH #167). Optional columns are appended only when present in the data, so a
    # deployment with neither display_logic nor legacy duplicates gets the same shape
    # it always had, plus `sequence`.
    columns = ["user_id", "phase", "page", "sequence", "schema", "label_name", "value"]
    for optional in ("hidden", "superseded"):
        if any(optional in row for row in context.phase_responses):
            columns.append(optional)

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


ANNOTATION_CHANGE_COLUMNS = [
    "user_id", "instance_id", "phase", "page", "timestamp",
    "schema", "old_label", "old_value", "new_label", "new_value", "action", "source",
]


def _write_annotation_changes(context: ExportContext, output_path: str,
                              fmt_name: str, delimiter: str) -> Optional[str]:
    """Write the annotation revision trail. Returns file path or None.

    One row per recorded change, so a study can show *that* an annotator moved from
    scale point 5 to 4 even though only 4 is stored as the answer. Sourced from the
    behavioral data Potato already persists in ``user_state.json``; the exporter never
    has to reconstruct history from the label dict.

    Written only when ``export_include_annotation_changes: true`` — the trail is
    considerably larger than the annotations themselves, and it carries per-keystroke
    detail that not every study wants to distribute.
    """
    if not (context.config or {}).get("export_include_annotation_changes", False):
        return None

    rows = []
    for ann in context.annotations:
        for change in ann.get("_changes") or []:
            if not isinstance(change, dict):
                continue
            rows.append({
                "user_id": ann.get("user_id", ""),
                "instance_id": ann.get("instance_id", ""),
                "phase": change.get("phase") or "",
                "page": change.get("page") or "",
                "timestamp": change.get("timestamp", ""),
                "schema": change.get("schema_name", ""),
                "old_label": change.get("old_label") or "",
                "old_value": change.get("old_value") if change.get("old_value") is not None else "",
                "new_label": change.get("label_name") or "",
                "new_value": change.get("new_value") if change.get("new_value") is not None else "",
                "action": change.get("action", ""),
                "source": change.get("source", ""),
            })

    if not rows:
        return None

    rows.sort(key=lambda r: (r["user_id"], r["instance_id"], r["timestamp"] or 0))
    out_file = os.path.join(output_path, f"annotation_changes.{fmt_name}")
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ANNOTATION_CHANGE_COLUMNS,
                                delimiter=delimiter, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return out_file


AUTHENTICITY_COLUMNS = [
    "user_id", "instance_id", "views", "elapsed_ms", "server_span_ms",
    # leaving the page
    "hidden_events", "hidden_ms", "blur_events", "blur_ms", "max_away_ms",
    "linked_away_events", "linked_away_ms",
    # copy / paste
    "item_copy_events", "item_copy_chars", "item_select_events",
    "item_context_menu_events", "other_copy_events", "cut_events",
    "paste_events", "item_paste_events", "external_paste_events",
    "external_paste_words", "max_external_paste_words",
    "max_away_after_item_copy_ms", "max_paste_words_after_item_copy",
    # window / pointer / automation
    "min_window_ratio", "large_screen", "resize_events", "zoom_changes",
    "pointer_moves", "pointer_distance_px", "mouse_clicks", "teleport_clicks",
    "touch_input", "untrusted_events", "webdriver",
    # detector output
    "verdict_level", "flags",
]

_AUTHENTICITY_BOOL_COLUMNS = {"large_screen", "touch_input", "webdriver"}


def _write_authenticity(context: ExportContext, output_path: str,
                        fmt_name: str, delimiter: str) -> Optional[str]:
    """Write per-item authenticity paradata. Returns file path or None.

    One row per (user, instance): whether the annotator left the page, copied
    the item, pasted outside text, or showed signs of automation -- counts and
    durations, never text. Only items that have an annotation record are
    exported; survey and training pages are in the admin rollup. Written only when
    ``export_include_authenticity: true``, for the same reason as the typing
    sidecar: these describe identifiable annotators.
    """
    if not (context.config or {}).get("export_include_authenticity", False):
        return None

    rows = []
    for ann in context.annotations:
        record = ann.get("_authenticity") or {}
        summary = record.get("summary") if isinstance(record, dict) else None
        if not isinstance(summary, dict):
            continue
        verdict = record.get("verdict") or {}
        row = {"user_id": ann.get("user_id", ""),
               "instance_id": ann.get("instance_id", "")}
        for col in AUTHENTICITY_COLUMNS[2:-2]:
            value = summary.get(col, "")
            if col in _AUTHENTICITY_BOOL_COLUMNS:
                value = int(bool(value))
            row[col] = value
        row["verdict_level"] = verdict.get("level", "")
        row["flags"] = "|".join(verdict.get("flag_names") or [])
        rows.append(row)

    if not rows:
        return None

    rows.sort(key=lambda r: (r["user_id"], r["instance_id"]))
    out_file = os.path.join(output_path, f"authenticity.{fmt_name}")
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=AUTHENTICITY_COLUMNS,
                                delimiter=delimiter, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return out_file


TYPING_DYNAMICS_COLUMNS = [
    "user_id", "instance_id", "schema", "label",
    # volume / product-to-process
    "keystrokes", "final_chars", "chars_typed", "chars_deleted",
    "chars_per_keystroke", "active_ms",
    # rhythm
    "iki_median_ms", "iki_log_cv",
    # pausing
    "pause_2s", "pause_10s", "pause_total_ms",
    # bursting / revision
    "bursts", "burst_mean_chars", "revision_ratio", "non_terminal_edits",
    # external insertion
    "paste_events", "pasted_chars", "pasted_fraction",
    "silent_insert_ratio", "external_insert_ratio",
    # attention / integrity
    "blur_total_ms", "max_blur_before_insert_ms", "untrusted_events",
    "virtual_keyboard",
    # detector output
    "verdict_level", "flags",
]


def _write_typing_dynamics(context: ExportContext, output_path: str,
                           fmt_name: str, delimiter: str) -> Optional[str]:
    """Write per-field typing-dynamics features. Returns file path or None.

    One row per (user, instance, free-text field): how the response was
    produced, not what it said. Sourced from the ``typing_summaries`` Potato
    persists in ``user_state.json``.

    Written only when ``export_include_typing_dynamics: true``. These are
    behavioural measurements of identifiable annotators, so distributing them
    is an explicit choice rather than a default. Raw keystroke event streams are
    not here at all — they stay in the project database and have their own
    exporter.
    """
    if not (context.config or {}).get("export_include_typing_dynamics", False):
        return None

    rows = []
    for ann in context.annotations:
        for field_key, summary in (ann.get("_typing") or {}).items():
            if not isinstance(summary, dict):
                continue
            schema, _, label = field_key.partition(":::")
            pauses = summary.get("pause_counts") or {}
            verdict = summary.get("verdict") or {}
            rows.append({
                "user_id": ann.get("user_id", ""),
                "instance_id": ann.get("instance_id", ""),
                "schema": schema,
                "label": label,
                "keystrokes": summary.get("keystrokes", 0),
                "final_chars": summary.get("final_chars", 0),
                "chars_typed": summary.get("chars_typed", 0),
                "chars_deleted": summary.get("chars_deleted", 0),
                "chars_per_keystroke": round(summary.get("chars_per_keystroke", 0) or 0, 3),
                "active_ms": summary.get("active_ms", 0),
                "iki_median_ms": round(summary.get("iki_median_ms", 0) or 0, 1),
                "iki_log_cv": round(summary.get("iki_log_cv", 0) or 0, 4),
                "pause_2s": pauses.get("2000", 0),
                "pause_10s": pauses.get("10000", 0),
                "pause_total_ms": summary.get("pause_total_ms", 0),
                "bursts": summary.get("bursts", 0),
                "burst_mean_chars": round(summary.get("burst_mean_chars", 0) or 0, 2),
                "revision_ratio": round(summary.get("revision_ratio", 0) or 0, 4),
                "non_terminal_edits": summary.get("non_terminal_edits", 0),
                "paste_events": summary.get("paste_events", 0),
                "pasted_chars": summary.get("pasted_chars", 0),
                "pasted_fraction": round(summary.get("pasted_fraction", 0) or 0, 4),
                "silent_insert_ratio": round(summary.get("silent_insert_ratio", 0) or 0, 4),
                "external_insert_ratio": round(summary.get("external_insert_ratio", 0) or 0, 4),
                "blur_total_ms": summary.get("blur_total_ms", 0),
                "max_blur_before_insert_ms": summary.get("max_blur_before_insert_ms", 0),
                "untrusted_events": summary.get("untrusted_events", 0),
                "virtual_keyboard": int(bool(summary.get("virtual_keyboard"))),
                "verdict_level": verdict.get("level", ""),
                "flags": "|".join(verdict.get("flag_names") or []),
            })

    if not rows:
        return None

    rows.sort(key=lambda r: (r["user_id"], r["instance_id"], r["schema"], r["label"]))
    out_file = os.path.join(output_path, f"typing_dynamics.{fmt_name}")
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TYPING_DYNAMICS_COLUMNS,
                                delimiter=delimiter, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return out_file


def _write_delimited(context: ExportContext, output_path: str,
                     fmt_name: str, delimiter: str) -> ExportResult:
    """Write annotations as a delimited file (CSV or TSV)."""
    os.makedirs(output_path, exist_ok=True)
    out_file = os.path.join(output_path, f"annotations.{fmt_name}")

    # Flatten all annotations to collect the full set of columns
    single_select = _single_select_names(context)
    ambiguities = []
    with_origin = origin_in_use(context.annotations)
    with_engine = engine_in_use(context.annotations)
    rows = [_flatten_annotation(ann, single_select, ambiguities, context,
                                with_origin=with_origin, with_engine=with_engine)
            for ann in context.annotations]

    # Collect all column names preserving order (instance_id, user_id first)
    columns = ["instance_id", "user_id"]
    seen = set(columns)
    for row in rows:
        for key in row:
            if key not in seen:
                columns.append(key)
                seen.add(key)

    files_written = []
    if rows:
        with open(out_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns, delimiter=delimiter,
                                    extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        files_written.append(out_file)
    # With no item annotations a study still has its other records: survey
    # pages (a survey-only study is what the survey importers build), a
    # jsPsych-only study, or one where everyone was screened out.
    phase_file = _write_phase_delimited(context, output_path, fmt_name, delimiter)
    if phase_file:
        files_written.append(phase_file)
    changes_file = _write_annotation_changes(context, output_path, fmt_name, delimiter)
    if changes_file:
        files_written.append(changes_file)
    typing_file = _write_typing_dynamics(context, output_path, fmt_name, delimiter)
    if typing_file:
        files_written.append(typing_file)
    authenticity_file = _write_authenticity(context, output_path, fmt_name, delimiter)
    if authenticity_file:
        files_written.append(authenticity_file)
    # Experiment designs: who was in which condition and what they were
    # shown (participants), and the timed-trial records (trials).
    from .experiment_sidecars import write_participants, write_regions, write_trials
    for writer in (write_participants, write_trials, write_regions):
        sidecar = writer(context, output_path, fmt_name, delimiter)
        if sidecar:
            files_written.append(sidecar)

    warnings = []
    # Cloze keys whose length does not match the passage's blanks: scored
    # only up to the blank count, which the person exporting should know.
    from potato.server_utils.schemas.cloze import key_mismatches
    for _scheme in (context.schemas or []):
        if isinstance(_scheme, dict) and _scheme.get("annotation_type") == "cloze":
            _bad = key_mismatches(_scheme, context.items or {})
            if _bad:
                warnings.append(
                    f"cloze '{_scheme.get('name')}': {len(_bad)} item(s) have an answer key "
                    f"whose length differs from the passage's blanks ({', '.join(_bad[:5])}"
                    f"{', ...' if len(_bad) > 5 else ''}); only the blanks were scored")
    if not rows:
        warnings.append(f"No item annotations, so annotations.{fmt_name} was not written"
                        + ("." if files_written else "; nothing else to export either."))
    excl = _phase_exclusion_warning(context)
    if excl:
        warnings.append(excl)
    amb = _ambiguity_warning(ambiguities)
    if amb:
        warnings.append(amb)
        logger.warning(amb)

    return ExportResult(
        success=True,
        format_name=fmt_name,
        files_written=files_written,
        warnings=warnings,
        stats={
            "num_records": len(rows),
            "num_columns": len(columns),
            "num_single_select_collapsed": len(ambiguities),
            "num_phase_responses": len(context.phase_responses) if phase_file else 0,
            "num_phase_responses_excluded": (
                len(context.phase_responses) if not phase_file else 0),
        },
    )
