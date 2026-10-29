"""
Consensus Exporter (``consensus``)

Aggregates many annotators' work on each item into a consensus, in the way
citizen-science projects do after volunteers have classified each subject
(Zooniverse's aggregation reducers are the model). See potato/aggregation/.

Files, each written only when the project has a scheme of that kind:

    consensus_questions.csv  per item and radio / select / likert / multiselect
                             question: classifiers, top answer, its count and
                             fraction, ties, status (retired / needs_review)
                             and the reason
    consensus_votes.csv      per item, question and answer: count, fraction
    consensus_numeric.csv    per item and slider / number question: n, mean,
                             median, sd, min, max
    consensus_points.csv     per item, image scheme, label and point cluster:
                             centre, size, annotators, spread, variances
    consensus_boxes.csv      per item, image scheme, label and box group:
                             median box, support, mean and minimum IoU
    consensus.json           all of the above plus the settings used

Parameters come from the ``consensus_aggregation`` config block, overridden by
``--option`` (potato/aggregation/config.py lists them).
"""

from __future__ import annotations

import csv
import json
import math
import os
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

QUESTION_COLUMNS = ["instance_id", "schema", "type", "n_classifiers", "top_answer",
                    "top_count", "top_fraction", "tied", "status", "reason"]
VOTE_COLUMNS = ["instance_id", "schema", "answer", "count", "fraction", "n_classifiers"]
NUMERIC_COLUMNS = ["instance_id", "schema", "type", "n", "mean", "median", "sd",
                   "min", "max"]
POINT_COLUMNS = ["instance_id", "schema", "label", "cluster", "x", "y", "x_px", "y_px",
                 "size", "n_annotators", "spread", "spread_px", "var_x", "var_y",
                 "cov_xy", "annotators", "label_points", "label_annotators",
                 "label_noise", "n_classifiers", "note"]
BOX_COLUMNS = ["instance_id", "schema", "label", "group", "x", "y", "width", "height",
               "x_px", "y_px", "width_px", "height_px", "support", "n_classifiers",
               "support_fraction", "mean_iou", "min_iou", "annotators"]


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        return round(value, 6)
    if isinstance(value, (list, tuple, set, frozenset)):
        return ";".join(str(v) for v in value)
    return value


class ConsensusExporter(BaseExporter):
    format_name = "consensus"
    description = ("Consensus across annotators: vote fractions per answer, point "
                   "clusters and consensus boxes (Zooniverse-style aggregation)")
    file_extensions = [".csv", ".json"]

    def _settings(self, context: ExportContext, options: Optional[dict]):
        from potato.aggregation.config import parse_consensus_config
        return parse_consensus_config(context.config, options)

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        from potato.aggregation.config import ConsensusConfigError
        from potato.aggregation.engine import aggregatable_schemes
        try:
            settings = self._settings(context, None)
        except ConsensusConfigError as exc:
            return False, str(exc)
        if not aggregatable_schemes(context.schemas, settings):
            return False, ("No scheme to aggregate: the consensus export reads radio, "
                           "select, likert, multiselect, slider, number and "
                           "image_annotation schemes")
        if not context.annotations:
            return False, "No annotations to export"
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        from potato.aggregation.config import ConsensusConfigError
        from potato.aggregation.engine import aggregate, aggregatable_schemes

        try:
            settings = self._settings(context, options)
        except ConsensusConfigError as exc:
            return ExportResult(success=False, format_name=self.format_name,
                                errors=[str(exc)])
        schemes = aggregatable_schemes(context.schemas, settings)
        if not schemes:
            return ExportResult(success=False, format_name=self.format_name,
                                errors=[self.can_export(context)[1] or
                                        "No scheme to aggregate"])
        if not context.annotations:
            return ExportResult(success=False, format_name=self.format_name,
                                errors=["No annotations to export"])

        result = aggregate(context.config, context.annotations, context.items or {},
                           context.schemas, settings)
        kinds = {s.get("annotation_type") for s in schemes}
        os.makedirs(output_path, exist_ok=True)
        files: List[str] = []

        def write(fname: str, columns: List[str], rows: List[Dict[str, Any]]) -> None:
            path = os.path.join(output_path, fname)
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
                writer.writeheader()
                for row in rows:
                    writer.writerow({k: _cell(row.get(k)) for k in columns})
            files.append(path)

        if kinds & {"radio", "select", "likert", "multiselect"}:
            write("consensus_questions.csv", QUESTION_COLUMNS, result["questions"])
            votes = [{"instance_id": q["instance_id"], "schema": q["schema"],
                      "n_classifiers": q["n_classifiers"], **a}
                     for q in result["questions"] for a in q["answers"]]
            write("consensus_votes.csv", VOTE_COLUMNS, votes)
        if kinds & {"slider", "number"}:
            write("consensus_numeric.csv", NUMERIC_COLUMNS, result["numeric"])
        if "image_annotation" in kinds:
            point_rows = []
            for entry in result["points"]:
                base = {"instance_id": entry["instance_id"], "schema": entry["schema"],
                        "label": entry["label"], "label_points": entry["n_points"],
                        "label_annotators": entry["n_annotators"],
                        "label_noise": entry["noise"],
                        "n_classifiers": entry["n_classifiers"]}
                if entry["clusters"]:
                    point_rows.extend({**base, **c} for c in entry["clusters"])
                else:
                    note = entry.get("skipped") or "no cluster (every point is noise)"
                    point_rows.append({**base, "note": note})
            write("consensus_points.csv", POINT_COLUMNS, point_rows)
            box_rows = [{"instance_id": e["instance_id"], "schema": e["schema"],
                         "label": e["label"], **g}
                        for e in result["boxes"] for g in e["groups"]]
            write("consensus_boxes.csv", BOX_COLUMNS, box_rows)

        json_path = os.path.join(output_path, "consensus.json")
        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, ensure_ascii=False, default=list)
        files.append(json_path)

        questions = result["questions"]
        stats = {
            "questions": len(questions),
            "retired": sum(1 for q in questions if q["status"] == "retired"),
            "needs_review": sum(1 for q in questions if q["status"] != "retired"),
            "numeric_questions": len(result["numeric"]),
            "point_clusters": sum(len(p["clusters"]) for p in result["points"]),
            "box_groups": sum(len(b["groups"]) for b in result["boxes"]),
        }
        return ExportResult(success=True, format_name=self.format_name,
                            files_written=files, warnings=result["warnings"],
                            stats=stats)
