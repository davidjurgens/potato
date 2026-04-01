"""
Visual Analog Scale (VAS) Layout

A continuous line scale with no tick marks or discrete bins. Annotators click/drag
to a position, returning a precise float value. Psychophysically superior to Likert
scales for fine-grained judgments.

Research: Stevens (1957) "On the Psychophysical Law"; standard in clinical pain assessment.
"""

import logging

from .identifier_utils import (
    safe_generate_layout,
    generate_element_identifier,
    generate_validation_attribute,
    escape_html_content,
    generate_layout_attributes
)


logger = logging.getLogger(__name__)

# Defaults
DEFAULT_MIN = 0
DEFAULT_MAX = 100
DEFAULT_SHOW_VALUE = False


def generate_vas_layout(annotation_scheme):
    """
    Generate HTML for a Visual Analog Scale interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - left_label: Label for the left endpoint
            - right_label: Label for the right endpoint
            - min_value: Minimum value (default 0)
            - max_value: Maximum value (default 100)
            - show_value: Whether to show numeric value after selection (default False)
            - precision: Decimal places to round to (default 1)

    Returns:
        tuple: (html_string, key_bindings)
    """
    return safe_generate_layout(annotation_scheme, _generate_vas_layout_internal)


def _generate_vas_layout_internal(annotation_scheme):
    schema_name = annotation_scheme['name']
    description = annotation_scheme['description']
    left_label = annotation_scheme.get('left_label', '')
    right_label = annotation_scheme.get('right_label', '')
    min_value = annotation_scheme.get('min_value', DEFAULT_MIN)
    max_value = annotation_scheme.get('max_value', DEFAULT_MAX)
    show_value = annotation_scheme.get('show_value', DEFAULT_SHOW_VALUE)
    precision = annotation_scheme.get('precision', 1)

    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)
    identifiers = generate_element_identifier(schema_name, schema_name, "range")

    # The key difference from slider: step="any" for continuous values,
    # no tick marks, no value display by default, minimal styling
    # Compute step from precision (e.g., precision=1 → step=0.1)
    step_value = 10 ** -precision if precision > 0 else 1
    initial_value = round((min_value + max_value) / 2, precision)

    value_display = ""
    if show_value:
        value_display = f"""
            <div class="vas-value-display" id="{identifiers['id']}-value-display">
                <span id="{identifiers['name']}-value">—</span>
            </div>
        """

    html = f"""
    <form id="{escape_html_content(schema_name)}" class="annotation-form shadcn-vas-container"
          action="/action_page.php"
          data-annotation-id="{escape_html_content(str(annotation_scheme.get('annotation_id', '')))}"
          data-annotation-type="vas"
          data-schema-name="{escape_html_content(schema_name)}"
          {layout_attrs}>
        <fieldset schema_name="{escape_html_content(schema_name)}">
            <legend class="shadcn-vas-title">{escape_html_content(description)}</legend>
            <div class="vas-scale-wrapper">
                <div class="vas-labels">
                    <span class="vas-label-left">{escape_html_content(left_label)}</span>
                    <span class="vas-label-right">{escape_html_content(right_label)}</span>
                </div>
                <div class="vas-track-container">
                    <input type="range"
                           class="vas-input annotation-input"
                           id="{identifiers['id']}"
                           name="{identifiers['name']}"
                           schema="{identifiers['schema']}"
                           label_name="{identifiers['label_name']}"
                           validation="{validation}"
                           min="{min_value}"
                           max="{max_value}"
                           step="{step_value}"
                           value="{initial_value}">
                    <div class="vas-track-line"></div>
                </div>
                {value_display}
            </div>
        </fieldset>
    </form>
    """

    # Inline JS to round value and update display
    if show_value:
        html += f"""
    <script>
    (function() {{
        var input = document.getElementById("{identifiers['id']}");
        var display = document.getElementById("{identifiers['name']}-value");
        var precision = {precision};
        function updateDisplay() {{
            if (display) display.textContent = parseFloat(input.value).toFixed(precision);
        }}
        input.addEventListener('input', updateDisplay);
    }})();
    </script>
        """

    logger.info(f"Generated VAS layout for {schema_name}")
    return html, []
