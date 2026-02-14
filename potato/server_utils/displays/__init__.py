"""
Display Types Package

Provides renderers for different content types in instance display.
This module separates content display from annotation collection.

Usage:
    from potato.server_utils.displays import display_registry

    # Render a display field
    html = display_registry.render("image", field_config, data)

    # List available display types
    types = display_registry.get_supported_types()
"""

from .registry import display_registry, DisplayDefinition, DisplayRegistry
from .base import BaseDisplay, render_display_container
from .pdf_display import PDFDisplay
from .document_display import DocumentDisplay
from .spreadsheet_display import SpreadsheetDisplay
from .code_display import CodeDisplay

__all__ = [
    'display_registry',
    'DisplayDefinition',
    'DisplayRegistry',
    'BaseDisplay',
    'render_display_container',
    'PDFDisplay',
    'DocumentDisplay',
    'SpreadsheetDisplay',
    'CodeDisplay',
]
