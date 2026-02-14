"""
Select Layout
"""

import os
from pathlib import Path

from potato.ai.ai_help_wrapper import get_ai_wrapper, get_dynamic_ai_help
from .identifier_utils import (
    safe_generate_layout,
    generate_element_identifier,
    generate_validation_attribute,
    escape_html_content,
    generate_layout_attributes
)


def generate_select_layout(annotation_scheme):
    """
    Generate HTML for a select dropdown interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - labels: List of options or path to file containing options
            - use_predefined_labels: Use predefined label sets (country, ethnicity, religion)
            - label_requirement (dict): Optional validation settings
                - required (bool): Whether selection is mandatory

    Returns:
        tuple: (html_string, key_bindings)
            html_string: Complete HTML for the select interface
            key_bindings: Empty list (no keyboard shortcuts)
    """
    return safe_generate_layout(annotation_scheme, _generate_select_layout_internal)

def _generate_select_layout_internal(annotation_scheme):
    """
    Internal function to generate select layout after validation.
    """
    # Generate consistent identifiers
    identifiers = generate_element_identifier(annotation_scheme["name"], "select-one", "select")
    validation = generate_validation_attribute(annotation_scheme)

    # Get layout attributes for grid positioning
    layout_attrs = generate_layout_attributes(annotation_scheme)

    schematic = (
          f'<form id="{escape_html_content(annotation_scheme["name"])}" class="annotation-form select" action="/action_page.php" data-annotation-id="{annotation_scheme["annotation_id"]}" data-annotation-type="select" data-schema-name="{escape_html_content(annotation_scheme["name"])}" {layout_attrs}>     {get_ai_wrapper()}'
        + "  <fieldset>"
        + f"  <legend>{escape_html_content(annotation_scheme['description'])}</legend>"
        + (
            f'  <select type="select-one" class="{escape_html_content(annotation_scheme["description"])} annotation-input" '
            f'id="{identifiers["id"]}" name="{identifiers["name"]}" validation="{validation}" '
            f'schema="{identifiers["schema"]}" label_name="{identifiers["label_name"]}">'
        )
    )

    cur_program_dir = Path(os.path.abspath(__file__)).parent.parent.parent.absolute()  # get the current program dir (for the case of pypi, it will be the path where potato is installed)
    predefined_labels_dict = {
        "country": os.path.join(cur_program_dir, "static/survey_assets/country_dropdown_list.html"),
        "ethnicity": os.path.join(cur_program_dir, "static/survey_assets/ethnicity_dropdown_list.html"),
        "religion": os.path.join(cur_program_dir, "static/survey_assets/religion_dropdown_list.html"),
    }

    # directly use the predefined labels if annotation_scheme["use_predefined_labels"] is defined
    if (
        "use_predefined_labels" in annotation_scheme
        and annotation_scheme["use_predefined_labels"] in predefined_labels_dict
    ):
        with open(predefined_labels_dict[annotation_scheme["use_predefined_labels"]]) as r:
            schematic += r.read()

    else:
        # if annotation_scheme['labels'] is defined as a path
        if type(annotation_scheme["labels"]) == str and os.path.exists(annotation_scheme["labels"]):
            with open(annotation_scheme["labels"], "r") as r:
                labels = [it.strip() for it in r.readlines()]
        else:
            labels = annotation_scheme["labels"]

        for i, label_data in enumerate(labels, 1):
            label = label_data if isinstance(label_data, str) else label_data["name"]
            option_identifiers = generate_element_identifier(annotation_scheme["name"], label, "option")
            label_content = label

            schematic += f'<option class="{option_identifiers["schema"]}" id="{option_identifiers["id"]}" '
            schematic += f'name="{option_identifiers["name"]}" value="{escape_html_content(label_content)}">'
            schematic += f'{escape_html_content(label_content)}</option>'

    schematic += "  </select>\n</fieldset>\n</form>\n"
    return schematic, []
