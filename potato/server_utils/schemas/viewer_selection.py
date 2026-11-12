"""
Viewer selection schema (``annotation_type: viewer_selection``).

Stores what the annotator selected in a third-party viewer display: residues
in a ``protein_structure``, features and the locus in a ``genome_locus``. The
scheme names the display field with ``viewer_field`` and talks to it through
the browser API every viewer display exposes::

    window.potatoViewers[field].getSelection() / setSelection(sel)
                               .onSelectionChange(cb) / describe(sel)

The answer is one hidden input holding JSON::

    {"viewer": "protein_structure",
     "items": [{"chain": "A", "resi": 57, "resn": "HIS", "label": "binding site"}]}

    {"viewer": "genome_locus", "locus": "chr1:1450-1550",
     "items": [{"chr": "chr1", "start": 1500, "end": 1500, "kind": "variant",
                "name": "rs1", "ref": "A", "alt": "G", "track": "Calls"}]}

Each viewer's item shape is defined by :func:`viewer_display.validate_selection`.
The server does not run it on save: the JSON is stored as the browser sent it.
Call it to audit stored answers.

Options:

``labels``          label each selection ("binding site", "epitope"). The
                    annotator picks the label first; new selections take it.
``min_selections``  the item counts as incomplete until this many are chosen.
``max_selections``  selecting more is refused, with a message.

On load the stored JSON is handed back to the viewer (``setSelection``), so
the 3D view, the residue table and the list all show the saved state.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable, List, Tuple

from .identifier_utils import (
    escape_html_content, generate_element_identifier, generate_layout_attributes,
    generate_validation_attribute, safe_generate_layout)

logger = logging.getLogger(__name__)

#: Colours for labelled selections, in label order. Kept clear of the four
#: pLDDT band colours (blue, light blue, yellow, orange) so a selected residue
#: never reads as a confidence band, and dark enough for white text in the
#: residue table.
LABEL_COLOURS = ("#c2255c", "#2b8a3e", "#6741d9", "#8f5a2b", "#087f5b", "#a61e4d",
                 "#495057", "#5c940d")


def label_names(scheme: Dict[str, Any]) -> List[str]:
    out = []
    for item in scheme.get("labels") or []:
        name = item.get("name") if isinstance(item, dict) else item
        if isinstance(name, str) and name:
            out.append(name)
    return out


def _labels(scheme: Dict[str, Any]) -> List[Dict[str, str]]:
    out = []
    for i, item in enumerate(scheme.get("labels") or []):
        if isinstance(item, dict):
            name, colour = item.get("name"), item.get("color")
        else:
            name, colour = item, None
        out.append({"name": str(name),
                    "color": str(colour or LABEL_COLOURS[i % len(LABEL_COLOURS)])})
    return out


def validate_scheme(scheme: Dict[str, Any], path: str) -> List[str]:
    """Problems with one viewer_selection scheme, on its own."""
    errors = []
    field = scheme.get("viewer_field")
    if not isinstance(field, str) or not field.strip():
        errors.append(f"{path}.viewer_field must name the instance_display field of a "
                      f"viewer display (protein_structure, genome_locus)")
    labels = scheme.get("labels")
    if labels is not None:
        if not isinstance(labels, list) or not labels:
            errors.append(f"{path}.labels must be a non-empty list of names")
        else:
            names = []
            for n, item in enumerate(labels):
                name = item.get("name") if isinstance(item, dict) else item
                if isinstance(name, bool) or not isinstance(name, str) or not name.strip():
                    errors.append(
                        f"{path}.labels[{n}] must be a name (text). YAML reads bare "
                        f"yes/no/on/off as true/false; quote them.")
                else:
                    names.append(name)
                if isinstance(item, dict):
                    extra = sorted(set(item) - {"name", "color"})
                    if extra:
                        errors.append(f"{path}.labels[{n}] has unknown key(s) {', '.join(extra)}")
            dupes = sorted({x for x in names if names.count(x) > 1})
            if dupes:
                errors.append(f"{path}.labels repeats {', '.join(dupes)}")
    lo, hi = scheme.get("min_selections"), scheme.get("max_selections")
    for key, value in (("min_selections", lo), ("max_selections", hi)):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            errors.append(f"{path}.{key} must be a whole number (0 or more)")
    if isinstance(lo, int) and isinstance(hi, int) and not isinstance(lo, bool) \
            and not isinstance(hi, bool) and hi < lo:
        errors.append(f"{path}.max_selections ({hi}) is below min_selections ({lo})")
    if hi == 0:
        errors.append(f"{path}.max_selections of 0 would refuse every selection")
    return errors


def iter_viewer_selection_schemes(config: Dict[str, Any]) -> Iterable[Tuple[str, Dict[str, Any]]]:
    schemes = (config or {}).get("annotation_schemes") or []
    if isinstance(schemes, list):
        for i, s in enumerate(schemes):
            if isinstance(s, dict) and s.get("annotation_type") == "viewer_selection":
                yield f"annotation_schemes[{i}]", s


def parse_stored(value: Any) -> Dict[str, Any]:
    """A stored answer as an object (empty when there is none or it is not JSON)."""
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def generate_viewer_selection_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    schema_name = annotation_scheme["name"]
    problems = validate_scheme(annotation_scheme, schema_name)
    if problems:
        raise ValueError("; ".join(problems))
    esc = escape_html_content(schema_name)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")
    validation = generate_validation_attribute(annotation_scheme)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    instructions = annotation_scheme.get("instructions", "")
    labels = _labels(annotation_scheme)
    config = {
        "schema": schema_name,
        "viewerField": annotation_scheme["viewer_field"],
        "labels": labels,
        "minSelections": annotation_scheme.get("min_selections"),
        "maxSelections": annotation_scheme.get("max_selections"),
    }
    label_bar = ""
    if labels:
        buttons = "".join(
            f'<button type="button" class="vs-label" role="radio" '
            f'aria-checked="{"true" if i == 0 else "false"}" tabindex="{0 if i == 0 else -1}" '
            f'data-label="{escape_html_content(l["name"])}">'
            f'<span class="vs-swatch" style="background:{escape_html_content(l["color"])}" '
            f'aria-hidden="true"></span>{escape_html_content(l["name"])}</button>'
            for i, l in enumerate(labels))
        label_bar = (f'<div class="vs-labels" role="radiogroup" '
                     f'aria-label="Label for new selections">'
                     f'<span class="vs-labels-title" aria-hidden="true">New selections:</span>'
                     f'{buttons}</div>')
    html = f"""
    <form id="{esc}" class="annotation-form viewer-selection" action="javascript:void(0)"
          data-annotation-type="viewer_selection" data-schema-name="{esc}"
          data-selection-config='{escape_html_content(json.dumps(config))}' {layout_attrs}>
        <fieldset schema="{esc}">
            <legend class="vs-title">{escape_html_content(annotation_scheme["description"])}</legend>
            {f'<p class="vs-instructions">{escape_html_content(instructions)}</p>' if instructions else ''}
            {label_bar}
            <p class="vs-context" hidden></p>
            <p class="vs-empty">Nothing selected yet.</p>
            <ul class="vs-list" aria-label="Selected"></ul>
            <p class="vs-count"></p>
            <p class="vs-message" role="status" aria-live="polite"></p>
            <input type="hidden" class="annotation-input viewer-selection-input"
                   id="{identifiers['id']}" name="{identifiers['name']}"
                   schema="{identifiers['schema']}" label_name="{identifiers['label_name']}"
                   validation="{validation}" value="">
        </fieldset>
    </form>
    """
    return html, []
