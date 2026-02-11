"""
Code Display Component

Renders source code with syntax highlighting and line number support.

Usage:
    In instance_display config:
    fields:
      - key: source_code
        type: code
        display_options:
          language: python
          show_line_numbers: true
          max_height: 500
"""

from typing import Dict, Any, List, Optional
import html
import logging

from .base import BaseDisplay

logger = logging.getLogger(__name__)


class CodeDisplay(BaseDisplay):
    """
    Display type for source code with syntax highlighting.

    Uses Pygments for server-side highlighting or can use client-side
    highlighting with highlight.js.
    """

    name = "code"
    required_fields = ["key"]
    optional_fields = {
        "language": None,            # Language for syntax highlighting
        "show_line_numbers": True,   # Show line numbers
        "max_height": 500,           # Max container height
        "max_width": None,           # Max container width
        "wrap_lines": False,         # Wrap long lines
        "highlight_lines": None,     # List of line numbers to highlight
        "start_line": 1,             # Starting line number
        "theme": "default",          # Color theme
        "copy_button": True,         # Show copy to clipboard button
    }
    description = "Source code display with syntax highlighting"
    supports_span_target = True

    def render(self, field_config: Dict[str, Any], data: Any) -> str:
        """
        Render source code content.

        Args:
            field_config: Display configuration
            data: Either a dict with extracted content or raw code string

        Returns:
            HTML string for rendering
        """
        options = self.get_display_options(field_config)
        field_key = field_config.get("key", "code")

        # Handle different data formats
        if isinstance(data, dict):
            # Pre-extracted FormatOutput data
            if "rendered_html" in data:
                return self._wrap_content(data["rendered_html"], options, field_key)

            code = data.get("text", "")
            language = data.get("metadata", {}).get("language", options.get("language"))
        elif isinstance(data, str):
            code = data
            language = options.get("language")
        else:
            return f'<div class="code-error">Unsupported content type</div>'

        # Generate code HTML
        is_span_target = field_config.get("span_target", False)
        code_html = self._render_code(code, language, options, field_key, is_span_target)
        return self._wrap_content(code_html, options, field_key)

    def _wrap_content(
        self,
        content: str,
        options: Dict[str, Any],
        field_key: str
    ) -> str:
        """
        Wrap code content in container with styles.
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
        language = options.get("language") or "text"
        theme = options.get("theme", "default")

        return f'''
            <div class="code-display code-theme-{theme}"
                 data-field-key="{field_key}"
                 data-language="{language}"
                 style="{style_str}">
                {self._render_copy_button() if options.get("copy_button") else ""}
                {content}
            </div>
        '''

    def _render_copy_button(self) -> str:
        """
        Render copy to clipboard button.
        """
        return '''
            <button type="button" class="code-copy-btn" title="Copy to clipboard">
                <svg viewBox="0 0 24 24" width="16" height="16">
                    <path fill="currentColor" d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/>
                </svg>
            </button>
        '''

    def _render_code(
        self,
        code: str,
        language: Optional[str],
        options: Dict[str, Any],
        field_key: str = "code",
        is_span_target: bool = False
    ) -> str:
        """
        Render code with line numbers and optional highlighting.

        When is_span_target is True, uses a simpler pre/code structure
        that works better with span annotation positioning.
        """
        # For span targets, use simpler rendering for accurate position calculation
        if is_span_target:
            return self._render_code_simple(code, language, options, field_key)

        lines = code.split("\n")
        parts = []

        show_line_numbers = options.get("show_line_numbers", True)
        start_line = options.get("start_line", 1)
        highlight_lines = set(options.get("highlight_lines") or [])
        wrap_lines = options.get("wrap_lines", False)

        wrap_class = "code-wrap" if wrap_lines else "code-nowrap"
        lang_class = f"language-{language}" if language else ""

        content_classes = ["code-content", wrap_class]
        content_class_str = " ".join(content_classes)

        parts.append(f'<div class="{content_class_str}" id="text-content-{field_key}">')
        parts.append(f'<table class="code-table {lang_class}">')

        for i, line in enumerate(lines):
            line_num = i + start_line
            line_classes = ["code-line"]

            if line_num in highlight_lines:
                line_classes.append("highlighted-line")

            escaped_line = html.escape(line) if line else "&nbsp;"

            parts.append(f'<tr id="L{line_num}" class="{" ".join(line_classes)}">')

            if show_line_numbers:
                parts.append(
                    f'<td class="line-number" '
                    f'data-line="{line_num}">{line_num}</td>'
                )

            parts.append(
                f'<td class="line-content">'
                f'<code>{escaped_line}</code>'
                f'</td>'
            )

            parts.append('</tr>')

        parts.append('</table>')
        parts.append('</div>')

        return "\n".join(parts)

    def _render_code_simple(
        self,
        code: str,
        language: Optional[str],
        options: Dict[str, Any],
        field_key: str
    ) -> str:
        """
        Render code in a simple pre/code format for span annotation.

        This avoids table structures that interfere with text position calculations.
        Uses a flat text structure without data-original-text so the span system
        uses DOM textContent directly (which matches what the user sees and selects).
        """
        lang_class = f"language-{language}" if language else ""

        # Escape code for HTML but preserve structure
        escaped_code = html.escape(code)

        # Don't use data-original-text - let span system use DOM textContent
        # This ensures canonical text matches what user sees and selects
        return f'''
            <div class="code-content code-simple text-content" id="text-content-{field_key}">
                <pre class="code-pre {lang_class}"><code>{escaped_code}</code></pre>
            </div>
        '''

    def get_css_classes(self, field_config: Dict[str, Any]) -> List[str]:
        """Get CSS classes for the display container."""
        classes = super().get_css_classes(field_config)
        options = self.get_display_options(field_config)

        if field_config.get("span_target"):
            classes.append("span-target-code")

        language = options.get("language")
        if language:
            classes.append(f"language-{language}")

        theme = options.get("theme", "default")
        classes.append(f"code-theme-{theme}")

        return classes

    def get_data_attributes(
        self,
        field_config: Dict[str, Any],
        data: Any
    ) -> Dict[str, str]:
        """Get data attributes for JavaScript initialization."""
        attrs = super().get_data_attributes(field_config, data)
        options = self.get_display_options(field_config)

        language = options.get("language")
        if language:
            attrs["language"] = language

        if isinstance(data, dict) and "metadata" in data:
            meta = data["metadata"]
            if "language" in meta:
                attrs["language"] = meta["language"]
            if "line_count" in meta:
                attrs["line-count"] = str(meta["line_count"])

        return attrs

    def get_js_init(self) -> Optional[str]:
        """
        Return JavaScript initialization code for code displays.
        """
        return '''
            if (typeof initCodeDisplays === 'function') {
                initCodeDisplays();
            }
        '''
