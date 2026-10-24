"""
Free list schema (``annotation_type: free_list``).

The participant answers a prompt such as "List all the kinds of fruit you can
think of" by typing items one at a time; Enter (or the Add button) adds the
item to the end of the list. Items keep the order they were given in, since
the order is part of the data (Weller & Romney 1988, ch. 2): there is no
reordering. An item can be deleted, and the deletion undone.

Options: ``min_items``, ``max_items``, ``time_limit_s`` (a countdown that
starts with a Start button; when it ends the list is locked),
``allow_duplicates`` and ``normalize``. ``normalize`` is applied by the
``cultural_domain`` export, never to what is stored: the stored list is what
the participant typed.

Stored as one hidden input holding JSON::

    {"items": ["apple", "banana"], "timings_ms": [2140, 5310],
     "elapsed_ms": 9020, "time_up": false, "started": true}

``timings_ms[i]`` is the time from the start of the list (the first focus on
the entry box, or the Start button when timed) to when item ``i`` was added.
Time spent on other pages is not counted.
"""

import json
import logging
from typing import Any, Dict, List, Tuple

from .identifier_utils import (
    escape_html_content, generate_element_identifier, generate_layout_attributes,
    generate_validation_attribute, safe_generate_layout)

logger = logging.getLogger(__name__)

NORMALIZE_STEPS = ("lowercase", "trim")
MAX_ITEM_LENGTH = 200
#: The most items the ``cultural_domain`` export reads from one list when
#: ``max_items`` is not set. The page stops at ``max_items``; a stored answer
#: is not checked on save, so the export cuts a list that is longer.
MAX_LIST_ITEMS = 300


def list_limit(scheme: Dict[str, Any]) -> int:
    """The most items a list may have: ``max_items``, else MAX_LIST_ITEMS."""
    hi = scheme.get("max_items")
    return hi if _positive_int(hi) else MAX_LIST_ITEMS


def _positive_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def normalize_steps(value) -> List[str]:
    """``normalize`` as a list of steps: true means lowercase and trim."""
    if value is True:
        return list(NORMALIZE_STEPS)
    if not value:
        return []
    if isinstance(value, str):
        value = [value]
    return [str(v) for v in value]


def validate_scheme(scheme: Dict[str, Any]) -> None:
    """Raise ValueError for a free_list scheme that cannot work as configured."""
    for key in ("min_items", "max_items"):
        if key in scheme and scheme[key] is not None and not _positive_int(scheme[key]):
            raise ValueError(f"{key} must be a whole number above 0")
    lo, hi = scheme.get("min_items"), scheme.get("max_items")
    if lo and hi and lo > hi:
        raise ValueError(f"min_items ({lo}) is larger than max_items ({hi})")
    limit = scheme.get("time_limit_s")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, (int, float)) or limit <= 0):
        raise ValueError("time_limit_s must be a number of seconds above 0")
    norm = scheme.get("normalize")
    if norm is not None and not isinstance(norm, bool):
        steps = normalize_steps(norm)
        unknown = [s for s in steps if s not in NORMALIZE_STEPS]
        if unknown or not isinstance(norm, (list, str)):
            raise ValueError("normalize must be true, false, or a list of: " + ", ".join(NORMALIZE_STEPS))


def generate_free_list_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    schema_name = annotation_scheme["name"]
    esc = escape_html_content(schema_name)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")
    validation = generate_validation_attribute(annotation_scheme)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    instructions = annotation_scheme.get("instructions", "")
    config = json.dumps({
        "schema": schema_name,
        "min_items": annotation_scheme.get("min_items"),
        "max_items": annotation_scheme.get("max_items"),
        "time_limit_s": annotation_scheme.get("time_limit_s"),
        "allow_duplicates": bool(annotation_scheme.get("allow_duplicates", False)),
        "placeholder": annotation_scheme.get("placeholder") or "Type an item, then press Enter",
        "max_length": MAX_ITEM_LENGTH,
    })
    entry_id = f"{esc}-fl-entry"

    html = f"""
    <form id="{esc}" class="annotation-form free-list" action="javascript:void(0)"
          data-annotation-type="free_list" data-schema-name="{esc}"
          data-free-list-config='{escape_html_content(config)}' {layout_attrs}>
        <fieldset schema="{esc}">
            <legend class="fl-title">{escape_html_content(annotation_scheme["description"])}</legend>
            {f'<p class="fl-instructions">{escape_html_content(instructions)}</p>' if instructions else ''}
            <div class="fl-root" data-entry-id="{entry_id}">
                <p class="fl-loading" role="status">Loading…</p>
            </div>
            <input type="hidden" class="annotation-input free-list-input"
                   id="{identifiers['id']}" name="{identifiers['name']}"
                   schema="{identifiers['schema']}" label_name="{identifiers['label_name']}"
                   validation="{validation}" value="">
        </fieldset>
    </form>
    """
    return html, []
