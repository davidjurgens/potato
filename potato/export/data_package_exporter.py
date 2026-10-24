"""
Frictionless Data Package and Psych-DS Exporters

Both wrap the CSV export (annotations.csv plus whichever sidecars the project
produces: participants, trials, phase answers, runtime trial tables) in the
metadata a data repository or a reviewer's validator expects.

* ``data_package``: a Frictionless Data Package v2 -- ``datapackage.json``
  listing every CSV as a resource with a Table Schema (each column's type
  inferred from its values; a column named after a question carries that
  question's wording as its description and, for a single-choice question,
  its options as an ``enum`` constraint). Read by ``frictionless validate``,
  Zenodo and the Open Science Framework's previews.
* ``psych_ds``: the Psych-DS layout -- ``dataset_description.json``
  (schema.org ``Dataset`` JSON-LD listing every column in
  ``variableMeasured``) and the CSVs under ``data/`` with Psych-DS
  keyword file names (``study-<task>_table-annotations_data.csv``). Read by
  the Psych-DS validator.
"""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

_CHOICE_TYPES = {"radio", "select", "likert"}


def _run_csv(context: ExportContext, path: str) -> Tuple[ExportResult, List[str]]:
    from .runtime_exporter import RuntimeExporter
    from .tabular_exporter import CSVExporter
    os.makedirs(path, exist_ok=True)
    result = CSVExporter().export(context, path)
    files = [f for f in result.files_written if f.endswith(".csv")]
    runtime = RuntimeExporter()
    ok, _ = runtime.can_export(context)
    if ok:
        r = runtime.export(context, path)
        files += [f for f in r.files_written if f.endswith(".csv")]
    return result, files


def _infer_type(values: List[str]) -> str:
    seen = [v for v in values if v not in ("", None)]
    if not seen:
        return "string"
    if all(re.fullmatch(r"-?\d+", v) for v in seen):
        return "integer"
    if all(re.fullmatch(r"-?\d+(\.\d+)?([eE][-+]?\d+)?", v) for v in seen):
        return "number"
    if all(v.lower() in ("true", "false") for v in seen):
        return "boolean"
    return "string"


def scheme_for_column(name: str, schemes: Dict[str, dict]) -> Tuple[Optional[dict], Optional[str]]:
    """The question a CSV column belongs to: ``(scheme, None)`` for a column
    named after the question, ``(scheme, label)`` for a ``schema.label`` column."""
    if name in schemes:
        return schemes[name], None
    head, dot, rest = name.partition(".")
    if dot and head in schemes:
        return schemes[head], rest
    return None, None


def table_schema(csv_path: str, schemes: Dict[str, dict], max_rows: int = 5000) -> Dict[str, Any]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        columns: List[List[str]] = [[] for _ in header]
        for i, row in enumerate(reader):
            if i >= max_rows:
                break
            for j, cell in enumerate(row[:len(header)]):
                columns[j].append(cell)
    fields = []
    for name, values in zip(header, columns):
        field: Dict[str, Any] = {"name": name, "type": _infer_type(values)}
        scheme, label = scheme_for_column(name, schemes)
        if scheme and scheme.get("description"):
            field["description"] = (str(scheme["description"]) if label is None
                                    else f"{scheme['description']} ({label})")
        # A whole-question column (written when stored labels had to be
        # resolved) holds one of the options; a per-label column `schema.label`
        # holds that label or is empty. Each gets the enum its values bear out.
        if scheme and scheme.get("annotation_type") in _CHOICE_TYPES and scheme.get("labels"):
            labels = [l if isinstance(l, str) else l.get("name") for l in scheme["labels"]]
            allowed = labels if label is None else [label]
            present = {v for v in values if v}
            if label is None or label in labels:
                if present <= set(allowed):
                    field["constraints"] = {"enum": allowed}
        fields.append(field)
    return {"fields": fields}


def _resource_name(path: str) -> str:
    base = os.path.splitext(os.path.basename(path))[0].lower()
    return re.sub(r"[^a-z0-9._-]+", "-", base).strip("-") or "data"


def _all_schemes(context: ExportContext) -> Dict[str, dict]:
    """Annotation questions and survey-page questions, by name."""
    schemes = {s.get("name"): s for s in context.schemas or [] if isinstance(s, dict)}
    try:
        from potato.server_utils.config_module import phase_page_schemes
        pages = phase_page_schemes(context.config or {}, (context.config or {}).get("task_dir")) or {}
    except Exception:
        pages = {}
    for page_schemes in pages.values():
        for s in page_schemes:
            if isinstance(s, dict) and s.get("name"):
                schemes.setdefault(s["name"], s)
    return schemes


class DataPackageExporter(BaseExporter):
    format_name = "data_package"
    description = "Frictionless Data Package v2 (CSV tables + datapackage.json with Table Schemas)"
    file_extensions = [".json", ".csv"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        from .tabular_exporter import _can_export_tabular
        return _can_export_tabular(context)

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        csv_result, files = _run_csv(context, output_path)
        if not csv_result.success:
            return csv_result
        schemes = _all_schemes(context)
        name = re.sub(r"[^a-z0-9._-]+", "-",
                      str((context.config or {}).get("annotation_task_name") or "potato").lower()).strip("-")
        package = {
            "$schema": "https://datapackage.org/profiles/2.0/datapackage.json",
            "name": name or "potato",
            "title": (context.config or {}).get("annotation_task_name") or "Potato annotations",
            "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "resources": [],
        }
        used = set()
        for path in files:
            rname = _resource_name(path)
            n = 2
            while rname in used:
                rname = f"{_resource_name(path)}-{n}"
                n += 1
            used.add(rname)
            package["resources"].append({
                "name": rname,
                "path": os.path.relpath(path, output_path).replace(os.sep, "/"),
                "format": "csv",
                "mediatype": "text/csv",
                "encoding": "utf-8",
                "schema": table_schema(path, schemes),
            })
        out = os.path.join(output_path, "datapackage.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(package, f, ensure_ascii=False, indent=2)
        return ExportResult(success=True, format_name=self.format_name,
                            files_written=csv_result.files_written + [out],
                            warnings=csv_result.warnings,
                            stats={"num_resources": len(package["resources"]), **(csv_result.stats or {})})


def _keyword_value(text: str) -> str:
    """Psych-DS keyword values: letters and digits only."""
    return re.sub(r"[^A-Za-z0-9]+", "", str(text or "")) or "potato"


def _variable(name: str, schemes: Dict[str, dict]):
    scheme, label = scheme_for_column(name, schemes)
    if not (scheme and scheme.get("description")):
        return name
    desc = str(scheme["description"]) if label is None else f"{scheme['description']} ({label})"
    return {"@type": "PropertyValue", "name": name, "description": desc}


class PsychDSExporter(BaseExporter):
    format_name = "psych_ds"
    description = "Psych-DS dataset (dataset_description.json + data/ with keyword file names)"
    file_extensions = [".json", ".csv"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        from .tabular_exporter import _can_export_tabular
        return _can_export_tabular(context)

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        staging = os.path.join(output_path, ".psychds-staging")
        csv_result, files = _run_csv(context, staging)
        if not csv_result.success:
            shutil.rmtree(staging, ignore_errors=True)
            return csv_result
        study = _keyword_value((context.config or {}).get("annotation_task_name"))
        data_dir = os.path.join(output_path, "data")
        os.makedirs(data_dir, exist_ok=True)
        written: List[str] = []
        variables: List[str] = []
        for path in files:
            table = _keyword_value(os.path.splitext(os.path.basename(path))[0])
            dest = os.path.join(data_dir, f"study-{study}_table-{table}_data.csv")
            shutil.copyfile(path, dest)
            written.append(dest)
            with open(dest, newline="", encoding="utf-8") as f:
                for col in next(csv.reader(f), []):
                    if col not in variables:
                        variables.append(col)
        shutil.rmtree(staging, ignore_errors=True)
        schemes = _all_schemes(context)
        description = {
            "@context": "https://schema.org/",
            "@type": "Dataset",
            "name": (context.config or {}).get("annotation_task_name") or "Potato annotations",
            "description": (context.config or {}).get("annotation_task_description")
                           or "Annotations and survey answers exported from Potato.",
            "dateCreated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "variableMeasured": [_variable(v, schemes) for v in variables],
        }
        out = os.path.join(output_path, "dataset_description.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(description, f, ensure_ascii=False, indent=2)
        written.append(out)
        return ExportResult(success=True, format_name=self.format_name, files_written=written,
                            warnings=csv_result.warnings,
                            stats={"num_tables": len(files), "num_variables": len(variables)})
