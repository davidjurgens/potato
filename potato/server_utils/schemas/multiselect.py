"""
Multiselect Layout

Generates a form interface that allows users to select multiple options from a list
of choices. Features include:
- Multiple column layout support
- Keyboard shortcuts
- Required/optional validation
- Individual label requirements
- Tooltip support
- Video label support
- Free response option
"""

import logging
from collections.abc import Mapping

from potato.ai.ai_help_wrapper import get_ai_wrapper, get_dynamic_ai_help
from .identifier_utils import (
    safe_generate_layout,
    generate_element_identifier,
    generate_element_value,
    generate_validation_attribute,
    escape_html_content
)


logger = logging.getLogger(__name__)

def generate_multiselect_layout(annotation_scheme):
    """
    Generate HTML for a multiple-choice selection interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - labels: List of label configurations, each either:
                - str: Simple label text
                - dict: Complex label with:
                    - name: Label identifier
                    - tooltip: Hover text description
                    - tooltip_file: Path to file containing tooltip text
                    - key_value: Keyboard shortcut key
                    - videopath: Path to video file (if video_as_label=True)
            - display_config (dict): Optional display settings
                - num_columns: Number of columns to arrange options (default: 1)
            - label_requirement (dict): Optional validation settings
                - required (bool): Whether any selection is mandatory
                - required_label (str|list): Specific labels that must be selected
            - sequential_key_binding (bool): Enable numeric key shortcuts
            - video_as_label (bool): Use videos instead of text for labels
            - has_free_response (dict): Optional free text input configuration
                - instruction: Label for free response field

    Returns:
        tuple: (html_string, key_bindings)
            html_string: Complete HTML for the multiselect interface
            key_bindings: List of (key, description) tuples for keyboard shortcuts
    """
    return safe_generate_layout(annotation_scheme, _generate_multiselect_layout_internal)

def _generate_multiselect_layout_internal(annotation_scheme):
    """
    Internal function to generate multiselect layout after validation.
    """
    logger.debug(f"Generating multiselect layout for schema: {annotation_scheme['name']}")

    # Initialize form wrapper
    schematic = f"""
    <form id="{escape_html_content(annotation_scheme['name'])}" class="annotation-form multiselect shadcn-multiselect-container" action="/action_page.php" data-annotation-id="{annotation_scheme["annotation_id"]}" data-annotation-type="multiselect" data-schema-name="{escape_html_content(annotation_scheme['name'])}">
        {get_ai_wrapper()}
        <fieldset schema="{escape_html_content(annotation_scheme['name'])}">
            <legend class="shadcn-multiselect-title">{escape_html_content(annotation_scheme['description'])}</legend>
    """

    # Initialize keyboard shortcut mappings
    key2label = {}
    label2key = {}
    key_bindings = []

    # Get display configuration
    display_info = annotation_scheme.get("display_config", {})
    n_columns = display_info.get("num_columns", 1)
    logger.debug(f"Using {n_columns} column layout")

    # Add grid with appropriate columns
    schematic += f'<div class="shadcn-multiselect-grid" style="grid-template-columns: repeat({n_columns}, 1fr);">'

    # Generate checkbox inputs for each label
    for i, label_data in enumerate(annotation_scheme["labels"], 1):
        # Extract label information
        label = label_data if isinstance(label_data, str) else label_data["name"]

        # Generate consistent identifiers
        identifiers = generate_element_identifier(annotation_scheme["name"], label, "checkbox")
        key_value = generate_element_value(label_data, i, annotation_scheme)
        validation = generate_validation_attribute(annotation_scheme, label)

        # Handle tooltips
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

        # Format label content
        label_content = _format_label_content(label_data, annotation_scheme)

        # Display keyboard shortcut if available
        key_display = f'<span class="shadcn-multiselect-key">{label2key[label].upper()}</span>' if label in label2key else ''

        # Generate checkbox input
        schematic += f"""
            <div class="shadcn-multiselect-item">
                <input class="{identifiers['schema']} shadcn-multiselect-checkbox annotation-input"
                       type="checkbox"
                       id="{identifiers['id']}"
                       name="{identifiers['name']}"
                       value="{escape_html_content(key_value)}"
                       label_name="{identifiers['label_name']}"
                       schema="{identifiers['schema']}"
                       onclick="whetherNone(this);registerAnnotation(this)"
                       validation="{validation}">
                <label for="{identifiers['id']}" {tooltip} schema="{identifiers['schema']}" class="shadcn-multiselect-label">
                    {label_content} {key_display}
                </label>
            </div>
        """

    schematic += "</div>"

    # Add optional free response field
    if annotation_scheme.get("has_free_response"):
        schematic += _generate_free_response(annotation_scheme, n_columns)

    schematic += "</fieldset></form>"

    logger.info(f"Successfully generated multiselect layout for {annotation_scheme['name']} "
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

def _format_label_content(label_data, annotation_scheme):
    """
    Format the label content, handling both text and video labels.

    Args:
        label_data: Label configuration
        annotation_scheme: Full annotation scheme configuration

    Returns:
        str: Formatted label content (text or video HTML)
    """
    if annotation_scheme.get("video_as_label") and isinstance(label_data, dict) and "videopath" in label_data:
        # Video label
        video_path = label_data["videopath"]
        return f'<video src="{escape_html_content(video_path)}" controls style="max-width: 200px; max-height: 150px;"></video>'
    else:
        # Text label
        label = label_data if isinstance(label_data, str) else label_data["name"]
        return escape_html_content(label)

def _generate_free_response(annotation_scheme, n_columns):
    """
    Generate free response field for multiselect.

    Args:
        annotation_scheme: Schema configuration
        n_columns: Number of columns in the grid

    Returns:
        str: HTML for free response field
    """
    free_response_identifiers = generate_element_identifier(annotation_scheme["name"], "free_response", "text")
    instruction = annotation_scheme["has_free_response"].get("instruction", "Other")

    return f"""
        <div class="shadcn-multiselect-free-response" style="grid-column: 1 / -1;">
            <span class="shadcn-multiselect-label">{escape_html_content(instruction)}</span>
            <input class="{free_response_identifiers['schema']} shadcn-multiselect-free-input annotation-input"
                   type="text"
                   id="{free_response_identifiers['id']}"
                   name="{free_response_identifiers['name']}"
                   schema="{free_response_identifiers['schema']}"
                   label_name="{free_response_identifiers['label_name']}">
        </div>
    """
