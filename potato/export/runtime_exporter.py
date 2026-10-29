"""
Runtime Exporter

Exports the data from runtime phase pages (``type: jspsych``, ``type: osweb``,
...). Like the keystroke exporter it reads the project's SQLite store rather
than user_state.json, where the trial data is never kept
(see potato/runtimes/store.py).

Output files, one set per runtime used (``<kind>`` is ``jspsych``,
``osweb``, ...):
    <kind>_runs.csv         one row per run: participant, page, attempt,
                            status, trial count, conditions
    <kind>_trials.csv       one row per trial, every column the runtime recorded
                            (the union across trials; nested values as JSON)
    <kind>_interaction.csv  blur / focus / fullscreen events per run
    <kind>_raw/<user>/<page>-<run>.json   each run's data exactly as the runtime gave it

Runs that never finished (a reload, a closed tab) are exported with
status ``started`` or ``partial`` so they can be excluded or analyzed.

The ``jspsych`` format is the same export restricted to jsPsych pages.
"""

import csv
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

RUN_COLUMNS = ["run_id", "user_id", "phase", "page", "attempt", "status",
               "started_at", "finished_at", "n_trials"]

#: Columns placed first in the trials table, in this order, when present.
LEADING_TRIAL_COLUMNS = ["run_id", "user_id", "page", "attempt", "run_status",
                         "trial_index", "trial_type", "time_elapsed", "rt",
                         "response", "stimulus"]


def _cell(value: Any) -> Any:
    # csv writes a Python bool as True/False; jsPsych's own data.csv() and the
    # R and pandas readers expect true/false.
    if isinstance(value, bool) or (type(value).__module__ == "numpy"
                                   and type(value).__name__ in ("bool", "bool_")):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


def _safe(part: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in str(part))


class RuntimeExporter(BaseExporter):
    """Exports runs and trial data from runtime phase pages."""

    format_name = "runtime"
    description = "Trial data from runtime phase pages (jsPsych, headphone check, external tasks)"
    file_extensions = [".csv", ".json"]
    #: Restrict to one runtime (None: every runtime the project uses).
    kind: Optional[str] = None

    def _task_dir_and_project(self, context: ExportContext) -> Tuple[str, str]:
        config = context.config or {}
        return (config.get("task_dir") or "."), (config.get("annotation_task_name") or "potato")

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        from potato.runtimes.phase import has_runtime_pages
        config = context.config or {}
        what = f"type: {self.kind}" if self.kind else "runtime (jsPsych, OSWeb, ...)"
        if not has_runtime_pages(config, self.kind):
            return False, f"This project has no {what} phase."
        try:
            from potato.runtimes import store
            task_dir, project = self._task_dir_and_project(context)
            if not store.list_runs(task_dir, project, runtime=self.kind):
                return False, "No runs recorded yet."
        except Exception as e:
            return False, f"Could not open the run store: {e}"
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        from potato.runtimes import store
        task_dir, project = self._task_dir_and_project(context)
        try:
            runs = store.list_runs(task_dir, project, runtime=self.kind, with_data=True)
        except Exception as e:
            return ExportResult(success=False, format_name=self.format_name,
                                errors=[f"Could not read runs: {e}"])
        if not runs:
            return ExportResult(success=False, format_name=self.format_name,
                                errors=["No runs found to export."])
        os.makedirs(output_path, exist_ok=True)
        files_written: List[str] = []
        stats = {"num_runs": 0, "num_complete": 0, "num_trials": 0, "num_users": 0}
        users = set()
        for kind in sorted({r.get("runtime") or "jspsych" for r in runs}):
            subset = [r for r in runs if (r.get("runtime") or "jspsych") == kind]
            written, s = self._export_kind(kind, subset, output_path)
            files_written.extend(written)
            for k in ("num_runs", "num_complete", "num_trials"):
                stats[k] += s[k]
            users |= {r["user_id"] for r in subset}
        stats["num_users"] = len(users)
        return ExportResult(success=True, format_name=self.format_name,
                            files_written=files_written, stats=stats)

    def _export_kind(self, kind: str, runs: List[Dict[str, Any]], output_path: str):
        factors = sorted({f for r in runs for f in (r.get("conditions") or {})})
        run_rows, trial_rows, interaction_rows = [], [], []
        trial_columns: List[str] = []
        seen_columns = set()
        files_written: List[str] = []
        raw_dir = os.path.join(output_path, f"{kind}_raw")

        for run in runs:
            conds = {f"condition_{f}": (run.get("conditions") or {}).get(f) for f in factors}
            run_rows.append({**{c: run.get(c) for c in RUN_COLUMNS}, **conds})
            for t in run.get("trials") or []:
                row = {"run_id": run["run_id"], "user_id": run["user_id"],
                       "page": run["page"], "attempt": run.get("attempt"),
                       "run_status": run.get("status"), **conds}
                for key, value in t.items():
                    row.setdefault(key, _cell(value))
                for key in row:
                    if key not in seen_columns:
                        seen_columns.add(key)
                        trial_columns.append(key)
                trial_rows.append(row)
            for ev in run.get("interaction") or []:
                interaction_rows.append({"run_id": run["run_id"], "user_id": run["user_id"],
                                         "page": run["page"],
                                         "event": ev.get("event"), "trial": ev.get("trial"),
                                         "time": ev.get("time")})
            user_dir = os.path.join(raw_dir, _safe(run["user_id"]))
            os.makedirs(user_dir, exist_ok=True)
            raw_path = os.path.join(user_dir, f"{_safe(run['page'])}-{run['run_id']}.json")
            with open(raw_path, "w", encoding="utf-8") as f:
                json.dump(run.get("trials") or [], f, ensure_ascii=False, indent=1)
            files_written.append(raw_path)

        leading = [c for c in LEADING_TRIAL_COLUMNS if c in seen_columns]
        cond_cols = [f"condition_{f}" for f in factors]
        rest = [c for c in trial_columns if c not in leading and c not in cond_cols]
        trial_columns = leading + cond_cols + rest

        def write(rows: List[Dict[str, Any]], columns: List[str], name: str) -> str:
            path = os.path.join(output_path, name)
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
                writer.writeheader()
                for r in rows:
                    writer.writerow(r)
            return path

        files_written.insert(0, write(run_rows, RUN_COLUMNS + cond_cols, f"{kind}_runs.csv"))
        files_written.insert(1, write(trial_rows, trial_columns, f"{kind}_trials.csv"))
        if interaction_rows:
            files_written.insert(2, write(interaction_rows,
                                          ["run_id", "user_id", "page", "event", "trial", "time"],
                                          f"{kind}_interaction.csv"))
        return files_written, {
            "num_runs": len(run_rows),
            "num_complete": sum(1 for r in run_rows if r["status"] == "complete"),
            "num_trials": len(trial_rows)}


class JsPsychExporter(RuntimeExporter):
    """The runtime export restricted to jsPsych pages."""

    format_name = "jspsych"
    description = "Trial data from embedded jsPsych timelines (type: jspsych phases)"
    kind = "jspsych"
