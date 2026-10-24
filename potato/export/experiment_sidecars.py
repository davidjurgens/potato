"""
Sidecar tables for experiment designs, written beside the CSV/TSV export.

``participants.<fmt>``  one row per participant: assigned condition, page and
                        question orders, pages skipped by ``show_when``,
                        screen-outs, and a summary of each jsPsych run.
                        Written when the config uses any of those features.
``trials.<fmt>``        one row per timed trial (``trial_timing``): outcome,
                        key, label, reaction time, intended and measured
                        timings, and the server's flags. A trial that timed
                        out has no label, so this table, not the main export,
                        is the complete record of a timed task.

Both read the stored user states directly: the main export is built from
labelled items and would miss a timed-out one.
"""

import csv
import json
import os
from typing import Any, Dict, List, Optional

from .base import ExportContext

TRIAL_COLUMNS = [
    "user_id", "instance_id", "outcome", "key", "label", "rt_ms",
    "intended_fixation_ms", "intended_stimulus_duration_ms",
    "intended_trial_duration_ms", "intended_iti_ms",
    "fixation_ms_actual", "stimulus_ms_actual", "iti_actual_ms",
    "frame_ms", "timer_resolution_ms", "early_keys", "reloads",
    "tab_hidden", "fullscreen_at_onset", "server_elapsed_ms",
    "onset_epoch_ms", "previous_attempts", "flags",
]


def _uses_flow_features(config: dict) -> bool:
    from potato.server_utils.phase_flow import has_flow_rules, phases_dict
    if config.get("conditions"):
        return True
    if has_flow_rules(config):
        return True
    from potato.runtimes.phase import has_runtime_pages
    return has_runtime_pages(config)


def _states(context: ExportContext):
    from potato.server_utils.stored_states import iter_stored_states
    from potato.user_state_management import upgrade_flow_record
    for user_dir, state in iter_stored_states(context.output_dir, context.config):
        # A state saved before runtime phases keeps its runs under "jspsych".
        if isinstance(state.get("flow_record"), dict):
            upgrade_flow_record(state["flow_record"])
        yield state.get("user_id", user_dir), state


def _write(path: str, rows: List[Dict[str, Any]], columns: List[str], delimiter: str) -> str:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, delimiter=delimiter,
                                extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def write_participants(context: ExportContext, output_path: str,
                       fmt_name: str, delimiter: str) -> Optional[str]:
    config = context.config or {}
    if not _uses_flow_features(config):
        return None
    factors = list(((config.get("conditions") or {}).get("factors") or {}).keys())
    columns = (["user_id"] + [f"condition_{f}" for f in factors] +
               ["condition_ordinal", "cell_ordinal", "latin_ordinal", "final_phase",
                "screened_out", "screened_out_page",
                "skipped_pages", "page_orders", "question_orders", "runtime_runs",
                "runtime_answers"])
    rows = []
    for user_id, state in _states(context):
        rec = state.get("flow_record") or {}
        conds = rec.get("conditions") or {}
        phase_page = state.get("current_phase_and_page") or [None, None]
        out = rec.get("screened_out") or {}
        row = {
            "user_id": user_id,
            "condition_ordinal": rec.get("condition_ordinal", ""),
            "cell_ordinal": rec.get("cell_ordinal", ""),
            "latin_ordinal": rec.get("latin_ordinal", ""),
            "final_phase": phase_page[0] if isinstance(phase_page, list) else "",
            "screened_out": int(bool(out)),
            "screened_out_page": out.get("page", ""),
            "skipped_pages": "|".join(s.get("page", "") for s in rec.get("skipped_pages") or []),
            "page_orders": json.dumps(rec.get("page_orders") or {}, sort_keys=True),
            "question_orders": json.dumps(rec.get("question_orders") or {}, sort_keys=True),
            "runtime_runs": json.dumps({p: {k: v.get(k) for k in ("kind", "status", "attempts",
                                                                   "page_loads", "n_trials", "run_id")}
                                        for p, v in (rec.get("runtimes") or {}).items()},
                                       sort_keys=True),
            # What runtime pages derived from their runs (a headphone check's pass).
            "runtime_answers": json.dumps(rec.get("runtime_answers") or {}, sort_keys=True),
        }
        for f in factors:
            row[f"condition_{f}"] = conds.get(f, "")
        rows.append(row)
    if not rows:
        return None
    rows.sort(key=lambda r: r["user_id"])
    return _write(os.path.join(output_path, f"participants.{fmt_name}"), rows, columns, delimiter)


REGION_COLUMNS = ["user_id", "instance_id", "region", "text", "rt_ms", "correct",
                  "side", "errors", "trial_outcome", "onset_epoch_ms"]


def write_regions(context: ExportContext, output_path: str,
                  fmt_name: str, delimiter: str) -> Optional[str]:
    """One row per region of a word-by-word trial (self-paced reading,
    maze): its text and reading time, and for the maze whether the right word
    was chosen."""
    config = context.config or {}
    block = config.get("trial_timing")
    if not (isinstance(block, dict) and block.get("enabled") and block.get("presentation")):
        return None
    factors = list(((config.get("conditions") or {}).get("factors") or {}).keys())
    columns = REGION_COLUMNS[:2] + [f"condition_{f}" for f in factors] + REGION_COLUMNS[2:]
    rows = []
    for user_id, state in _states(context):
        conds = (state.get("flow_record") or {}).get("conditions") or {}
        for instance_id, rec in (state.get("instance_id_to_trial") or {}).items():
            if not isinstance(rec, dict):
                continue
            for r in rec.get("regions") or []:
                row = {"user_id": user_id, "instance_id": instance_id,
                       "region": r.get("index", ""), "text": r.get("text", ""),
                       "rt_ms": r.get("rt_ms", ""),
                       "correct": "" if "correct" not in r else int(bool(r["correct"])),
                       "side": r.get("side", ""), "errors": r.get("errors", ""),
                       "trial_outcome": rec.get("outcome", ""),
                       "onset_epoch_ms": rec.get("onset_epoch_ms", "")}
                for f in factors:
                    row[f"condition_{f}"] = conds.get(f, "")
                rows.append(row)
    if not rows:
        return None
    rows.sort(key=lambda r: (r["user_id"], float(r["onset_epoch_ms"] or 0), r["region"]))
    return _write(os.path.join(output_path, f"regions.{fmt_name}"), rows, columns, delimiter)


def write_trials(context: ExportContext, output_path: str,
                 fmt_name: str, delimiter: str) -> Optional[str]:
    config = context.config or {}
    if not (isinstance(config.get("trial_timing"), dict) and config["trial_timing"].get("enabled")):
        return None
    factors = list(((config.get("conditions") or {}).get("factors") or {}).keys())
    columns = TRIAL_COLUMNS[:2] + [f"condition_{f}" for f in factors] + TRIAL_COLUMNS[2:]
    rows = []
    for user_id, state in _states(context):
        conds = (state.get("flow_record") or {}).get("conditions") or {}
        for instance_id, rec in (state.get("instance_id_to_trial") or {}).items():
            if not isinstance(rec, dict):
                continue
            intended = rec.get("intended") or {}
            row = {"user_id": user_id, "instance_id": instance_id}
            for col in TRIAL_COLUMNS[2:]:
                if col.startswith("intended_"):
                    row[col] = intended.get(col[len("intended_"):], "")
                elif col == "flags":
                    row[col] = "|".join(rec.get("flags") or [])
                elif col == "previous_attempts":
                    row[col] = len(rec.get("previous_attempts") or [])
                elif col in ("tab_hidden", "fullscreen_at_onset"):
                    row[col] = int(bool(rec.get(col)))
                else:
                    value = rec.get(col)
                    row[col] = "" if value is None else value
            for f in factors:
                row[f"condition_{f}"] = conds.get(f, "")
            rows.append(row)
    if not rows:
        return None
    def _onset(r):
        try:
            return float(r["onset_epoch_ms"])
        except (TypeError, ValueError):
            return float("inf")
    rows.sort(key=lambda r: (r["user_id"], _onset(r)))
    return _write(os.path.join(output_path, f"trials.{fmt_name}"), rows, columns, delimiter)


def has_design_records(context: ExportContext) -> bool:
    """True when the sidecars have something to write: a configured
    experiment-flow feature or timed trials, and at least one saved state
    holding a flow record or a trial record. Lets the CSV/TSV export run for
    a study with no item annotations (a jsPsych-only study, say)."""
    config = context.config or {}
    timed = isinstance(config.get("trial_timing"), dict) and config["trial_timing"].get("enabled")
    if not (timed or _uses_flow_features(config)):
        return False
    try:
        for _user, state in _states(context):
            if state.get("flow_record") or state.get("instance_id_to_trial"):
                return True
    except Exception:
        return False
    return False
