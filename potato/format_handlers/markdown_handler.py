"""
Markdown Format Handler

Parses Markdown files and extracts text with source line mapping.
Supports syntax highlighting for code blocks.

Usage:
    from potato.format_handlers.markdown_handler import MarkdownHandler

    handler = MarkdownHandler()
    output = handler.extract("document.md", {
        "highlight_code": True,
        "gfm": True,  # GitHub Flavored Markdown
    })
"""

from typing import Dict, List, Any, Optional
from pathlib import Path
import html
import logging
import re
import uuid

from .base import BaseFormatHandler, FormatOutput
from .coordinate_mapping import CoordinateMapper, CodeCoordinate, DocumentCoordinate

logger = logging.getLogger(__name__)

# Check if dependencies are available
try:
    import mistune
    MISTUNE_AVAILABLE = True
except ImportError:
    MISTUNE_AVAILABLE = False
    mistune = None

try:
    from pygments import highlight
    from pygments.lexers import get_lexer_by_name, guess_lexer
    from pygments.formatters import HtmlFormatter
    PYGMENTS_AVAILABLE = True
except ImportError:
    PYGMENTS_AVAILABLE = False


class MarkdownHandler(BaseFormatHandler):
    """
    Handler for Markdown files.

    Uses mistune for parsing and Pygments for syntax highlighting.
    Maintains line/column coordinate mappings.
    """

    format_name = "markdown"
    supported_extensions = [".md", ".markdown", ".mdown", ".mkd"]
    description = "Markdown parsing with line/column mapping and syntax highlighting"
    requires_dependencies = ["mistune"]

    def get_default_options(self) -> Dict[str, Any]:
        """Get default extraction options."""
        return {
            "highlight_code": True,
            "gfm": True,  # GitHub Flavored Markdown
            "include_raw_blocks": False,
            "preserve_line_breaks": True,
        }

    def extract(
        self,
        file_path: str,
        options: Optional[Dict[str, Any]] = None
    ) -> FormatOutput:
        """
        Parse and render a Markdown file.

        Args:
            file_path: Path to the Markdown file
            options: Extraction options:
                - highlight_code: Syntax highlight code blocks
                - gfm: Use GitHub Flavored Markdown extensions
                - preserve_line_breaks: Keep original line structure

        Returns:
            FormatOutput with text, rendered HTML, and coordinate mappings
        """
        if not MISTUNE_AVAILABLE:
            raise ImportError(
                "mistune is required for Markdown extraction. "
                "Install with: pip install mistune"
            )

        opts = self.merge_options(options)

        # Read source file
        path = Path(file_path)
        source_text = path.read_text(encoding="utf-8")

        # Build line index for coordinate mapping
        line_offsets = self._build_line_index(source_text)

        # Parse and render
        mapper = CoordinateMapper()
        rendered_html = self._render_markdown(source_text, opts)

        # Build coordinate mappings for each line
        for line_num, (start, end) in enumerate(line_offsets, start=1):
            mapper.add_mapping(
                start,
                end,
                CodeCoordinate(line=line_num, column=1)
            )

        metadata = {
            "format": "markdown",
            "source_file": str(file_path),
            "line_count": len(line_offsets),
            "char_count": len(source_text),
            "headings": self._extract_headings(source_text),
        }

        coord_dict = mapper.to_dict()
        coord_dict["get_coords_for_range"] = mapper.get_coords_for_range

        return FormatOutput(
            text=source_text,
            rendered_html=rendered_html,
            coordinate_map=coord_dict,
            metadata=metadata,
            format_name=self.format_name,
            source_path=str(file_path),
        )

    def _build_line_index(self, text: str) -> List[tuple]:
        """
        Build an index of line start/end offsets.

        Returns:
            List of (start, end) tuples for each line
        """
        lines = []
        start = 0

        for line in text.split("\n"):
            end = start + len(line)
            lines.append((start, end))
            start = end + 1  # +1 for newline

        return lines

    def _render_markdown(self, text: str, opts: Dict[str, Any]) -> str:
        """
        Render Markdown to HTML using mistune.
        """
        # Create custom renderer with code highlighting
        if opts.get("highlight_code") and PYGMENTS_AVAILABLE:
            renderer = HighlightRenderer()
        else:
            renderer = None

        # Configure mistune
        if opts.get("gfm"):
            # Use plugins for GFM features
            md = mistune.create_markdown(
                renderer=renderer,
                plugins=['strikethrough', 'table', 'task_lists']
            )
        else:
            md = mistune.create_markdown(renderer=renderer)

        html_content = md(text)

        # Wrap in container
        return f'<div class="markdown-content">{html_content}</div>'

    def _extract_headings(self, text: str) -> List[Dict[str, Any]]:
        """
        Extract heading structure from Markdown source.
        """
        headings = []
        heading_pattern = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)

        for match in heading_pattern.finditer(text):
            level = len(match.group(1))
            title = match.group(2).strip()
            headings.append({
                "level": level,
                "title": title,
                "offset": match.start(),
                "line": text[:match.start()].count("\n") + 1,
            })

        return headings

    def extract_toc(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Extract table of contents from a Markdown file.

        Args:
            file_path: Path to the Markdown file

        Returns:
            List of heading entries with level, title, and line number
        """
        path = Path(file_path)
        source_text = path.read_text(encoding="utf-8")
        return self._extract_headings(source_text)


class HighlightRenderer(mistune.HTMLRenderer if MISTUNE_AVAILABLE else object):
    """
    Custom Mistune renderer with Pygments syntax highlighting.
    """

    def __init__(self):
        if MISTUNE_AVAILABLE:
            super().__init__()
        self.formatter = HtmlFormatter(cssclass="highlight") if PYGMENTS_AVAILABLE else None

    def block_code(self, code: str, info: str = None) -> str:
        """
        Render a code block with syntax highlighting.
        """
        if not PYGMENTS_AVAILABLE or not self.formatter:
            escaped = html.escape(code)
            lang_attr = f' class="language-{info}"' if info else ''
            return f'<pre><code{lang_attr}>{escaped}</code></pre>\n'

        try:
            if info:
                lexer = get_lexer_by_name(info, stripall=True)
            else:
                lexer = guess_lexer(code)
        except Exception:
            # Fall back to plain text
            escaped = html.escape(code)
            return f'<pre><code>{escaped}</code></pre>\n'

        return highlight(code, lexer, self.formatter)

    def codespan(self, text: str) -> str:
        """
        Render inline code.
        """
        escaped = html.escape(text)
        return f'<code class="inline-code">{escaped}</code>'
