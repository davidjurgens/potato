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
from .agent_trace_display import AgentTraceDisplay
from .gallery_display import GalleryDisplay
from .interactive_chat_display import InteractiveChatDisplay

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
    'AgentTraceDisplay',
    'GalleryDisplay',
    'InteractiveChatDisplay',
]
