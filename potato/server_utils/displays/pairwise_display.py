"""
Pairwise Display Type

Renders content in a side-by-side comparison layout for pairwise annotation tasks.
"""

import html
from typing import Dict, Any, List

from .base import BaseDisplay


class PairwiseDisplay(BaseDisplay):
    """
    Display type for pairwise/comparison content.

    Displays multiple items side-by-side for comparison annotation tasks.
    The data should be a list or dict with multiple items to compare.
    """

    name = "pairwise"
    required_fields = ["key"]
    optional_fields = {
        "cell_width": "50%",
        "show_labels": True,
        "labels": None,  # Custom labels like ["Option A", "Option B"]
        "vertical_on_mobile": True,
    }
    description = "Side-by-side comparison display"
    supports_span_target = False

    def render(self, field_config: Dict[str, Any], data: Any) -> str:
        """
        Render pairwise comparison content as HTML.

        Args:
            field_config: The field configuration
            data: The comparison data - should be:
                  - List of items to compare
                  - Dict with keys for each item

        Returns:
            HTML string for the pairwise display
        """
        if not data:
            return '<div class="pairwise-placeholder">No comparison data provided</div>'

        # Get display options
        options = self.get_display_options(field_config)
        cell_width = options.get("cell_width", "50%")
        show_labels = options.get("show_labels", True)
        custom_labels = options.get("labels")
        vertical_on_mobile = options.get("vertical_on_mobile", True)

        field_key = html.escape(field_config.get("key", ""), quote=True)

        # Normalize data to a list of items
        items = self._normalize_items(data)

        if not items:
            return '<div class="pairwise-placeholder">No items to compare</div>'

        # Generate labels
        labels = self._get_labels(items, custom_labels)

        # Calculate cell width based on number of items
        if cell_width == "auto":
            cell_width = f"{100 / len(items)}%"

        # Build HTML for each cell
        cell_html_list = []
        for i, item in enumerate(items):
            label = labels[i] if i < len(labels) else f"Option {i + 1}"
            content = self._render_item(item)

            label_html = ""
            if show_labels:
                escaped_label = html.escape(str(label))
                label_html = f'<div class="pairwise-label">{escaped_label}</div>'

            cell_html = f'''
            <div class="pairwise-cell" style="width: {cell_width}; flex: 0 0 {cell_width};" data-cell-index="{i}">
                {label_html}
                <div class="pairwise-content">{content}</div>
            </div>
            '''
            cell_html_list.append(cell_html)

        # Combine all cells
        all_cells_html = "\n".join(cell_html_list)

        # Container classes
        container_classes = ["pairwise-display-content"]
        if vertical_on_mobile:
            container_classes.append("vertical-on-mobile")

        return f'''
        <div class="{' '.join(container_classes)}" data-field-key="{field_key}" data-item-count="{len(items)}">
            {all_cells_html}
        </div>
        '''

    def _normalize_items(self, data: Any) -> List[Any]:
        """
        Normalize data to a list of items.

        Args:
            data: Raw comparison data

        Returns:
            List of items to compare
        """
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            # Return values in order, or use special keys if present
            if "left" in data and "right" in data:
                return [data["left"], data["right"]]
            if "a" in data and "b" in data:
                return [data["a"], data["b"]]
            if "1" in data and "2" in data:
                return [data["1"], data["2"]]
            # Otherwise return all values
            return list(data.values())
        else:
            # Single item - wrap in list
            return [data]

    def _get_labels(self, items: List[Any], custom_labels: List[str] = None) -> List[str]:
        """
        Generate labels for the comparison items.

        Args:
            items: The items being compared
            custom_labels: Custom labels if provided

        Returns:
            List of label strings
        """
        if custom_labels and len(custom_labels) >= len(items):
            return custom_labels[:len(items)]

        # Default labels
        if len(items) == 2:
            return ["A", "B"]
        else:
            return [f"Option {i + 1}" for i in range(len(items))]

    def _render_item(self, item: Any) -> str:
        """
        Render a single comparison item.

        Args:
            item: The item to render

        Returns:
            HTML string for the item
        """
        if item is None:
            return '<span class="pairwise-empty">No content</span>'

        if isinstance(item, str):
            # Plain text - escape and preserve newlines
            escaped = html.escape(item)
            return escaped.replace('\n', '<br>')

        if isinstance(item, dict):
            # Check for common patterns
            if "text" in item:
                text = str(item["text"])
                escaped = html.escape(text)
                return escaped.replace('\n', '<br>')
            if "content" in item:
                content = str(item["content"])
                escaped = html.escape(content)
                return escaped.replace('\n', '<br>')
            # Render as key-value pairs
            parts = []
            for key, value in item.items():
                escaped_key = html.escape(str(key))
                escaped_value = html.escape(str(value))
                parts.append(f'<div><strong>{escaped_key}:</strong> {escaped_value}</div>')
            return ''.join(parts)

        if isinstance(item, list):
            # Render as list items
            parts = ['<ul class="pairwise-list">']
            for sub_item in item:
                escaped = html.escape(str(sub_item))
                parts.append(f'<li>{escaped}</li>')
            parts.append('</ul>')
            return ''.join(parts)

        # Default - convert to string
        return html.escape(str(item))

    def get_css_classes(self, field_config: Dict[str, Any]) -> List[str]:
        """Get CSS classes for the container."""
        classes = super().get_css_classes(field_config)
        return classes
