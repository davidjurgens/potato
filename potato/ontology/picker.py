"""
Page markup for ontology-backed labels.

``picker_html(scheme)`` is the search box a generator puts in its form. The
browser half is ``static/ontology-picker.js``; it asks ``/api/ontology/search``
for matches and turns a picked term into an ordinary option of the scheme:

* radio / multiselect: a radio button or checkbox whose ``label_name`` is the
  term id and whose value is the term record as JSON
* span: a span-label chip whose label is the term id
* image_annotation: a ``.label-btn`` whose ``data-label`` is the term id

so saving, restoring, agreement and export treat it like any other label.

A picked term has no input in the cached page template, so before the
annotation page restores a user's answers, :func:`add_stored_term_inputs` adds
an input for each stored term; the existing restore walk then checks it.
``term_option_html`` is the one place the option markup is built on the
server; the JS builds the same markup.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

from potato.server_utils.schemas.identifier_utils import (
    escape_html_content,
    generate_validation_attribute,
)

from .source import (
    MIN_QUERY_LENGTH,
    encode_record,
    normalize_record,
)

logger = logging.getLogger(__name__)

PICKER_TYPES = ("radio", "multiselect", "span", "image_annotation")

#: Tableau 10, for image label buttons. The JS uses the same list and hash.
PALETTE = ["#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F",
           "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC"]

_CURIE = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-]*:[A-Za-z0-9_.\-]+$")


def fnv1a(text: str) -> int:
    h = 0x811C9DC5
    for b in text.encode("utf-8"):
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def term_color(obo_id: str) -> str:
    return PALETTE[fnv1a(obo_id) % len(PALETTE)]


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(text))


def _source_note(scheme: Dict[str, Any]) -> str:
    """'CL, version X' for a file source; the service name for OLS4."""
    ls = scheme.get("label_source") or {}
    name = str(ls.get("ontology", "")).upper()
    if ls.get("service") == "ols4":
        return f"{name} via OLS4"
    try:
        from potato.server_utils.config_module import config
        from .source import source_for_scheme
        version = source_for_scheme(scheme, config).version
    except Exception as e:  # unit tests without a loaded config, unreadable file
        logger.debug("No version for %s: %s", scheme.get("name"), e)
        version = ""
    return f"{name}, version {version}" if version else name


def picker_html(scheme: Dict[str, Any]) -> str:
    """The search box for a scheme with ``label_source``; '' for any other."""
    ls = scheme.get("label_source")
    atype = scheme.get("annotation_type")
    if not isinstance(ls, dict) or atype not in PICKER_TYPES:
        return ""
    name = str(scheme.get("name", ""))
    sid = "ontology-" + slug(name)
    e = escape_html_content
    onto = str(ls.get("ontology", "")).upper()
    fixed = [l for l in (scheme.get("labels") or []) if l]
    validation = ""
    sentinel = ""
    if atype in ("radio", "multiselect"):
        validation = generate_validation_attribute(scheme)
        if validation == "required" and not fixed:
            # A picker-only scheme has no inputs until a term is picked, so
            # nothing would tell the required check that it is unanswered.
            sentinel = ('<input type="hidden" class="ontology-required-sentinel" '
                        'validation="required" value="">')
    target_field = scheme.get("target_field", "") if atype == "span" else ""
    prompt = (f"Or search {onto} for another term" if fixed else f"Search {onto} terms")
    return f"""
            <div class="ontology-picker" data-ontology-picker="true"
                 data-schema="{e(name)}" data-annotation-type="{e(atype)}"
                 data-ontology="{e(onto)}" data-service="{e(ls.get('service', ''))}"
                 data-min-query="{MIN_QUERY_LENGTH}" data-validation="{e(validation)}"
                 data-target-field="{e(target_field)}">
                <label class="ontology-picker-label" for="{sid}-input">{e(prompt)}</label>
                <div class="ontology-picker-box">
                    <input type="search" id="{sid}-input" class="ontology-picker-input"
                           role="combobox" aria-autocomplete="list" aria-expanded="false"
                           aria-controls="{sid}-list" aria-describedby="{sid}-hint"
                           autocomplete="off" autocapitalize="none" spellcheck="false"
                           enterkeyhint="search"
                           placeholder="Name, synonym or id">
                    <ul id="{sid}-list" class="ontology-picker-results" role="listbox"
                        aria-label="Matching {e(onto)} terms" hidden></ul>
                </div>
                <p id="{sid}-hint" class="ontology-picker-hint"><span class="ontology-picker-keys">Up and Down move through the matches, Enter picks one, Escape closes the list. </span>Source: {e(_source_note(scheme))}.</p>
                <p class="ontology-picker-status" role="status" aria-live="polite"></p>
                {sentinel}
            </div>
    """


def term_option_html(atype: str, schema: str, record: Dict[str, str],
                     validation: str = "", checked: bool = False) -> str:
    """A radio or checkbox option for a picked term (mirrors the JS)."""
    e = escape_html_content
    obo_id = record["obo_id"]
    input_id = f"{slug(schema)}__onto__{slug(obo_id)}"
    value = e(encode_record(record))
    label_html = (f'<span class="ontology-term-label">{e(record.get("label") or obo_id)}</span> '
                  f'<span class="ontology-term-id">{e(obo_id)}</span>')
    checked_attr = " checked" if checked else ""
    if atype == "radio":
        return (
            f'<div class="shadcn-radio-option ontology-term-option" data-ontology-term="{e(obo_id)}">'
            f'<input class="{e(schema)} shadcn-radio-input annotation-input" type="radio" '
            f'id="{input_id}" name="{e(schema)}" value="{value}" selection_constraint="single" '
            f'schema="{e(schema)}" label_name="{e(obo_id)}" '
            f'onclick="onlyOne(this);registerAnnotation(this);" validation="{e(validation)}"{checked_attr}>'
            f'<label for="{input_id}" class="shadcn-radio-label">{label_html}</label></div>')
    return (
        f'<div class="shadcn-multiselect-item ontology-term-option" data-ontology-term="{e(obo_id)}">'
        f'<input class="{e(schema)} shadcn-multiselect-checkbox annotation-input" type="checkbox" '
        f'id="{input_id}" name="{e(schema)}:::{e(obo_id)}" value="{value}" '
        f'label_name="{e(obo_id)}" schema="{e(schema)}" '
        f'onclick="whetherNone(this);registerAnnotation(this)" validation="{e(validation)}"{checked_attr}>'
        f'<label for="{input_id}" schema="{e(schema)}" class="shadcn-multiselect-label">'
        f'{label_html}</label></div>')


def label_button_html(obo_id: str, label: str) -> str:
    """An image_annotation label button for a term (mirrors the JS)."""
    e = escape_html_content
    color = term_color(obo_id)
    text = label or obo_id
    return (f'<button type="button" class="label-btn ontology-term-btn" data-label="{e(obo_id)}" '
            f'data-color="{color}" aria-pressed="false" title="{e(text)} ({e(obo_id)})" '
            f'style="--label-color: {color};"><span class="label-color-dot" aria-hidden="true" '
            f'style="background-color: {color};"></span>{e(text)}</button>')


def _fragment(html: str):
    from bs4 import BeautifulSoup
    return BeautifulSoup(html, "html.parser")


def _stored_labels(annotations: Any, schema: str) -> Dict[str, Any]:
    if not isinstance(annotations, dict):
        return {}
    values = annotations.get(schema)
    return values if isinstance(values, dict) else {}


def add_stored_term_inputs(soup, annotations: Any, config_data: Optional[Dict[str, Any]] = None) -> int:
    """Give every stored ontology term an input to restore into.

    ``annotations`` is ``{schema: {label_name: value}}`` as the restore walk
    reads it. Returns how many elements were added. Never raises: a failure
    here must not stop the page rendering.
    """
    added = 0
    try:
        for picker in soup.find_all("div", attrs={"data-ontology-picker": "true"}):
            schema = picker.get("data-schema") or ""
            atype = picker.get("data-annotation-type") or ""
            form = picker.find_parent("form")
            stored = _stored_labels(annotations, schema)
            if form is None or not stored:
                continue
            if atype in ("radio", "multiselect"):
                added += _restore_options(form, picker, atype, schema, stored)
            elif atype == "image_annotation":
                added += _restore_label_buttons(form, schema, stored, config_data)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Could not prepare ontology terms for restore: %s", e)
    return added


def _restore_options(form, picker, atype, schema, stored) -> int:
    container = form.find(class_="shadcn-radio-options" if atype == "radio"
                          else "shadcn-multiselect-grid")
    if container is None:
        return 0
    have = {inp.get("label_name") for inp in form.find_all("input") if inp.get("label_name")}
    validation = picker.get("data-validation") or ""
    added = 0
    any_term = False
    for label_name, value in stored.items():
        record = normalize_record(value)
        if record is None or record["obo_id"] != label_name:
            continue
        any_term = True
        if label_name in have:
            continue
        container.append(_fragment(term_option_html(atype, schema, record, validation)))
        have.add(label_name)
        added += 1
    if any_term:
        sentinel = picker.find("input", class_="ontology-required-sentinel")
        if sentinel is not None:
            sentinel["value"] = "1"
    return added


def _restore_label_buttons(form, schema, stored, config_data) -> int:
    raw = stored.get("_data")
    try:
        shapes = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return 0
    if not isinstance(shapes, list):
        return 0
    group = form.find(class_="label-group")
    if group is None:
        return 0
    have = {b.get("data-label") for b in form.find_all(class_="label-btn")}
    wanted = []
    for shape in shapes:
        label = shape.get("label") if isinstance(shape, dict) else None
        if isinstance(label, str) and _CURIE.match(label) and label not in have:
            wanted.append(label)
            have.add(label)
    if not wanted:
        return 0
    source = None
    try:
        from potato.server_utils.config_module import config as global_config
        from .source import find_scheme, source_for_scheme
        cfg = config_data if config_data is not None else global_config
        scheme = find_scheme(cfg, schema)
        source = source_for_scheme(scheme, cfg) if scheme else None
    except Exception as e:
        logger.debug("No ontology source for %s: %s", schema, e)
    for obo_id in wanted:
        record = None
        if source is not None:
            try:
                record = source.get_term(obo_id)
            except Exception:
                record = None
        group.append(_fragment(label_button_html(obo_id, (record or {}).get("label", ""))))
    return len(wanted)
