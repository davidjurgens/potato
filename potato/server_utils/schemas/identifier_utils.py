"""
Identifier Utilities for Schema Generation

This module provides centralized functions for generating consistent identifiers
and validating schema configurations across all annotation schema types.
"""

import html
import logging
from typing import Dict, Any, Tuple, List

logger = logging.getLogger(__name__)

def validate_schema_config(annotation_scheme: dict) -> bool:
    """
    Validate schema configuration before generating HTML.

    Args:
        annotation_scheme: Schema configuration dictionary

    Returns:
        bool: True if valid, raises exception if invalid

    Raises:
        ValueError: If configuration is invalid
    """
    # Check required fields
    required_fields = ["name", "description"]
    for field in required_fields:
        if field not in annotation_scheme:
            raise ValueError(f"Missing required field: {field}")

    # Validate schema name
    schema_name = annotation_scheme["name"]
    if not schema_name or not str(schema_name).strip():
        raise ValueError("Schema name cannot be empty")

    # Validate description
    description = annotation_scheme["description"]
    if not description or not str(description).strip():
        raise ValueError("Schema description cannot be empty")

    # Validate labels if present
    if "labels" in annotation_scheme:
        labels = annotation_scheme["labels"]
        if not labels:
            raise ValueError("Labels list cannot be empty")

        # Check for duplicate labels
        label_names = []
        for label in labels:
            if isinstance(label, str):
                label_names.append(label.strip())
            elif isinstance(label, dict) and "name" in label:
                label_names.append(label["name"].strip())
            else:
                raise ValueError(f"Invalid label format: {label}")

        # Check for empty labels
        if any(not name for name in label_names):
            raise ValueError("Label names cannot be empty")

        # Check for duplicates
        if len(label_names) != len(set(label_names)):
            duplicates = [name for name in set(label_names) if label_names.count(name) > 1]
            raise ValueError(f"Duplicate labels found: {duplicates}")

    logger.debug(f"Schema configuration validation passed for: {schema_name}")
    return True

def generate_element_identifier(schema_name: str, label_name: str, element_type: str = "default") -> Dict[str, str]:
    """
    Generate consistent identifiers for form elements.

    Args:
        schema_name: Name of the annotation schema
        label_name: Name of the specific label/option
        element_type: Type of element (radio, checkbox, text, etc.)

    Returns:
        dict: Contains id, name, schema, and label_name attributes
    """
    # Sanitize inputs
    safe_schema = escape_html_content(schema_name.strip())
    safe_label = escape_html_content(label_name.strip())

    # Generate unique identifier (using underscore to avoid conflicts with CSS selectors)
    element_id = f"{safe_schema}_{safe_label}_{element_type}".replace(":::", "_")

    # For radio buttons, use schema name as the group name to ensure mutual exclusivity
    if element_type == "radio":
        element_name = safe_schema
    else:
        element_name = f"{safe_schema}:::{safe_label}"

    return {
        "id": element_id,
        "name": element_name,
        "schema": safe_schema,
        "label_name": safe_label
    }

def generate_element_value(label_data: Any, index: int, annotation_scheme: dict) -> str:
    """
    Generate consistent value attributes for form elements.

    Args:
        label_data: Label configuration (string or dict)
        index: Index of the label in the list
        annotation_scheme: Full schema configuration

    Returns:
        str: Value to use for the element
    """
    # Handle custom key_value first
    if isinstance(label_data, dict) and "key_value" in label_data:
        return str(label_data["key_value"])

    # Handle sequential key binding
    if annotation_scheme.get("sequential_key_binding"):
        return str(index % 10)

    # Default to label name
    if isinstance(label_data, str):
        return label_data
    elif isinstance(label_data, dict) and "name" in label_data:
        return label_data["name"]

    # Fallback to index
    return str(index)

def escape_html_content(content: str) -> str:
    """
    Escape HTML content to prevent injection.

    Args:
        content: Content to escape

    Returns:
        str: Escaped content
    """
    if not content:
        return ""
    return html.escape(str(content))

def safe_generate_layout(annotation_scheme: dict, layout_function: callable, *args, **kwargs) -> Tuple[str, List[Tuple[str, str]]]:
    """
    Safely generate layout with proper error handling.

    Args:
        annotation_scheme: Schema configuration
        layout_function: Function to generate layout
        *args, **kwargs: Additional arguments for the layout function

    Returns:
        tuple: (html_string, key_bindings)
    """
    try:
        # Validate configuration
        validate_schema_config(annotation_scheme)

        # Generate layout
        return layout_function(annotation_scheme, *args, **kwargs)

    except Exception as e:
        schema_name = annotation_scheme.get('name', 'unknown')
        logger.error(f"Failed to generate layout for schema '{schema_name}': {e}")

        # Return error HTML instead of crashing
        error_html = f"""
        <div class="annotation-error" style="border: 2px solid #ff0000; padding: 10px; margin: 10px 0; background-color: #fff5f5;">
            <h4 style="color: #ff0000; margin: 0 0 10px 0;">Error Generating Annotation Form</h4>
            <p style="margin: 0; color: #666;">Schema: {escape_html_content(schema_name)}</p>
            <p style="margin: 5px 0 0 0; color: #333;">{escape_html_content(str(e))}</p>
        </div>
        """
        return error_html, []

def generate_validation_attribute(annotation_scheme: dict, label_name: str = None) -> str:
    """
    Generate validation attribute for form elements.

    Args:
        annotation_scheme: Schema configuration
        label_name: Specific label name for required_label validation

    Returns:
        str: Validation attribute value
    """
    label_requirement = annotation_scheme.get("label_requirement", {})

    # Debug logging
    logger.debug(f"generate_validation_attribute called with label_requirement: {label_requirement}")
    logger.debug(f"label_name: {label_name}")

    # Check for required_label validation
    if label_name and label_requirement.get("required_label"):
        required_labels = label_requirement["required_label"]
        if isinstance(required_labels, str) and label_name == required_labels:
            logger.debug(f"Returning 'required_label' for label: {label_name}")
            return "required_label"
        elif isinstance(required_labels, list) and label_name in required_labels:
            logger.debug(f"Returning 'required_label' for label: {label_name}")
            return "required_label"

    # Check for general required validation
    if label_requirement.get("required"):
        logger.debug(f"Returning 'required' for general requirement")
        return "required"

    logger.debug(f"Returning empty string - no validation requirements met")
    return ""


def generate_tooltip_html(label_data: Dict[str, Any]) -> str:
    """
    Generate tooltip HTML attribute from label data.

    This function provides centralized tooltip generation for all schema types.
    It checks for tooltip text in the label configuration, either directly or
    from an external file.

    Args:
        label_data: Label configuration dictionary that may contain:
            - tooltip: Direct tooltip text string
            - tooltip_file: Path to file containing tooltip text

    Returns:
        str: Tooltip HTML attribute string (e.g., 'data-toggle="tooltip" ...')
             or empty string if no tooltip is configured

    Example:
        >>> label_data = {"name": "Option 1", "tooltip": "Select this option"}
        >>> generate_tooltip_html(label_data)
        'data-toggle="tooltip" data-html="true" data-placement="top" title="Select this option"'
    """
    if not isinstance(label_data, dict):
        return ""

    tooltip_text = ""

    # Check for direct tooltip text
    if "tooltip" in label_data:
        tooltip_text = label_data["tooltip"]
        logger.debug(f"Found direct tooltip text for label")

    # Check for tooltip file
    elif "tooltip_file" in label_data:
        try:
            with open(label_data["tooltip_file"], "rt") as f:
                tooltip_text = "".join(f.readlines())
            logger.debug(f"Read tooltip from file: {label_data['tooltip_file']}")
        except FileNotFoundError:
            logger.error(f"Tooltip file not found: {label_data['tooltip_file']}")
            return ""
        except PermissionError:
            logger.error(f"Permission denied reading tooltip file: {label_data['tooltip_file']}")
            return ""
        except Exception as e:
            logger.error(f"Failed to read tooltip file '{label_data['tooltip_file']}': {e}")
            return ""

    if tooltip_text:
        escaped_tooltip = escape_html_content(tooltip_text)
        return f'data-toggle="tooltip" data-html="true" data-placement="top" title="{escaped_tooltip}"'

    return ""