"""
Textbox Layout
"""

import logging

logger = logging.getLogger(__name__)


def generate_textbox_layout(annotation_scheme):
    """
    Generate HTML for a textbox input interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - labels: Optional list of labels for multiple textboxes
            - label_requirement (dict): Optional validation settings
                - required (bool): Whether input is mandatory
            - textarea (dict): Optional textarea configuration
                - on (bool): Whether to use textarea instead of input
                - rows (int): Number of rows for textarea
                - cols (int): Number of columns for textarea
            - allow_paste (bool): Whether to allow pasting text
            - custom_css (dict): Optional CSS styling

    Returns:
        tuple: (html_string, key_bindings)
            html_string: Complete HTML for the textbox interface
            key_bindings: Empty list (no keyboard shortcuts)
    """
    logger.debug(f"Generating textbox layout for schema: {annotation_scheme['name']}")

    schema_name = annotation_scheme["name"]

    # Initialize form wrapper
    schematic = f"""
    <form id="{schema_name}" class="annotation-form textbox shadcn-textbox-container" action="/action_page.php">
        <fieldset schema_name="{schema_name}">
            <legend class="shadcn-textbox-title">{annotation_scheme["description"]}</legend>
    """

    # Handle custom CSS if provided
    display_info = annotation_scheme.get("display_config", {})
    custom_css = ""
    if "custom_css" in display_info:
        custom_css_parts = []
        for k, v in display_info["custom_css"].items():
            custom_css_parts.append(f"{k}: {v}")
        custom_css = "; ".join(custom_css_parts)

    # Set paste settings
    paste_setting = ''
    if "allow_paste" in annotation_scheme and annotation_scheme["allow_paste"] == False:
        paste_setting = 'onpaste="alert(\'Pasting is not allowed for the current study\');return false;"'

    # Handle multiple textboxes with different labels
    if "labels" not in annotation_scheme or annotation_scheme["labels"] == None:
        labels = ["text_box"]
    else:
        labels = annotation_scheme["labels"]

    # Generate input field(s) for each label
    for label in labels:
        name = f"{schema_name}:::{label}"
        class_name = schema_name
        validation = ""

        # Set validation if required
        label_requirement = annotation_scheme.get("label_requirement", {})
        if label_requirement and label_requirement.get("required"):
            validation = "required"
            logger.debug(f"Setting required validation for {name}")

        # Determine if using textarea
        is_textarea = False
        textarea_attrs = ""

        # Check for multiline flag (new format) or textarea.on (old format)
        if annotation_scheme.get("multiline") or annotation_scheme.get("textarea", {}).get("on"):
            is_textarea = True
            # Use multiline config or fall back to textarea config
            if annotation_scheme.get("multiline"):
                rows = annotation_scheme.get("rows", "3")
                cols = annotation_scheme.get("cols", "40")
            else:
                rows = annotation_scheme["textarea"].get("rows", "3")
                cols = annotation_scheme["textarea"].get("cols", "40")
            textarea_attrs = f"rows='{rows}' cols='{cols}'"

        # Show label if not the default text_box label
        label_text = "" if label == "text_box" else label

        schematic += f"""
            <div class="shadcn-textbox-item">
                {f'<label for="{name}" schema="{schema_name}" class="shadcn-textbox-label">{label_text}</label>' if label_text else ''}
        """

        if is_textarea:
            # Render textarea for multiline input
            schematic += f"""
                <textarea class="{class_name} shadcn-textbox-input shadcn-textbox-textarea annotation-input"
                          id="{name}"
                          name="{name}"
                          validation="{validation}"
                          schema="{schema_name}"
                          label_name="{label}"
                          {textarea_attrs}
                          style="{custom_css}"
                          {paste_setting}></textarea>
            """
        else:
            # Render input for single-line text
            schematic += f"""
                <input class="{class_name} shadcn-textbox-input annotation-input"
                       type="text"
                       id="{name}"
                       name="{name}"
                       validation="{validation}"
                       schema="{schema_name}"
                       label_name="{label}"
                       style="{custom_css}"
                       {paste_setting}>
            """

        schematic += "</div>"

    schematic += "</fieldset></form>"

    logger.info(f"Successfully generated textbox layout for {schema_name} with {len(labels)} fields")
    return schematic, []
