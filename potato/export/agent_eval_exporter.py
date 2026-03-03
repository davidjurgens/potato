"""
Agent Evaluation Exporter

Exports annotations in a structured format optimized for agent evaluation,
producing per-trace aggregated scores, error distributions, and per-step
assessment summaries.

Output format:
{
    "summary": {
        "total_traces": 10,
        "total_annotators": 3,
        "schemas_evaluated": ["task_success", "efficiency", ...]
    },
    "per_trace": [
        {
            "trace_id": "trace_001",
            "annotations": {
                "task_success": {"distribution": {"success": 2, "partial": 1}, "majority": "success"},
                "efficiency": {"mean": 4.2, "std": 0.5, "values": [4, 5, 4]},
                "mast_errors": {"counts": {"no_errors": 3}, "total_annotations": 3}
            },
            "annotator_count": 3
        }
    ],
    "aggregate": {
        "task_success": {"success_rate": 0.7, "partial_rate": 0.2, "failure_rate": 0.1},
        "efficiency": {"overall_mean": 3.8, "overall_std": 0.9},
        "mast_errors": {"total_distribution": {"no_errors": 25, "step_repetition": 3, ...}}
    }
}
"""

import csv
import io
import json
import logging
import os
from collections import Counter, defaultdict
from typing import Dict, List, Any, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

logger = logging.getLogger(__name__)


class AgentEvalExporter(BaseExporter):
    """
    Exporter for agent trace evaluation annotations.

    Produces structured JSON output optimized for evaluation dashboards
    and leaderboard computation.
    """

    format_name = "agent_eval"
    description = "Agent evaluation export with aggregated scores and error distributions"
    file_extensions = [".json"]

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        options = options or {}
        files_written = []
        warnings = []

        try:
            # Group annotations by trace
            trace_annotations = self._group_by_trace(context.annotations)

            # Get schema info
            schema_map = {s["name"]: s for s in context.schemas}

            # Compute per-trace aggregations
            per_trace_results = []
            for trace_id, annotations in sorted(trace_annotations.items()):
                trace_result = self._aggregate_trace(trace_id, annotations, schema_map)
                per_trace_results.append(trace_result)

            # Compute global aggregations
            aggregate = self._compute_aggregate(per_trace_results, schema_map)

            # Build summary
            all_annotators = set()
            for anns in trace_annotations.values():
                for ann in anns:
                    all_annotators.add(ann.get("user_id", "unknown"))

            summary = {
                "total_traces": len(trace_annotations),
                "total_annotators": len(all_annotators),
                "annotators": sorted(all_annotators),
                "schemas_evaluated": sorted(schema_map.keys()),
            }

            # Build output
            output = {
                "summary": summary,
                "per_trace": per_trace_results,
                "aggregate": aggregate,
            }

            # Write output
            os.makedirs(output_path, exist_ok=True)
            output_file = os.path.join(output_path, "agent_evaluation.json")
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=2, ensure_ascii=False)
            files_written.append(output_file)

            # Also write a per-trace CSV for easy analysis
            csv_file = os.path.join(output_path, "agent_evaluation_summary.csv")
            self._write_summary_csv(csv_file, per_trace_results, schema_map)
            files_written.append(csv_file)

            return ExportResult(
                success=True,
                format_name=self.format_name,
                files_written=files_written,
                warnings=warnings,
                stats={
                    "total_traces": len(trace_annotations),
                    "total_annotations": sum(len(a) for a in trace_annotations.values()),
                    "total_annotators": len(all_annotators),
                },
            )

        except Exception as e:
            logger.error(f"Agent eval export failed: {e}")
            return ExportResult(
                success=False,
                format_name=self.format_name,
                errors=[str(e)],
            )

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not context.annotations:
            return False, "No annotations to export"
        if not context.schemas:
            return False, "No annotation schemas defined"
        return True, ""

    def _group_by_trace(self, annotations: List[dict]) -> Dict[str, List[dict]]:
        """Group annotations by instance (trace) ID."""
        grouped = defaultdict(list)
        for ann in annotations:
            trace_id = ann.get("instance_id", "unknown")
            grouped[trace_id].append(ann)
        return dict(grouped)

    def _aggregate_trace(self, trace_id: str, annotations: List[dict],
                         schema_map: Dict[str, dict]) -> dict:
        """Aggregate annotations for a single trace."""
        result = {
            "trace_id": trace_id,
            "annotator_count": len(set(a.get("user_id", "unknown") for a in annotations)),
            "annotations": {},
        }

        # Group by schema
        schema_values = defaultdict(list)
        for ann in annotations:
            labels = ann.get("labels", {})
            for schema_name, value in labels.items():
                schema_values[schema_name].append(value)

        # Aggregate each schema
        for schema_name, values in schema_values.items():
            schema_config = schema_map.get(schema_name, {})
            schema_type = schema_config.get("annotation_type", "")

            if schema_type in ("radio", "select"):
                result["annotations"][schema_name] = self._aggregate_categorical(values)
            elif schema_type in ("likert", "slider", "number"):
                result["annotations"][schema_name] = self._aggregate_numeric(values)
            elif schema_type == "multiselect":
                result["annotations"][schema_name] = self._aggregate_multiselect(values)
            elif schema_type == "multirate":
                result["annotations"][schema_name] = self._aggregate_multirate(values)
            elif schema_type == "text":
                result["annotations"][schema_name] = {"responses": values}
            else:
                result["annotations"][schema_name] = {"values": values}

        return result

    def _aggregate_categorical(self, values: List) -> dict:
        """Aggregate categorical (radio/select) annotations."""
        # Flatten nested dicts - values might be {"label": "value"} or just strings
        flat_values = []
        for v in values:
            if isinstance(v, dict):
                # Take the key with the highest value (convert to float for comparison)
                if v:
                    def _sort_key(k):
                        try:
                            return float(v[k])
                        except (ValueError, TypeError):
                            return 0
                    flat_values.append(max(v.keys(), key=_sort_key))
            else:
                flat_values.append(str(v))

        distribution = dict(Counter(flat_values))
        majority = max(distribution, key=distribution.get) if distribution else ""

        return {
            "distribution": distribution,
            "majority": majority,
            "agreement": max(distribution.values()) / len(flat_values) if flat_values else 0,
        }

    def _aggregate_numeric(self, values: List) -> dict:
        """Aggregate numeric (likert/slider) annotations."""
        numeric_values = []
        for v in values:
            if isinstance(v, (int, float)):
                numeric_values.append(float(v))
            elif isinstance(v, str):
                try:
                    numeric_values.append(float(v))
                except ValueError:
                    pass
            elif isinstance(v, dict):
                # Try to extract numeric value
                for val in v.values():
                    try:
                        numeric_values.append(float(val))
                    except (ValueError, TypeError):
                        pass

        if not numeric_values:
            return {"mean": None, "values": values}

        mean = sum(numeric_values) / len(numeric_values)
        # Use sample standard deviation (N-1) when N > 1, population (N) when N == 1
        n = len(numeric_values)
        variance = sum((x - mean) ** 2 for x in numeric_values) / max(n - 1, 1)
        std = variance ** 0.5

        return {
            "mean": round(mean, 3),
            "std": round(std, 3),
            "min": min(numeric_values),
            "max": max(numeric_values),
            "values": numeric_values,
        }

    def _aggregate_multiselect(self, values: List) -> dict:
        """Aggregate multiselect annotations."""
        counts = Counter()
        total = 0
        for v in values:
            total += 1
            if isinstance(v, dict):
                for label, selected in v.items():
                    if selected:
                        counts[label] += 1
            elif isinstance(v, list):
                for label in v:
                    counts[label] += 1

        return {
            "counts": dict(counts),
            "total_annotations": total,
        }

    def _aggregate_multirate(self, values: List) -> dict:
        """Aggregate multirate annotations."""
        item_ratings = defaultdict(list)
        for v in values:
            if isinstance(v, dict):
                for item_name, rating in v.items():
                    try:
                        item_ratings[item_name].append(float(rating))
                    except (ValueError, TypeError):
                        item_ratings[item_name].append(rating)

        result = {}
        for item_name, ratings in item_ratings.items():
            numeric = [r for r in ratings if isinstance(r, (int, float))]
            if numeric:
                result[item_name] = {
                    "mean": round(sum(numeric) / len(numeric), 3),
                    "values": ratings,
                }
            else:
                result[item_name] = {"values": ratings}

        return {"per_item": result}

    def _compute_aggregate(self, per_trace_results: List[dict],
                           schema_map: Dict[str, dict]) -> dict:
        """Compute aggregate statistics across all traces."""
        aggregate = {}

        for schema_name, schema_config in schema_map.items():
            schema_type = schema_config.get("annotation_type", "")

            if schema_type in ("radio", "select"):
                aggregate[schema_name] = self._aggregate_categorical_global(
                    per_trace_results, schema_name
                )
            elif schema_type in ("likert", "slider", "number"):
                aggregate[schema_name] = self._aggregate_numeric_global(
                    per_trace_results, schema_name
                )
            elif schema_type == "multiselect":
                aggregate[schema_name] = self._aggregate_multiselect_global(
                    per_trace_results, schema_name
                )

        return aggregate

    def _aggregate_categorical_global(self, results: List[dict], schema_name: str) -> dict:
        """Compute global rates for categorical annotations."""
        all_majorities = []
        total_dist = Counter()

        for result in results:
            ann = result.get("annotations", {}).get(schema_name, {})
            if "majority" in ann:
                all_majorities.append(ann["majority"])
            if "distribution" in ann:
                for label, count in ann["distribution"].items():
                    total_dist[label] += count

        # Compute rates
        total = sum(total_dist.values())
        rates = {}
        for label, count in total_dist.items():
            rates[f"{label}_rate"] = round(count / total, 3) if total > 0 else 0

        return {
            "rates": rates,
            "total_distribution": dict(total_dist),
            "majority_distribution": dict(Counter(all_majorities)),
        }

    def _aggregate_numeric_global(self, results: List[dict], schema_name: str) -> dict:
        """Compute global stats for numeric annotations."""
        all_means = []
        for result in results:
            ann = result.get("annotations", {}).get(schema_name, {})
            if ann.get("mean") is not None:
                all_means.append(ann["mean"])

        if not all_means:
            return {"overall_mean": None}

        overall_mean = sum(all_means) / len(all_means)
        n = len(all_means)
        variance = sum((x - overall_mean) ** 2 for x in all_means) / max(n - 1, 1)

        return {
            "overall_mean": round(overall_mean, 3),
            "overall_std": round(variance ** 0.5, 3),
            "num_traces": len(all_means),
        }

    def _aggregate_multiselect_global(self, results: List[dict], schema_name: str) -> dict:
        """Compute global counts for multiselect annotations."""
        total_counts = Counter()
        for result in results:
            ann = result.get("annotations", {}).get(schema_name, {})
            for label, count in ann.get("counts", {}).items():
                total_counts[label] += count

        return {"total_distribution": dict(total_counts)}

    def _write_summary_csv(self, csv_path: str, per_trace_results: List[dict],
                           schema_map: Dict[str, dict]) -> None:
        """Write a summary CSV with one row per trace."""
        if not per_trace_results:
            return

        # Collect all column names
        columns = ["trace_id", "annotator_count"]
        for result in per_trace_results:
            for schema_name in result.get("annotations", {}):
                schema_type = schema_map.get(schema_name, {}).get("annotation_type", "")
                if schema_type in ("radio", "select"):
                    col = f"{schema_name}_majority"
                    if col not in columns:
                        columns.append(col)
                elif schema_type in ("likert", "slider", "number"):
                    col = f"{schema_name}_mean"
                    if col not in columns:
                        columns.append(col)

        # Write CSV using csv module for proper escaping
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            for result in per_trace_results:
                row = [result["trace_id"], str(result["annotator_count"])]
                for col in columns[2:]:
                    schema_name = col.rsplit("_", 1)[0]
                    ann = result.get("annotations", {}).get(schema_name, {})
                    if col.endswith("_majority"):
                        row.append(str(ann.get("majority", "")))
                    elif col.endswith("_mean"):
                        row.append(str(ann.get("mean", "")))
                    else:
                        row.append("")
                writer.writerow(row)
