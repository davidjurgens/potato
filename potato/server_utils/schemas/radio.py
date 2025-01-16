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
    logger.debug(f"Generating radio layout for schema: {annotation_scheme['name']}")

    # Check for horizontal layout override
    if annotation_scheme.get("horizontal"):
        horizontal = True
        logger.debug("Using horizontal layout")

    # Initialize form wrapper
    schema_name = annotation_scheme["name"]
    schematic = f"""
        <form id="{schema_name}" class="annotation-form radio" action="/action_page.php">
            <fieldset schema="{schema_name}">
                <legend>{annotation_scheme['description']}</legend>
    """

    # Initialize keyboard shortcut mappings
    key2label = {}
    label2key = {}
    key_bindings = []

    # Setup validation requirements
    validation = ""
    label_requirement = annotation_scheme.get("label_requirement", {})
    if label_requirement and label_requirement.get("required"):
        validation = "required"
        logger.debug("Setting required validation")

    # Generate radio inputs for each label
    for i, label_data in enumerate(annotation_scheme["labels"], 1):
        # Extract label information
        label = label_data if isinstance(label_data, str) else label_data["name"]
        name = f"{schema_name}:::{label}"
        class_name = schema_name
        key_value = name
        br_label = "" if horizontal else "<br/>"

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
                key_bindings.append((key_value, f"{class_name}: {label}"))
                logger.debug(f"Added key binding '{key_value}' for label '{label}'")

        # Format label content with optional keyboard shortcut display
        label_content = label
        if label in label2key:
            label_content = f"{label_content} [{label2key[label].upper()}]"

        # Generate radio input
        schematic += f"""
            <input class="{class_name}"
                   type="radio"
                   id="{name}"
                   name="{name}"
                   value="{key_value}"
                   selection_constraint="single"
                   schema="{schema_name}"
                   label_name="{label}"
                   onclick="onlyOne(this);registerAnnotation(this);"
                   validation="{validation}">
            <label for="{name}" {tooltip}>{label_content}</label>{br_label}
        """

    # Add optional free response field
    if annotation_scheme.get("has_free_response"):
        logger.debug("Adding free response field")
        name = f"{schema_name}:::free_response"
        instruction = annotation_scheme["has_free_response"].get("instruction", "Other")

        schematic += f"""
            {instruction}
            <input class="{schema_name}"
                   type="text"
                   id="{name}"
                   name="{name}"
                   label_name="free_response">
            <label for="{name}"></label><br/>
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
        return f'data-toggle="tooltip" data-html="true" data-placement="top" title="{tooltip_text}"'
    return ""
