"""
Listening test schema (``annotation_type: listening_test``).

One scheme, seven methods:

=========  ===================================================================
mushra     ITU-R BS.1534-3: reference, hidden reference, anchors, one 0-100
           slider per sample, switching at the same position, looping
bs1116     ITU-R BS.1116: reference plus A and B, one of which is the hidden
           reference; 1.0-5.0 impairment scale for each
acr        ITU-T P.800 / P.808 / P.910 absolute category rating, 5 categories
dcr        degradation category rating: reference then sample, 5 categories
ccr        comparison category rating: two samples, -3..+3
abx        is X the same as A or as B
p835       ITU-T P.835: speech signal, background and overall, 5 each
=========  ===================================================================

The page asks ``/api/listening/plan`` for the trial (slot names and opaque
audio URLs) and ``static/listening-test.js`` builds the player and the rating
controls. Answers are one hidden input holding JSON:

* mushra / bs1116: ``{"ratings": {"s1": 84, ...}, "played": [...]}``
* acr / dcr / ccr: ``{"rating": <category index, best = 0>, "played": [...]}``
* p835: ``{"sig": i, "bak": i, "ovrl": i, "played": [...]}``
* abx: ``{"choice": "A" | "B", "played": [...]}``

Slots are mapped back to conditions in the ``listening_test`` export.
"""

import json
import logging
from typing import Any, Dict, List, Tuple

from .identifier_utils import (
    escape_html_content, generate_element_identifier, generate_layout_attributes,
    generate_validation_attribute, safe_generate_layout)

logger = logging.getLogger(__name__)


def generate_listening_test_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    from potato.listening.plan import METHODS
    schema_name = annotation_scheme["name"]
    method = annotation_scheme.get("method", "mushra")
    if method not in METHODS:
        raise ValueError(f"listening_test '{schema_name}': method must be one of {', '.join(METHODS)}")
    esc = escape_html_content(schema_name)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")
    validation = generate_validation_attribute(annotation_scheme)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    instructions = annotation_scheme.get("instructions", "")
    config = json.dumps({"schema": schema_name, "method": method})

    html = f"""
    <form id="{esc}" class="annotation-form listening-test" action="javascript:void(0)"
          data-annotation-type="listening_test" data-schema-name="{esc}"
          data-listening-config='{escape_html_content(config)}' {layout_attrs}>
        <fieldset schema="{esc}">
            <legend class="lt-title">{escape_html_content(annotation_scheme["description"])}</legend>
            {f'<p class="lt-instructions">{escape_html_content(instructions)}</p>' if instructions else ''}
            <div class="lt-root" tabindex="0" aria-label="Listening test controls">
                <p class="lt-loading" role="status">Loading audio…</p>
            </div>
            <input type="hidden" class="annotation-input listening-test-input"
                   id="{identifiers['id']}" name="{identifiers['name']}"
                   schema="{identifiers['schema']}" label_name="{identifiers['label_name']}"
                   validation="{validation}" value="">
        </fieldset>
    </form>
    """
    return html, []
