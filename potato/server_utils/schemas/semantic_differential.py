"""
Semantic Differential Layout

Generates bipolar adjective scales arranged in a matrix.
Each row has a left and right pole with radio buttons between them.

Research basis:
- Osgood, Suci & Tannenbaum (1957) "The Measurement of Meaning"
  University of Illinois Press
- Mohammad (2018) "Obtaining Reliable Human Ratings of Valence, Arousal, and Dominance
  for 20,000 English Words" ACL
"""

import logging

from potato.ai.ai_help_wrapper import get_ai_wrapper
from .identifier_utils import (
    safe_generate_layout,
    generate_element_identifier,
    generate_validation_attribute,
    escape_html_content,
    generate_layout_attributes,
)

logger = logging.getLogger(__name__)

DEFAULT_SCALE_POINTS = 7


def generate_semantic_differential_layout(annotation_scheme):
    """
    Generate HTML for a semantic differential annotation interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - pairs: List of [left_adjective, right_adjective] pairs
            - scale_points: Number of points per scale (default 7)

    Returns:
        tuple: (html_string, key_bindings)
    """
    return safe_generate_layout(annotation_scheme, _generate_semantic_differential_layout_internal)


def _generate_semantic_differential_layout_internal(annotation_scheme):
    schema_name = annotation_scheme["name"]
    safe_schema = escape_html_content(schema_name)
    description = annotation_scheme["description"]
    pairs = annotation_scheme.get("pairs", [])
    scale_points = annotation_scheme.get("scale_points", DEFAULT_SCALE_POINTS)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)

    if not pairs:
        raise ValueError(f"semantic_differential schema '{schema_name}' requires 'pairs'")

    for pair in pairs:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError(f"Each pair must be a list of two strings, got: {pair}")

    html = f"""
    <form id="{safe_schema}" class="annotation-form semantic_differential shadcn-semantic-differential-container"
          data-annotation-id="{escape_html_content(str(annotation_scheme.get('annotation_id', '')))}"
          data-annotation-type="semantic_differential"
          data-schema-name="{safe_schema}"
          {layout_attrs}>
        {get_ai_wrapper()}
        <fieldset schema="{safe_schema}">
            <legend class="shadcn-semantic-differential-title">{escape_html_content(description)}</legend>
            <div class="semantic-differential-matrix">
    """

    for pair_idx, pair in enumerate(pairs):
        left = escape_html_content(pair[0])
        right = escape_html_content(pair[1])
        # Use combined pair as label identifier
        pair_label = f"{pair[0]}__{pair[1]}"
        safe_pair_label = escape_html_content(pair_label)

        html += f"""
                <div class="semantic-differential-row">
                    <span class="semantic-differential-pole semantic-differential-left">{left}</span>
                    <div class="semantic-differential-scale">
        """

        for point in range(1, scale_points + 1):
            value = str(point)
            identifiers = generate_element_identifier(schema_name, f"{pair_label}_{value}", "radio")
            # Use pair_label as the radio group name for mutual exclusivity
            radio_name = f"{safe_schema}:::{safe_pair_label}"
            is_center = point == (scale_points + 1) // 2

            html += f"""
                        <div class="semantic-differential-point{' center' if is_center else ''}">
                            <input class="{identifiers['schema']} semantic-differential-radio annotation-input"
                                   type="radio"
                                   id="{identifiers['id']}"
                                   name="{radio_name}"
                                   value="{value}"
                                   schema="{identifiers['schema']}"
                                   label_name="{safe_pair_label}"
                                   validation="{validation}"
                                   onclick="onlyOneSD(this);registerAnnotation(this);">
                            <label class="semantic-differential-button{' center' if is_center else ''}"
                                   for="{identifiers['id']}"></label>
                        </div>
            """

        html += f"""
                    </div>
                    <span class="semantic-differential-pole semantic-differential-right">{right}</span>
                </div>
        """

    html += """
            </div>
        </fieldset>
    </form>
    """

    # JS for mutual exclusivity within each pair row
    html += """
    <script>
    function onlyOneSD(radio) {
        const name = radio.getAttribute('name');
        const radios = document.querySelectorAll('input[name="' + name + '"]');
        radios.forEach(r => { if (r !== radio) r.checked = false; });
        radio.checked = true;
    }
    </script>
    """

    key_bindings = []
    logger.info(f"Generated semantic_differential layout for {schema_name} with {len(pairs)} pairs")
    return html, key_bindings
