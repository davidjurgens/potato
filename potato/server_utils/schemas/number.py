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
    <form id="{escape_html_content(annotation_scheme['name'])}" class="annotation-form number shadcn-number-container" data-annotation-type="number" data-schema-name="{escape_html_content(annotation_scheme['name'])}" action="javascript:void(0)" data-annotation-id="{escape_html_content(str(annotation_scheme.get("annotation_id", "")))}" {layout_attrs}>
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
            with open(annotation_scheme["tooltip_file"], "rt", encoding="utf-8") as f:
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

    Both spellings of each bound are honored. ``min_value``/``max_value`` match
    the slider and vas schemas; ``min``/``max``/``step`` are what the registry
    has always advertised and what the shipped examples and configuration docs
    use (examples/advanced/all-annotation-types/config.yaml). Reading only the
    first pair meant every documented `min:`/`max:`/`step:` on a number scheme
    rendered an unconstrained input. The ``*_value`` form wins when both appear.

    Args:
        annotation_scheme (dict): Configuration containing min/max/step values

    Returns:
        str: Space-separated attribute string
    """
    attrs = []
    bounds = {}

    for attr, keys in (("min", ("min_value", "min")),
                       ("max", ("max_value", "max")),
                       ("step", ("step",))):
        for key in keys:
            if key in annotation_scheme:
                attrs.append(f'{attr}="{escape_html_content(str(annotation_scheme[key]))}"')
                logger.debug("Setting %s from '%s': %s", attr, key, annotation_scheme[key])
                bounds[attr] = annotation_scheme[key]
                break

    _refuse_inverted_range(annotation_scheme, bounds)
    return " ".join(attrs)


def _refuse_inverted_range(annotation_scheme, bounds):
    """Raise when min > max, which `slider` and `range_slider` already do.

    `<input type="number" min="10" max="1">` cannot be filled: Chrome reports
    every value invalid, with its own message -- "Minimum value (10) must be
    less than the maximum value (1)" -- which is the check Potato skipped. One
    such field makes `form.checkValidity()` false for the whole page, so a
    scheme nobody could answer blocks every other scheme beside it.

    Refused rather than warned, unlike the slider's out-of-range
    `starting_value`: there is no usable widget to keep running here, and both
    spellings of the bounds are checked so `min:`/`max:` is not a way around
    the check that `min_value:`/`max_value:` gets.
    """
    if "min" not in bounds or "max" not in bounds:
        return
    try:
        low, high = float(bounds["min"]), float(bounds["max"])
    except (TypeError, ValueError):
        # A non-numeric bound is a different complaint and the browser will
        # ignore the attribute; do not turn it into this error.
        return
    if low > high:
        raise Exception(
            f'Number scheme "{annotation_scheme.get("name", "?")}" has a '
            f'minimum above its maximum ({bounds["min"]} > {bounds["max"]}), '
            f"so no value can be entered and the whole page fails validation."
        )
