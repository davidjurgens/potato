"""
Likert Scale Layout

Generates a likert scale rating interface with radio buttons arranged horizontally.
Each button represents a point on the scale between min_label and max_label.

This module provides functionality for creating HTML-based Likert scale interfaces
that can be used for collecting ordinal data responses. The scale supports:
- Customizable number of points
- Optional numeric display
- Keyboard shortcuts
- Required/optional validation
- Bad text option for invalid inputs
"""

import logging

logger = logging.getLogger(__name__)

def generate_likert_layout(annotation_scheme):
    """
    Generate HTML for a likert scale annotation interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - size: Number of scale points
            - min_label: Label for minimum value
            - max_label: Label for maximum value
            - sequential_key_binding: Enable number key bindings (1-9)
            - displaying_score: Show numeric values on buttons
            - label_requirement: Validation settings
                - required (bool): Whether response is mandatory
            - bad_text_label (dict): Optional configuration for invalid text option
                - label_content (str): Label text for bad text option

    Returns:
        tuple: (html_string, key_bindings)
            html_string: Complete HTML for the likert scale interface
            key_bindings: List of (key, description) tuples for keyboard shortcuts

    Raises:
        Exception: If required fields are missing from annotation_scheme
    """
    logger.debug(f"Generating likert layout for schema: {annotation_scheme['name']}")

    # Use radio layout if complex labels specified
    if "labels" in annotation_scheme:
        logger.info(f"Complex labels detected for {annotation_scheme['name']}, using radio layout")
        return generate_radio_layout(annotation_scheme, horizontal=False)

    # Validate required fields
    required_fields = ["size", "min_label", "max_label"]
    for required in required_fields:
        if required not in annotation_scheme:
            error_msg = f'Likert scale for "{annotation_scheme["name"]}" missing required field: {required}'
            logger.error(error_msg)
            raise Exception(error_msg)

    logger.debug(f"Creating {annotation_scheme['size']}-point likert scale")

    # Initialize form wrapper
    schematic = f"""
        <form id="{annotation_scheme['name']}" class="annotation-form likert" action="/action_page.php">
            <fieldset schema="{annotation_scheme['name']}">
                <legend>{annotation_scheme['description']}</legend>
                <ul class="likert" style="text-align: center;">
                    <li>{annotation_scheme['min_label']}</li>
    """

    # Setup validation and key bindings
    key_bindings = []
    validation = ""
    if annotation_scheme.get("label_requirement", {}).get("required"):
        validation = "required"
        logger.debug(f"Setting required validation for {annotation_scheme['name']}")

    # Generate scale points
    for i in range(1, annotation_scheme["size"] + 1):
        label = f"{i}"
        name = f"{annotation_scheme['name']}:::{label}"
        key_value = str(i % 10)

        # Handle key bindings for scales with less than 10 points
        if (annotation_scheme.get("sequential_key_binding")
            and annotation_scheme["size"] < 10):
            key_bindings.append((key_value, f"{annotation_scheme['name']}: {key_value}"))
            logger.debug(f"Added key binding '{key_value}' for point {i}")

        # Format label content - show numbers if displaying_score is enabled
        label_content = str(i) if annotation_scheme.get("displaying_score") else ""
        line_break = "<br>" if label_content else ""

        # Generate radio input for each scale point
        schematic += f"""
            <li>
                <input class="{annotation_scheme['name']}"
                       type="radio"
                       id="{name}"
                       name="{name}"
                       value="{key_value}"
                       schema="{annotation_scheme['name']}"
                       label_name="{key_value}"
                       selection_constraint="single"
                       validation="{validation}"
                       onclick="onlyOne(this);registerAnnotation(this);">
                {line_break}
                <label for="{name}">{label_content}</label>
            </li>
        """

    # Add max label to complete the scale
    schematic += f"<li>{annotation_scheme['max_label']}</li>"

    # Add optional bad text input for invalid/problematic cases
    if "label_content" in annotation_scheme.get("bad_text_label", {}):
        logger.debug(f"Adding bad text option for {annotation_scheme['name']}")
        name = f"{annotation_scheme['name']}:::bad_text"
        schematic += f"""
            <li>
                <input class="{annotation_scheme['name']}"
                       type="radio"
                       id="{name}"
                       name="{name}"
                       value="0"
                       validation="{validation}"
                       onclick="onlyOne(this);registerAnnotation(this);">
                <br>
                <label for="{name}">
                    {annotation_scheme['bad_text_label']['label_content']}
                </label>
            </li>
        """

    schematic += "</ul></fieldset></form>"

    logger.info(f"Successfully generated likert layout for {annotation_scheme['name']} "
                f"with {annotation_scheme['size']} points")
    return schematic, key_bindings
