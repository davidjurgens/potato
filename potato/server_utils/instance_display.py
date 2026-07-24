"""
Instance Display Renderer

Provides the main InstanceDisplayRenderer class that handles rendering
instance content for display, separate from annotation collection.

This module enables the new `instance_display` configuration section
that explicitly defines what content to show annotators.

Usage:
    from potato.server_utils.instance_display import InstanceDisplayRenderer

    renderer = InstanceDisplayRenderer(config)
    html = renderer.render(instance_data)
    template_vars = renderer.get_template_variables(instance_data)
"""

import html as html_module
import logging
import os
from typing import Dict, Any, List, Optional

from .displays import display_registry

logger = logging.getLogger(__name__)


class InstanceDisplayError(Exception):
    """Exception raised when instance display rendering fails."""
    pass


class InstanceDisplayRenderer:
    """
    Renders instance content for display based on configuration.

    This class separates content display from annotation collection,
    allowing any combination of display types with any annotation schemes.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the renderer.

        Args:
            config: The full configuration dictionary
        """
        self.config = config
        self.display_config = config.get("instance_display", {})
        self.fields = self.display_config.get("fields", [])
        self.layout = self.display_config.get("layout", {})

        # Turn-level annotation schemes (turn_level: true) attach inline
        # widgets to turns of turn-capable displays. Resolved here (the one
        # place with access to the full config) and injected into field
        # configs via the internal "_turn_schemes" key at render time.
        from .turn_annotations import get_turn_level_schemes
        self.turn_level_schemes = get_turn_level_schemes(config)

        # Extract span targets — query the registry instead of a hardcoded list
        self.span_targets = [
            f["key"] for f in self.fields
            if f.get("span_target") and display_registry.type_supports_span_target(f.get("type", ""))
        ]

        # Warn about span_target on unsupported types
        for f in self.fields:
            if f.get("span_target") and not display_registry.type_supports_span_target(f.get("type", "")):
                logger.warning(
                    f"Field '{f.get('key')}' has span_target=true but display type "
                    f"'{f.get('type')}' does not support span annotation. "
                    f"Span annotation will not work on this field."
                )

        # Track if we have instance_display configured
        self.has_instance_display = bool(self.fields)

        logger.debug(
            f"InstanceDisplayRenderer initialized: "
            f"has_instance_display={self.has_instance_display}, "
            f"span_targets={self.span_targets}"
        )

    def render(self, instance_data: Dict[str, Any]) -> str:
        """
        Render all display fields for an instance.

        Args:
            instance_data: The instance data dictionary

        Returns:
            HTML string containing all rendered display fields

        Raises:
            InstanceDisplayError: If a required field is missing from instance data
        """
        if not self.has_instance_display:
            # No instance_display configured, return empty
            # (legacy behavior will be handled by the template)
            return ""

        # Validate all required fields exist
        self._validate_fields(instance_data)

        # Get layout configuration
        direction = self.layout.get("direction", "vertical")
        gap = self.layout.get("gap", "20px")

        # Build container classes and styles
        container_classes = ["instance-display-container", f"layout-{direction}"]
        container_style = f"gap: {gap};"

        # Render each field
        rendered_fields = []
        for field in self.fields:
            field_html = self._render_field(field, instance_data)
            rendered_fields.append(field_html)

        # Combine into container
        fields_html = "\n".join(rendered_fields)

        # Build data attributes for raw field access by annotation schemas
        # Include all string/URL fields from instance data for source_field lookups
        import json
        raw_data = {}
        for key, value in instance_data.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                raw_data[key] = value
        raw_data_json = html_module.escape(json.dumps(raw_data))

        return f'''
        <div class="{' '.join(container_classes)}" style="{container_style}" data-instance-fields="{raw_data_json}">
            {fields_html}
        </div>
        '''

    def _validate_fields(self, instance_data: Dict[str, Any]) -> None:
        """
        Validate that all configured fields exist in the instance data.

        Fields whose display type is marked ``lazy_populated`` in the
        display registry (``interactive_chat``, ``live_agent``,
        ``live_coding_agent``) are exempt -- their data key is expected
        to be written after initial render (by a live agent session).

        Args:
            instance_data: The instance data dictionary

        Raises:
            InstanceDisplayError: If any non-lazy field is missing
        """
        non_lazy = [
            f for f in self.fields
            if not display_registry.is_lazy_populated(f.get("type", ""))
        ]
        missing_non_lazy = [
            f["key"] for f in non_lazy if f["key"] not in instance_data
        ]
        # Every non-lazy field missing is almost always a config/data
        # key mismatch (e.g. fields reference task_description but the
        # data uses task), not a transient lazy state -- make it loud so
        # it isn't silently rendered as a blank page.
        if non_lazy and len(missing_non_lazy) == len(non_lazy):
            logger.error(
                "instance_display: ALL %d non-lazy field(s) %s are absent "
                "from the instance data (available keys: %s). This is "
                "almost certainly a config/data key mismatch.",
                len(non_lazy), missing_non_lazy,
                list(instance_data.keys()),
            )

        for field in self.fields:
            key = field["key"]
            if key in instance_data:
                continue
            field_type = field.get("type", "")
            if display_registry.is_lazy_populated(field_type):
                logger.debug(
                    "Skipping validation for lazy-populated field '%s' (type=%s); "
                    "data is written after initial render.",
                    key, field_type,
                )
                continue
            available = list(instance_data.keys())
            raise InstanceDisplayError(
                f"Display field '{key}' not found in instance data. "
                f"Available fields: {available}"
            )

    def _render_field(self, field: Dict[str, Any], instance_data: Dict[str, Any]) -> str:
        """
        Render a single display field.

        Args:
            field: The field configuration
            instance_data: The instance data dictionary

        Returns:
            HTML string for the field
        """
        key = field["key"]
        field_type = field["type"]
        data = instance_data.get(key)

        # For format-based display types, process the file if data is a file path
        format_display_types = ["pdf", "document", "spreadsheet", "code"]
        if field_type in format_display_types and isinstance(data, str):
            data = self._process_format_file(data, field_type, field)

        field = self._with_turn_schemes(field)
        field = self._with_run_tree(field, instance_data)

        try:
            rendered = display_registry.render(field_type, field, data)

            # Check if resizable is enabled (global setting or per-field override)
            global_resizable = self.display_config.get("resizable", True)
            field_resizable = field.get("display_options", {}).get("resizable", global_resizable)

            # Wrap with resizable container if enabled
            if field_resizable:
                rendered = self._wrap_resizable(rendered, field)

            return rendered
        except ValueError as e:
            logger.error(f"Error rendering field '{key}': {e}")
            return f'<div class="display-error">Error rendering field "{key}": {e}</div>'

    def _with_turn_schemes(self, field: Dict[str, Any]) -> Dict[str, Any]:
        """Return a field config copy carrying its bound turn-level schemes.

        Uses the internal "_turn_schemes" key (never user-configurable) so
        turn-capable displays can render per-turn annotation slots. Fields
        with no bound schemes are returned unchanged.
        """
        if not self.turn_level_schemes:
            return field
        from .turn_annotations import schemes_for_field
        bound = schemes_for_field(self.turn_level_schemes, field.get("key", ""))
        if not bound:
            return field
        field = dict(field)
        field["_turn_schemes"] = bound
        return field

    def _with_run_tree(self, field: Dict[str, Any], instance_data: Dict[str, Any]) -> Dict[str, Any]:
        """Return a field config copy carrying the item's run tree.

        The run tree (sub-agent hierarchy, ``extra_fields["run_tree"]`` from
        trace converters) lives at item level, but displays only see their
        own field's data — inject it via the internal "_run_tree" key for
        the trace displays that render it as a sidebar.
        """
        if field.get("type") != "agent_trace":
            return field
        run_tree = instance_data.get("run_tree")
        if not isinstance(run_tree, list) or not run_tree:
            return field
        field = dict(field)
        field["_run_tree"] = run_tree
        return field

    def _wrap_resizable(self, inner_html: str, field: Dict[str, Any]) -> str:
        """
        Wrap rendered content in a resizable container.

        Args:
            inner_html: The rendered field HTML
            field: The field configuration

        Returns:
            HTML wrapped in resizable container
        """
        display_options = field.get("display_options", {})
        max_height = display_options.get("max_height", 500)
        min_height = display_options.get("min_height", 100)

        style = f"max-height: {max_height}px; min-height: {min_height}px; position: relative;"

        return f'''<div class="display-field-resizable" style="{style}">
            {inner_html}
        </div>'''

    def _process_format_file(
        self,
        file_path: str,
        display_type: str,
        field: Dict[str, Any]
    ) -> Any:
        """
        Process a file using the format handler system.

        If the data is a file path and a format handler is available,
        extract the content and return FormatOutput data.

        Args:
            file_path: Path to the file to process
            display_type: The display type (pdf, document, etc.)
            field: The field configuration

        Returns:
            Either the original file_path (for client-side rendering like PDF.js)
            or extracted content dict for server-side rendering
        """
        try:
            from potato.format_handlers import format_handler_registry
        except ImportError:
            # Format handlers not available, return original data
            logger.debug("Format handlers not available, using raw file path")
            return file_path

        # Check if the file path should be processed
        # For PDFs, we typically use client-side rendering with PDF.js
        # unless explicitly configured for server-side extraction
        display_options = field.get("display_options", {})

        if display_type == "pdf":
            # Link mode renders the visual PDF client-side (PDF.js). For scanned /
            # image-only PDFs the client text layer is empty, so when OCR is
            # enabled we extract per-page words server-side and hand them to the
            # client to build a selectable text layer. The original path/URL is
            # kept as source_path so PDF.js still renders the page image.
            if display_options.get("annotation_mode") == "link" and display_options.get("ocr"):
                local_path = self._resolve_local_pdf_path(file_path)
                try:
                    from potato.format_handlers.pdf_handler import PDFHandler
                    ocr_pages = PDFHandler().extract_words_by_page(local_path, {
                        "ocr": display_options.get("ocr"),
                        "ocr_dpi": display_options.get("ocr_dpi", 200),
                        "ocr_lang": display_options.get("ocr_lang", "eng"),
                        "max_pages": display_options.get("max_pages"),
                    })
                    return {"source_path": file_path, "ocr_pages": ocr_pages}
                except Exception as e:
                    logger.warning(f"PDF OCR word extraction failed for {file_path}: {e}")
                    return file_path

            # By default, PDFs use client-side rendering (return path as-is)
            # If server_extract is set, use the format handler
            if not display_options.get("server_extract", False):
                return file_path

        # Check if format handler can handle this file
        if not format_handler_registry.can_handle(file_path):
            logger.debug(f"No format handler for {file_path}, using raw data")
            return file_path

        try:
            # Extract content using format handler
            extraction_options = display_options.get("extraction_options", {})
            output = format_handler_registry.extract(file_path, options=extraction_options)

            # Return as dict for the display renderer
            return {
                "text": output.text,
                "rendered_html": output.rendered_html,
                "coordinate_map": output.coordinate_map,
                "metadata": output.metadata,
                "format_name": output.format_name,
                "source_path": output.source_path,
            }
        except Exception as e:
            logger.warning(f"Format handler extraction failed for {file_path}: {e}")
            return file_path

    def _resolve_local_pdf_path(self, value: str) -> str:
        """
        Map a PDF field value to a local filesystem path for server-side OCR.

        Client-facing values are usually ``/media/<file>`` URLs (served from
        ``<task_dir>/<media_directory>/``); OCR needs the file on disk. Absolute
        or already-local paths are returned as-is (resolved against task_dir).
        """
        if not isinstance(value, str) or value.startswith(("http://", "https://")):
            return value
        task_dir = self.config.get("task_dir", ".")
        if value.startswith("/media/"):
            media_dir = self.config.get("media_directory", "media")
            base = media_dir if os.path.isabs(media_dir) else os.path.join(task_dir, media_dir)
            return os.path.join(base, value[len("/media/"):])
        if os.path.isabs(value):
            return value
        return os.path.join(task_dir, value)

    def get_template_variables(self, instance_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get template variables for Jinja access.

        Returns a dictionary with:
        - display_html: The complete rendered display HTML
        - display_fields: Dictionary of field key -> rendered HTML
        - display_raw: Dictionary of field key -> raw data value
        - span_targets: List of field keys that are span targets
        - multi_span_mode: Boolean indicating if multiple span targets exist
        - has_instance_display: Boolean indicating if instance_display is configured

        Args:
            instance_data: The instance data dictionary

        Returns:
            Dictionary of template variables
        """
        result = {
            "display_html": "",
            "display_fields": {},
            "display_raw": {},
            "span_targets": self.span_targets,
            "multi_span_mode": len(self.span_targets) > 1,
            "has_instance_display": self.has_instance_display,
        }

        if not self.has_instance_display:
            return result

        # Validate fields. A missing field here is a real config problem
        # (lazy-populated types like interactive_chat are already filtered
        # out by _validate_fields), but the renderer surfaces it inline
        # via ``display_error`` so the page still loads -- WARN is the
        # right severity, not ERROR.
        try:
            self._validate_fields(instance_data)
        except InstanceDisplayError as e:
            logger.warning(f"Field validation failed: {e}")
            result["display_error"] = str(e)
            return result

        # Render complete display
        result["display_html"] = self.render(instance_data)

        # Render individual fields and collect raw data
        for field in self.fields:
            key = field["key"]
            field_type = field["type"]
            data = instance_data.get(key)

            result["display_raw"][key] = data

            try:
                result["display_fields"][key] = display_registry.render(
                    field_type,
                    self._with_run_tree(self._with_turn_schemes(field),
                                        instance_data),
                    data)
            except ValueError as e:
                logger.error(f"Error rendering field '{key}': {e}")
                result["display_fields"][key] = f'<div class="display-error">Error: {e}</div>'

        return result

    def get_span_target_fields(self) -> List[Dict[str, Any]]:
        """
        Get the list of fields configured as span targets.

        Returns:
            List of field configuration dictionaries for span targets
        """
        return [f for f in self.fields if f.get("span_target")]

    def get_primary_text_field(self) -> Optional[str]:
        """
        Get the primary text field key for legacy compatibility.

        Returns the first span target if any, otherwise the first text field,
        otherwise None.

        Returns:
            Field key string or None
        """
        # First, check span targets
        if self.span_targets:
            return self.span_targets[0]

        # Then look for any text field
        for field in self.fields:
            if field.get("type") == "text":
                return field["key"]

        return None

    def should_use_legacy_display(self) -> bool:
        """
        Check if legacy display mode should be used.

        Returns True if no instance_display is configured, meaning
        the template should fall back to displaying text_key.

        Returns:
            True if legacy mode should be used
        """
        return not self.has_instance_display


def get_instance_display_renderer(config: Dict[str, Any]) -> InstanceDisplayRenderer:
    """
    Get or create an InstanceDisplayRenderer for the given config.

    This is a convenience function that creates a renderer.
    In the future, this could cache renderers per config hash.

    Args:
        config: The configuration dictionary

    Returns:
        InstanceDisplayRenderer instance
    """
    return InstanceDisplayRenderer(config)
