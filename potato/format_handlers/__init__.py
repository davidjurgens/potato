"""
Format Handlers Module

Provides a pluggable system for parsing various document formats (PDF, DOCX, Markdown,
spreadsheets, source code) and extracting annotatable content with coordinate mappings.

Usage:
    from potato.format_handlers import format_handler_registry, FormatOutput

    # Auto-detect and extract content from a file
    output = format_handler_registry.extract("document.pdf")

    # Access extracted content
    text = output.text
    html = output.rendered_html
    coords = output.coordinate_map

    # List supported formats
    formats = format_handler_registry.get_supported_formats()
"""

from .base import BaseFormatHandler, FormatOutput
from .registry import format_handler_registry, FormatHandlerRegistry
from .coordinate_mapping import (
    CoordinateMapper,
    CharacterCoordinate,
    PDFCoordinate,
    SpreadsheetCoordinate,
    DocumentCoordinate,
    CodeCoordinate,
    BoundingBoxCoordinate,
)

__all__ = [
    # Core classes
    "BaseFormatHandler",
    "FormatOutput",
    "FormatHandlerRegistry",
    "format_handler_registry",
    # Coordinate types
    "CoordinateMapper",
    "CharacterCoordinate",
    "PDFCoordinate",
    "SpreadsheetCoordinate",
    "DocumentCoordinate",
    "CodeCoordinate",
    "BoundingBoxCoordinate",
]
