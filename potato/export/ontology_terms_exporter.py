"""
Ontology Terms Exporter (``--format ontology_terms``)

For schemes with ``label_source`` (ontology-backed labels). Writes one row per
picked term:

    ontology_terms.csv    user_id, instance_id, schema, annotation_type,
                          ontology, obo_id, label, iri, ontology_version,
                          start, end, text, shape_index, shape_type, known
    ontology_terms.jsonl  the same rows as JSON objects

Where the record comes from:

* radio / multiselect store the whole record ``{obo_id, label, iri,
  ontology_version}`` as the label's value, so the row is that record.
* span and image_annotation store only the term id (the span ``name``, the
  shape ``label``). The rest is looked up in the ``.obo`` file (``service:
  file``; the version is the file's current one) or in the terms the OLS4
  proxy has returned (``service: ols4``; ``annotation_output/ontology_cache``).

``known`` is ``false`` when the id is not in the current file or cache: the
term was removed from a later file, or the value was not written by the picker.
Fixed (non-ontology) labels on the same scheme are not rows here; the csv,
jsonl and parquet exports carry them as usual.
"""

from __future__ import annotations

import csv
import json
import os
from typing import Any, Dict, List, Optional

from .base import BaseExporter, ExportContext, ExportResult

COLUMNS = ["user_id", "instance_id", "schema", "annotation_type", "ontology", "obo_id",
           "label", "iri", "ontology_version", "start", "end", "text",
           "shape_index", "shape_type", "known"]


def _ontology_schemes(context: ExportContext) -> Dict[str, dict]:
    return {s["name"]: s for s in context.schemas or []
            if isinstance(s, dict) and isinstance(s.get("label_source"), dict)}


def _source(scheme: dict, config: dict):
    try:
        from potato.ontology.source import source_for_scheme
        return source_for_scheme(scheme, config)
    except Exception:
        return None


def _lookup(source, obo_id: str) -> Optional[Dict[str, str]]:
    if source is None:
        return None
    try:
        return source.get_term(obo_id)
    except Exception:
        return None


class OntologyTermsExporter(BaseExporter):
    format_name = "ontology_terms"
    description = "Ontology-backed labels: one row per picked term (obo_id, label, IRI, version)"
    file_extensions = [".csv", ".jsonl"]

    def can_export(self, context: ExportContext) -> tuple:
        if not _ontology_schemes(context):
            return False, "No annotation scheme has a label_source"
        return True, ""

    def rows(self, context: ExportContext) -> List[Dict[str, Any]]:
        from potato.ontology.source import CURIE_RE, normalize_record
        schemes = _ontology_schemes(context)
        sources = {name: _source(s, context.config or {}) for name, s in schemes.items()}
        out: List[Dict[str, Any]] = []

        def row(rec, base, record, known, **extra):
            r = {c: "" for c in COLUMNS}
            r.update(base)
            r.update({k: record.get(k, "") for k in ("obo_id", "label", "iri", "ontology_version")})
            r["known"] = known
            r.update(extra)
            out.append(r)

        for rec in context.annotations or []:
            for name, scheme in schemes.items():
                atype = scheme.get("annotation_type")
                base = {"user_id": rec.get("user_id", ""), "instance_id": rec.get("instance_id", ""),
                        "schema": name, "annotation_type": atype,
                        "ontology": scheme["label_source"].get("ontology", "")}
                src = sources.get(name)
                if atype in ("radio", "multiselect"):
                    for label_name, value in ((rec.get("labels") or {}).get(name) or {}).items():
                        record = normalize_record(value)
                        if record is None or record["obo_id"] != label_name:
                            continue  # a fixed label or free response
                        known = _lookup(src, record["obo_id"]) is not None
                        row(rec, base, record, known)
                elif atype == "span":
                    for span in (rec.get("spans") or {}).get(name) or []:
                        obo_id = span.get("name") or span.get("label") or ""
                        if not CURIE_RE.match(str(obo_id)):
                            continue
                        found = _lookup(src, obo_id)
                        record = found or {"obo_id": obo_id, "label": span.get("title") or ""}
                        text = span.get("text")
                        if text is None:
                            try:
                                text = context.covered_text(rec.get("instance_id", ""), span)
                            except Exception:
                                text = ""
                        row(rec, base, record, found is not None,
                            start=span.get("start", ""), end=span.get("end", ""), text=text or "")
                elif atype == "image_annotation":
                    shapes = (rec.get("image_annotations") or {}).get(name)
                    if shapes is None:
                        raw = ((rec.get("labels") or {}).get(name) or {}).get("_data")
                        try:
                            shapes = json.loads(raw) if isinstance(raw, str) else raw
                        except ValueError:
                            shapes = None
                    for i, shape in enumerate(shapes if isinstance(shapes, list) else []):
                        obo_id = shape.get("label") if isinstance(shape, dict) else None
                        if not obo_id or not CURIE_RE.match(str(obo_id)):
                            continue
                        found = _lookup(src, obo_id)
                        record = found or {"obo_id": obo_id}
                        row(rec, base, record, found is not None,
                            shape_index=i, shape_type=shape.get("type", ""))
        return out

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        rows = self.rows(context)
        if not rows:
            return ExportResult(success=False, format_name=self.format_name,
                                errors=["No ontology terms have been picked yet"])
        os.makedirs(output_path, exist_ok=True)
        csv_path = os.path.join(output_path, "ontology_terms.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=COLUMNS)
            writer.writeheader()
            for r in rows:
                writer.writerow({k: ("true" if v is True else "false" if v is False else v)
                                 for k, v in r.items()})
        jsonl_path = os.path.join(output_path, "ontology_terms.jsonl")
        with open(jsonl_path, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        unknown = sum(1 for r in rows if not r["known"])
        warnings = []
        if unknown:
            warnings.append(f"{unknown} picked term(s) are not in the current ontology "
                            f"file or cache (column known=false)")
        return ExportResult(success=True, format_name=self.format_name,
                            files_written=[csv_path, jsonl_path], warnings=warnings,
                            stats={"rows": len(rows), "unknown": unknown})
