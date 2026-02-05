"""
HTML Sanitizer Module

Provides XSS-safe HTML sanitization for the annotation platform. This module
allows legitimate span annotation HTML while blocking potentially dangerous
elements and attributes.

The sanitizer uses an allowlist approach - only explicitly permitted elements
and attributes are kept, everything else is escaped or removed.

Usage:
    from potato.server_utils.html_sanitizer import sanitize_html

    # In Jinja2 template:
    {{ instance | sanitize_html }}
"""

import re
import html
import logging
from typing import Set, Dict, List, Tuple
from markupsafe import Markup

logger = logging.getLogger(__name__)

# Elements allowed in sanitized HTML
ALLOWED_ELEMENTS: Set[str] = {
    # Span annotations
    'span',
    # Basic formatting (may be in source data)
    'b', 'i', 'u', 'strong', 'em', 'mark',
    # Line breaks
    'br',
    # Dialogue/conversation layout elements
    'div',
}

# Attributes allowed per element
ALLOWED_ATTRIBUTES: Dict[str, Set[str]] = {
    'span': {
        'class',
        'style',
        'data-annotation-id',
        'data-label',
        'schema',
        'title',
    },
    'div': {
        'class',
        'style',
        'data-speaker',
        'data-speaker-index',
    },
    'mark': {'class', 'style'},
    # Most elements get no attributes
    '*': set(),
}

# Allowed CSS properties in style attributes
ALLOWED_CSS_PROPERTIES: Set[str] = {
    'background-color',
    'color',
    'font-weight',
    'font-style',
    'text-decoration',
    # Layout properties for dialogue/pairwise display
    'display',
    'width',
    'padding',
    'margin',
    'box-sizing',
    'vertical-align',
    'gap',
}

# Dangerous patterns to block
DANGEROUS_PATTERNS = [
    re.compile(r'javascript:', re.IGNORECASE),
    re.compile(r'vbscript:', re.IGNORECASE),
    re.compile(r'data:', re.IGNORECASE),
    re.compile(r'expression\s*\(', re.IGNORECASE),
]


def sanitize_html(text: str) -> Markup:
    """
    Sanitize HTML content while preserving legitimate span annotations.

    This function:
    1. Parses HTML using regex (lightweight, no external deps)
    2. Allows only whitelisted elements and attributes
    3. Sanitizes style attributes to only allow safe CSS
    4. Escapes all other content

    Args:
        text: The HTML content to sanitize

    Returns:
        Markup: Sanitized HTML safe for rendering (wrapped in Markup to prevent
                double-escaping by Jinja2's auto-escape)

    Example:
        >>> sanitize_html('<span class="span-highlight">text</span>')
        Markup('<span class="span-highlight">text</span>')

        >>> sanitize_html('<script>alert("xss")</script>')
        Markup('&lt;script&gt;alert("xss")&lt;/script&gt;')
    """
    if not text:
        return Markup("")

    # Check for dangerous patterns in the raw text
    for pattern in DANGEROUS_PATTERNS:
        if pattern.search(text):
            logger.warning(f"Blocked dangerous pattern in HTML content")
            text = pattern.sub('', text)

    result = []
    pos = 0

    # Regex to find HTML tags
    tag_pattern = re.compile(
        r'<(/?)(\w+)([^>]*)(/?)>',
        re.IGNORECASE | re.DOTALL
    )

    for match in tag_pattern.finditer(text):
        # Add escaped text before this tag
        if match.start() > pos:
            result.append(html.escape(text[pos:match.start()]))

        is_close = match.group(1) == '/'
        tag_name = match.group(2).lower()
        attrs_str = match.group(3)
        is_self_close = match.group(4) == '/'

        if tag_name in ALLOWED_ELEMENTS:
            # Build sanitized tag
            if is_close:
                result.append(f'</{tag_name}>')
            else:
                sanitized_attrs = _sanitize_attributes(tag_name, attrs_str)
                if is_self_close:
                    result.append(f'<{tag_name}{sanitized_attrs} />')
                else:
                    result.append(f'<{tag_name}{sanitized_attrs}>')
        else:
            # Escape the entire tag
            result.append(html.escape(match.group(0)))

        pos = match.end()

    # Add remaining text (escaped)
    if pos < len(text):
        result.append(html.escape(text[pos:]))

    # Return as Markup to prevent Jinja2's auto-escape from escaping again
    return Markup(''.join(result))


def _sanitize_attributes(tag_name: str, attrs_str: str) -> str:
    """
    Sanitize attributes for a given tag.

    Args:
        tag_name: The tag name (lowercase)
        attrs_str: The raw attributes string

    Returns:
        str: Sanitized attributes string (with leading space if non-empty)
    """
    if not attrs_str or not attrs_str.strip():
        return ""

    # Get allowed attributes for this tag
    allowed = ALLOWED_ATTRIBUTES.get(tag_name, ALLOWED_ATTRIBUTES.get('*', set()))

    # Parse attributes
    attr_pattern = re.compile(
        r'''(\w+(?:-\w+)*)\s*=\s*(?:"([^"]*)"|'([^']*)'|(\S+))''',
        re.IGNORECASE
    )

    sanitized = []
    for match in attr_pattern.finditer(attrs_str):
        attr_name = match.group(1).lower()
        # Get value from whichever group matched
        attr_value = match.group(2) or match.group(3) or match.group(4) or ""

        if attr_name not in allowed:
            continue

        # Special handling for style attribute
        if attr_name == 'style':
            attr_value = _sanitize_style(attr_value)
            if not attr_value:
                continue

        # Special handling for class attribute
        if attr_name == 'class':
            attr_value = _sanitize_class(attr_value)

        # Escape the value
        escaped_value = html.escape(attr_value, quote=True)
        sanitized.append(f'{attr_name}="{escaped_value}"')

    if sanitized:
        return ' ' + ' '.join(sanitized)
    return ""


def _sanitize_style(style: str) -> str:
    """
    Sanitize a CSS style attribute.

    Only allows specific CSS properties that are known to be safe.

    Args:
        style: The style attribute value

    Returns:
        str: Sanitized style string
    """
    if not style:
        return ""

    # Check for dangerous patterns
    for pattern in DANGEROUS_PATTERNS:
        if pattern.search(style):
            logger.warning("Blocked dangerous pattern in style attribute")
            return ""

    sanitized_props = []

    # Parse CSS properties
    for prop in style.split(';'):
        prop = prop.strip()
        if not prop:
            continue

        if ':' not in prop:
            continue

        name, value = prop.split(':', 1)
        name = name.strip().lower()
        value = value.strip()

        if name in ALLOWED_CSS_PROPERTIES:
            # Basic value validation - no functions except safe color functions
            if 'url(' in value.lower():
                continue
            sanitized_props.append(f'{name}: {value}')

    return '; '.join(sanitized_props)


def _sanitize_class(class_str: str) -> str:
    """
    Sanitize a class attribute.

    Only allows alphanumeric characters, hyphens, and underscores.

    Args:
        class_str: The class attribute value

    Returns:
        str: Sanitized class string
    """
    if not class_str:
        return ""

    # Split into individual classes
    classes = class_str.split()

    # Filter to safe class names
    safe_pattern = re.compile(r'^[a-zA-Z_-][a-zA-Z0-9_-]*$')
    safe_classes = [c for c in classes if safe_pattern.match(c)]

    return ' '.join(safe_classes)


def escape_for_attribute(text: str) -> str:
    """
    Escape text for use in an HTML attribute.

    This is a stricter escape than html.escape() - it also escapes
    backticks and other characters that could be used in template injection.

    Args:
        text: The text to escape

    Returns:
        str: Escaped text safe for attribute values
    """
    if not text:
        return ""

    return (
        html.escape(text, quote=True)
        .replace('`', '&#96;')
        .replace('$', '&#36;')
    )


# Register as Jinja2 filter
def register_jinja_filters(app):
    """
    Register HTML sanitization filters with a Flask app.

    Call this during app initialization:
        from potato.server_utils.html_sanitizer import register_jinja_filters
        register_jinja_filters(app)

    Args:
        app: Flask application instance
    """
    app.jinja_env.filters['sanitize_html'] = sanitize_html
    app.jinja_env.filters['escape_attr'] = escape_for_attribute
    logger.info("Registered HTML sanitization Jinja2 filters")
