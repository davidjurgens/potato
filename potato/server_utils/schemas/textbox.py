"""
Textbox Layout
"""

import logging

from ai.ai_help_wrapper import get_ai_wrapper, get_dynamic_ai_help
from .identifier_utils import (
    safe_generate_layout,
    generate_element_identifier,
    generate_validation_attribute,
    escape_html_content
)


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
    return safe_generate_layout(annotation_scheme, _generate_textbox_layout_internal)

def _generate_textbox_layout_internal(annotation_scheme):
    """
    Internal function to generate textbox layout after validation.
    """
    logger.debug(f"Generating textbox layout for schema: {annotation_scheme['name']}")

    # Initialize form wrapper
    schematic = f"""
    <form id="{escape_html_content(annotation_scheme['name'])}" class="annotation-form textbox shadcn-textbox-container" action="/action_page.php" data-annotation-id="{annotation_scheme["annotation_id"]}">
            {get_ai_wrapper()}
        <fieldset schema_name="{escape_html_content(annotation_scheme['name'])}">
            <legend class="shadcn-textbox-title">{escape_html_content(annotation_scheme["description"])}</legend>
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
        # Generate consistent identifiers
        identifiers = generate_element_identifier(annotation_scheme["name"], label, "text")
        validation = generate_validation_attribute(annotation_scheme)

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
                {f'<label for="{identifiers["id"]}" schema="{identifiers["schema"]}" class="shadcn-textbox-label">{escape_html_content(label_text)}</label>' if label_text else ''}
        """

        if is_textarea:
            # Render textarea for multiline input
            schematic += f"""
                <textarea class="{identifiers['schema']} shadcn-textbox-input shadcn-textbox-textarea annotation-input"
                          id="{identifiers['id']}"
                          name="{identifiers['name']}"
                          validation="{validation}"
                          schema="{identifiers['schema']}"
                          label_name="{identifiers['label_name']}"
                          {textarea_attrs}
                          style="{custom_css}"
                          {paste_setting}></textarea>
            """
        else:
            # Render input for single-line text
            schematic += f"""
                <input class="{identifiers['schema']} shadcn-textbox-input annotation-input"
                       type="text"
                       id="{identifiers['id']}"
                       name="{identifiers['name']}"
                       validation="{validation}"
                       schema="{identifiers['schema']}"
                       label_name="{identifiers['label_name']}"
                       style="{custom_css}"
                       {paste_setting}>
            """

        schematic += "</div>"

    schematic += "</fieldset></form>"

    logger.debug(f"Generated textbox schematic for {annotation_scheme['name']}")
    logger.info(f"Successfully generated textbox layout for {annotation_scheme['name']} with {len(labels)} fields")
    return schematic, []
