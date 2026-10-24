"""
Belief elicitation (``annotation_type: belief_elicitation``).

Two modes:

``point`` (default)
    The probability, 0 to 100, that an event happens, set on a slider.
    Stored as ``{"report": 70}``.

``bins``
    A distribution: the participant spreads 100 points over the ``bins``
    (for example ranges of a quantity). Stored as ``{"bins": [10, 40, ...]}``,
    one entry per bin. The page shows the running total and reports the
    question incomplete until it is exactly 100.

``potato/incentives.py`` pays these with the binarized scoring rule (rule
``method: bsr``) once the true outcome is known.
"""

import json
from typing import Any, Dict, List, Tuple

from .identifier_utils import (
    escape_html_content, generate_element_identifier, generate_layout_attributes,
    generate_validation_attribute, safe_generate_layout)

MODES = ("point", "bins")
TOTAL = 100


def validate_belief_elicitation(scheme: Dict[str, Any]) -> None:
    """Raise ValueError naming the first problem."""
    mode = scheme.get("mode", "point")
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}, got {mode!r}")
    bins = scheme.get("bins")
    if mode == "bins":
        if (not isinstance(bins, list) or len(bins) < 2
                or not all(isinstance(b, (str, int, float)) and not isinstance(b, bool)
                           and str(b).strip() for b in bins)):
            raise ValueError("mode: bins needs `bins`, a list of at least two bin labels")
        if len({str(b) for b in bins}) != len(bins):
            raise ValueError("bin labels must be distinct")
    elif bins is not None:
        raise ValueError("`bins` applies to mode: bins only")
    step = scheme.get("step")
    if step is not None:
        if mode != "point":
            raise ValueError("`step` applies to mode: point only")
        if isinstance(step, bool) or not isinstance(step, (int, float)) or step <= 0 or step > 50:
            raise ValueError("step must be a number between 0 and 50, such as 1 or 5")
    for key in ("left_label", "right_label"):
        if key in scheme:
            if mode != "point":
                raise ValueError(f"`{key}` applies to mode: point only")
            if not isinstance(scheme[key], str):
                raise ValueError(f"{key} must be text")


def generate_belief_elicitation_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    validate_belief_elicitation(annotation_scheme)
    name = annotation_scheme["name"]
    esc = escape_html_content(name)
    ids = generate_element_identifier(name, name, "hidden")
    validation = generate_validation_attribute(annotation_scheme)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    instructions = annotation_scheme.get("instructions", "")
    mode = annotation_scheme.get("mode", "point")
    entry_id = f"{ids['id']}_entry"

    if mode == "point":
        step = annotation_scheme.get("step", 1)
        left = annotation_scheme.get("left_label", "Certainly not")
        right = annotation_scheme.get("right_label", "Certainly")
        config = {"mode": "point", "step": step}
        body = f"""
            <div class="be-point">
                <label class="be-label" for="{entry_id}">Probability (0 to 100%)</label>
                <div class="be-slider-row">
                    <input type="range" class="be-slider" id="{entry_id}" min="0" max="100" step="{step:g}"
                           value="50" aria-valuetext="not set">
                    <output class="be-value" for="{entry_id}">&ndash;</output>
                </div>
                <div class="be-ends" aria-hidden="true">
                    <span>0% &middot; {escape_html_content(left)}</span>
                    <span>{escape_html_content(right)} &middot; 100%</span>
                </div>
            </div>"""
    else:
        bins = [str(b) for b in annotation_scheme["bins"]]
        config = {"mode": "bins", "bins": len(bins), "total": TOTAL}
        rows = "".join(
            f'<div class="be-bin" data-bin="{i}">'
            f'<label class="be-bin-label" for="{entry_id}_{i}">{escape_html_content(b)}</label>'
            f'<input type="number" class="be-bin-input" id="{entry_id}_{i}" data-bin="{i}" '
            f'min="0" max="{TOTAL}" step="1" inputmode="numeric" autocomplete="off" placeholder="0">'
            f'<span class="be-bar" aria-hidden="true"><span class="be-bar-fill"></span></span>'
            f'</div>'
            for i, b in enumerate(bins))
        body = f"""
            <div class="be-bins" role="group" aria-label="Points per range">{rows}</div>
            <p class="be-total" aria-live="polite">
                Total: <strong class="be-sum">0</strong> of {TOTAL}
                <span class="be-left"></span>
            </p>"""

    html = f"""
    <form id="{esc}" class="annotation-form belief-elicitation incentive-widget" action="javascript:void(0)"
          data-annotation-type="belief_elicitation" data-schema-name="{esc}"
          data-belief='{escape_html_content(json.dumps(config))}' {layout_attrs}>
        <fieldset schema="{esc}">
            <legend class="iw-title">{escape_html_content(annotation_scheme["description"])}</legend>
            {f'<p class="iw-instructions">{escape_html_content(instructions)}</p>' if instructions else ''}
            {body}
            <p class="iw-status" aria-live="polite"></p>
            <input type="hidden" class="annotation-input incentive-input"
                   id="{ids['id']}" name="{ids['name']}"
                   schema="{ids['schema']}" label_name="{ids['label_name']}"
                   validation="{validation}" value="">
        </fieldset>
    </form>
    """
    return html, []
