"""
Trajectory Correction Exporter

Turns ``trajectory_edit`` annotations (human-corrected agent traces) into
training-ready data:

- ``trajectory_corrections.json`` — full records with the original trace, the
  reconstructed corrected trace, and per-field edit details.
- ``trajectory_sft.jsonl`` — one record per *edited* trace:
  ``{"prompt": <task>, "completion": <corrected_trace>}`` (SFT target).
- ``trajectory_dpo.jsonl`` — one record per *edited* trace:
  ``{"prompt": <task>, "chosen": <corrected_trace>, "rejected": <original_trace>}``.

Unedited annotations are counted but never produce SFT/DPO records (no point
training on an unchanged trajectory); the count of skipped/unedited traces is
reported in ``stats`` and ``warnings`` so coverage is never silently dropped.
"""

import copy
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

logger = logging.getLogger(__name__)


class TrajectoryCorrectionExporter(BaseExporter):
    """Exporter for trajectory_edit annotations → SFT/DPO training data."""

    format_name = "trajectory_correction"
    description = "Corrected agent trajectories as SFT targets and DPO preference pairs"
    file_extensions = [".json", ".jsonl"]

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        options = options or {}
        warnings: List[str] = []

        try:
            trajedit_schemas = {
                s["name"]: s for s in context.schemas
                if s.get("annotation_type") == "trajectory_edit"
            }
            if not trajedit_schemas:
                return ExportResult(
                    success=False, format_name=self.format_name,
                    errors=["No trajectory_edit schemas defined"],
                )

            records: List[dict] = []
            n_unedited = 0
            n_unparseable = 0

            for ann in context.annotations:
                instance_id = ann.get("instance_id", "")
                labels = ann.get("labels", {}) or {}
                item = context.items.get(instance_id, {}) or {}

                for schema_name, value in labels.items():
                    scheme = trajedit_schemas.get(schema_name)
                    if scheme is None:
                        continue

                    label_val = value.get("label", "") if isinstance(value, dict) else value
                    if not isinstance(label_val, str) or not label_val.strip():
                        continue
                    try:
                        correction = json.loads(label_val)
                    except (ValueError, TypeError):
                        n_unparseable += 1
                        continue

                    record = self._build_record(
                        instance_id, ann.get("user_id", ""), scheme, item, correction
                    )
                    if record is None:
                        continue
                    records.append(record)
                    if record["n_edits"] == 0:
                        n_unedited += 1

            edited_records = [r for r in records if r["n_edits"] > 0]
            if n_unedited:
                warnings.append(
                    f"{n_unedited} annotation(s) had no edits — included in "
                    f"corrections.json but excluded from SFT/DPO output."
                )

            os.makedirs(output_path, exist_ok=True)
            files_written = []

            corrections_file = os.path.join(output_path, "trajectory_corrections.json")
            with open(corrections_file, "w", encoding="utf-8") as f:
                json.dump({"records": records, "n_total": len(records),
                           "n_edited": len(edited_records),
                           "n_unedited": n_unedited}, f, indent=2, ensure_ascii=False)
            files_written.append(corrections_file)

            sft_file = os.path.join(output_path, "trajectory_sft.jsonl")
            with open(sft_file, "w", encoding="utf-8") as f:
                for r in edited_records:
                    f.write(json.dumps({
                        "prompt": r["task"],
                        "completion": r["corrected_trace"],
                        "trace_id": r["trace_id"],
                    }, ensure_ascii=False) + "\n")
            files_written.append(sft_file)

            dpo_file = os.path.join(output_path, "trajectory_dpo.jsonl")
            with open(dpo_file, "w", encoding="utf-8") as f:
                for r in edited_records:
                    f.write(json.dumps({
                        "prompt": r["task"],
                        "chosen": r["corrected_trace"],
                        "rejected": r["original_trace"],
                        "trace_id": r["trace_id"],
                    }, ensure_ascii=False) + "\n")
            files_written.append(dpo_file)

            return ExportResult(
                success=True, format_name=self.format_name,
                files_written=files_written, warnings=warnings,
                stats={
                    "total_corrections": len(records),
                    "edited_traces": len(edited_records),
                    "unedited_traces": n_unedited,
                    "unparseable": n_unparseable,
                },
            )

        except Exception as e:
            logger.error(f"Trajectory correction export failed: {e}")
            return ExportResult(
                success=False, format_name=self.format_name, errors=[str(e)],
            )

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not context.annotations:
            return False, "No annotations to export"
        if not any(s.get("annotation_type") == "trajectory_edit" for s in context.schemas):
            return False, "No trajectory_edit schema defined"
        return True, ""

    def _build_record(self, instance_id: str, user_id: str, scheme: dict,
                      item: dict, correction: dict) -> Optional[dict]:
        """Reconstruct the corrected trace from the original + per-field edits."""
        steps_key = scheme.get("steps_key", "steps")
        final_answer_key = scheme.get("final_answer_key", "final_answer")

        original_steps = item.get(steps_key, [])
        if not isinstance(original_steps, list):
            original_steps = []

        corrected_steps = copy.deepcopy(original_steps)
        edits = correction.get("steps", []) or []
        applied_edits = []

        for e in edits:
            if not e.get("edited"):
                continue
            idx = e.get("step_index")
            field = e.get("field")
            edited_text = e.get("edited_text", "")
            if idx is None or field is None:
                continue
            if 0 <= idx < len(corrected_steps):
                step = corrected_steps[idx]
                if isinstance(step, dict):
                    step[field] = edited_text
                elif isinstance(step, str) and field == scheme.get("step_text_key", "action"):
                    corrected_steps[idx] = edited_text
                applied_edits.append({
                    "step_index": idx, "field": field,
                    "original_text": e.get("original_text", ""),
                    "edited_text": edited_text,
                    "edit_distance_chars": e.get("edit_distance_chars", 0),
                    "edit_distance_words": e.get("edit_distance_words", 0),
                    "reason": e.get("reason", ""),
                })

        # Final answer correction (optional)
        original_final = item.get(final_answer_key)
        corrected_final = original_final
        fa = correction.get("final_answer")
        if isinstance(fa, dict) and fa.get("edited"):
            corrected_final = fa.get("edited_text", original_final)
            applied_edits.append({
                "step_index": None, "field": final_answer_key,
                "original_text": fa.get("original_text", original_final),
                "edited_text": corrected_final,
                "edit_distance_chars": fa.get("edit_distance_chars", 0),
                "edit_distance_words": fa.get("edit_distance_words", 0),
                "reason": "",
            })

        task = item.get("task_description", item.get("task", item.get("text", "")))

        original_trace = {"task": task, "steps": original_steps}
        corrected_trace = {"task": task, "steps": corrected_steps}
        if original_final is not None or corrected_final is not None:
            original_trace[final_answer_key] = original_final
            corrected_trace[final_answer_key] = corrected_final

        return {
            "trace_id": instance_id,
            "annotator": user_id,
            "task": task,
            "original_trace": original_trace,
            "corrected_trace": corrected_trace,
            "edits": applied_edits,
            "n_edits": len(applied_edits),
            "total_edit_distance": correction.get("total_edit_distance", 0),
        }
