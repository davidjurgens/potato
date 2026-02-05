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

__all__ = [
    'display_registry',
    'DisplayDefinition',
    'DisplayRegistry',
]
