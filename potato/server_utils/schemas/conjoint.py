"""
Discrete Choice / Conjoint Analysis Layout

Present annotators with 2-4 product/concept profiles defined by attribute-level
combinations and ask them to choose the preferred one (or "none"). Enables estimation
of attribute importance through experimental design.

Research: Green & Srinivasan (1990); Louviere, Flynn & Marley (2015).
"""

import json
import logging

from .identifier_utils import (
    safe_generate_layout,
    generate_element_identifier,
    generate_validation_attribute,
    escape_html_content,
    generate_layout_attributes
)


logger = logging.getLogger(__name__)

DEFAULT_PROFILES_PER_SET = 3


def generate_conjoint_layout(annotation_scheme):
    """
    Generate HTML for a Discrete Choice / Conjoint Analysis interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - profiles_per_set: Number of profiles to show (2-4)
            - attributes: List of {name, levels} dicts
            - show_none_option: Whether to show "None of these" option
            - profiles_field: Data field with pre-specified profiles (null = generate)

    Returns:
        tuple: (html_string, key_bindings)
    """
    return safe_generate_layout(annotation_scheme, _generate_conjoint_layout_internal)


def _generate_conjoint_layout_internal(annotation_scheme):
    schema_name = annotation_scheme['name']
    description = annotation_scheme['description']
    profiles_per_set = annotation_scheme.get('profiles_per_set', DEFAULT_PROFILES_PER_SET)
    attributes = annotation_scheme.get('attributes', [])
    show_none_option = annotation_scheme.get('show_none_option', True)
    profiles_field = annotation_scheme.get('profiles_field', None)

    if not attributes and not profiles_field:
        raise ValueError(f"conjoint schema '{schema_name}' requires 'attributes' or 'profiles_field'")

    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)
    identifiers = generate_element_identifier(schema_name, schema_name, "radio")

    config_json = json.dumps({
        'profiles_per_set': profiles_per_set,
        'attributes': attributes,
        'profiles_field': profiles_field,
    })

    # Build profile cards (placeholder structure — populated by JS from data or generated)
    profile_cards_html = ""
    for i in range(profiles_per_set):
        profile_num = i + 1
        radio_id = f"{identifiers['id']}-profile-{profile_num}"

        # Build attribute rows placeholder
        attr_rows = ""
        for attr in attributes:
            attr_rows += f"""
                <tr class="conjoint-attr-row">
                    <td class="conjoint-attr-name">{escape_html_content(attr['name'])}</td>
                    <td class="conjoint-attr-value" data-attr="{escape_html_content(attr['name'])}" data-profile="{profile_num}">—</td>
                </tr>
            """

        profile_cards_html += f"""
            <div class="conjoint-profile-card" data-profile="{profile_num}">
                <div class="conjoint-profile-header">Option {profile_num}</div>
                <table class="conjoint-profile-table">
                    <tbody>
                        {attr_rows}
                    </tbody>
                </table>
                <div class="conjoint-profile-select">
                    <label class="conjoint-radio-label">
                        <input type="radio"
                               class="conjoint-radio annotation-input"
                               id="{radio_id}"
                               name="{identifiers['name']}"
                               schema="{identifiers['schema']}"
                               label_name="{identifiers['label_name']}"
                               validation="{validation}"
                               value="{profile_num}"
                               onclick="conjointSelect('{escape_html_content(schema_name)}', {profile_num})">
                        <span class="conjoint-select-text">Choose this</span>
                    </label>
                </div>
            </div>
        """

    none_option_html = ""
    if show_none_option:
        none_radio_id = f"{identifiers['id']}-none"
        none_option_html = f"""
            <div class="conjoint-none-option">
                <label class="conjoint-radio-label conjoint-none-label">
                    <input type="radio"
                           class="conjoint-radio annotation-input"
                           id="{none_radio_id}"
                           name="{identifiers['name']}"
                           schema="{identifiers['schema']}"
                           label_name="{identifiers['label_name']}"
                           validation="{validation}"
                           value="none"
                           onclick="conjointSelect('{escape_html_content(schema_name)}', 'none')">
                    <span class="conjoint-select-text">None of these</span>
                </label>
            </div>
        """

    html = f"""
    <form id="{escape_html_content(schema_name)}" class="annotation-form shadcn-conjoint-container"
          action="/action_page.php"
          data-annotation-id="{escape_html_content(str(annotation_scheme.get('annotation_id', '')))}"
          data-annotation-type="conjoint"
          data-schema-name="{escape_html_content(schema_name)}"
          data-profiles-field="{escape_html_content(profiles_field or '')}"
          {layout_attrs}>
        <fieldset schema_name="{escape_html_content(schema_name)}">
            <legend class="shadcn-conjoint-title">{escape_html_content(description)}</legend>

            <div class="conjoint-profiles" id="{schema_name}-profiles">
                {profile_cards_html}
            </div>

            {none_option_html}
        </fieldset>
    </form>

    <script>
    (function() {{
        var conjointConfig = {config_json};

        window.conjointSelect = function(schemaName, profileNum) {{
            // Update visual selection state
            var container = document.getElementById(schemaName);
            container.querySelectorAll('.conjoint-profile-card').forEach(function(card) {{
                card.classList.remove('conjoint-selected');
            }});
            if (profileNum !== 'none') {{
                var card = container.querySelector('.conjoint-profile-card[data-profile="' + profileNum + '"]');
                if (card) card.classList.add('conjoint-selected');
            }}
        }};
    }})();
    </script>
    """

    logger.info(f"Generated conjoint layout for {schema_name}")
    return html, []
