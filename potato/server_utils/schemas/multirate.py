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
from collections.abc import Mapping

logger = logging.getLogger(__name__)

def generate_multirate_layout(annotation_scheme):
    """
    Generate HTML for a multi-item rating interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - options: List of items to be rated, each either:
                - str: Simple item text
                - dict: Complex item with:
                    - name: Item identifier
                    - label: Display text
                    - tooltip: Hover text description
                    - tooltip_file: Path to tooltip text file
            - labels: List of rating options to choose from
            - display_config (dict): Optional display settings
                - num_columns: Number of columns (default: 1)
            - arrangement (str): Layout direction ('vertical' or 'horizontal')
            - label_requirement (dict): Optional validation settings
                - required (bool): Whether ratings are mandatory

    Returns:
        tuple: (html_string, key_bindings)
            html_string: Complete HTML for the multirate interface
            key_bindings: List of (key, description) tuples for keyboard shortcuts
    """
    logger.debug(f"Generating multirate layout for schema: {annotation_scheme['name']}")

    # Initialize form wrapper
    schematic = f"""
        <form id="{annotation_scheme['name']}" class="annotation-form multirate" action="/action_page.php">
            <fieldset schema="{annotation_scheme['name']}">
                <legend>{annotation_scheme['description']}</legend>
                <table>
    """

    # Setup validation and key bindings
    key_bindings = []
    validation = ""
    if annotation_scheme.get("label_requirement", {}).get("required"):
        validation = "required"
        logger.debug("Setting required validation")

    # Get display configuration
    display_info = annotation_scheme.get("display_config", {})
    n_columns = display_info.get("num_columns", 1)
    logger.debug(f"Using {n_columns} column layout")

    # Generate header row with rating options
    ratings = annotation_scheme["labels"]
    num_headers = min(len(annotation_scheme["options"]), n_columns)

    schematic += "<tr>"
    for _ in range(num_headers):
        schematic += "<td>&nbsp;</td>"
        for rating in ratings:
            schematic += f"<td>&nbsp;{rating}&nbsp;</td>"
    schematic += "</tr>"

    # Handle item arrangement
    options = annotation_scheme["options"]
    if annotation_scheme.get('arrangement') == 'vertical':
        options = _arrange_items_vertically(options, n_columns)
        logger.debug("Using vertical arrangement for items")

    # Generate rating rows for each item
    for i, label_data in enumerate(options, 1):
        if (i - 1) % n_columns == 0:
            schematic += '<tr schema="multirate">'

        # Extract item information
        label = label_data if isinstance(label_data, str) else label_data["label"]
        option = label_data if isinstance(label_data, str) else label_data["name"]
        name = f"{annotation_scheme['name']}:::{option}"

        # Handle tooltips
        tooltip = _generate_tooltip(label_data) if isinstance(label_data, Mapping) else ""

        # Generate rating inputs for this item
        schematic += f'<td style="text-align:right; vertical-align: middle;">{label}</td>'
        for rating in ratings:
            input_id = f"{name}.{rating}"
            schematic += f"""
                <td style="text-align:center;">
                    <input name="{name}"
                           type="radio"
                           id="{input_id}"
                           value="{rating}"
                           onclick="onlyOne(this);this.blur();"
                           validation="{validation}"
                           style="vertical-align: middle; margin: 0px;"/>
                </td>
            """

        if i % n_columns == 0:
            schematic += "</tr>"

    schematic += "</table></fieldset></form>"

    logger.info(f"Successfully generated multirate layout for {annotation_scheme['name']} "
                f"with {len(options)} items and {len(ratings)} rating options")
    return schematic, key_bindings

def _arrange_items_vertically(options, n_columns):
    """
    Rearrange items for vertical column layout.

    Args:
        options (list): List of items to arrange
        n_columns (int): Number of columns to use

    Returns:
        list: Rearranged items for vertical layout
    """
    logger.debug(f"Rearranging {len(options)} items into {n_columns} vertical columns")

    # Calculate rows needed
    n_rows = len(options) // n_columns
    if (len(options) % n_columns) > 0:
        n_rows += 1

    # Distribute items into columns
    cols = [[] for _ in range(n_columns)]
    col_idx = 0
    for i, opt in enumerate(options):
        if i > 0 and i % n_rows == 0:
            col_idx += 1
        cols[col_idx].append(opt)

    # Reconstruct list in vertical order
    reordered_options = []
    for row in range(n_rows):
        for col in cols:
            if row < len(col):
                reordered_options.append(col[row])

    return reordered_options

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
