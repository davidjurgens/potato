"""
Number Layout

Generates a form interface for numeric input. Features include:
- Custom CSS styling options
- Tooltip support
- Required/optional validation
- Min/max value constraints
"""

import logging

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
    logger.debug(f"Generating number layout for schema: {annotation_scheme['name']}")

    # Initialize form wrapper
    schematic = f"""
        <form id="{annotation_scheme['name']}" class="annotation-form number" action="/action_page.php">
            <fieldset schema="{annotation_scheme['name']}">
                <legend>{annotation_scheme['description']}</legend>
    """

    # Handle CSS styling
    custom_css = _generate_css_style(annotation_scheme)
    logger.debug(f"Applied custom CSS: {custom_css}")

    # Setup validation
    validation = ""
    if annotation_scheme.get("label_requirement", {}).get("required"):
        validation = "required"
        logger.debug("Setting required validation")

    # Generate tooltip
    tooltip = _generate_tooltip(annotation_scheme)

    # Generate number input
    name = f"{annotation_scheme['name']}:::number"
    input_attrs = _generate_input_attributes(annotation_scheme)

    schematic += f"""
        <input class="{annotation_scheme['name']}"
               type="number"
               id="{name}"
               name="{name}"
               style="{custom_css}"
               validation="{validation}"
               {input_attrs}>
        <label for="{name}" {tooltip}></label>
    """

    schematic += "</fieldset></form>"

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
        return f'data-toggle="tooltip" data-html="true" data-placement="top" title="{tooltip_text}"'
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
