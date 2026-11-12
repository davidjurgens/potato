"""
Chemistry exporter (``chemistry``).

For ``chemical_structure`` schemes and ``viewer_selection`` schemes bound to
a ``molecule`` display. Writes:

    chemical_structures.csv   one row per answer: participant, item, scheme,
                              SMILES (OpenChemLib), RDKit SMILES, InChI,
                              InChIKey, OpenChemLib ID code, formula, whether
                              the pre-filled structure was changed, problems,
                              and the answer-key result when the scheme has
                              an answer_field
    chemical_structures.sdf   the same answers as an SD file: each molfile
                              with the row's fields as SD properties
    molecule_atoms.csv        one row per selected atom: participant, item,
                              scheme, display field, atom (0-based source
                              index), molfile number (atom + 1), element, label

InChI, InChIKey and RDKit SMILES come from the browser when RDKit.js was
loaded (``identifiers_from: browser``). Otherwise they are computed here with
the rdkit Python package (``identifiers_from: server``) when it is
installed, and left blank (``none``) when it is not, with a warning naming
``pip install "potato-annotation[chemistry]"``.
"""

from __future__ import annotations

import csv
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

STRUCTURE_COLUMNS = ["user_id", "instance_id", "schema", "smiles", "rdkit_smiles", "inchi",
                     "inchikey", "idcode", "formula", "changed", "problems",
                     "identifiers_from", "answer_correct", "answer_reason"]
ATOM_COLUMNS = ["user_id", "instance_id", "schema", "viewer_field", "atom", "number",
                "element", "label"]


def _sd_value(value: Any) -> str:
    text = "" if value is None else str(value)
    # An SD data item ends at a blank line; keep each value on its lines.
    return "\n".join(line for line in text.splitlines() if line.strip()) or ""


class ChemistryExporter(BaseExporter):
    format_name = "chemistry"
    description = ("Chemical structures (CSV with SMILES / InChIKey, SD file) and atoms "
                   "selected on molecule displays")
    file_extensions = [".csv", ".sdf"]

    @staticmethod
    def _structure_schemes(context: ExportContext) -> Dict[str, dict]:
        return {s["name"]: s for s in context.schemas or []
                if s.get("annotation_type") == "chemical_structure"}

    @staticmethod
    def _atom_schemes(context: ExportContext) -> Dict[str, str]:
        fields = ((context.config or {}).get("instance_display") or {}).get("fields") or []
        molecule_fields = {str(f.get("key")) for f in fields
                           if isinstance(f, dict) and f.get("type") == "molecule"}
        return {s["name"]: s.get("viewer_field") for s in context.schemas or []
                if s.get("annotation_type") == "viewer_selection"
                and s.get("viewer_field") in molecule_fields}

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not (self._structure_schemes(context) or self._atom_schemes(context)):
            return False, "No chemical_structure scheme or molecule atom selection in this project"
        if not context.annotations:
            return False, "No annotations to export"
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        from potato.chemistry import PY_EXTRA_HINT, rdkit_python
        from potato.chemistry.structures import grade, parse_stored, server_identifiers
        os.makedirs(output_path, exist_ok=True)
        schemes = self._structure_schemes(context)
        atom_schemes = self._atom_schemes(context)
        have_rdkit = rdkit_python() is not None
        rows: List[Dict[str, Any]] = []
        molfiles: List[Tuple[str, Dict[str, Any]]] = []
        atoms: List[Dict[str, Any]] = []
        warnings: List[str] = []

        for ann in context.annotations:
            uid, iid = str(ann.get("user_id", "")), str(ann.get("instance_id", ""))
            labels = ann.get("labels") or {}
            for name, scheme in schemes.items():
                answer = parse_stored(labels.get(name))
                if not answer.get("molfile") and not answer.get("smiles"):
                    continue
                source = "browser" if answer.get("inchikey") else "none"
                ids = {k: answer.get(k, "") for k in ("rdkit_smiles", "inchi", "inchikey")}
                if source == "none" and have_rdkit:
                    computed = server_identifiers(answer)
                    if computed:
                        ids.update(computed)
                        source = "server"
                row = {"user_id": uid, "instance_id": iid, "schema": name,
                       "smiles": answer.get("smiles", ""), **ids,
                       "idcode": answer.get("idcode", ""), "formula": answer.get("formula", ""),
                       "changed": "" if "changed" not in answer else int(bool(answer["changed"])),
                       "problems": " | ".join(answer.get("problems") or []),
                       "identifiers_from": source, "answer_correct": "", "answer_reason": ""}
                field = scheme.get("answer_field")
                if field:
                    item = context.items.get(iid) or {}
                    key = item.get(field) if isinstance(item, dict) else None
                    if key in (None, ""):
                        row["answer_reason"] = "this item has no answer key"
                    else:
                        ok, reason = grade(answer, key)
                        row["answer_correct"] = int(ok)
                        row["answer_reason"] = reason
                rows.append(row)
                if answer.get("molfile"):
                    molfiles.append((answer["molfile"], row))
            for name, viewer_field in atom_schemes.items():
                raw = labels.get(name)
                if isinstance(raw, dict) and len(raw) == 1:
                    raw = next(iter(raw.values()))
                try:
                    sel = json.loads(raw) if isinstance(raw, str) else raw
                except ValueError:
                    continue
                if not isinstance(sel, dict) or sel.get("viewer") not in (None, "molecule"):
                    continue
                for item in sel.get("items") or []:
                    if not isinstance(item, dict) or not isinstance(item.get("atom"), int):
                        continue
                    atoms.append({"user_id": uid, "instance_id": iid, "schema": name,
                                  "viewer_field": viewer_field, "atom": item["atom"],
                                  "number": item["atom"] + 1, "element": item.get("element", ""),
                                  "label": item.get("label", "")})

        if any(r["identifiers_from"] == "none" for r in rows):
            warnings.append(
                "Some answers have no InChI/InChIKey: RDKit.js was not loaded in the browser "
                + ("and RDKit could not read the structure."
                   if have_rdkit else f"and the rdkit package is not installed ({PY_EXTRA_HINT})."))
        if any(s.get("answer_field") for s in schemes.values()) and not have_rdkit:
            warnings.append(f"Answer keys were graded without the rdkit package; only InChIKey "
                            f"keys against browser InChIKeys can match ({PY_EXTRA_HINT}).")

        files: List[str] = []
        if schemes:
            path = os.path.join(output_path, "chemical_structures.csv")
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=STRUCTURE_COLUMNS, extrasaction="ignore")
                w.writeheader()
                for r in rows:
                    w.writerow(r)
            files.append(path)
            path = os.path.join(output_path, "chemical_structures.sdf")
            with open(path, "w", encoding="utf-8") as f:
                for molfile, row in molfiles:
                    block = molfile.rstrip("\n")
                    if "M  END" not in block:
                        continue
                    f.write(block[:block.rindex("M  END") + len("M  END")] + "\n")
                    for col in STRUCTURE_COLUMNS:
                        value = _sd_value(row.get(col))
                        if value != "":
                            f.write(f">  <{col}>\n{value}\n\n")
                    f.write("$$$$\n")
            files.append(path)
        if atom_schemes:
            path = os.path.join(output_path, "molecule_atoms.csv")
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=ATOM_COLUMNS, extrasaction="ignore")
                w.writeheader()
                for r in atoms:
                    w.writerow(r)
            files.append(path)

        if not rows and not atoms:
            return ExportResult(success=False, format_name=self.format_name,
                                errors=["No chemical structures or molecule atom selections "
                                        "have been annotated yet"], warnings=warnings)
        return ExportResult(success=True, format_name=self.format_name, files_written=files,
                            warnings=warnings,
                            stats={"num_structures": len(rows), "num_atoms": len(atoms)})
