"""
Pure Display Layout

Generates a simple display-only interface that shows text content without any
interaction elements. This is useful for:
- Displaying instructions
- Showing static content
- Presenting read-only information
- Headers and section dividers

Supports an optional `allow_html: true` flag that lets administrators include
trusted HTML formatting (e.g., <b>, <br>, <ul>) in description and labels.
When enabled, content is sanitized through the project's HTML sanitizer to
block dangerous elements while preserving safe formatting.
"""

import logging
from .identifier_utils import (
    safe_generate_layout,
    escape_html_content,
    generate_layout_attributes
)

logger = logging.getLogger(__name__)


def _sanitize_or_escape(content: str, allow_html: bool) -> str:
    """
    Sanitize or escape content based on the allow_html flag.

    When allow_html is True, uses the project's HTML sanitizer which allows
    safe elements (b, i, u, em, strong, br, span, div, ul, ol, li, etc.)
    while blocking scripts and dangerous attributes.

    When allow_html is False (default), fully escapes all HTML.
    """
    if not content:
        return ""
    if allow_html:
        from potato.server_utils.html_sanitizer import sanitize_html
        return str(sanitize_html(str(content)))
    return escape_html_content(content)


def generate_pure_display_layout(annotation_scheme):
    """
    Generate HTML for a display-only text interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Main text to display as header
            - labels: List of text strings to display as content
            - allow_html: (optional, default False) If True, allows trusted
              HTML in description and labels (sanitized for safety)

    Returns:
        tuple: (html_string, key_bindings)
            html_string: Complete HTML for the display interface
            key_bindings: Empty list (no interactions available)

    Example:
        annotation_scheme = {
            "name": "instructions",
            "description": "Task Instructions",
            "labels": ["Step 1: Read the text", "Step 2: Select options"]
        }

    Example with HTML:
        annotation_scheme = {
            "name": "consent_header",
            "description": "<b>Consent Form</b>",
            "labels": ["Please read the <em>following</em> carefully."],
            "allow_html": True
        }
    """
    return safe_generate_layout(annotation_scheme, _generate_pure_display_layout_internal)

def _generate_pure_display_layout_internal(annotation_scheme):
    """
    Internal function to generate pure display layout after validation.
    """
    logger.debug(f"Generating pure display layout for schema: {annotation_scheme['name']}")

    allow_html = annotation_scheme.get('allow_html', False)

    # Get layout attributes for grid positioning
    layout_attrs = generate_layout_attributes(annotation_scheme)

    # Name is always escaped (used in HTML attributes, not content)
    escaped_name = escape_html_content(annotation_scheme['name'])

    # Description and labels respect allow_html flag
    description = _sanitize_or_escape(annotation_scheme['description'], allow_html)

    # Format content with header and body text
    schematic = f"""
        <form id="{escaped_name}" class="annotation-form pure-display" action="/action_page.php" {layout_attrs}>
            <fieldset schema="{escaped_name}">
                <legend>{description}</legend>
                <div class="display-content">
                    {format_display_content(annotation_scheme.get('labels', []), allow_html)}
                </div>
            </fieldset>
        </form>
    """

    logger.info(f"Successfully generated pure display layout for {annotation_scheme['name']}")
    return schematic, []

def format_display_content(labels, allow_html=False):
    """
    Format the display content from a list of labels.

    Args:
        labels (list): List of strings to display
        allow_html (bool): If True, sanitize rather than escape HTML content

    Returns:
        str: HTML formatted content with line breaks between items
    """
    if not labels:
        logger.warning("No labels provided for pure display content")
        return ""

    logger.debug(f"Formatting {len(labels)} content lines")
    processed_labels = [_sanitize_or_escape(label, allow_html) for label in labels]
    return "<br>".join(processed_labels)
