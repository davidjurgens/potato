"""
Interval labels on a signal (``annotation_type: interval_label``).

Labels time intervals and point events on a ``time_series`` display named by
``signal_field``. Two modes:

``free``   pick a label (button or key), drag across the plot to label an
           interval, or click to mark a point event (labels with
           ``kind: event``). Intervals apply to all channels or, with
           ``channel_scope: channel`` (or ``either`` and the toggle), to the
           channel where the drag started.
``epoch``  the recording is cut into ``epoch_length``-second windows shown
           one at a time; a label key labels the current epoch and moves to
           the next (``auto_advance``). The display's overview strip shows
           which epochs are labelled; click it to jump.

The answer is one hidden input holding JSON, times in seconds (or the
recording's own time unit)::

    {"intervals": [{"start": 30.0, "end": 60.0, "label": "N2", "channel": null}],
     "events":    [{"time": 41.25, "label": "arousal", "channel": "C3-A2"}]}

``channel`` is a channel name, or null for all channels. Entries that came
from the file's own annotations and were not changed carry
``"source": "file"``.

Pre-annotations (EDF+ annotations, a WFDB ``.atr`` file, a BIDS
``events.tsv`` named by ``preannotation_field``) are shown when the stored
answer is empty, and are saved with the annotator's first change or when
they press "Keep these". ``preannotation_labels`` renames file labels to
scheme labels.
"""

from __future__ import annotations

import json
import logging
import math
import re
from typing import Any, Dict, List, Tuple

from .identifier_utils import (
    escape_html_content, generate_element_identifier, generate_layout_attributes,
    generate_validation_attribute, safe_generate_layout)

logger = logging.getLogger(__name__)

MODES = ("free", "epoch")
CHANNEL_SCOPES = ("all", "channel", "either")
LABEL_KINDS = ("interval", "event")
LABEL_KEYS = {"name", "key_value", "color", "kind", "tooltip", "description"}
#: Okabe-Ito colours (distinguishable with the common colour-vision
#: deficiencies), in label order.
LABEL_COLOURS = ("#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#56B4E9",
                 "#8C6D1F", "#6C757D", "#F0E442")
DEFAULT_KEYS = list("123456789") + list("qwertyuiop")
#: Keys the scheme itself uses; a label may not take them.
RESERVED_KEYS = {"Delete", "Backspace", "Escape", "PageUp", "PageDown", "Home", "End",
                 "ArrowLeft", "ArrowRight", "+", "-", "="}
_COLOUR = re.compile(r"^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$")


def labels_of(scheme: Dict[str, Any]) -> List[Dict[str, str]]:
    """Labels with their key, colour and kind filled in."""
    out = []
    used = set()
    explicit = {str(lab["key_value"]) for lab in scheme.get("labels") or []
                if isinstance(lab, dict) and lab.get("key_value") is not None}
    reserved = {str(scheme.get("next_key", "]")), str(scheme.get("previous_key", "["))}
    pool = [k for k in DEFAULT_KEYS if k not in explicit and k not in reserved]
    for i, item in enumerate(scheme.get("labels") or []):
        lab = item if isinstance(item, dict) else {"name": item}
        key = lab.get("key_value")
        key = str(key) if key is not None else None
        if key is None:
            while pool and pool[0] in used:
                pool.pop(0)
            key = pool.pop(0) if pool else ""
        if key in used:
            logger.warning("interval_label '%s': key %s is used by two labels; the second "
                           "one has no key", scheme.get("name"), key)
            key = ""
        if key:
            used.add(key)
        out.append({
            "name": str(lab["name"]),
            "key": key,
            "color": str(lab.get("color") or LABEL_COLOURS[i % len(LABEL_COLOURS)]),
            "kind": str(lab.get("kind") or "interval"),
            "tooltip": str(lab.get("tooltip") or lab.get("description") or ""),
        })
    return out


def validate_binding(config: Dict[str, Any]) -> List[str]:
    """Each interval_label scheme's signal_field names a time_series display field."""
    fields = ((config or {}).get("instance_display") or {}).get("fields") or []
    by_key = {str(f.get("key")): f for f in fields if isinstance(f, dict)}
    errors = []
    schemes = (config or {}).get("annotation_schemes") or []
    for i, scheme in enumerate(schemes if isinstance(schemes, list) else []):
        if not isinstance(scheme, dict) or scheme.get("annotation_type") != "interval_label":
            continue
        target = scheme.get("signal_field")
        if not isinstance(target, str) or not target:
            continue
        field = by_key.get(target)
        if field is None or field.get("type") != "time_series":
            known = ", ".join(sorted(k for k, f in by_key.items() if f.get("type") == "time_series"))
            errors.append(f"annotation_schemes[{i}].signal_field '{target}' does not name a "
                          f"time_series display field in instance_display "
                          f"(time_series fields: {known or 'none'})")
    return errors


def validate_scheme(scheme: Dict[str, Any], path: str) -> List[str]:
    """Problems with one interval_label scheme, on its own. Whether
    ``signal_field`` names a time_series field is checked at load by
    validate_binding()."""
    errors: List[str] = []
    field = scheme.get("signal_field")
    if not isinstance(field, str) or not field:
        errors.append(f"{path}.signal_field must name the instance_display field "
                      f"(type: time_series) to label")
    labels = scheme.get("labels")
    if not isinstance(labels, list) or not labels:
        errors.append(f"{path}.labels must be a non-empty list")
        labels = []
    names = set()
    for n, lab in enumerate(labels):
        where = f"{path}.labels[{n}]"
        if isinstance(lab, bool) or isinstance(lab, (int, float)):
            errors.append(f"{where} must be text (YAML reads yes/no/on/off as true/false; "
                          f"quote it)")
            continue
        if isinstance(lab, dict):
            extra = sorted(set(lab) - LABEL_KEYS)
            if extra:
                errors.append(f"{where} has unknown key(s) {', '.join(extra)}; "
                              f"accepted: {', '.join(sorted(LABEL_KEYS))}")
            name = lab.get("name")
            if lab.get("kind", "interval") not in LABEL_KINDS:
                errors.append(f"{where}.kind must be interval or event")
            if "color" in lab and not (isinstance(lab["color"], str) and _COLOUR.match(lab["color"])):
                errors.append(f"{where}.color must be a hex colour such as #0072B2")
            kv = lab.get("key_value")
            if kv is not None:
                if isinstance(kv, bool) or not isinstance(kv, (str, int)) or len(str(kv)) != 1:
                    errors.append(f"{where}.key_value must be one character")
                elif str(kv) in RESERVED_KEYS:
                    errors.append(f"{where}.key_value '{kv}' is used to move and zoom")
        elif isinstance(lab, str):
            name = lab
        else:
            errors.append(f"{where} must be a label name or a mapping with name")
            continue
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{where} needs a name")
            continue
        if name in names:
            errors.append(f"{where}: label '{name}' appears twice")
        names.add(name)
    mode = scheme.get("mode", "free")
    if mode not in MODES:
        errors.append(f"{path}.mode must be free or epoch")
    el = scheme.get("epoch_length", 30)
    if isinstance(el, bool) or not isinstance(el, (int, float)) or not math.isfinite(el) or el <= 0:
        errors.append(f"{path}.epoch_length must be a positive number of seconds")
    if scheme.get("channel_scope", "all") not in CHANNEL_SCOPES:
        errors.append(f"{path}.channel_scope must be one of {', '.join(CHANNEL_SCOPES)}")
    for key in ("auto_advance", "allow_overlap", "pre_annotations", "require_all_epochs"):
        if key in scheme and not isinstance(scheme[key], bool):
            errors.append(f"{path}.{key} must be true or false")
    for key in ("next_key", "previous_key"):
        v = scheme.get(key)
        if v is not None and (not isinstance(v, str) or len(v) != 1 or v in RESERVED_KEYS):
            errors.append(f"{path}.{key} must be one character (not one used to move or zoom)")
    if scheme.get("next_key", "]") == scheme.get("previous_key", "["):
        errors.append(f"{path}.next_key and previous_key must differ")
    nav = {scheme.get("next_key", "]"), scheme.get("previous_key", "[")}
    for n, lab in enumerate(labels):
        if isinstance(lab, dict) and lab.get("key_value") is not None and str(lab["key_value"]) in nav:
            errors.append(f"{path}.labels[{n}].key_value '{lab['key_value']}' is the next/previous key")
    mi = scheme.get("min_annotations")
    if mi is not None and (isinstance(mi, bool) or not isinstance(mi, int) or mi < 0):
        errors.append(f"{path}.min_annotations must be a whole number, 0 or more")
    pf = scheme.get("preannotation_field")
    if pf is not None and (not isinstance(pf, str) or not pf):
        errors.append(f"{path}.preannotation_field must be the name of an item field")
    pl = scheme.get("preannotation_labels")
    if pl is not None:
        if not isinstance(pl, dict):
            errors.append(f"{path}.preannotation_labels must map file labels to scheme labels")
        else:
            for k, v in pl.items():
                if v is not None and str(v) not in names:
                    errors.append(f"{path}.preannotation_labels maps '{k}' to '{v}', which is "
                                  f"not one of the labels")
    if scheme.get("require_all_epochs") and mode != "epoch":
        errors.append(f"{path}.require_all_epochs applies to mode: epoch only")
    instr = scheme.get("instructions")
    if instr is not None and not isinstance(instr, str):
        errors.append(f"{path}.instructions must be text")
    return errors


def generate_interval_label_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    schema_name = annotation_scheme["name"]
    errors = validate_scheme(annotation_scheme, schema_name)
    if errors:
        raise ValueError("; ".join(errors))
    labels = labels_of(annotation_scheme)
    mode = annotation_scheme.get("mode", "free")
    esc = escape_html_content(schema_name)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")
    validation = generate_validation_attribute(annotation_scheme)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    instructions = annotation_scheme.get("instructions", "")
    cfg = {
        "schema": schema_name,
        "signalField": annotation_scheme["signal_field"],
        "mode": mode,
        "epochLength": float(annotation_scheme.get("epoch_length", 30)),
        "labels": labels,
        "channelScope": annotation_scheme.get("channel_scope", "all"),
        "autoAdvance": bool(annotation_scheme.get("auto_advance", True)),
        "allowOverlap": bool(annotation_scheme.get("allow_overlap", mode != "epoch")),
        "nextKey": annotation_scheme.get("next_key", "]"),
        "previousKey": annotation_scheme.get("previous_key", "["),
        "preAnnotations": bool(annotation_scheme.get("pre_annotations", True))
                          or bool(annotation_scheme.get("preannotation_field")),
        "requireAllEpochs": bool(annotation_scheme.get("require_all_epochs", False)),
        "minAnnotations": int(annotation_scheme.get("min_annotations") or 0),
    }
    buttons = []
    for lab in labels:
        key = f'<kbd class="il-key">{escape_html_content(lab["key"])}</kbd>' if lab["key"] else ""
        title = f' title="{escape_html_content(lab["tooltip"])}"' if lab["tooltip"] else ""
        kind = " (event)" if lab["kind"] == "event" else ""
        buttons.append(
            f'<button type="button" class="il-label" data-label="{escape_html_content(lab["name"])}" '
            f'data-kind="{lab["kind"]}" aria-pressed="false"{title}>'
            f'<span class="il-swatch" style="background:{escape_html_content(lab["color"])}" aria-hidden="true"></span>'
            f'{key}<span class="il-name">{escape_html_content(lab["name"])}</span>'
            f'<span class="il-kind">{kind}</span></button>')
    scope = ""
    if cfg["channelScope"] == "either":
        scope = (
            f'<div class="il-scope" role="radiogroup" aria-label="New labels apply to">'
            f'<span class="il-scope-title">Apply to</span>'
            f'<label><input type="radio" name="il-scope-{esc}" value="all" checked> all channels</label>'
            f'<label><input type="radio" name="il-scope-{esc}" value="channel"> the channel I drag on</label>'
            f'</div>')
    epoch = ""
    if mode == "epoch":
        epoch = ('<div class="il-epoch" aria-live="polite">'
                 '<button type="button" class="il-step" data-step="-1" aria-label="Previous epoch">&#8249;</button>'
                 '<span class="il-epoch-text">Epoch</span>'
                 '<button type="button" class="il-step" data-step="1" aria-label="Next epoch">&#8250;</button>'
                 '<button type="button" class="il-clear-epoch">Clear this epoch</button>'
                 '</div>')
    nk, pk = escape_html_content(cfg["nextKey"]), escape_html_content(cfg["previousKey"])
    if mode == "epoch":
        keys_help = (f"Keys: a label key labels this epoch{' and moves on' if cfg['autoAdvance'] else ''}; "
                     f"{pk} / {nk} or Page Up / Page Down move between epochs; "
                     f"Delete clears the selected entry.")
    else:
        keys_help = (f"Keys: a label key picks the label; drag on the plot to label an interval, "
                     f"click to mark an event; {pk} / {nk} or Page Up / Page Down move one window; "
                     f"Delete removes the selected entry; Escape deselects.")
    keybindings = [(lab["key"], f"{schema_name}: {lab['name']}") for lab in labels if lab["key"]]
    keybindings += [(cfg["previousKey"], f"{schema_name}: previous window"),
                    (cfg["nextKey"], f"{schema_name}: next window")]
    html = f"""
    <form id="{esc}" class="annotation-form interval-label" action="javascript:void(0)"
          data-annotation-type="interval_label" data-schema-name="{esc}"
          data-il-config='{escape_html_content(json.dumps(cfg))}' {layout_attrs}>
        <fieldset schema="{esc}">
            <legend class="il-title">{escape_html_content(annotation_scheme["description"])}</legend>
            {f'<p class="il-instructions">{escape_html_content(instructions)}</p>' if instructions else ''}
            <div class="il-labels" role="toolbar" aria-label="Labels">{''.join(buttons)}</div>
            {scope}
            {epoch}
            <p class="il-pre" hidden>
                <span class="il-pre-text"></span>
                <button type="button" class="il-keep">Keep these</button>
                <button type="button" class="il-discard">Discard them</button>
            </p>
            <p class="il-message" role="status" aria-live="polite"></p>
            <div class="il-list-wrap">
                <table class="il-list">
                    <caption class="il-list-caption">Labelled intervals and events</caption>
                    <thead><tr><th scope="col">Time</th><th scope="col">Label</th>
                        <th scope="col">Channel</th><th scope="col"><span class="il-sr">Actions</span></th></tr></thead>
                    <tbody></tbody>
                </table>
                <p class="il-empty">Nothing labelled yet.</p>
            </div>
            <p class="il-keys">{keys_help}</p>
            <input type="hidden" class="annotation-input interval-label-input"
                   id="{identifiers['id']}" name="{identifiers['name']}"
                   schema="{identifiers['schema']}" label_name="{identifiers['label_name']}"
                   validation="{validation}" value="">
        </fieldset>
    </form>
    """
    return html, keybindings
