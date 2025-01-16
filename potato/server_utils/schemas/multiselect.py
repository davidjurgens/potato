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
    logger.debug(f"Generating multiselect layout for schema: {annotation_scheme['name']}")

    # Initialize form wrapper
    schematic = f"""
        <form id="{annotation_scheme['name']}" class="annotation-form multiselect" action="/action_page.php">
            <fieldset schema="{annotation_scheme['name']}">
                <legend>{annotation_scheme['description']}</legend>
    """

    # Initialize keyboard shortcut mappings
    key2label = {}
    label2key = {}
    key_bindings = []

    # Get display configuration
    display_info = annotation_scheme.get("display_config", {})
    n_columns = display_info.get("num_columns", 1)
    logger.debug(f"Using {n_columns} column layout")

    schematic += "<table>"

    # Setup validation requirements
    validation = ""
    label_requirement = annotation_scheme.get("label_requirement", {})
    if label_requirement and label_requirement.get("required"):
        validation = "required"
        logger.debug("Setting required validation")

    # Handle required label validation
    required_label = set()
    if label_requirement and "required_label" in label_requirement:
        req_label = label_requirement["required_label"]
        if isinstance(req_label, str):
            required_label.add(req_label)
        elif isinstance(req_label, list):
            required_label = set(req_label)
        else:
            logger.warning(f"Invalid required_label format: {req_label}")
        logger.debug(f"Required labels: {required_label}")

    # Generate checkbox inputs for each label
    for i, label_data in enumerate(annotation_scheme["labels"], 1):
        # Start new row if needed
        if (i - 1) % n_columns == 0:
            schematic += "<tr>"
        schematic += "<td>"

        # Extract label information
        label = label_data if isinstance(label_data, str) else label_data["name"]
        schema = annotation_scheme["name"]
        name = f"{schema}:::{label}"
        class_name = schema
        key_value = name

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
                key_bindings.append((key_value, f"{class_name}: {label}"))
                logger.debug(f"Added key binding '{key_value}' for label '{label}'")

        # Handle sequential key bindings
        if (annotation_scheme.get("sequential_key_binding")
            and len(annotation_scheme["labels"]) <= 10):
            key_value = str(i % 10)
            key2label[key_value] = label
            label2key[label] = key_value

        # Format label content
        label_content = _format_label_content(label_data, annotation_scheme)

        # Set validation requirements
        final_validation = "required_label" if label in required_label else validation

        # Generate checkbox input
        schematic += f"""
            <label for="{name}" {tooltip} schema="{schema}">
                <input class="{class_name}"
                       type="checkbox"
                       id="{name}"
                       name="{name}"
                       value="{key_value}"
                       label_name="{label}"
                       schema="{schema}"
                       onclick="whetherNone(this);registerAnnotation(this)"
                       validation="{final_validation}">
                {label_content}
            </label><br/>
        """

        schematic += "</td>"
        if i % n_columns == 0:
            schematic += "</tr>"

    # Add optional free response field
    if annotation_scheme.get("has_free_response"):
        schematic += _generate_free_response(annotation_scheme, n_columns)

    schematic += "</table></fieldset></form>"

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
        return f'data-toggle="tooltip" data-html="true" data-placement="top" title="{tooltip_text}"'
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
    if not annotation_scheme.get("video_as_label"):
        return label_data if isinstance(label_data, str) else label_data["name"]

    if not isinstance(label_data, Mapping) or "videopath" not in label_data:
        logger.error("Video path missing for video label")
        return ""

    return f"""
        <video width="320" height="240" autoplay loop muted>
            <source src="{label_data['videopath']}" type="video/mp4" />
        </video>
    """

def _generate_free_response(annotation_scheme, n_columns):
    """
    Generate HTML for free response input field.

    Args:
        annotation_scheme: Annotation scheme configuration
        n_columns: Number of columns in layout

    Returns:
        str: HTML for free response input
    """
    if not annotation_scheme.get("has_free_response"):
        return ""

    name = f"{annotation_scheme['name']}:::free_response"
    instruction = (annotation_scheme["has_free_response"].get("instruction", "Other"))

    return f"""
        <tr>
            <td colspan="{n_columns}">
                <div style="float:left; display:flex; flex-direction:row;">
                    {instruction}
                    <input class="{annotation_scheme['name']}"
                           type="text"
                           id="{name}"
                           name="{name}">
                    <label for="{name}"></label>
                </div>
            </td>
        </tr>
    """
