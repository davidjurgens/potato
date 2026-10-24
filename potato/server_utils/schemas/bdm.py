"""
Becker-DeGroot-Marschak bid (``annotation_type: bdm``).

Asks for the most the participant would pay ("What is the most you would pay
for X?") as a number between ``min`` and ``max``, typed (``input: number``,
the default) or set on a slider (``input: slider``).

The answer is one hidden input holding JSON: ``{"bid": 4.5}``.

The price is never drawn on the page. ``potato/incentives.py`` draws it after
the participant has finished (rule ``method: bdm``): a bid at or above the
price buys at the price, a lower bid does not buy.
"""

import json
from typing import Any, Dict, List, Tuple

from .identifier_utils import (
    escape_html_content, generate_element_identifier, generate_layout_attributes,
    generate_validation_attribute, safe_generate_layout)
from .price_list import money

INPUTS = ("number", "slider")


def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_bdm(scheme: Dict[str, Any]) -> None:
    """Raise ValueError naming the first problem."""
    if "max" not in scheme:
        raise ValueError("needs `max`, the largest bid allowed")
    lo, hi, step = scheme.get("min", 0), scheme.get("max"), scheme.get("step", 0.01)
    if not (_num(lo) and _num(hi)) or lo < 0 or hi <= lo:
        raise ValueError("min and max must be numbers with 0 <= min < max")
    if not _num(step) or step <= 0 or step > hi - lo:
        raise ValueError("step must be a positive number no larger than max - min")
    if scheme.get("input", "number") not in INPUTS:
        raise ValueError(f"input must be one of {', '.join(INPUTS)}")
    if "currency" in scheme and not isinstance(scheme["currency"], str):
        raise ValueError("currency must be a string such as '$' or '£'")
    if "bid_label" in scheme and not (isinstance(scheme["bid_label"], str) and scheme["bid_label"].strip()):
        raise ValueError("bid_label must be non-empty text")


def generate_bdm_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    validate_bdm(annotation_scheme)
    name = annotation_scheme["name"]
    esc = escape_html_content(name)
    ids = generate_element_identifier(name, name, "hidden")
    validation = generate_validation_attribute(annotation_scheme)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    instructions = annotation_scheme.get("instructions", "")
    lo = float(annotation_scheme.get("min", 0))
    hi = float(annotation_scheme["max"])
    step = float(annotation_scheme.get("step", 0.01))
    mode = annotation_scheme.get("input", "number")
    currency = str(annotation_scheme.get("currency", "$"))
    bid_label = str(annotation_scheme.get("bid_label", "Your bid"))
    config = json.dumps({"min": lo, "max": hi, "step": step, "input": mode, "currency": currency})
    entry_id = f"{ids['id']}_entry"
    range_text = f"from {money(lo, currency)} to {money(hi, currency)}"

    if mode == "slider":
        entry = f"""
            <label class="bdm-label" for="{entry_id}">{escape_html_content(bid_label)}</label>
            <div class="bdm-slider-row">
                <span class="bdm-end" aria-hidden="true">{escape_html_content(money(lo, currency))}</span>
                <input type="range" class="bdm-slider" id="{entry_id}" min="{lo:g}" max="{hi:g}" step="{step:g}"
                       value="{(lo + hi) / 2:g}" aria-describedby="{entry_id}_range">
                <span class="bdm-end" aria-hidden="true">{escape_html_content(money(hi, currency))}</span>
                <output class="bdm-value" for="{entry_id}">&ndash;</output>
            </div>"""
    else:
        entry = f"""
            <label class="bdm-label" for="{entry_id}">{escape_html_content(bid_label)}</label>
            <div class="bdm-number-row">
                <span class="bdm-currency" aria-hidden="true">{escape_html_content(currency)}</span>
                <input type="number" class="bdm-number" id="{entry_id}" min="{lo:g}" max="{hi:g}" step="{step:g}"
                       inputmode="decimal" autocomplete="off" aria-describedby="{entry_id}_range">
            </div>"""

    html = f"""
    <form id="{esc}" class="annotation-form bdm incentive-widget" action="javascript:void(0)"
          data-annotation-type="bdm" data-schema-name="{esc}"
          data-bdm='{escape_html_content(config)}' {layout_attrs}>
        <fieldset schema="{esc}">
            <legend class="iw-title">{escape_html_content(annotation_scheme["description"])}</legend>
            {f'<p class="iw-instructions">{escape_html_content(instructions)}</p>' if instructions else ''}
            <div class="bdm-entry">{entry}</div>
            <p class="bdm-range iw-hint" id="{entry_id}_range">Any amount {escape_html_content(range_text)}.</p>
            <p class="iw-status" aria-live="polite"></p>
            <input type="hidden" class="annotation-input incentive-input"
                   id="{ids['id']}" name="{ids['name']}"
                   schema="{ids['schema']}" label_name="{ids['label_name']}"
                   validation="{validation}" value="">
        </fieldset>
    </form>
    """
    return html, []
