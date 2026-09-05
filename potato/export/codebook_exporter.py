"""
Codebook Exporter

Exports the project codebook (label/code taxonomy) to a CSV file with one row per
code. Designed for qualitative-research workflows where the codebook is a
deliverable in its own right.

Output columns:
    schema           annotation_scheme name
    annotation_type  schema type (radio, multiselect, span, hierarchical_multiselect)
    code             label name
    parent           parent code (for hierarchical schemas)
    description      the code's definition. From the project codebook's
                     "Short definition" / "Definition" block when the code has
                     one, otherwise the description / tooltip in the config.
    color            color hex if defined
    n_uses           number of times this code was applied across all annotators

Codes a coder added at /codebook during the study are included, with their
definitions -- the codebook, not the YAML, is the source of truth for a scheme
that declares ``codebook: true``.
"""

import csv
import logging
import os
from typing import Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

logger = logging.getLogger(__name__)


# Schemas that contribute codes to a codebook export.
CODEBOOK_SCHEMA_TYPES = {
    "radio", "multiselect", "select", "likert",
    "span", "hierarchical_multiselect", "tree_annotation",
}


class CodebookExporter(BaseExporter):
    format_name = "codebook"
    description = "Project codebook (CSV) with code names, hierarchy, and use counts"
    file_extensions = [".csv"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        has_codeable_schema = any(
            s.get("annotation_type") in CODEBOOK_SCHEMA_TYPES
            for s in context.schemas
        )
        if not has_codeable_schema:
            return False, "No codeable schema (radio/multiselect/span/etc.) in config"
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        options = options or {}
        os.makedirs(output_path, exist_ok=True)
        out_file = os.path.join(output_path, "codebook.csv")

        use_counts = self._count_label_uses(context)
        definitions = self._codebook_definitions(context)

        rows = []
        for scheme in context.schemas:
            atype = scheme.get("annotation_type")
            if atype not in CODEBOOK_SCHEMA_TYPES:
                continue
            schema_name = scheme.get("name", "")
            for code_row in self._iter_codes(scheme):
                code_row["schema"] = schema_name
                code_row["annotation_type"] = atype
                code_row["n_uses"] = use_counts.get(
                    (schema_name, code_row["code"]), 0
                )
                if not code_row.get("description"):
                    code_row["description"] = definitions.get(code_row["code"], "")
                rows.append(code_row)

        fieldnames = [
            "schema", "annotation_type", "code", "parent",
            "description", "color", "n_uses",
        ]
        with open(out_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in rows:
                writer.writerow({k: r.get(k, "") for k in fieldnames})

        logger.info(f"Codebook exported to {out_file}: {len(rows)} codes")
        return ExportResult(
            success=True,
            format_name=self.format_name,
            files_written=[out_file],
            stats={"codes_exported": len(rows)},
        )

    @staticmethod
    def _codebook_definitions(context):
        """``{code name: definition}`` from the project codebook, if there is one.

        The definition a coder writes at /codebook lives in a `code_block`
        row, not in the config, so `description` was empty for every code even
        when every code had been defined -- on an export whose whole purpose is
        to hand someone the codebook. Prefers the short definition, falls back
        to the full one.

        Returns {} when the project has no codebook database, which is every
        non-QDA project.
        """
        task_dir = context.config.get("task_dir", ".")
        if not os.path.exists(os.path.join(task_dir, "project.sqlite")):
            return {}
        project = context.config.get("annotation_task_name") or "default"
        try:
            from potato.codebook import blocks
            from potato.codebook.codebook import Codebook
        except Exception:
            return {}

        out = {}
        try:
            for code in Codebook.load(task_dir, project)._codes:
                bodies = {}
                for block in blocks.list_blocks(task_dir, project,
                                                code_id=code["id"]):
                    body = (block.get("body_md") or "").strip()
                    if body:
                        bodies.setdefault(block.get("block_type"), body)
                definition = bodies.get("short_def") or bodies.get("definition")
                if definition:
                    out[code["name"]] = definition
        except Exception as e:
            logger.warning(f"Could not read codebook definitions: {e}")
        return out

    @staticmethod
    def _iter_codes(scheme):
        """Yield {code, parent, description, color} dicts for a schema."""
        atype = scheme.get("annotation_type")

        if atype == "hierarchical_multiselect":
            yield from CodebookExporter._iter_hierarchical(scheme.get("labels", []), parent="")
            return
        if atype == "tree_annotation":
            yield from CodebookExporter._iter_hierarchical(scheme.get("labels", []), parent="")
            return

        labels = scheme.get("labels", [])
        for label in labels:
            if isinstance(label, dict):
                name = label.get("name", "")
                yield {
                    "code": name,
                    "parent": "",
                    "description": label.get("description") or label.get("tooltip", ""),
                    "color": label.get("color", ""),
                }
            else:
                yield {"code": str(label), "parent": "", "description": "", "color": ""}

    @staticmethod
    def _iter_hierarchical(nodes, parent):
        if not isinstance(nodes, list):
            return
        for node in nodes:
            if isinstance(node, dict):
                name = node.get("name", "")
                yield {
                    "code": name,
                    "parent": parent,
                    "description": node.get("description") or node.get("tooltip", ""),
                    "color": node.get("color", ""),
                }
                children = node.get("children") or node.get("labels") or []
                yield from CodebookExporter._iter_hierarchical(children, parent=name)
            else:
                yield {"code": str(node), "parent": parent, "description": "", "color": ""}

    @staticmethod
    def _count_label_uses(context):
        counts = {}
        for ann in context.annotations:
            labels = ann.get("labels", {}) or {}
            for schema_name, schema_payload in labels.items():
                names = []
                if isinstance(schema_payload, dict):
                    names = [k for k, v in schema_payload.items() if v]
                elif isinstance(schema_payload, list):
                    names = [str(x) for x in schema_payload]
                elif schema_payload not in (None, ""):
                    names = [str(schema_payload)]
                for n in names:
                    key = (schema_name, n)
                    counts[key] = counts.get(key, 0) + 1

            spans = ann.get("spans", {}) or {}
            for schema_name, span_list in spans.items():
                for span in span_list or []:
                    # `name` is where a stored span keeps its code. Without it
                    # every span code exported n_uses 0 -- the one column a
                    # qualitative researcher sorts by, zero for the scheme the
                    # codebook belongs to.
                    label = (span.get("name") or span.get("label")
                             or span.get("annotation"))
                    if label:
                        key = (schema_name, label)
                        counts[key] = counts.get(key, 0) + 1

        return counts
