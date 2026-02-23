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

    # Check for options_from_data (dynamic multirate)
    options_from_data = annotation_scheme.get('options_from_data')
    if options_from_data and 'options' not in annotation_scheme:
        return _generate_dynamic_multirate(annotation_scheme, options_from_data)

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


# JavaScript template for dynamic multirate (options_from_data)
DYNAMIC_MULTIRATE_JS = """
<script>
(function() {
    var container = document.getElementById('dynamic-multirate-{{ schema_name }}');
    if (!container) return;
    var dataKey = container.getAttribute('data-options-from-data');
    var ratings = JSON.parse(container.getAttribute('data-ratings'));
    var schemaName = {{ schema_name_js }};
    var validation = {{ validation_js }};

    // Try to find instance data - look in various places
    function getInstanceData() {
        // Check for display field data attributes
        var fields = document.querySelectorAll('[data-field-key="' + dataKey + '"]');
        if (fields.length > 0) {
            var text = fields[0].textContent;
            try { return JSON.parse(text); } catch(e) {}
        }
        // Check for raw instance data in script tag
        var instanceScript = document.getElementById('instance');
        if (instanceScript) {
            try {
                var data = JSON.parse(instanceScript.textContent);
                if (data.text && typeof data.text === 'object') return data.text[dataKey];
            } catch(e) {}
        }
        return null;
    }

    function escapeHtml(str) {
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }
    function escapeAttr(str) {
        return str.replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }

    function buildTable(options) {
        if (!options || !Array.isArray(options) || options.length === 0) {
            container.innerHTML = '<p style="color:#666;font-style:italic">No dynamic options available for this instance.</p>';
            return;
        }
        var html = '<table class="shadcn-multirate-table"><thead><tr><th>&nbsp;</th>';
        for (var r = 0; r < ratings.length; r++) {
            html += '<th>' + escapeHtml(ratings[r]) + '</th>';
        }
        html += '</tr></thead><tbody>';
        for (var i = 0; i < options.length; i++) {
            var label = typeof options[i] === 'string' ? options[i] : (options[i].label || options[i].name || String(i));
            var safeName = schemaName + ':::' + label.replace(/[^a-zA-Z0-9_]/g, '_');
            html += '<tr schema="multirate"><td>' + escapeHtml(label) + '</td>';
            for (var r = 0; r < ratings.length; r++) {
                html += '<td class="shadcn-radio-cell"><input name="' + escapeAttr(safeName) +
                    '" type="radio" id="' + escapeAttr(safeName) + '.' + escapeAttr(ratings[r]) +
                    '" value="' + escapeAttr(ratings[r]) +
                    '" onclick="this.blur();" validation="' + escapeAttr(validation) +
                    '" class="shadcn-multirate-radio annotation-input" schema="' +
                    escapeAttr(schemaName) + '" label_name="' + escapeAttr(label) +
                    '" aria-label="' + escapeAttr(label + ': ' + ratings[r]) + '" /></td>';
            }
            html += '</tr>';
        }
        html += '</tbody></table>';
        container.querySelector('.dynamic-multirate-body').innerHTML = html;
    }

    // Build table from data attribute (server-injected)
    var preloadedData = container.getAttribute('data-options-values');
    if (preloadedData) {
        try { buildTable(JSON.parse(preloadedData)); } catch(e) { console.error('Dynamic multirate parse error:', e); }
    } else {
        var data = getInstanceData();
        if (data) buildTable(data);
    }
})();
</script>
"""

DYNAMIC_MULTIRATE_TEMPLATE = """
<form id="{{ schema_name }}" class="annotation-form multirate shadcn-multirate-container"
      action="/action_page.php" data-annotation-id="{{ annotation_id }}" {{ layout_attrs }}>
    <fieldset schema="{{ schema_name }}">
        <legend class="shadcn-multirate-title">{{ description }}</legend>
        <div id="dynamic-multirate-{{ schema_name }}"
             class="dynamic-multirate-container"
             data-options-from-data="{{ data_key }}"
             data-ratings='{{ ratings_json }}'
             data-options-values='{{ options_values_json }}'>
            <div class="dynamic-multirate-body">
                <p style="color:#666;font-style:italic">Loading options from instance data...</p>
            </div>
        </div>
    </fieldset>
</form>
"""


def _generate_dynamic_multirate(annotation_scheme, options_from_data):
    """
    Generate a dynamic multirate layout that reads options from instance data.

    The generated HTML includes a JavaScript snippet that populates the multirate
    table at page load time using data from the instance's specified field.

    Args:
        annotation_scheme: Schema configuration dict
        options_from_data: Name of the instance data field containing options

    Returns:
        tuple: (html_string, key_bindings)
    """
    import json
    import html as html_module

    schema_name = annotation_scheme['name']
    description = annotation_scheme.get('description', '')
    ratings = annotation_scheme.get('labels', [])
    validation = generate_validation_attribute(annotation_scheme)
    layout_attrs = generate_layout_attributes(annotation_scheme)

    ratings_json = json.dumps(ratings)

    template_data = {
        'schema_name': escape_html_content(schema_name),
        'description': escape_html_content(description),
        'data_key': escape_html_content(options_from_data),
        'ratings_json': html_module.escape(ratings_json),
        'options_values_json': '[]',  # Will be filled by server at render time
        'annotation_id': annotation_scheme.get('annotation_id', ''),
        'layout_attrs': layout_attrs,
        'validation': validation,
        # JS-safe values using json.dumps to produce quoted strings
        'schema_name_js': json.dumps(schema_name),
        'validation_js': json.dumps(validation),
    }

    template = Template(DYNAMIC_MULTIRATE_TEMPLATE + DYNAMIC_MULTIRATE_JS)
    html = template.render(**template_data)

    logger.info(f"Generated dynamic multirate for {schema_name} "
                f"reading options from '{options_from_data}'")

    return html, []


def populate_dynamic_multirate(html_str, instance_data):
    """
    Post-process rendered HTML to inject instance-specific options into
    dynamic multirate schemas.

    Called from render_page_with_annotations() after template rendering.

    Args:
        html_str: The rendered HTML string
        instance_data: The instance data dictionary

    Returns:
        Modified HTML string with dynamic multirate options populated
    """
    import json
    import re
    import html as html_module

    # Find all dynamic multirate containers
    pattern = r'data-options-from-data="([^"]+)"'
    matches = list(re.finditer(pattern, html_str))

    # Process in reverse order so earlier match offsets remain valid
    for match in reversed(matches):
        data_key = html_module.unescape(match.group(1))
        options = instance_data.get(data_key, [])

        if options and isinstance(options, list):
            # Use html.escape on the JSON to safely embed in a single-quoted attribute
            options_attr = html_module.escape(json.dumps(options))
            # Search for the placeholder attribute near this match
            search_start = max(0, match.start() - 200)
            search_end = min(len(html_str), match.end() + 500)
            local_html = html_str[search_start:search_end]

            old_attr = "data-options-values='[]'"
            if old_attr in local_html:
                html_str = html_str[:search_start] + local_html.replace(
                    old_attr,
                    f"data-options-values='{options_attr}'",
                    1,  # Replace only the first occurrence in this window
                ) + html_str[search_end:]

    return html_str