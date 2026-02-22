"""
Multirate Layout

Generates a matrix-style interface for rating multiple items on the same scale.
Features include:
- Multiple column layout support
- Configurable rating options
- Vertical/horizontal arrangement options
- Tooltip support
- Required/optional validation
"""

import logging
import os
from collections.abc import Mapping
from jinja2 import Template
from .identifier_utils import (
    safe_generate_layout,
    generate_element_identifier,
    generate_validation_attribute,
    escape_html_content,
    generate_layout_attributes
)

logger = logging.getLogger(__name__)

# HTML template using Jinja2 with comprehensive styling that preserves horizontal layout
MULTIRATE_TEMPLATE = """
<form id="{{ schema_name }}" class="annotation-form multirate shadcn-multirate-container" action="/action_page.php" data-annotation-id="{{ annotation_id }}" {{ layout_attrs }}>
    <fieldset schema="{{ schema_name }}">
        <legend class="shadcn-multirate-title">{{ description }}</legend>
        <table class="shadcn-multirate-table">
            <thead>
                <tr>
                    {% for col in range(num_headers) %}
                        <th>&nbsp;</th>
                        {% for rating in ratings %}
                            <th>{{ rating }}</th>
                        {% endfor %}
                    {% endfor %}
                </tr>
            </thead>
            <tbody>
                {% for row in rows %}
                    <tr schema="multirate">
                        {% for item in row %}
                            {% if item %}
                                <td {{ item.tooltip|safe }}>{{ item.label }}</td>
                                {% for rating in ratings %}
                                    <td class="shadcn-radio-cell">
                                        <input name="{{ item.name }}"
                                               type="radio"
                                               id="{{ item.id }}.{{ rating }}"
                                               value="{{ rating }}"
                                               onclick="this.blur();"
                                               validation="{{ validation }}"
                                               class="shadcn-multirate-radio annotation-input"
                                               schema="{{ schema_name }}"
                                               label_name="{{ item.label_name }}"
                                               aria-label="{{ item.label }}: {{ rating }}" />
                                    </td>
                                {% endfor %}
                            {% else %}
                                <td></td>
                                {% for rating in ratings %}
                                    <td></td>
                                {% endfor %}
                            {% endif %}
                        {% endfor %}
                    </tr>
                {% endfor %}
            </tbody>
        </table>
    </fieldset>
</form>
"""

def generate_multirate_layout(annotation_scheme):
    """
    Generate HTML for a multi-item rating interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - options: List of items to be rated
            - labels: List of rating options to choose from
            - display_config (dict): Optional display settings
            - arrangement (str): Layout direction ('vertical' or 'horizontal')
            - label_requirement (dict): Optional validation settings

    Returns:
        tuple: (html_string, key_bindings)
            html_string: Complete HTML for the multirate interface
            key_bindings: List of (key, description) tuples for keyboard shortcuts
    """
    return safe_generate_layout(annotation_scheme, _generate_multirate_layout_internal)

def _generate_multirate_layout_internal(annotation_scheme):
    """
    Internal function to generate multirate layout after validation.
    """
    logger.debug(f"Generating multirate layout for schema: {annotation_scheme['name']}")

    # Extract configuration
    schema_name = annotation_scheme['name']
    description = annotation_scheme['description']
    options = annotation_scheme['options']
    ratings = annotation_scheme['labels']

    # Get display configuration
    display_config = annotation_scheme.get('display_config', {})
    num_columns = display_config.get('num_columns', 1)

    # Set validation
    validation = generate_validation_attribute(annotation_scheme)

    # Get layout attributes for grid positioning
    layout_attrs = generate_layout_attributes(annotation_scheme)

    # Preprocess items for template
    processed_items = []
    for option in options:
        if isinstance(option, str):
            identifiers = generate_element_identifier(schema_name, option, "multirate")
            processed_items.append({
                'label': escape_html_content(option),
                'name': identifiers['name'],
                'id': identifiers['id'],
                'label_name': identifiers['label_name'],
                'tooltip': ""
            })
        else:
            identifiers = generate_element_identifier(schema_name, option['name'], "multirate")
            processed_items.append({
                'label': escape_html_content(option['label']),
                'name': identifiers['name'],
                'id': identifiers['id'],
                'label_name': identifiers['label_name'],
                'tooltip': _generate_tooltip(option)
            })

    # Arrange items according to specified layout
    if annotation_scheme.get('arrangement') == 'vertical':
        arranged_items = _arrange_items_vertically(processed_items, num_columns)
    else:
        arranged_items = _arrange_items_horizontally(processed_items, num_columns)

    # Format template data
    template_data = {
        'schema_name': escape_html_content(schema_name),
        'description': escape_html_content(description),
        'ratings': [escape_html_content(rating) for rating in ratings],
        'num_headers': min(len(options), num_columns),
        'rows': arranged_items,
        'validation': validation,
        'annotation_id': annotation_scheme.get('annotation_id', ''),
        'layout_attrs': layout_attrs
    }

    # Render template
    template = Template(MULTIRATE_TEMPLATE)
    html = template.render(**template_data)

    logger.info(f"Successfully generated multirate layout for {schema_name} "
                f"with {len(options)} items and {len(ratings)} rating options")

    return html, []  # No key bindings implemented


def _arrange_items_horizontally(items, num_columns):
    """
    Arrange items in a horizontal layout with specified number of columns.

    Args:
        items (list): List of processed item dictionaries
        num_columns (int): Number of columns

    Returns:
        list: List of rows, where each row is a list of items
    """
    rows = []
    for i in range(0, len(items), num_columns):
        row = items[i:i+num_columns]
        # Pad the row if it's not full
        while len(row) < num_columns:
            row.append(None)
        rows.append(row)
    return rows


def _arrange_items_vertically(items, num_columns):
    """
    Rearrange items for vertical column layout.

    Args:
        items (list): List of processed item dictionaries
        num_columns (int): Number of columns

    Returns:
        list: List of rows, where each row is a list of items arranged vertically
    """
    logger.debug(f"Rearranging {len(items)} items into {num_columns} vertical columns")

    # Calculate rows needed
    num_rows = (len(items) + num_columns - 1) // num_columns  # Ceiling division

    # Distribute items into columns
    columns = [[] for _ in range(num_columns)]
    for i, item in enumerate(items):
        col_idx = i // num_rows
        if col_idx < num_columns:
            columns[col_idx].append(item)

    # Create rows from columns
    rows = []
    for row_idx in range(num_rows):
        row = []
        for col in columns:
            row.append(col[row_idx] if row_idx < len(col) else None)
        rows.append(row)

    return rows


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