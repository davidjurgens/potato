"""
Source Code Format Handler

Parses source code files with syntax highlighting and line/column
coordinate mapping for code annotation tasks.

Usage:
    from potato.format_handlers.code_handler import CodeHandler

    handler = CodeHandler()
    output = handler.extract("script.py", {
        "show_line_numbers": True,
        "highlight_syntax": True,
    })
"""

from typing import Dict, List, Any, Optional
from pathlib import Path
import html
import logging
import re

from .base import BaseFormatHandler, FormatOutput
from .coordinate_mapping import CoordinateMapper, CodeCoordinate

logger = logging.getLogger(__name__)

# Check if Pygments is available
try:
    from pygments import highlight
    from pygments.lexers import get_lexer_by_name, get_lexer_for_filename, guess_lexer
    from pygments.formatters import HtmlFormatter
    from pygments.token import Token
    PYGMENTS_AVAILABLE = True
except ImportError:
    PYGMENTS_AVAILABLE = False


# Common source code extensions and their languages
LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "jsx",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".r": "r",
    ".R": "r",
    ".sql": "sql",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "zsh",
    ".ps1": "powershell",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".xml": "xml",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".less": "less",
    ".lua": "lua",
    ".pl": "perl",
    ".m": "matlab",
    ".jl": "julia",
    ".hs": "haskell",
    ".ml": "ocaml",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".clj": "clojure",
    ".lisp": "lisp",
    ".vim": "vim",
    ".dockerfile": "docker",
    ".tf": "terraform",
    ".proto": "protobuf",
    ".graphql": "graphql",
}


class CodeHandler(BaseFormatHandler):
    """
    Handler for source code files.

    Provides syntax highlighting via Pygments and line/column coordinate
    mapping for code annotation.
    """

    format_name = "code"
    supported_extensions = list(LANGUAGE_MAP.keys())
    description = "Source code with syntax highlighting and line/column mapping"
    requires_dependencies = ["pygments"]

    def get_default_options(self) -> Dict[str, Any]:
        """Get default extraction options."""
        return {
            "highlight_syntax": True,
            "show_line_numbers": True,
            "language": None,  # Auto-detect from extension
            "tab_size": 4,
            "max_lines": None,
            "start_line": 1,
            "extract_structure": True,  # Extract function/class names
        }

    def extract(
        self,
        file_path: str,
        options: Optional[Dict[str, Any]] = None
    ) -> FormatOutput:
        """
        Parse and render a source code file.

        Args:
            file_path: Path to the source code file
            options: Extraction options:
                - highlight_syntax: Apply syntax highlighting
                - show_line_numbers: Include line numbers in output
                - language: Override language detection
                - tab_size: Spaces per tab for rendering
                - max_lines: Limit number of lines
                - extract_structure: Extract function/class definitions

        Returns:
            FormatOutput with code text, highlighted HTML, and coordinates
        """
        opts = self.merge_options(options)
        path = Path(file_path)

        # Read source file
        source_text = path.read_text(encoding="utf-8")

        # Expand tabs if needed
        if opts.get("tab_size"):
            source_text = source_text.expandtabs(opts["tab_size"])

        # Build line index and coordinates
        lines = source_text.split("\n")
        mapper = CoordinateMapper()
        line_offsets = []
        current_offset = 0

        # Apply line limits
        start_line = opts.get("start_line", 1) - 1  # Convert to 0-indexed
        max_lines = opts.get("max_lines")
        end_line = min(len(lines), start_line + max_lines) if max_lines else len(lines)

        # Build coordinate mappings for each line
        for line_num, line in enumerate(lines):
            line_start = current_offset
            line_end = current_offset + len(line)
            line_offsets.append((line_start, line_end))

            # Only map lines within our range
            if start_line <= line_num < end_line:
                mapper.add_mapping(
                    line_start,
                    line_end,
                    CodeCoordinate(
                        line=line_num + 1,  # 1-indexed
                        column=1,
                    )
                )

            current_offset = line_end + 1  # +1 for newline

        # Extract text for the requested range
        if start_line > 0 or max_lines:
            display_lines = lines[start_line:end_line]
            display_text = "\n".join(display_lines)
        else:
            display_text = source_text

        # Detect language
        language = opts.get("language")
        if not language:
            ext = path.suffix.lower()
            language = LANGUAGE_MAP.get(ext, "text")

        # Render HTML
        if opts.get("highlight_syntax") and PYGMENTS_AVAILABLE:
            rendered_html = self._render_highlighted(
                display_text, language, opts, start_line + 1
            )
        else:
            rendered_html = self._render_plain(
                display_text, opts, start_line + 1
            )

        # Extract code structure
        structure = []
        if opts.get("extract_structure"):
            structure = self._extract_structure(source_text, language)

        metadata = {
            "format": "code",
            "source_file": str(file_path),
            "language": language,
            "line_count": len(lines),
            "char_count": len(source_text),
            "displayed_lines": (start_line + 1, end_line),
            "structure": structure,
        }

        coord_dict = mapper.to_dict()
        coord_dict["get_coords_for_range"] = mapper.get_coords_for_range

        return FormatOutput(
            text=display_text,
            rendered_html=rendered_html,
            coordinate_map=coord_dict,
            metadata=metadata,
            format_name=self.format_name,
            source_path=str(file_path),
        )

    def _render_highlighted(
        self,
        code: str,
        language: str,
        opts: Dict[str, Any],
        start_line: int
    ) -> str:
        """
        Render code with Pygments syntax highlighting.
        """
        try:
            lexer = get_lexer_by_name(language, stripall=False)
        except Exception:
            try:
                lexer = guess_lexer(code)
            except Exception:
                lexer = get_lexer_by_name("text")

        # Configure formatter
        formatter_opts = {
            "cssclass": "code-highlight",
            "linenos": opts.get("show_line_numbers", True),
            "linenostart": start_line,
            "lineanchors": "line",
            "anchorlinenos": True,
        }

        if opts.get("show_line_numbers"):
            formatter_opts["linenos"] = "table"

        formatter = HtmlFormatter(**formatter_opts)
        highlighted = highlight(code, lexer, formatter)

        # Wrap in container
        return f'<div class="code-content language-{language}">{highlighted}</div>'

    def _render_plain(
        self,
        code: str,
        opts: Dict[str, Any],
        start_line: int
    ) -> str:
        """
        Render code as plain text with optional line numbers.
        """
        lines = code.split("\n")
        html_parts = []

        html_parts.append('<div class="code-content code-plain">')
        html_parts.append('<table class="code-table">')

        for i, line in enumerate(lines, start=start_line):
            escaped_line = html.escape(line) or "&nbsp;"

            if opts.get("show_line_numbers"):
                html_parts.append(
                    f'<tr id="line-{i}">'
                    f'<td class="line-number" data-line="{i}">{i}</td>'
                    f'<td class="line-content"><code>{escaped_line}</code></td>'
                    f'</tr>'
                )
            else:
                html_parts.append(
                    f'<tr id="line-{i}">'
                    f'<td class="line-content"><code>{escaped_line}</code></td>'
                    f'</tr>'
                )

        html_parts.append('</table>')
        html_parts.append('</div>')

        return "\n".join(html_parts)

    def _extract_structure(
        self,
        code: str,
        language: str
    ) -> List[Dict[str, Any]]:
        """
        Extract code structure (functions, classes) using pattern matching.

        This is a simplified extraction that works for common languages.
        For production use, consider using language-specific parsers.
        """
        structure = []

        # Pattern definitions for common languages
        patterns = {
            "python": {
                "function": r"^\s*(?:async\s+)?def\s+(\w+)\s*\(",
                "class": r"^\s*class\s+(\w+)\s*[:\(]",
            },
            "javascript": {
                "function": r"(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>|(?:const|let|var)\s+(\w+)\s*=\s*function)",
                "class": r"class\s+(\w+)",
            },
            "java": {
                "function": r"(?:public|private|protected|static|\s)+[\w<>\[\]]+\s+(\w+)\s*\([^\)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{",
                "class": r"(?:public|private|protected)?\s*class\s+(\w+)",
            },
            "go": {
                "function": r"func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(",
                "class": r"type\s+(\w+)\s+struct",
            },
            "rust": {
                "function": r"(?:pub\s+)?fn\s+(\w+)",
                "class": r"(?:pub\s+)?struct\s+(\w+)",
            },
        }

        # Get patterns for this language (or use generic)
        lang_patterns = patterns.get(language, {})

        lines = code.split("\n")
        for line_num, line in enumerate(lines, start=1):
            # Check for functions
            if "function" in lang_patterns:
                match = re.search(lang_patterns["function"], line)
                if match:
                    name = next((g for g in match.groups() if g), None)
                    if name:
                        structure.append({
                            "type": "function",
                            "name": name,
                            "line": line_num,
                        })

            # Check for classes/structs
            if "class" in lang_patterns:
                match = re.search(lang_patterns["class"], line)
                if match:
                    name = match.group(1)
                    structure.append({
                        "type": "class",
                        "name": name,
                        "line": line_num,
                    })

        return structure

    def get_language(self, file_path: str) -> str:
        """
        Detect the programming language from a file path.

        Args:
            file_path: Path to the source file

        Returns:
            Language identifier
        """
        ext = Path(file_path).suffix.lower()
        return LANGUAGE_MAP.get(ext, "text")
