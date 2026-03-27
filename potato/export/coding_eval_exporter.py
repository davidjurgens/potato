"""
Coding Agent Evaluation Exporter

Exports coding agent annotations in formats useful for training:
- PRM (Process Reward Model): per-step reward signals
- DPO/RLHF preference format: chosen/rejected trace pairs
- SWE-bench compatible evaluation results
- Code review format: structured review data
"""

import json
import os
import logging
from typing import Dict, List, Any, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

logger = logging.getLogger(__name__)


class CodingEvalExporter(BaseExporter):
    """Export coding agent annotations for ML training pipelines."""

    format_name = "coding_eval"
    description = "Coding agent evaluation data (PRM, DPO, SWE-bench, code review)"
    file_extensions = [".jsonl", ".json"]

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        options = options or {}
        export_types = options.get("types", ["prm", "preference", "swebench", "code_review"])
        files_written = []
        warnings = []
        stats = {}

        os.makedirs(output_path, exist_ok=True)

        if "prm" in export_types:
            path, count = self._export_prm(context, output_path)
            if path:
                files_written.append(path)
                stats["prm_instances"] = count

        if "preference" in export_types:
            path, count = self._export_preference(context, output_path)
            if path:
                files_written.append(path)
                stats["preference_pairs"] = count

        if "swebench" in export_types:
            path, count = self._export_swebench(context, output_path)
            if path:
                files_written.append(path)
                stats["swebench_results"] = count

        if "code_review" in export_types:
            path, count = self._export_code_review(context, output_path)
            if path:
                files_written.append(path)
                stats["code_reviews"] = count

        return ExportResult(
            success=True,
            format_name=self.format_name,
            files_written=files_written,
            warnings=warnings,
            stats=stats,
        )

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not context.annotations:
            return False, "No annotations to export"

        # Check for relevant schema types
        schema_types = {s.get("annotation_type") for s in context.schemas}
        relevant = schema_types & {"process_reward", "code_review", "pairwise", "radio"}
        if not relevant:
            return False, "No coding evaluation schemas found (process_reward, code_review, pairwise, radio)"

        return True, ""

    def _export_prm(self, context: ExportContext, output_dir: str) -> Tuple[Optional[str], int]:
        """Export PRM training data."""
        output_path = os.path.join(output_dir, "prm_training_data.jsonl")
        count = 0

        with open(output_path, "w") as f:
            for ann in context.annotations:
                instance_id = ann.get("instance_id", "")
                labels = ann.get("labels", {})

                for schema_name, value in labels.items():
                    if not isinstance(value, dict):
                        continue
                    label_val = value.get("label", "")
                    if not isinstance(label_val, str):
                        continue

                    try:
                        parsed = json.loads(label_val)
                    except (json.JSONDecodeError, TypeError):
                        continue

                    if not isinstance(parsed, dict) or "steps" not in parsed:
                        continue

                    steps = parsed["steps"]
                    if not isinstance(steps, list):
                        continue

                    record = {
                        "instance_id": instance_id,
                        "annotator": ann.get("user_id", ""),
                        "steps": [
                            {"index": s.get("index", i), "reward": s.get("reward", 0)}
                            for i, s in enumerate(steps)
                        ],
                    }
                    if "mode" in parsed:
                        record["mode"] = parsed["mode"]

                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    count += 1

        if count == 0:
            os.remove(output_path)
            return None, 0

        logger.info(f"Exported {count} PRM records to {output_path}")
        return output_path, count

    def _export_preference(self, context: ExportContext, output_dir: str) -> Tuple[Optional[str], int]:
        """Export DPO/RLHF preference pairs from pairwise annotations."""
        output_path = os.path.join(output_dir, "preference_pairs.jsonl")
        count = 0

        with open(output_path, "w") as f:
            for ann in context.annotations:
                instance_id = ann.get("instance_id", "")
                labels = ann.get("labels", {})

                for schema_name, value in labels.items():
                    if not isinstance(value, dict):
                        continue

                    label_val = value.get("label", "")
                    # Pairwise annotations store "A" or "B"
                    if label_val not in ("A", "B", "a", "b"):
                        continue

                    # Get the instance data to extract prompt
                    item_data = context.items.get(instance_id, {})
                    prompt = item_data.get("task_description", item_data.get("text", ""))

                    record = {
                        "instance_id": instance_id,
                        "prompt": prompt,
                        "chosen": label_val.upper(),
                        "annotator": ann.get("user_id", ""),
                    }
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    count += 1

        if count == 0:
            os.remove(output_path)
            return None, 0

        logger.info(f"Exported {count} preference pairs to {output_path}")
        return output_path, count

    def _export_swebench(self, context: ExportContext, output_dir: str) -> Tuple[Optional[str], int]:
        """Export SWE-bench compatible evaluation results."""
        output_path = os.path.join(output_dir, "swebench_results.jsonl")
        count = 0

        with open(output_path, "w") as f:
            for ann in context.annotations:
                instance_id = ann.get("instance_id", "")
                labels = ann.get("labels", {})

                # Look for task_success or similar radio annotation
                resolved = None
                for schema_name, value in labels.items():
                    if not isinstance(value, dict):
                        continue
                    label_val = value.get("label", "")
                    if label_val in ("success", "resolved", "correct"):
                        resolved = True
                    elif label_val in ("failure", "unresolved", "incorrect"):
                        resolved = False
                    elif label_val in ("partial", "partially_resolved"):
                        resolved = False  # SWE-bench is binary

                if resolved is not None:
                    record = {
                        "instance_id": instance_id,
                        "resolved": resolved,
                        "annotator": ann.get("user_id", ""),
                    }
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    count += 1

        if count == 0:
            os.remove(output_path)
            return None, 0

        logger.info(f"Exported {count} SWE-bench results to {output_path}")
        return output_path, count

    def _export_code_review(self, context: ExportContext, output_dir: str) -> Tuple[Optional[str], int]:
        """Export structured code review data."""
        output_path = os.path.join(output_dir, "code_reviews.jsonl")
        count = 0

        with open(output_path, "w") as f:
            for ann in context.annotations:
                instance_id = ann.get("instance_id", "")
                labels = ann.get("labels", {})

                for schema_name, value in labels.items():
                    if not isinstance(value, dict):
                        continue
                    label_val = value.get("label", "")
                    if not isinstance(label_val, str):
                        continue

                    try:
                        parsed = json.loads(label_val)
                    except (json.JSONDecodeError, TypeError):
                        continue

                    if not isinstance(parsed, dict):
                        continue

                    # Check for code review structure
                    if "verdict" in parsed or "comments" in parsed:
                        record = {
                            "instance_id": instance_id,
                            "annotator": ann.get("user_id", ""),
                            "verdict": parsed.get("verdict", ""),
                            "comments": parsed.get("comments", []),
                            "file_ratings": parsed.get("file_ratings", {}),
                        }
                        f.write(json.dumps(record, ensure_ascii=False) + "\n")
                        count += 1

        if count == 0:
            os.remove(output_path)
            return None, 0

        logger.info(f"Exported {count} code reviews to {output_path}")
        return output_path, count
