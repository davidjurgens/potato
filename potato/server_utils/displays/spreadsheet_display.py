"""
Spreadsheet Display Component

Renders tabular data with support for row-based or cell-based annotation.

Usage:
    In instance_display config:
    fields:
      - key: data_table
        type: spreadsheet
        display_options:
          annotation_mode: row
          show_headers: true
          max_height: 400
"""

from typing import Dict, Any, List, Optional
import html
import logging

from .base import BaseDisplay

logger = logging.getLogger(__name__)


class SpreadsheetDisplay(BaseDisplay):
    """
    Display type for tabular/spreadsheet data.

    Renders data as an HTML table with support for row-based
    or cell-based annotation modes.
    """

    name = "spreadsheet"
    required_fields = ["key"]
    optional_fields = {
        "annotation_mode": "row",    # "row", "cell", or "range"
        "show_headers": True,        # Show column headers
        "max_height": 400,           # Max container height
        "max_width": None,           # Max container width
        "striped": True,             # Alternating row colors
        "hoverable": True,           # Highlight row on hover
        "sortable": False,           # Enable column sorting
        "filterable": False,         # Enable column filtering
        "selectable": True,          # Enable row/cell selection
        "compact": False,            # Compact table styling
        # New styling options
        "border_style": "default",   # "default", "bordered", "minimal", "rounded", "none"
        "header_style": "default",   # "default", "dark", "primary", "gradient", "light", "transparent"
        "custom_class": None,        # Additional CSS classes for the table
        "custom_css": None,          # Inline CSS styles for the table
    }
    description = "Spreadsheet/table display with row or cell annotation"
    supports_span_target = True

    # Valid values for style options
    VALID_BORDER_STYLES = ["default", "bordered", "minimal", "rounded", "none"]
    VALID_HEADER_STYLES = ["default", "dark", "primary", "gradient", "light", "transparent"]

    def validate_config(self, field_config: Dict[str, Any]) -> List[str]:
        """
        Validate spreadsheet display configuration.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = super().validate_config(field_config)
        options = field_config.get("display_options", {})

        # Validate border_style
        border_style = options.get("border_style", "default")
        if border_style not in self.VALID_BORDER_STYLES:
            errors.append(
                f"Invalid border_style '{border_style}'. "
                f"Must be one of: {', '.join(self.VALID_BORDER_STYLES)}"
            )

        # Validate header_style
        header_style = options.get("header_style", "default")
        if header_style not in self.VALID_HEADER_STYLES:
            errors.append(
                f"Invalid header_style '{header_style}'. "
                f"Must be one of: {', '.join(self.VALID_HEADER_STYLES)}"
            )

        # Validate annotation_mode
        annotation_mode = options.get("annotation_mode", "row")
        valid_modes = ["row", "cell", "range"]
        if annotation_mode not in valid_modes:
            errors.append(
                f"Invalid annotation_mode '{annotation_mode}'. "
                f"Must be one of: {', '.join(valid_modes)}"
            )

        return errors

    def render(self, field_config: Dict[str, Any], data: Any) -> str:
        """
        Render spreadsheet data.

        Args:
            field_config: Display configuration
            data: Either a dict with extracted content, list of lists,
                  or list of dicts

        Returns:
            HTML string for rendering
        """
        options = self.get_display_options(field_config)
        field_key = field_config.get("key", "spreadsheet")

        # Handle different data formats
        if isinstance(data, dict):
            # Pre-extracted FormatOutput data
            if "rendered_html" in data:
                return self._wrap_content(data["rendered_html"], options, field_key)

            # Extract from metadata
            rows = data.get("rows", [])
            headers = data.get("headers", data.get("metadata", {}).get("headers", []))
        elif isinstance(data, list):
            if data and isinstance(data[0], dict):
                # List of dictionaries
                headers = list(data[0].keys()) if data else []
                rows = [[row.get(h, "") for h in headers] for row in data]
            else:
                # List of lists
                rows = data
                headers = []
        else:
            return f'<div class="spreadsheet-error">Unsupported data format</div>'

        # Generate table HTML
        table_html = self._render_table(rows, headers, options, field_key)
        return self._wrap_content(table_html, options, field_key)

    def _wrap_content(
        self,
        content: str,
        options: Dict[str, Any],
        field_key: str
    ) -> str:
        """
        Wrap table content in container with styles.
        """
        styles = []
        max_height = options.get("max_height")
        max_width = options.get("max_width")

        if max_height:
            styles.append(f"max-height: {max_height}px")
            styles.append("overflow-y: auto")
        if max_width:
            styles.append(f"max-width: {max_width}px")
            styles.append("overflow-x: auto")

        style_str = "; ".join(styles) if styles else ""
        mode = options.get("annotation_mode", "row")

        # Container classes
        container_classes = ["spreadsheet-display"]

        # Add border-rounded class to container for rounded style
        border_style = options.get("border_style", "default")
        if border_style == "rounded":
            container_classes.append("border-rounded")

        container_class_str = " ".join(container_classes)

        return f'''
            <div class="{container_class_str}"
                 data-field-key="{field_key}"
                 data-annotation-mode="{mode}"
                 style="{style_str}">
                {content}
            </div>
        '''

    def _render_table(
        self,
        rows: List[List],
        headers: List[str],
        options: Dict[str, Any],
        field_key: str
    ) -> str:
        """
        Render data as HTML table.
        """
        parts = []
        mode = options.get("annotation_mode", "row")

        # Table classes
        table_classes = ["spreadsheet-table"]
        if options.get("striped"):
            table_classes.append("table-striped")
        if options.get("hoverable"):
            table_classes.append("table-hoverable")
        if options.get("compact"):
            table_classes.append("table-compact")
        if options.get("selectable"):
            table_classes.append("table-selectable")

        # Border style class
        border_style = options.get("border_style", "default")
        if border_style and border_style != "default":
            table_classes.append(f"border-{border_style}")

        # Header style class
        header_style = options.get("header_style", "default")
        if header_style and header_style != "default":
            table_classes.append(f"header-{header_style}")

        # Custom class from admin config
        custom_class = options.get("custom_class")
        if custom_class:
            # Support both string and list of classes
            if isinstance(custom_class, list):
                table_classes.extend(custom_class)
            else:
                table_classes.append(custom_class)

        class_str = " ".join(table_classes)

        # Custom inline CSS
        custom_css = options.get("custom_css", "")
        style_attr = f' style="{html.escape(custom_css)}"' if custom_css else ""

        parts.append(f'<table class="{class_str}" data-mode="{mode}"{style_attr}>')

        # Headers
        if headers and options.get("show_headers", True):
            parts.append('<thead><tr>')
            if options.get("selectable") and mode == "row":
                parts.append('<th class="select-col"></th>')
            for col_idx, header in enumerate(headers):
                sortable_attr = 'data-sortable="true"' if options.get("sortable") else ""
                parts.append(
                    f'<th data-col="{col_idx}" {sortable_attr}>'
                    f'{html.escape(str(header))}</th>'
                )
            parts.append('</tr></thead>')

        # Body
        parts.append('<tbody>')
        for row_idx, row in enumerate(rows):
            row_classes = ["spreadsheet-row"]
            if mode == "row":
                row_classes.append("selectable-row")

            parts.append(
                f'<tr class="{" ".join(row_classes)}" '
                f'data-row="{row_idx}">'
            )

            # Row selection checkbox
            if options.get("selectable") and mode == "row":
                parts.append(
                    f'<td class="select-col">'
                    f'<input type="checkbox" class="row-select" data-row="{row_idx}">'
                    f'</td>'
                )

            for col_idx, cell in enumerate(row):
                cell_value = str(cell) if cell is not None else ""
                cell_classes = ["spreadsheet-cell"]
                if mode == "cell":
                    cell_classes.append("selectable-cell")

                cell_ref = self._get_cell_ref(row_idx, col_idx)

                parts.append(
                    f'<td class="{" ".join(cell_classes)}" '
                    f'data-row="{row_idx}" '
                    f'data-col="{col_idx}" '
                    f'data-cell-ref="{cell_ref}">'
                    f'{html.escape(cell_value)}'
                    f'</td>'
                )

            parts.append('</tr>')

        parts.append('</tbody>')
        parts.append('</table>')

        # Add selection summary for row mode
        if options.get("selectable") and mode == "row":
            parts.append('''
                <div class="spreadsheet-selection-summary">
                    <span class="selected-count">0</span> rows selected
                </div>
            ''')

        return "\n".join(parts)

    def _get_cell_ref(self, row: int, col: int) -> str:
        """
        Get A1-style cell reference.
        """
        # Convert column to letter
        col_letter = ""
        col_num = col + 1
        while col_num > 0:
            col_num, remainder = divmod(col_num - 1, 26)
            col_letter = chr(65 + remainder) + col_letter
        return f"{col_letter}{row + 1}"

    def get_css_classes(self, field_config: Dict[str, Any]) -> List[str]:
        """Get CSS classes for the display container."""
        classes = super().get_css_classes(field_config)
        options = self.get_display_options(field_config)

        if field_config.get("span_target"):
            classes.append("span-target-spreadsheet")

        mode = options.get("annotation_mode", "row")
        classes.append(f"spreadsheet-mode-{mode}")

        return classes

    def get_data_attributes(
        self,
        field_config: Dict[str, Any],
        data: Any
    ) -> Dict[str, str]:
        """Get data attributes for JavaScript initialization."""
        attrs = super().get_data_attributes(field_config, data)
        options = self.get_display_options(field_config)

        attrs["annotation-mode"] = options.get("annotation_mode", "row")
        attrs["selectable"] = str(options.get("selectable", True)).lower()

        return attrs

    def get_js_init(self) -> Optional[str]:
        """
        Return JavaScript initialization code for spreadsheet interactivity.
        """
        return '''
            if (typeof initSpreadsheetDisplays === 'function') {
                initSpreadsheetDisplays();
            }
        '''
