"""
Base Display Class

Provides a base class for custom display types that can be registered
as plugins. Third-party developers can extend this class to create
custom content renderers.

Usage:
    from potato.server_utils.displays.base import BaseDisplay

    class MyCustomDisplay(BaseDisplay):
        name = "my_custom"
        required_fields = ["key"]
        optional_fields = {"my_option": "default_value"}

        def render(self, field_config, data):
            return f'<div class="my-custom">{data}</div>'
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional


class BaseDisplay(ABC):
    """
    Abstract base class for display type implementations.

    Subclasses must implement the `render` method and define
    class attributes for registration.

    Class Attributes:
        name: Unique identifier for this display type (e.g., "text", "image")
        required_fields: List of required configuration field names
        optional_fields: Dictionary of optional fields with their default values
        description: Human-readable description of this display type
        supports_span_target: Whether this type can be a span annotation target
    """

    name: str = ""
    required_fields: List[str] = []
    optional_fields: Dict[str, Any] = {}
    description: str = ""
    supports_span_target: bool = False

    @abstractmethod
    def render(self, field_config: Dict[str, Any], data: Any) -> str:
        """
        Render the content as HTML.

        Args:
            field_config: The field configuration from instance_display.fields
            data: The actual data value from the instance

        Returns:
            HTML string for rendering the content
        """
        pass

    def get_css_classes(self, field_config: Dict[str, Any]) -> List[str]:
        """
        Get CSS classes to apply to the display container.

        Override in subclasses to add custom classes.

        Args:
            field_config: The field configuration

        Returns:
            List of CSS class names
        """
        return [f"display-field", f"display-type-{self.name}"]

    def get_data_attributes(self, field_config: Dict[str, Any], data: Any) -> Dict[str, str]:
        """
        Get data attributes to add to the display container.

        These are used for JavaScript interactions and linking
        annotation schemas to display fields.

        Args:
            field_config: The field configuration
            data: The actual data value

        Returns:
            Dictionary of data attribute names (without 'data-' prefix) to values
        """
        attrs = {
            "field-key": field_config.get("key", ""),
            "field-type": self.name,
        }
        if field_config.get("span_target"):
            attrs["span-target"] = "true"
        return attrs

    def get_js_init(self) -> Optional[str]:
        """
        Get JavaScript initialization code for this display type.

        Override in subclasses that need client-side initialization.

        Returns:
            JavaScript code string or None if not needed
        """
        return None

    def validate_config(self, field_config: Dict[str, Any]) -> List[str]:
        """
        Validate the field configuration.

        Args:
            field_config: The field configuration to validate

        Returns:
            List of error messages (empty if valid)
        """
        errors = []

        # Check required fields
        for field in self.required_fields:
            if field not in field_config:
                errors.append(f"Missing required field '{field}' for display type '{self.name}'")

        return errors

    def get_display_options(self, field_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get display options with defaults applied.

        Args:
            field_config: The field configuration

        Returns:
            Dictionary of display options with defaults filled in
        """
        options = field_config.get("display_options", {})
        result = dict(self.optional_fields)  # Start with defaults
        result.update(options)  # Override with user-specified options
        return result


def render_display_container(
    inner_html: str,
    css_classes: List[str],
    data_attrs: Dict[str, str],
    label: Optional[str] = None
) -> str:
    """
    Render a display container with the given content.

    This helper function wraps content in a standard display container
    with proper classes and data attributes.

    Args:
        inner_html: The inner HTML content
        css_classes: CSS classes to apply
        data_attrs: Data attributes to add
        label: Optional label/header for the display

    Returns:
        Complete HTML for the display container
    """
    class_str = " ".join(css_classes)
    attr_str = " ".join(f'data-{k}="{v}"' for k, v in data_attrs.items())

    parts = []
    parts.append(f'<div class="{class_str}" {attr_str}>')

    if label:
        parts.append(f'  <div class="display-field-label">{label}</div>')

    parts.append(f'  <div class="display-field-content">')
    parts.append(f'    {inner_html}')
    parts.append(f'  </div>')
    parts.append(f'</div>')

    return "\n".join(parts)
