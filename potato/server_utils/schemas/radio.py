"""
Radio Layout

Generates a form interface with mutually exclusive radio button options.
Features include:
- Vertical or horizontal layout options
- Keyboard shortcuts
- Required/optional validation
- Tooltip support
- Free response option
"""

import logging
from collections.abc import Mapping
from .identifier_utils import (
    safe_generate_layout,
    generate_element_identifier,
    generate_element_value,
    generate_validation_attribute,
    escape_html_content
)

logger = logging.getLogger(__name__)

def generate_radio_layout(annotation_scheme, horizontal=False):
    """
    Generate HTML for a radio button selection interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - labels: List of label configurations, each either:
                - str: Simple label text
                - dict: Complex label with:
                    - name: Label identifier
                    - tooltip: Hover text description
                    - tooltip_file: Path to tooltip text file
                    - key_value: Keyboard shortcut key
            - label_requirement (dict): Optional validation settings
                - required (bool): Whether selection is mandatory
            - horizontal (bool): Whether to arrange options horizontally
            - has_free_response (dict): Optional free text input configuration
                - instruction: Label for free response field

        horizontal (bool): Override horizontal layout setting

    Returns:
        tuple: (html_string, key_bindings)
            html_string: Complete HTML for the radio interface
            key_bindings: List of (key, description) tuples for keyboard shortcuts
    """
    return safe_generate_layout(annotation_scheme, _generate_radio_layout_internal, horizontal)

def _generate_radio_layout_internal(annotation_scheme, horizontal=False):
    """
    Internal function to generate radio layout after validation.
    """
    logger.debug(f"Generating radio layout for schema: {annotation_scheme['name']}")

    # Check for horizontal layout override
    if annotation_scheme.get("horizontal"):
        horizontal = True
        logger.debug("Using horizontal layout")

    # Initialize form wrapper
    schema_name = annotation_scheme["name"]
    schematic = f"""
    <form id="{escape_html_content(schema_name)}" class="annotation-form radio shadcn-radio-container" action="/action_page.php">
        <fieldset schema="{escape_html_content(schema_name)}">
            <legend class="shadcn-radio-title">{escape_html_content(annotation_scheme['description'])}</legend>
            <div class="shadcn-radio-options{' horizontal' if horizontal else ''}">
    """

    # Initialize keyboard shortcut mappings
    key2label = {}
    label2key = {}
    key_bindings = []

    # Generate radio inputs for each label
    for i, label_data in enumerate(annotation_scheme["labels"], 1):
        # Extract label information
        label = label_data if isinstance(label_data, str) else label_data["name"]

        # Generate consistent identifiers (use element_type='radio')
        identifiers = generate_element_identifier(schema_name, label, "radio")

        key_value = generate_element_value(label_data, i, annotation_scheme)
        validation = generate_validation_attribute(annotation_scheme)

        # Handle tooltips and keyboard shortcuts
        tooltip = ""
        if isinstance(label_data, Mapping):
            tooltip = _generate_tooltip(label_data)

            # Handle keyboard shortcuts
            if "key_value" in label_data:
                key_value = label_data["key_value"]
                if key_value in key2label:
                    logger.warning(f"Keyboard input conflict: {key_value}")
                    continue
                key2label[key_value] = label
                label2key[label] = key_value
                key_bindings.append((key_value, f"{identifiers['schema']}: {label}"))
                logger.debug(f"Added key binding '{key_value}' for label '{label}'")

        # Handle sequential key bindings
        if (annotation_scheme.get("sequential_key_binding")
            and len(annotation_scheme["labels"]) <= 10):
            key_value = str(i % 10)
            key2label[key_value] = label
            label2key[label] = key_value
            key_bindings.append((key_value, f"{identifiers['schema']}: {label}"))
            logger.debug(f"Added sequential key binding '{key_value}' for label '{label}'")

        # Format label content with optional keyboard shortcut display
        label_content = label
        if label in label2key:
            label_content = f"{label_content} [{label2key[label].upper()}]"

        # Generate radio input
        schematic += f"""
            <div class="shadcn-radio-option">
                <input class="{identifiers['schema']} shadcn-radio-input annotation-input"
                       type="radio"
                       id="{identifiers['id']}"
                       name="{identifiers['name']}"
                       value="{escape_html_content(key_value)}"
                       selection_constraint="single"
                       schema="{identifiers['schema']}"
                       label_name="{identifiers['label_name']}"
                       onclick="onlyOne(this);registerAnnotation(this);"
                       validation="{validation}">
                <label for="{identifiers['id']}" class="shadcn-radio-label" {tooltip}>{escape_html_content(label_content)}</label>
            </div>
        """

    schematic += "</div>"

    # Add optional free response field
    if annotation_scheme.get("has_free_response"):
        logger.debug("Adding free response field")
        free_response_identifiers = generate_element_identifier(schema_name, "free_response", "text")
        instruction = annotation_scheme["has_free_response"].get("instruction", "Other")

        schematic += f"""
            <div class="shadcn-radio-free-response">
                <span class="shadcn-radio-label">{escape_html_content(instruction)}</span>
                <input class="{free_response_identifiers['schema']} shadcn-radio-free-input annotation-input"
                       type="text"
                       id="{free_response_identifiers['id']}"
                       name="{free_response_identifiers['name']}"
                       schema="{free_response_identifiers['schema']}"
                       label_name="{free_response_identifiers['label_name']}">
                <label for="{free_response_identifiers['id']}"></label>
            </div>
        """

    schematic += "</fieldset></form>"

    logger.info(f"Successfully generated radio layout for {schema_name} "
                f"with {len(annotation_scheme['labels'])} options")
    return schematic, key_bindings

def _generate_tooltip(label_data):
    """
    Generate tooltip HTML attribute from label data.

    Args:
        label_data (dict): Label configuration containing tooltip information

    Returns:
        str: Tooltip HTML attribute or empty string if no tooltip
    """
    tooltip_text = ""
    if "tooltip" in label_data:
        tooltip_text = label_data["tooltip"]
    elif "tooltip_file" in label_data:
        try:
            with open(label_data["tooltip_file"], "rt") as f:
                tooltip_text = "".join(f.readlines())
        except Exception as e:
            logger.error(f"Failed to read tooltip file: {e}")
            return ""

    if tooltip_text:
        escaped_tooltip = escape_html_content(tooltip_text)
        return f'data-toggle="tooltip" data-html="true" data-placement="top" title="{escaped_tooltip}"'
    return ""
