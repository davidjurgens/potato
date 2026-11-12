"""
Triad test schema (``annotation_type: triad_test``).

Shows the items of a domain three at a time and asks which one is most
different (Weller & Romney 1988, ch. 5). All the triads of one scheme are
answered on one item or phase page, one triad at a time, with a progress line
("Triad 3 of 13"). The keys 1, 2 and 3 choose a position.

The domain is either ``labels`` in the config or a list in the item under
``items_field``. Which triads are asked is described in
:mod:`potato.cultural_domain.triads`; the page builds the plan with
``static/triad-design.js`` and shuffles the triad order and the item
positions per participant, item and scheme.

Stored as one hidden input holding JSON::

    {"design": "steiner",
     "triads": [["apple", "pear", "lime", "lime"], ...]}

Each triad lists its three items in the positions they were shown, then the
item chosen as most different (``null`` until answered). The
``cultural_domain`` export turns the answers into an item-by-item similarity
matrix.
"""

import json
import logging
from typing import Any, Dict, List, Tuple

from potato.cultural_domain.triads import DESIGNS, MAX_DOMAIN, domain_items, steiner_exists

from .identifier_utils import (
    escape_html_content, generate_element_identifier, generate_layout_attributes,
    generate_validation_attribute, safe_generate_layout)

logger = logging.getLogger(__name__)

DEFAULT_QUESTION = "Which is most different?"


def validate_scheme(scheme: Dict[str, Any]) -> None:
    """Raise ValueError for a triad_test scheme that cannot work as configured."""
    labels, field = scheme.get("labels"), scheme.get("items_field")
    if labels and field:
        raise ValueError("give the domain as labels or as items_field, not both")
    if labels is not None:
        if not isinstance(labels, list):
            raise ValueError("labels must be a list of the domain's items")
        items = domain_items(labels)
        if len(items) < 3:
            raise ValueError("labels must name at least three different items")
        if len(items) > MAX_DOMAIN:
            raise ValueError(f"a triad test domain may have at most {MAX_DOMAIN} items")
        if scheme.get("design") == "steiner" and not steiner_exists(len(items)):
            raise ValueError(
                f"design: steiner needs a number of items that is 1 or 3 mod 6 "
                f"(7, 9, 13, 15, ...); there are {len(items)}. Use auto or sample")
    elif field is not None and not (isinstance(field, str) and field):
        raise ValueError("items_field must name the item field holding the list")
    design = scheme.get("design", "auto")
    if design not in DESIGNS:
        raise ValueError(f"design must be one of {', '.join(DESIGNS)}")
    mt = scheme.get("max_triads")
    if mt is not None and (isinstance(mt, bool) or not isinstance(mt, int) or mt < 1):
        raise ValueError("max_triads must be a whole number above 0")


def generate_triad_test_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    schema_name = annotation_scheme["name"]
    design = annotation_scheme.get("design", "auto")
    if design not in DESIGNS:
        raise ValueError(f"triad_test '{schema_name}': design must be one of {', '.join(DESIGNS)}")
    labels = annotation_scheme.get("labels")
    domain = domain_items(labels) if labels else None
    if domain is not None and len(domain) < 3:
        raise ValueError(f"triad_test '{schema_name}': labels must name at least three items")
    esc = escape_html_content(schema_name)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")
    validation = generate_validation_attribute(annotation_scheme)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    instructions = annotation_scheme.get("instructions", "")
    config = json.dumps({
        "schema": schema_name,
        "labels": domain,
        "items_field": annotation_scheme.get("items_field", "items"),
        "design": design,
        "max_triads": annotation_scheme.get("max_triads"),
        "question": annotation_scheme.get("question") or DEFAULT_QUESTION,
    })

    html = f"""
    <form id="{esc}" class="annotation-form triad-test" action="javascript:void(0)"
          data-annotation-type="triad_test" data-schema-name="{esc}"
          data-triad-config='{escape_html_content(config)}' {layout_attrs}>
        <fieldset schema="{esc}">
            <legend class="tt-title">{escape_html_content(annotation_scheme["description"])}</legend>
            {f'<p class="tt-instructions">{escape_html_content(instructions)}</p>' if instructions else ''}
            <div class="tt-root" tabindex="-1">
                <p class="tt-loading" role="status">Loading the triads…</p>
            </div>
            <input type="hidden" class="annotation-input triad-test-input"
                   id="{identifiers['id']}" name="{identifiers['name']}"
                   schema="{identifiers['schema']}" label_name="{identifiers['label_name']}"
                   validation="{validation}" value="">
        </fieldset>
    </form>
    """
    return html, []
