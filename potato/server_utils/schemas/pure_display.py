"""
Pure Display Layout

Generates a simple display-only interface that shows text content without any
interaction elements. This is useful for:
- Displaying instructions
- Showing static content
- Presenting read-only information
- Headers and section dividers
"""

import logging

logger = logging.getLogger(__name__)

def generate_pure_display_layout(annotation_scheme):
    """
    Generate HTML for a display-only text interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Main text to display as header
            - labels: List of text strings to display as content

    Returns:
        tuple: (html_string, key_bindings)
            html_string: Complete HTML for the display interface
            key_bindings: None (no interactions available)

    Example:
        annotation_scheme = {
            "name": "instructions",
            "description": "Task Instructions",
            "labels": ["Step 1: Read the text", "Step 2: Select options"]
        }
    """
    logger.debug(f"Generating pure display layout for schema: {annotation_scheme['name']}")

    # Format content with header and body text
    schematic = f"""
        <form id="{annotation_scheme['name']}" class="annotation-form pure-display" action="/action_page.php">
            <fieldset schema="{annotation_scheme['name']}">
                <legend>{annotation_scheme['description']}</legend>
                <div class="display-content">
                    {format_display_content(annotation_scheme.get('labels', []))}
                </div>
            </fieldset>
        </form>
    """

    logger.info(f"Successfully generated pure display layout for {annotation_scheme['name']}")
    return schematic, None

def format_display_content(labels):
    """
    Format the display content from a list of labels.

    Args:
        labels (list): List of strings to display

    Returns:
        str: HTML formatted content with line breaks between items
    """
    if not labels:
        logger.warning("No labels provided for pure display content")
        return ""

    logger.debug(f"Formatting {len(labels)} content lines")
    return "<br>".join(labels)
