"""
Incentives Exporter (format ``incentives``)

Computes every participant's bonus from their stored ``price_list``, ``bdm``
and ``belief_elicitation`` answers under the config's ``incentives:`` rules
(see potato/incentives.py), and writes:

    bonuses.csv            one row per paid-for decision: user, Prolific id,
                           rule, the seed and every random draw, the payoff,
                           whether it was the paid decision, and the
                           participant's total (after max_bonus) and whether it
                           was capped
    bonuses_prolific.csv   Prolific's bulk bonus format, one
                           ``<participant_id>,<amount>`` line per participant
                           owed a bonus now, no header

The draws are seeded, so exporting again from the same answers writes the same
files. Nothing is paid: upload bonuses_prolific.csv in Prolific, or use the
admin route /admin/api/crowd/incentive_bonuses.
"""

from __future__ import annotations

import csv
import os
from typing import Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

COLUMNS = ["user_id", "prolific_id", "finished", "rule", "method", "scheme", "decision",
           "seed", "draws", "payoff", "paid", "pay_after", "note", "total", "capped", "currency"]


class IncentivesExporter(BaseExporter):
    format_name = "incentives"
    description = "Incentive payments: seeded draws and bonuses per participant, plus a Prolific bulk-bonus file"
    file_extensions = [".csv"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        block = (context.config or {}).get("incentives")
        if not isinstance(block, dict) or not block.get("enabled"):
            return False, "incentives.enabled is not true in this config"
        if not block.get("rules"):
            return False, "No incentives rules in this config"
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        from potato.incentives import compute_incentives, incentive_config_problems
        from potato.server_utils.stored_states import iter_stored_states

        config = context.config or {}
        config_dir = (os.path.dirname(os.path.abspath(config["config_file"]))
                      if config.get("config_file") else config.get("task_dir"))
        problems = incentive_config_problems(config, config_dir)
        if problems:
            return ExportResult(success=False, format_name=self.format_name, errors=problems)
        states = {}
        try:
            for name, state in iter_stored_states(context.output_dir, config, skip_unreadable=True):
                states[str(state.get("user_id", name))] = state
        except Exception as e:          # a database we cannot read
            return ExportResult(success=False, format_name=self.format_name,
                                errors=[f"could not read stored states: {e}"])
        report = compute_incentives(config, context.annotations, context.phase_responses,
                                    context.items, states, config_dir)

        os.makedirs(output_path, exist_ok=True)
        files = []
        path = os.path.join(output_path, "bonuses.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
            w.writeheader()
            for row in report.rows:
                t = report.totals.get(row["user_id"], {})
                w.writerow({**row, "finished": int(bool(row["finished"])), "paid": int(bool(row["paid"])),
                            "total": f"{t.get('total', 0):.2f}", "capped": int(bool(t.get("capped"))),
                            "currency": report.currency})
        files.append(path)

        try:
            prolific = report.prolific_rows()
        except ValueError as e:
            return ExportResult(success=False, format_name=self.format_name, files_written=files,
                                errors=[f"bonus rows refused: {e}"])
        path = os.path.join(output_path, "bonuses_prolific.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            for pid, amount in prolific:
                f.write(f"{pid},{amount}\n")
        files.append(path)

        return ExportResult(
            success=True, format_name=self.format_name, files_written=files,
            warnings=sorted(set(report.warnings)),
            stats={"participants": len(report.totals), "decisions": len(report.rows),
                   "prolific_rows": len(prolific),
                   "prolific_total": report.summary()["prolific_total"]})
