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

from potato.ai.ai_help_wrapper import get_ai_wrapper, get_dynamic_ai_help

from .identifier_utils import (
    safe_generate_layout,
    generate_element_identifier,
    generate_element_value,
    generate_validation_attribute,
    escape_html_content
)
from .radio import generate_radio_layout

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
            - annotation_id (int): match the config schema index

    Returns:
        tuple: (html_string, key_bindings)
            html_string: Complete HTML for the likert scale interface
            key_bindings: List of (key, description) tuples for keyboard shortcuts

    Raises:
        Exception: If required fields are missing from annotation_scheme
    """
    return safe_generate_layout(annotation_scheme, _generate_likert_layout_internal)

def _generate_likert_layout_internal(annotation_scheme):
    """
    Internal function to generate likert layout after validation.
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

    # Setup validation and key bindings
    key_bindings = []
    validation = generate_validation_attribute(annotation_scheme)
    
    # Initialize form wrapper
    schematic = f"""
    <form id="{escape_html_content(annotation_scheme['name'])}" class="annotation-form likert shadcn-likert-container" action="/action_page.php" data-annotation-id="{annotation_scheme["annotation_id"]}" data-annotation-type="likert" data-schema-name="{escape_html_content(annotation_scheme['name'])}">
        {get_ai_wrapper()}
        <fieldset schema="{escape_html_content(annotation_scheme['name'])}">
            <legend class="shadcn-likert-title">{escape_html_content(annotation_scheme['description'])}</legend>
            <div class="shadcn-likert-scale" style="max-width: min(100%, calc(300px + {annotation_scheme['size']} * 40px + 250px));">
                <div class="shadcn-likert-endpoint">{escape_html_content(annotation_scheme['min_label'])}</div>
                <div class="shadcn-likert-options">
                    <div class="shadcn-likert-track"></div>
    """

    # Generate scale points
    for i in range(1, annotation_scheme["size"] + 1):
        label = f"{i}"
        identifiers = generate_element_identifier(annotation_scheme['name'], label, "radio")
        key_value = generate_element_value(label, i, annotation_scheme)

        # Handle key bindings for scales with less than 10 points
        if (annotation_scheme.get("sequential_key_binding")
            and annotation_scheme["size"] < 10):
            key_bindings.append((key_value, f"{identifiers['schema']}: {key_value}"))
            logger.debug(f"Added key binding '{key_value}' for point {i}")

        # Format label content - show numbers if displaying_score is enabled
        label_content = str(i) if annotation_scheme.get("displaying_score") else ""

        # Generate radio input for each scale point
        schematic += f"""
                    <div class="shadcn-likert-option">
                        <input class="{identifiers['schema']} shadcn-likert-input annotation-input"
                               type="radio"
                               id="{identifiers['id']}"
                               name="{identifiers['name']}"
                               value="{escape_html_content(key_value)}"
                               schema="{identifiers['schema']}"
                               label_name="{identifiers['label_name']}"
                               selection_constraint="single"
                               validation="{validation}"
                               onclick="onlyOne(this);registerAnnotation(this);">
                        <label class="shadcn-likert-button" for="{identifiers['id']}"></label>
                        {f'<span class="shadcn-likert-label">{escape_html_content(label_content)}</span>' if label_content else ''}
                    </div>
        """

    # Add max label to complete the scale
    schematic += f"""
                </div>
                <div class="shadcn-likert-endpoint">{escape_html_content(annotation_scheme['max_label'])}</div>
            </div>
    """

    # Add optional bad text input for invalid/problematic cases
    if "label_content" in annotation_scheme.get("bad_text_label", {}):
        logger.debug(f"Adding bad text option for {annotation_scheme['name']}")
        bad_text_identifiers = generate_element_identifier(annotation_scheme['name'], "bad_text", "radio")
        schematic += f"""
            <div class="shadcn-likert-bad-text" style="width: 100%;">
                <input class="{bad_text_identifiers['schema']} shadcn-likert-input annotation-input"
                       type="radio"
                       id="{bad_text_identifiers['id']}"
                       name="{bad_text_identifiers['name']}"
                       value="0"
                       schema="{bad_text_identifiers['schema']}"
                       label_name="{bad_text_identifiers['label_name']}"
                       validation="{validation}"
                       onclick="onlyOne(this);registerAnnotation(this);">
                <label class="shadcn-likert-button" for="{bad_text_identifiers['id']}"></label>
                <span class="shadcn-likert-bad-text-label">
                    {escape_html_content(annotation_scheme['bad_text_label']['label_content'])}
                </span>
            </div>
        """
    schematic += """
        </fieldset></form>
    """

    logger.info(f"Successfully generated likert layout for {annotation_scheme['name']} "
                f"with {annotation_scheme['size']} points")
    return schematic, key_bindings
