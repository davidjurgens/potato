"""
Reporting and export functionality for simulation results.

This module provides the SimulationReporter class for exporting
simulation results in various formats.
"""

import json
import csv
import os
from typing import Dict, Any
from datetime import datetime

from .user_simulator import UserSimulationResult


class SimulationReporter:
    """Handles result collection and export.

    Supports multiple export formats:
    - JSON: Full structured results
    - CSV: Flat annotation records
    - JSONL: Line-delimited JSON for streaming
    """

    def __init__(self, output_dir: str):
        """Initialize reporter.

        Args:
            output_dir: Directory for output files
        """
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def export_results(
        self,
        results: Dict[str, UserSimulationResult],
        summary: Dict[str, Any],
    ) -> None:
        """Export all results to files.

        Creates:
        - summary_{timestamp}.json: Aggregate statistics
        - user_results_{timestamp}.json: Per-user detailed results
        - annotations_{timestamp}.csv: All annotations in flat format

        Args:
            results: Dict mapping user_id to UserSimulationResult
            summary: Summary statistics dictionary
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Export summary
        self._export_summary(summary, timestamp)

        # Export per-user results
        self._export_user_results(results, timestamp)

        # Export annotations CSV
        self._export_annotations_csv(results, timestamp)

        print(f"Results exported to {self.output_dir}/")

    def _export_summary(self, summary: Dict[str, Any], timestamp: str) -> None:
        """Export summary statistics to JSON.

        Args:
            summary: Summary dictionary
            timestamp: Timestamp string for filename
        """
        filepath = os.path.join(self.output_dir, f"summary_{timestamp}.json")
        with open(filepath, "w") as f:
            json.dump(summary, f, indent=2, default=str)
        print(f"  - Summary: {filepath}")

    def _export_user_results(
        self,
        results: Dict[str, UserSimulationResult],
        timestamp: str,
    ) -> None:
        """Export detailed per-user results to JSON.

        Args:
            results: Dict mapping user_id to UserSimulationResult
            timestamp: Timestamp string for filename
        """
        filepath = os.path.join(self.output_dir, f"user_results_{timestamp}.json")

        export_data = {}
        for user_id, result in results.items():
            export_data[user_id] = {
                "user_id": result.user_id,
                "total_annotations": len(result.annotations),
                "total_time": result.total_time,
                "attention_checks_passed": result.attention_checks_passed,
                "attention_checks_failed": result.attention_checks_failed,
                "gold_standard_correct": result.gold_standard_correct,
                "gold_standard_incorrect": result.gold_standard_incorrect,
                "was_blocked": result.was_blocked,
                "errors": result.errors,
                "start_time": (
                    result.start_time.isoformat() if result.start_time else None
                ),
                "end_time": result.end_time.isoformat() if result.end_time else None,
            }

        with open(filepath, "w") as f:
            json.dump(export_data, f, indent=2)
        print(f"  - User results: {filepath}")

    def _export_annotations_csv(
        self,
        results: Dict[str, UserSimulationResult],
        timestamp: str,
    ) -> None:
        """Export all annotations to CSV.

        Args:
            results: Dict mapping user_id to UserSimulationResult
            timestamp: Timestamp string for filename
        """
        filepath = os.path.join(self.output_dir, f"annotations_{timestamp}.csv")

        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "user_id",
                    "instance_id",
                    "schema_name",
                    "annotation",
                    "response_time",
                    "timestamp",
                    "was_attention_check",
                    "attention_check_passed",
                    "was_gold_standard",
                    "gold_standard_correct",
                ]
            )

            for user_id, result in results.items():
                for record in result.annotations:
                    writer.writerow(
                        [
                            user_id,
                            record.instance_id,
                            record.schema_name,
                            json.dumps(record.annotation),
                            record.response_time,
                            record.timestamp.isoformat(),
                            record.was_attention_check,
                            record.attention_check_passed,
                            record.was_gold_standard,
                            record.gold_standard_correct,
                        ]
                    )

        print(f"  - Annotations CSV: {filepath}")

    def export_annotations_jsonl(
        self,
        results: Dict[str, UserSimulationResult],
        timestamp: str,
    ) -> None:
        """Export all annotations to JSONL (line-delimited JSON).

        Useful for streaming processing and large datasets.

        Args:
            results: Dict mapping user_id to UserSimulationResult
            timestamp: Timestamp string for filename
        """
        filepath = os.path.join(self.output_dir, f"annotations_{timestamp}.jsonl")

        with open(filepath, "w") as f:
            for user_id, result in results.items():
                for record in result.annotations:
                    line_data = {
                        "user_id": user_id,
                        "instance_id": record.instance_id,
                        "schema_name": record.schema_name,
                        "annotation": record.annotation,
                        "response_time": record.response_time,
                        "timestamp": record.timestamp.isoformat(),
                        "was_attention_check": record.was_attention_check,
                        "attention_check_passed": record.attention_check_passed,
                        "was_gold_standard": record.was_gold_standard,
                        "gold_standard_correct": record.gold_standard_correct,
                    }
                    f.write(json.dumps(line_data) + "\n")

        print(f"  - Annotations JSONL: {filepath}")
