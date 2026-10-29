"""
Peak picking scheme (``annotation_type: peak_picking``).

Records peaks and integrated regions picked on a ``spectrum`` display. The
scheme names the display field with ``viewer_field`` and works through the
same browser API as ``viewer_selection`` (``window.potatoViewers[field]``):
the display owns the plot and the clicks, this scheme lists what was picked,
lets the annotator review suggested peaks, and gives each peak and region
its own fields (an assignment, a multiplicity).

The answer is one hidden input holding the display's selection as JSON::

    {"viewer": "spectrum",
     "items": [{"kind": "peak", "x": 4.12, "y": 812.0, "source": "auto",
                "fields": {"assignment": "OCH2", "multiplicity": "q"}},
               {"kind": "region", "from": 4.05, "to": 4.19, "integral": 41.7,
                "fields": {"label": "OCH2"}}],
     "rejected": [0.88]}

Options:

``peak_fields``     fields per peak: ``[{name, type: text|choice, options,
                    required, placeholder}]``. Default one text field, label.
``region_fields``   the same for integrated regions.
``min_peaks``       the item is incomplete until this many peaks are picked.
``max_peaks``       picking more is refused, with a message.
``require_review``  the item is incomplete until every suggested peak has
                    been accepted or rejected.
``allow_manual``    false: peaks can only come from the suggestions.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Tuple

from .identifier_utils import (
    escape_html_content, generate_element_identifier, generate_layout_attributes,
    generate_validation_attribute, safe_generate_layout)

FIELD_TYPES = ("text", "choice")
FIELD_KEYS = {"name", "type", "options", "required", "placeholder", "label"}
DEFAULT_FIELDS = [{"name": "label", "type": "text"}]
_FIELD_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]{0,63}$")


def fields_of(scheme: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    """Normalised field list for ``peak_fields`` / ``region_fields``."""
    raw = scheme.get(key)
    if raw is None:
        raw = DEFAULT_FIELDS
    out = []
    for f in raw if isinstance(raw, list) else []:
        if isinstance(f, str):
            f = {"name": f}
        if not isinstance(f, dict) or not isinstance(f.get("name"), str):
            continue
        entry = {"name": f["name"], "type": f.get("type") or ("choice" if f.get("options") else "text"),
                 "label": str(f.get("label") or f["name"].replace("_", " ").capitalize()),
                 "required": bool(f.get("required", False))}
        if entry["type"] == "choice":
            entry["options"] = [str(o) for o in f.get("options") or []]
        if f.get("placeholder"):
            entry["placeholder"] = str(f["placeholder"])
        out.append(entry)
    return out


def _validate_fields(value: Any, path: str) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        return [f"{path} must be a list of fields ({{name, type: text|choice, options}})"]
    errors, names = [], []
    for n, f in enumerate(value):
        where = f"{path}[{n}]"
        if isinstance(f, str):
            f = {"name": f}
        if not isinstance(f, dict):
            errors.append(f"{where} must be a mapping with a name")
            continue
        extra = sorted(set(f) - FIELD_KEYS)
        if extra:
            errors.append(f"{where} has unknown key(s) {', '.join(extra)}; "
                          f"accepted: {', '.join(sorted(FIELD_KEYS))}")
        name = f.get("name")
        if not isinstance(name, str) or not _FIELD_NAME.match(name):
            errors.append(f"{where}.name must be a short identifier (letters, digits, _ or -)")
        else:
            names.append(name)
        ftype = f.get("type") or ("choice" if f.get("options") else "text")
        if ftype not in FIELD_TYPES:
            errors.append(f"{where}.type must be text or choice")
        if ftype == "choice":
            opts = f.get("options")
            if not isinstance(opts, list) or not opts:
                errors.append(f"{where}.options must be a non-empty list for a choice field")
            elif any(isinstance(o, bool) or not isinstance(o, (str, int, float)) for o in opts):
                errors.append(f"{where}.options must be text. YAML reads bare yes/no/on/off "
                              f"as true/false; quote them.")
        elif "options" in f:
            errors.append(f"{where}.options is only used with type: choice")
        if "required" in f and not isinstance(f["required"], bool):
            errors.append(f"{where}.required must be true or false")
    dupes = sorted({x for x in names if names.count(x) > 1})
    if dupes:
        errors.append(f"{path} repeats {', '.join(dupes)}")
    return errors


def validate_scheme(scheme: Dict[str, Any], path: str) -> List[str]:
    """Problems with one peak_picking scheme, on its own."""
    errors = []
    field = scheme.get("viewer_field")
    if not isinstance(field, str) or not field.strip():
        errors.append(f"{path}.viewer_field must name the instance_display field of a "
                      f"spectrum display")
    errors += _validate_fields(scheme.get("peak_fields"), f"{path}.peak_fields")
    errors += _validate_fields(scheme.get("region_fields"), f"{path}.region_fields")
    lo, hi = scheme.get("min_peaks"), scheme.get("max_peaks")
    for key, value in (("min_peaks", lo), ("max_peaks", hi)):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            errors.append(f"{path}.{key} must be a whole number (0 or more)")
    if isinstance(lo, int) and isinstance(hi, int) and not isinstance(lo, bool) \
            and not isinstance(hi, bool) and hi < lo:
        errors.append(f"{path}.max_peaks ({hi}) is below min_peaks ({lo})")
    if hi == 0:
        errors.append(f"{path}.max_peaks of 0 would refuse every peak")
    for key in ("require_review", "allow_manual"):
        if key in scheme and not isinstance(scheme[key], bool):
            errors.append(f"{path}.{key} must be true or false")
    return errors


def iter_peak_picking_schemes(config: Dict[str, Any]) -> Iterable[Tuple[str, Dict[str, Any]]]:
    schemes = (config or {}).get("annotation_schemes") or []
    if isinstance(schemes, list):
        for i, s in enumerate(schemes):
            if isinstance(s, dict) and s.get("annotation_type") == "peak_picking":
                yield f"annotation_schemes[{i}]", s


def validate_binding(config: Dict[str, Any]) -> List[str]:
    """Each peak_picking scheme's viewer_field names a spectrum display field."""
    fields = ((config or {}).get("instance_display") or {}).get("fields") or []
    spectra = {str(f.get("key")): f for f in fields if isinstance(f, dict)}
    errors = []
    for path, scheme in iter_peak_picking_schemes(config):
        target = scheme.get("viewer_field")
        if not isinstance(target, str) or not target:
            continue
        field = spectra.get(target)
        if field is None or field.get("type") != "spectrum":
            known = ", ".join(sorted(k for k, f in spectra.items() if f.get("type") == "spectrum"))
            errors.append(f"{path}.viewer_field '{target}' does not name a spectrum display "
                          f"field in instance_display (spectrum fields: {known or 'none'})")
    return errors


def generate_peak_picking_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
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
    config = {
        "schema": schema_name,
        "viewerField": annotation_scheme["viewer_field"],
        "peakFields": fields_of(annotation_scheme, "peak_fields"),
        "regionFields": fields_of(annotation_scheme, "region_fields"),
        "minPeaks": annotation_scheme.get("min_peaks"),
        "maxPeaks": annotation_scheme.get("max_peaks"),
        "requireReview": bool(annotation_scheme.get("require_review", False)),
        "allowManual": annotation_scheme.get("allow_manual", True) is not False,
    }
    add_row = ""
    if config["allowManual"]:
        add_row = (
            f'<div class="pp-add">'
            f'<label class="pp-add-label" for="{esc}-add-x">Add a peak at</label>'
            f'<input type="text" inputmode="decimal" id="{esc}-add-x" class="pp-add-x" '
            f'autocomplete="off" aria-describedby="{esc}-add-hint">'
            f'<button type="button" class="pp-btn pp-add-btn">Add peak</button>'
            f'<span class="pp-add-hint" id="{esc}-add-hint"></span>'
            f'</div>')
    html = f"""
    <form id="{esc}" class="annotation-form peak-picking" action="javascript:void(0)"
          data-annotation-type="peak_picking" data-schema-name="{esc}"
          data-peak-config='{escape_html_content(json.dumps(config))}' {layout_attrs}>
        <fieldset schema="{esc}">
            <legend class="pp-title">{escape_html_content(annotation_scheme["description"])}</legend>
            {f'<p class="pp-instructions">{escape_html_content(instructions)}</p>' if instructions else ''}
            <section class="pp-suggestions" hidden aria-labelledby="{esc}-sugg-title">
                <div class="pp-section-head">
                    <h4 class="pp-section-title" id="{esc}-sugg-title">Suggested peaks</h4>
                    <span class="pp-sugg-count"></span>
                    <span class="pp-head-actions">
                        <button type="button" class="pp-btn pp-accept-all">Accept all</button>
                        <button type="button" class="pp-btn pp-reject-all">Reject all</button>
                    </span>
                </div>
                <ul class="pp-sugg-list"></ul>
                <p class="pp-rejected" hidden></p>
            </section>
            <section class="pp-peaks" aria-labelledby="{esc}-peaks-title">
                <div class="pp-section-head">
                    <h4 class="pp-section-title" id="{esc}-peaks-title">Peaks</h4>
                    <span class="pp-peak-count"></span>
                </div>
                <p class="pp-empty">No peaks picked yet.</p>
                <div class="pp-table-wrap"><table class="pp-table pp-peak-table" hidden>
                    <thead></thead><tbody></tbody></table></div>
            </section>
            <section class="pp-regions" hidden aria-labelledby="{esc}-regions-title">
                <div class="pp-section-head">
                    <h4 class="pp-section-title" id="{esc}-regions-title">Integrals</h4>
                </div>
                <div class="pp-table-wrap"><table class="pp-table pp-region-table">
                    <thead></thead><tbody></tbody></table></div>
            </section>
            {add_row}
            <p class="pp-message" role="status" aria-live="polite"></p>
            <input type="hidden" class="annotation-input peak-picking-input"
                   id="{identifiers['id']}" name="{identifiers['name']}"
                   schema="{identifiers['schema']}" label_name="{identifiers['label_name']}"
                   validation="{validation}" value="">
        </fieldset>
    </form>
    """
    return html, []


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
