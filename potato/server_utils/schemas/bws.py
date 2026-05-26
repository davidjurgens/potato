"""
Best-Worst Scaling (BWS) Layout

Generates a form interface for selecting the best and worst items from a tuple.
Features include:
- Labeled items display (A, B, C, D...) populated by JS from var_elems
- Best selection row — clickable tiles
- Worst selection row — clickable tiles
- Validation that best != worst
- Keyboard shortcuts: 1-9 for best, q/w/e/r for worst
- Two hidden inputs storing the best/worst position labels

Config keys:
    - name: Schema identifier
    - description: Display description (shown as heading)
    - best_description: Question text for best selection
    - worst_description: Question text for worst selection
    - tuple_size: Number of items per tuple (default: 4)
    - sequential_key_binding: Enable keyboard shortcuts (default: true)
    - label_requirement: Optional validation settings
"""

import logging
from typing import Any, Dict, List, Tuple

from potato.ai.ai_help_wrapper import get_ai_wrapper
from .identifier_utils import (
    safe_generate_layout,
    generate_validation_attribute,
    escape_html_content,
    generate_layout_attributes,
)

logger = logging.getLogger(__name__)


def generate_bws_layout(
    annotation_scheme: Dict[str, Any],
) -> Tuple[str, List[Tuple[str, str]]]:
    """
    Generate HTML for a Best-Worst Scaling interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - best_description: Question for best selection (default: "Which is BEST?")
            - worst_description: Question for worst selection (default: "Which is WORST?")
            - tuple_size: Items per tuple (default: 4)
            - sequential_key_binding: Enable keyboard shortcuts (default: true)
            - label_requirement (dict): Optional validation settings

    Returns:
        tuple: (html_string, key_bindings)
    """
    return safe_generate_layout(annotation_scheme, _generate_bws_layout_internal)


def _generate_bws_layout_internal(
    annotation_scheme: Dict[str, Any],
) -> Tuple[str, List[Tuple[str, str]]]:
    """Internal function to generate BWS layout after validation."""
    logger.debug(f"Generating BWS layout for schema: {annotation_scheme['name']}")

    schema_name = annotation_scheme["name"]
    description = annotation_scheme.get("description", "")
    best_description = annotation_scheme.get(
        "best_description", "Which is BEST?"
    )
    worst_description = annotation_scheme.get(
        "worst_description", "Which is WORST?"
    )
    tuple_size = annotation_scheme.get("tuple_size", 4)
    enable_keybindings = annotation_scheme.get("sequential_key_binding", True)

    # Validation attribute for both hidden inputs
    validation = generate_validation_attribute(annotation_scheme)

    # Escape for HTML
    escaped_schema = escape_html_content(schema_name)
    escaped_description = escape_html_content(description)
    escaped_best_desc = escape_html_content(best_description)
    escaped_worst_desc = escape_html_content(worst_description)

    # Layout attributes for grid positioning
    layout_attrs = generate_layout_attributes(annotation_scheme)

    # Position labels: A, B, C, D, ...
    positions = [chr(ord("A") + i) for i in range(tuple_size)]

    # Build best tiles
    best_tiles_html = ""
    for idx, pos in enumerate(positions):
        key_num = str(idx + 1)
        shortcut = f"[{key_num}]" if enable_keybindings else ""
        data_key = f'data-key="{key_num}"' if enable_keybindings else ""
        best_tiles_html += f"""
                <div class="bws-tile bws-best-tile" data-value="{pos}" data-schema="{escaped_schema}" data-role="best" tabindex="0" {data_key}>
                    <span class="bws-tile-label">{pos}</span>
                    <span class="bws-tile-shortcut">{shortcut}</span>
                </div>"""

    # Build worst tiles — keys q, w, e, r (row below 1, 2, 3, 4)
    worst_keys = "qwer"
    worst_tiles_html = ""
    for idx, pos in enumerate(positions):
        key_letter = worst_keys[idx] if idx < len(worst_keys) else chr(ord("a") + idx)
        shortcut = f"[{key_letter}]" if enable_keybindings else ""
        data_key = f'data-key="{key_letter}"' if enable_keybindings else ""
        worst_tiles_html += f"""
                <div class="bws-tile bws-worst-tile" data-value="{pos}" data-schema="{escaped_schema}" data-role="worst" tabindex="0" {data_key}>
                    <span class="bws-tile-label">{pos}</span>
                    <span class="bws-tile-shortcut">{shortcut}</span>
                </div>"""

    # Build the complete form
    schematic = f"""
    <form id="{escaped_schema}" class="annotation-form bws" action="javascript:void(0)" data-annotation-type="bws" data-schema-name="{escaped_schema}" data-tuple-size="{tuple_size}" data-annotation-id="{escape_html_content(str(annotation_scheme.get('annotation_id', '')))}" {layout_attrs}>
        {get_ai_wrapper()}
        <fieldset schema="{escaped_schema}">
            <legend class="bws-description">{escaped_description}</legend>

            <!-- BWS items display placeholder — populated by JS from var_elems -->
            <div class="bws-items-display" id="bws-items-display-{escaped_schema}"></div>

            <!-- Best selection -->
            <div class="bws-selection-section bws-best-section">
                <div class="bws-selection-label bws-best-label">{escaped_best_desc}</div>
                <div class="bws-selection-container bws-best-container">{best_tiles_html}
                </div>
            </div>

            <!-- Worst selection -->
            <div class="bws-selection-section bws-worst-section">
                <div class="bws-selection-label bws-worst-label">{escaped_worst_desc}</div>
                <div class="bws-selection-container bws-worst-container">{worst_tiles_html}
                </div>
            </div>

            <!-- Validation error message -->
            <div class="bws-validation-error" style="display:none;">Best and worst selections cannot be the same item.</div>

            <!-- Hidden inputs for form submission -->
            <input type="hidden" class="bws-value annotation-input"
                   name="{escaped_schema}:::best"
                   schema="{escaped_schema}"
                   label_name="best"
                   validation="{validation}"
                   value="">
            <input type="hidden" class="bws-value annotation-input"
                   name="{escaped_schema}:::worst"
                   schema="{escaped_schema}"
                   label_name="worst"
                   validation="{validation}"
                   value="">
        </fieldset>
    </form>
    """

    # Key bindings — best: 1,2,3,4  worst: q,w,e,r
    worst_binding_keys = "qwer"
    key_bindings = []
    if enable_keybindings:
        for idx, pos in enumerate(positions):
            key_bindings.append((str(idx + 1), f"{schema_name}: Best {pos}"))
            wk = worst_binding_keys[idx] if idx < len(worst_binding_keys) else chr(ord("a") + idx)
            key_bindings.append(
                (wk, f"{schema_name}: Worst {pos}")
            )

    logger.info(f"Successfully generated BWS layout for {schema_name}")
    return schematic, key_bindings
