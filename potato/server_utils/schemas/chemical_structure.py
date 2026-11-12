"""
Chemical structure schema (``annotation_type: chemical_structure``).

The annotator draws a structure, or corrects one the item supplies (an
optical structure recognition result shown beside the source image, or a
structure to check against a name). The editor is OpenChemLib's canvas
editor (committed, BSD-3-Clause). A SMILES string or a molfile can also be
pasted in, which is the keyboard route.

Stored answer: one hidden input holding JSON (see
:mod:`potato.chemistry.structures`): molfile V3000, the OpenChemLib
canonical SMILES and ID code, the formula, and, when RDKit.js is installed
(``potato vendor fetch rdkit``), the RDKit canonical SMILES, InChI and
InChIKey.

Options:

``prefill_field``    item field with a SMILES string or molfile (or a
                     ``.mol`` / ``.sdf`` / ``.smi`` file in the media
                     directory) the editor starts from. The untouched
                     structure is saved as the answer with ``changed: false``.
``prefill_format``   ``auto`` (default), ``smiles`` or ``molfile``.
``answer_field``     item field with an answer key, graded in the export with
                     the rdkit Python package. Never sent to the page.
``rdkit``            ``auto`` (default: use RDKit.js when it is installed),
                     ``true`` (require it; ``potato validate`` fails without
                     it) or ``false`` (OpenChemLib only).
``require_valid``    a structure with valence problems (or one RDKit cannot
                     sanitize) leaves the item incomplete. Default true.
``allow_empty``      an empty canvas is an acceptable answer. Default false.
``editor_height``    editor height in pixels (default 380, 240 to 900).
``show_identifiers`` show SMILES, formula and InChIKey under the editor.
                     Default true.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Tuple

from .identifier_utils import (
    escape_html_content, generate_element_identifier, generate_layout_attributes,
    generate_validation_attribute, safe_generate_layout)

logger = logging.getLogger(__name__)

PREFILL_FORMATS = ("auto", "smiles", "molfile")
DEFAULT_EDITOR_HEIGHT = 380


def validate_scheme(scheme: Dict[str, Any], path: str) -> List[str]:
    """Problems with one chemical_structure scheme."""
    errors = []
    for key in ("prefill_field", "answer_field"):
        if key in scheme and not (isinstance(scheme[key], str) and scheme[key].strip()):
            errors.append(f"{path}.{key} must be the name of an item field")
    if scheme.get("prefill_field") and scheme.get("prefill_field") == scheme.get("answer_field"):
        errors.append(f"{path}.answer_field must differ from prefill_field: the answer "
                      f"key is kept off the page, the prefill is shown on it")
    fmt = scheme.get("prefill_format", "auto")
    if fmt not in PREFILL_FORMATS:
        errors.append(f"{path}.prefill_format must be one of {', '.join(PREFILL_FORMATS)}, "
                      f"not {fmt!r}")
    if "prefill_format" in scheme and not scheme.get("prefill_field"):
        errors.append(f"{path}.prefill_format needs prefill_field")
    mode = scheme.get("rdkit", "auto")
    if not (mode == "auto" or isinstance(mode, bool)):
        errors.append(f"{path}.rdkit must be auto, true or false, not {mode!r}")
    for key in ("require_valid", "allow_empty", "show_identifiers"):
        if key in scheme and not isinstance(scheme[key], bool):
            errors.append(f"{path}.{key} must be true or false")
    height = scheme.get("editor_height", DEFAULT_EDITOR_HEIGHT)
    if isinstance(height, bool) or not isinstance(height, int) or not 240 <= height <= 900:
        errors.append(f"{path}.editor_height must be a whole number of pixels from 240 to 900")
    if "instructions" in scheme and not isinstance(scheme["instructions"], str):
        errors.append(f"{path}.instructions must be text")
    return errors


def generate_chemical_structure_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    from potato import chemistry
    schema_name = annotation_scheme["name"]
    problems = validate_scheme(annotation_scheme, schema_name)
    if problems:
        raise ValueError("; ".join(problems))
    esc = escape_html_content(schema_name)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")
    validation = generate_validation_attribute(annotation_scheme)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    instructions = annotation_scheme.get("instructions", "")
    mode = annotation_scheme.get("rdkit", "auto")
    rdkit = chemistry.rdkit_urls() if mode is not False else None
    height = int(annotation_scheme.get("editor_height", DEFAULT_EDITOR_HEIGHT))
    prefill = annotation_scheme.get("prefill_field")
    show_ids = annotation_scheme.get("show_identifiers", True)
    config = {
        "schema": schema_name,
        "oclUrl": chemistry.ocl_url(),
        "oclVersion": chemistry.OCL_VERSION,
        "rdkit": rdkit,
        "rdkitMode": mode,
        "prefillField": prefill or None,
        "prefillFormat": annotation_scheme.get("prefill_format", "auto"),
        "requireValid": annotation_scheme.get("require_valid", True),
        "allowEmpty": annotation_scheme.get("allow_empty", False),
    }
    dom = f"cs-{''.join(c if c.isalnum() else '-' for c in schema_name)}"
    reset = (f'<button type="button" class="cs-btn cs-reset" disabled>'
             f'Restore the given structure</button>' if prefill else "")
    readout = ""
    if show_ids:
        inchi_note = ("" if rdkit else
                      '<span class="cs-muted">needs RDKit.js (potato vendor fetch rdkit); '
                      'filled in at export when the rdkit package is installed</span>')
        readout = (
            f'<dl class="cs-readout" aria-label="Identifiers of the drawn structure">'
            f'<div><dt>SMILES</dt><dd class="cs-smiles cs-mono">–</dd></div>'
            f'<div><dt>Formula</dt><dd class="cs-formula">–</dd></div>'
            f'<div><dt>InChIKey</dt><dd class="cs-inchikey cs-mono">{inchi_note or "–"}</dd></div>'
            f'</dl>')
    html = f"""
    <form id="{esc}" class="annotation-form chemical-structure" action="javascript:void(0)"
          data-annotation-type="chemical_structure" data-schema-name="{esc}"
          data-chem-config='{escape_html_content(json.dumps(config))}' {layout_attrs}>
        <fieldset schema="{esc}">
            <legend class="cs-title">{escape_html_content(annotation_scheme["description"])}</legend>
            {f'<p class="cs-instructions">{escape_html_content(instructions)}</p>' if instructions else ''}
            <div class="cs-editor-wrap" style="height: {height}px">
                <div class="cs-editor" role="application"
                     aria-label="Structure editor: draw with the mouse, or paste a SMILES or molfile below"></div>
                <p class="cs-loading" role="status">Loading the structure editor…</p>
            </div>
            <div class="cs-row">
                <label class="cs-paste-label" for="{dom}-paste">SMILES or molfile</label>
                <textarea id="{dom}-paste" class="cs-paste cs-mono" rows="1" spellcheck="false"
                          autocomplete="off" placeholder="Paste or type, then Load"></textarea>
                <div class="cs-actions">
                    <button type="button" class="cs-btn cs-load">Load</button>
                    {reset}
                    <button type="button" class="cs-btn cs-clear">Clear</button>
                </div>
            </div>
            {readout}
            <p class="cs-problems" role="status" aria-live="polite"></p>
            <input type="hidden" class="annotation-input chemical-structure-input"
                   id="{identifiers['id']}" name="{identifiers['name']}"
                   schema="{identifiers['schema']}" label_name="{identifiers['label_name']}"
                   validation="{validation}" value="">
        </fieldset>
    </form>
    """
    return html, []
