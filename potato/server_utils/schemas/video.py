"""
Video Layout

Generates a form interface for displaying video content. Features include:
- Custom video player controls
- Autoplay options
- Loop control
- Muting options
- Custom CSS styling
- Multiple video source support
- Fallback content support
"""

import logging
import os.path
from .identifier_utils import (
    safe_generate_layout,
    escape_html_content
)

logger = logging.getLogger(__name__)

def generate_video_layout(annotation_scheme):
    """
    Generate HTML for a video player interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - video_path: Path to video file
            - custom_css (dict): Optional CSS styling
                - width: Video width (default: "320")
                - height: Video height (default: "240")
            - autoplay (bool): Whether to start playing automatically
            - loop (bool): Whether to loop video playback
            - muted (bool): Whether to mute audio by default
            - controls (bool): Whether to show player controls
            - fallback_text (str): Optional text to show if video fails
            - additional_sources (list): Optional additional video formats

    Returns:
        tuple: (html_string, key_bindings)
            html_string: Complete HTML for the video interface
            key_bindings: Empty list (no keyboard shortcuts)

    Raises:
        ValueError: If video_path is missing or invalid
    """
    return safe_generate_layout(annotation_scheme, _generate_video_layout_internal)

def _generate_video_layout_internal(annotation_scheme):
    """
    Internal function to generate video layout after validation.
    """
    logger.debug(f"Generating video layout for schema: {annotation_scheme['name']}")

    # Validate video path
    if "video_path" not in annotation_scheme:
        error_msg = f"Missing video_path in schema: {annotation_scheme['name']}"
        logger.error(error_msg)
        raise ValueError(error_msg)

    if not os.path.exists(annotation_scheme["video_path"]):
        error_msg = f"Video file not found: {annotation_scheme['video_path']}"
        logger.error(error_msg)
        raise ValueError(error_msg)

    # Initialize form wrapper
    schematic = f"""
        <form id="{escape_html_content(annotation_scheme['name'])}" class="annotation-form video" action="/action_page.php">
            <fieldset schema="{escape_html_content(annotation_scheme['name'])}">
                <legend>{escape_html_content(annotation_scheme['description'])}</legend>
    """

    # Generate video element with attributes
    video_attrs = _generate_video_attributes(annotation_scheme)
    css = _generate_css_style(annotation_scheme)

    schematic += f"""
        <video {video_attrs} style="{css}">
            {_generate_video_sources(annotation_scheme)}
            {_generate_fallback_content(annotation_scheme)}
        </video>
    """

    schematic += "</fieldset></form>"

    logger.info(f"Successfully generated video layout for {annotation_scheme['name']}")
    return schematic, []

def _generate_video_attributes(annotation_scheme):
    """
    Generate HTML attributes for video element.

    Args:
        annotation_scheme (dict): Video configuration settings

    Returns:
        str: Space-separated video attributes
    """
    attrs = []

    # Handle playback controls
    if annotation_scheme.get("controls", True):
        attrs.append("controls")
        logger.debug("Enabled video controls")

    if annotation_scheme.get("autoplay"):
        attrs.append("autoplay")
        logger.debug("Enabled autoplay")

    if annotation_scheme.get("loop"):
        attrs.append("loop")
        logger.debug("Enabled video loop")

    if annotation_scheme.get("muted"):
        attrs.append("muted")
        logger.debug("Enabled muted playback")

    return " ".join(attrs)

def _generate_css_style(annotation_scheme):
    """
    Generate CSS style string from configuration.

    Args:
        annotation_scheme (dict): Configuration containing custom_css settings

    Returns:
        str: Formatted CSS style string
    """
    css = annotation_scheme.get("custom_css", {})
    styles = []

    # Default dimensions if not specified
    width = css.get("width", "320")
    height = css.get("height", "240")

    styles.append(f"width: {width}px")
    styles.append(f"height: {height}px")

    return "; ".join(styles)

def _generate_video_sources(annotation_scheme):
    """
    Generate source elements for video formats.

    Args:
        annotation_scheme (dict): Configuration containing video sources

    Returns:
        str: HTML for video source elements
    """
    sources = []

    # Add main video source
    mime_type = _get_mime_type(annotation_scheme["video_path"])
    sources.append(
        f'<source src="{escape_html_content(annotation_scheme["video_path"])}" type="{mime_type}">'
    )
    logger.debug(f"Added primary video source: {annotation_scheme['video_path']}")

    # Add additional sources if specified
    for source in annotation_scheme.get("additional_sources", []):
        mime_type = _get_mime_type(source)
        sources.append(f'<source src="{escape_html_content(source)}" type="{mime_type}">')
        logger.debug(f"Added additional video source: {source}")

    return "\n".join(sources)

def _generate_fallback_content(annotation_scheme):
    """
    Generate fallback content for browsers that don't support video.

    Args:
        annotation_scheme (dict): Configuration containing fallback settings

    Returns:
        str: HTML for fallback content
    """
    fallback = annotation_scheme.get("fallback_text", "Your browser does not support the video tag.")
    logger.debug("Added fallback content for video element")
    return escape_html_content(fallback)

def _get_mime_type(file_path):
    """
    Determine MIME type from video file extension.

    Args:
        file_path (str): Path to video file

    Returns:
        str: MIME type string
    """
    ext = os.path.splitext(file_path)[1].lower()
    mime_types = {
        '.mp4': 'video/mp4',
        '.webm': 'video/webm',
        '.ogg': 'video/ogg'
    }
    return mime_types.get(ext, 'video/mp4')