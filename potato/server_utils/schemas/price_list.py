"""
Multiple price list (``annotation_type: price_list``).

A column of paired options A and B. The participant picks one option in every
row. Rows come from ``rows`` (written by the researcher) or from a preset:

``holt_laury``
    Holt & Laury (2002): ten rows. Option A pays $2.00 with probability p and
    $1.60 otherwise; option B pays $3.85 with probability p and $0.10
    otherwise; p = 0.1, 0.2, ..., 1.0. ``scale`` multiplies every amount.

``time_preference``
    One row per entry of ``amounts_later``: option A pays ``amount_now`` now,
    option B pays the later amount after ``delay_label``.

With ``single_switch: true`` the page keeps at most one switch point: picking
B in a row also picks B in every later row, and picking A also picks A in
every earlier row. Otherwise every row is free and the stored answer records
how many times the participant switched.

The answer is one hidden input holding JSON::

    {"choices": ["A", "A", "B", ...], "switches": 1, "multiple_switching": false}

Unanswered rows are ``null``. ``potato/incentives.py`` pays a price list with
the ``mpl_random_row`` rule, using the payoffs built by :func:`build_rows`.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .identifier_utils import (
    escape_html_content, generate_element_identifier, generate_layout_attributes,
    generate_validation_attribute, safe_generate_layout)

logger = logging.getLogger(__name__)

PRESETS = ("holt_laury", "time_preference")

#: Holt & Laury (2002), low-payoff treatment: (high, low) prize of each option.
HOLT_LAURY_A = (2.00, 1.60)
HOLT_LAURY_B = (3.85, 0.10)
HOLT_LAURY_ROWS = 10


def money(amount: float, currency: str = "$") -> str:
    """``$1.60``; the symbol goes before the amount."""
    return f"{currency}{amount:,.2f}"


def _pct(p: float) -> str:
    value = round(p * 100, 2)
    return f"{value:g}%"


def _lottery_text(pays: Sequence[Tuple[float, float]], currency: str) -> str:
    if len(pays) == 1:
        return f"{money(pays[0][1], currency)} for sure"
    return ", ".join(f"{_pct(p)} chance of {money(a, currency)}" for p, a in pays)


def _parse_pays(value: Any) -> Optional[List[Tuple[float, float]]]:
    """A number (a sure amount) or ``[[probability, amount], ...]``."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return [(1.0, float(value))]
    if isinstance(value, list):
        out = []
        for pair in value:
            if (not isinstance(pair, (list, tuple)) or len(pair) != 2
                    or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in pair)):
                raise ValueError("payoffs must be a number or a list of [probability, amount] pairs")
            out.append((float(pair[0]), float(pair[1])))
        return out
    raise ValueError("payoffs must be a number or a list of [probability, amount] pairs")


def build_rows(scheme: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The rows of a price list, each with its text and its payoffs.

    Every row is ``{"a": text, "b": text, "a_pays": [(p, amount), ...] | None,
    "b_pays": ..., "a_after": str, "b_after": str}``. ``*_after`` is empty for
    an option that pays now and the delay label for one that pays later.
    ``*_pays`` is None for a hand-written row without payoffs.
    """
    currency = str(scheme.get("currency", "$"))
    preset = scheme.get("preset")
    rows: List[Dict[str, Any]] = []
    if preset == "holt_laury":
        scale = float(scheme.get("scale", 1))
        for k in range(1, HOLT_LAURY_ROWS + 1):
            p = k / HOLT_LAURY_ROWS
            a = [(p, HOLT_LAURY_A[0] * scale)] + ([(1 - p, HOLT_LAURY_A[1] * scale)] if k < HOLT_LAURY_ROWS else [])
            b = [(p, HOLT_LAURY_B[0] * scale)] + ([(1 - p, HOLT_LAURY_B[1] * scale)] if k < HOLT_LAURY_ROWS else [])
            rows.append({"a": _lottery_text(a, currency), "b": _lottery_text(b, currency),
                         "a_pays": a, "b_pays": b, "a_after": "", "b_after": ""})
        return rows
    if preset == "time_preference":
        scale = float(scheme.get("scale", 1))
        now = float(scheme.get("amount_now", 0)) * scale
        now_label = str(scheme.get("now_label", "today"))
        delay = str(scheme.get("delay_label", "in 4 weeks"))
        for later in scheme.get("amounts_later") or []:
            later = float(later) * scale
            rows.append({"a": f"{money(now, currency)} {now_label}",
                         "b": f"{money(later, currency)} {delay}",
                         "a_pays": [(1.0, now)], "b_pays": [(1.0, later)],
                         "a_after": "", "b_after": delay})
        return rows
    for row in scheme.get("rows") or []:
        a_pays, b_pays = _parse_pays(row.get("a_pays")), _parse_pays(row.get("b_pays"))
        rows.append({
            "a": str(row["a"]) if row.get("a") is not None else _lottery_text(a_pays or [], currency),
            "b": str(row["b"]) if row.get("b") is not None else _lottery_text(b_pays or [], currency),
            "a_pays": a_pays, "b_pays": b_pays,
            "a_after": str(row.get("a_after") or ""), "b_after": str(row.get("b_after") or ""),
        })
    return rows


def count_switches(choices: Sequence[Optional[str]]) -> int:
    """How many times consecutive answered rows change option."""
    answered = [c for c in choices if c in ("A", "B")]
    return sum(1 for x, y in zip(answered, answered[1:]) if x != y)


def single_switch_fill(choices: List[Optional[str]], row: int, choice: str) -> List[Optional[str]]:
    """The single-switch rule the page applies on a click (kept here so it is
    tested in Python too): B in ``row`` sets B for every later row, A sets A
    for every earlier row."""
    out = list(choices)
    if choice == "B":
        for i in range(row, len(out)):
            out[i] = "B"
    else:
        for i in range(0, row + 1):
            out[i] = "A"
    return out


def validate_price_list(scheme: Dict[str, Any]) -> None:
    """Raise ValueError naming the first problem."""
    preset, rows = scheme.get("preset"), scheme.get("rows")
    if (preset is None) == (rows is None):
        raise ValueError("needs exactly one of `preset` (holt_laury or time_preference) or `rows`")
    if preset is not None and preset not in PRESETS:
        raise ValueError(f"preset must be one of {', '.join(PRESETS)}, got {preset!r}")
    if "scale" in scheme:
        scale = scheme["scale"]
        if preset is None:
            raise ValueError("scale applies to presets only; write the amounts into `rows` instead")
        if isinstance(scale, bool) or not isinstance(scale, (int, float)) or scale <= 0:
            raise ValueError("scale must be a positive number")
    if "currency" in scheme and not isinstance(scheme["currency"], str):
        raise ValueError("currency must be a string such as '$' or '£'")
    if "single_switch" in scheme and not isinstance(scheme["single_switch"], bool):
        raise ValueError("single_switch must be true or false")
    labels = scheme.get("option_labels")
    if labels is not None and (not isinstance(labels, list) or len(labels) != 2
                               or not all(isinstance(x, str) and x.strip() for x in labels)):
        raise ValueError("option_labels must be two strings, such as ['Option A', 'Option B']")
    tp_keys = ("amount_now", "amounts_later", "delay_label", "now_label")
    if preset == "time_preference":
        now = scheme.get("amount_now")
        if isinstance(now, bool) or not isinstance(now, (int, float)) or now < 0:
            raise ValueError("time_preference needs amount_now, a number of 0 or more")
        later = scheme.get("amounts_later")
        if (not isinstance(later, list) or len(later) < 2
                or any(isinstance(x, bool) or not isinstance(x, (int, float)) or x < 0 for x in later)):
            raise ValueError("time_preference needs amounts_later, a list of at least two amounts")
        for key in ("delay_label", "now_label"):
            if key in scheme and not (isinstance(scheme[key], str) and scheme[key].strip()):
                raise ValueError(f"{key} must be a non-empty string")
    else:
        stray = [k for k in tp_keys if k in scheme]
        if stray:
            raise ValueError(f"{', '.join(stray)} apply to preset: time_preference only")
    if rows is not None:
        if not isinstance(rows, list) or len(rows) < 2:
            raise ValueError("rows must be a list of at least two {a, b} rows")
        for i, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                raise ValueError(f"row {i} must be a mapping with `a` and `b`")
            unknown = set(row) - {"a", "b", "a_pays", "b_pays", "a_after", "b_after"}
            if unknown:
                raise ValueError(f"row {i}: unknown key(s) {', '.join(sorted(unknown))}")
            for side in ("a", "b"):
                text, pays = row.get(side), row.get(f"{side}_pays")
                if text is None and pays is None:
                    raise ValueError(f"row {i}: option {side.upper()} needs `{side}` (text) or `{side}_pays`")
                if text is not None and not (isinstance(text, str) and text.strip()):
                    raise ValueError(f"row {i}: `{side}` must be non-empty text")
                parsed = _parse_pays(pays)
                if parsed is not None:
                    if any(p <= 0 or p > 1 for p, _ in parsed) or abs(sum(p for p, _ in parsed) - 1) > 1e-6:
                        raise ValueError(f"row {i}: {side}_pays probabilities must be in (0, 1] and sum to 1")
                    if any(a < 0 for _, a in parsed):
                        raise ValueError(f"row {i}: {side}_pays amounts must be 0 or more")
                after = row.get(f"{side}_after")
                if after is not None and not isinstance(after, str):
                    raise ValueError(f"row {i}: {side}_after must be text such as 'in 4 weeks'")


def generate_price_list_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    validate_price_list(annotation_scheme)
    name = annotation_scheme["name"]
    esc = escape_html_content(name)
    ids = generate_element_identifier(name, name, "hidden")
    validation = generate_validation_attribute(annotation_scheme)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    instructions = annotation_scheme.get("instructions", "")
    labels = annotation_scheme.get("option_labels") or ["Option A", "Option B"]
    rows = build_rows(annotation_scheme)
    config = json.dumps({"rows": len(rows),
                         "single_switch": bool(annotation_scheme.get("single_switch", False))})

    body = []
    for i, row in enumerate(rows):
        n = i + 1
        buttons = "".join(
            f'<button type="button" role="radio" aria-checked="false" class="pl-choice" '
            f'data-row="{i}" data-choice="{side}" '
            f'aria-label="Decision {n}, {escape_html_content(labels[k])}: {escape_html_content(row[side.lower()])}">'
            f'<span class="pl-mark" aria-hidden="true"></span>'
            f'<span class="pl-tag" aria-hidden="true">{side}</span>'
            f'<span class="pl-text">{escape_html_content(row[side.lower()])}</span></button>'
            for k, side in enumerate(("A", "B")))
        body.append(f'<div class="pl-row" role="radiogroup" aria-label="Decision {n}" data-row="{i}">'
                    f'<span class="pl-num" aria-hidden="true">{n}</span>{buttons}</div>')

    html = f"""
    <form id="{esc}" class="annotation-form price-list incentive-widget" action="javascript:void(0)"
          data-annotation-type="price_list" data-schema-name="{esc}"
          data-price-list='{escape_html_content(config)}' {layout_attrs}>
        <fieldset schema="{esc}">
            <legend class="iw-title">{escape_html_content(annotation_scheme["description"])}</legend>
            {f'<p class="iw-instructions">{escape_html_content(instructions)}</p>' if instructions else ''}
            <div class="pl-table">
                <div class="pl-head" aria-hidden="true"><span class="pl-num">#</span>
                    <span>{escape_html_content(labels[0])}</span><span>{escape_html_content(labels[1])}</span></div>
                {''.join(body)}
            </div>
            <p class="iw-status" aria-live="polite"></p>
            <input type="hidden" class="annotation-input incentive-input"
                   id="{ids['id']}" name="{ids['name']}"
                   schema="{ids['schema']}" label_name="{ids['label_name']}"
                   validation="{validation}" value="">
        </fieldset>
    </form>
    """
    return html, []
