"""
Number Layout

Generates a form interface for numeric input. Features include:
- Custom CSS styling options
- Tooltip support
- Required/optional validation
- Min/max value constraints
"""

import logging

from potato.ai.ai_help_wrapper import get_ai_wrapper, get_dynamic_ai_help
from .identifier_utils import (
    safe_generate_layout,
    generate_element_identifier,
    generate_validation_attribute,
    escape_html_content,
    generate_layout_attributes
)


logger = logging.getLogger(__name__)

def generate_number_layout(annotation_scheme):
    """
    Generate HTML for a numeric input interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - custom_css (dict): Optional CSS styling
                - width: Input width (default: "60px")
                - height: Input height
                - font_size: Text size
            - tooltip: Optional hover text description
            - tooltip_file: Optional path to tooltip text file
            - label_requirement (dict): Optional validation settings
                - required (bool): Whether input is mandatory
            - min_value (int): Optional minimum allowed value
            - max_value (int): Optional maximum allowed value

    Returns:
        tuple: (html_string, key_bindings)
            html_string: Complete HTML for the number input interface
            key_bindings: Empty list (no keyboard shortcuts)
    """
    return safe_generate_layout(annotation_scheme, _generate_number_layout_internal)

def _generate_number_layout_internal(annotation_scheme):
    """
    Internal function to generate number layout after validation.
    """
    logger.debug(f"Generating number layout for schema: {annotation_scheme['name']}")

    # Get custom dimensions from config
    css = annotation_scheme.get("custom_css", {})
    width = css.get("width", "60px")

    # Get layout attributes for grid positioning
    layout_attrs = generate_layout_attributes(annotation_scheme)

    # Initialize form wrapper
    schematic = f"""
    <form id="{escape_html_content(annotation_scheme['name'])}" class="annotation-form number shadcn-number-container" action="/action_page.php" data-annotation-id="{annotation_scheme["annotation_id"]}" {layout_attrs}>
        {get_ai_wrapper()}
        <fieldset schema="{escape_html_content(annotation_scheme['name'])}">
            <legend class="shadcn-number-title">{escape_html_content(annotation_scheme['description'])}</legend>
            <div class="shadcn-number-input">
    """

    # Generate consistent identifiers
    identifiers = generate_element_identifier(annotation_scheme['name'], "number", "number")
    validation = generate_validation_attribute(annotation_scheme)

    # Generate tooltip
    tooltip = _generate_tooltip(annotation_scheme)

    # Generate number input
    input_attrs = _generate_input_attributes(annotation_scheme)

    schematic += f"""
                <input class="{identifiers['schema']} shadcn-number-field annotation-input"
                       type="number"
                       id="{identifiers['id']}"
                       name="{identifiers['name']}"
                       validation="{validation}"
                       schema="{identifiers['schema']}"
                       label_name="{identifiers['label_name']}"
                       {input_attrs}>
                <label for="{identifiers['id']}" {tooltip}></label>
            </div>
        </fieldset>
    </form>
    """

    logger.info(f"Successfully generated number layout for {annotation_scheme['name']}")
    return schematic, []

def _generate_css_style(annotation_scheme):
    """
    Generate CSS style string from configuration.

    Args:
        annotation_scheme (dict): Configuration containing custom_css settings

    Returns:
        str: Formatted CSS style string
    """
    css = annotation_scheme.get("custom_css", {})
    styles = []

    # Default width if not specified
    width = css.get("width", "60px")
    styles.append(f"width: {width}")

    # Optional height
    if "height" in css:
        styles.append(f"height: {css['height']}")

    # Optional font size
    if "font_size" in css:
        styles.append(f"font-size: {css['font_size']}")

    return "; ".join(styles)

def _generate_tooltip(annotation_scheme):
    """
    Generate tooltip HTML attribute from configuration.

    Args:
        annotation_scheme (dict): Configuration containing tooltip information

    Returns:
        str: Tooltip HTML attribute or empty string if no tooltip
    """
    tooltip_text = ""
    if "tooltip" in annotation_scheme:
        tooltip_text = annotation_scheme["tooltip"]
    elif "tooltip_file" in annotation_scheme:
        try:
            with open(annotation_scheme["tooltip_file"], "rt") as f:
                tooltip_text = "".join(f.readlines())
        except Exception as e:
            logger.error(f"Failed to read tooltip file: {e}")
            return ""

    if tooltip_text:
        escaped_tooltip = escape_html_content(tooltip_text)
        return f'data-toggle="tooltip" data-html="true" data-placement="top" title="{escaped_tooltip}"'
    return ""

def _generate_input_attributes(annotation_scheme):
    """
    Generate additional input attributes for number constraints.

    Args:
        annotation_scheme (dict): Configuration containing min/max values

    Returns:
        str: Space-separated attribute string
    """
    attrs = []

    if "min_value" in annotation_scheme:
        attrs.append(f'min="{annotation_scheme["min_value"]}"')
        logger.debug(f"Setting minimum value: {annotation_scheme['min_value']}")

    if "max_value" in annotation_scheme:
        attrs.append(f'max="{annotation_scheme["max_value"]}"')
        logger.debug(f"Setting maximum value: {annotation_scheme['max_value']}")

    return " ".join(attrs)
