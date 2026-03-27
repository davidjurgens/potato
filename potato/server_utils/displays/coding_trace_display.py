"""
Coding Trace Display Type

Purpose-built rendering for agentic coding system traces (Claude Code, OpenCode,
Cursor, Aider, SWE-Agent). Renders tool calls with appropriate formatting:
- Code diffs (Edit/Write) with red/green highlighting
- Terminal blocks (Bash) with dark monospace styling
- Code blocks (Read/Grep/Glob) with line numbers
- File tree sidebar showing all files touched
- Collapsible long outputs
- Turn structure: User messages → assistant reasoning → tool calls

Usage:
    In instance_display config:
    fields:
      - key: structured_turns
        type: coding_trace
        display_options:
          show_file_tree: true
          diff_view: unified
          collapse_long_outputs: true
          max_output_lines: 50
          terminal_theme: dark
"""

import html
import json
import os
import re
from typing import Dict, Any, List, Optional, Set, Tuple

from .base import BaseDisplay


# Tool type classifications - order matters: more specific sets checked first
CODE_READ_TOOLS = {"Read", "read"}
CODE_EDIT_TOOLS = {"Edit", "edit", "Replace", "replace"}
CODE_WRITE_TOOLS = {"Write", "write", "Create", "create"}
TERMINAL_TOOLS = {"Bash", "bash", "Terminal", "terminal", "Shell", "shell", "Run", "run"}
SEARCH_TOOLS = {"Grep", "grep", "Glob", "glob", "Search", "search", "Find", "find"}

# File extension to language mapping
EXTENSION_LANGUAGES = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".jsx": "jsx", ".tsx": "tsx", ".rb": "ruby", ".go": "go",
    ".rs": "rust", ".java": "java", ".c": "c", ".cpp": "cpp",
    ".h": "c", ".hpp": "cpp", ".cs": "csharp", ".swift": "swift",
    ".kt": "kotlin", ".scala": "scala", ".r": "r",
    ".sh": "bash", ".bash": "bash", ".zsh": "zsh",
    ".yaml": "yaml", ".yml": "yaml", ".json": "json",
    ".xml": "xml", ".html": "html", ".css": "css",
    ".sql": "sql", ".md": "markdown", ".toml": "toml",
    ".ini": "ini", ".cfg": "ini", ".dockerfile": "dockerfile",
}

# Badge colors for different tool types
TOOL_BADGE_COLORS = {
    "read": ("#e3f2fd", "#1565c0", "#1976d2"),      # Blue
    "edit": ("#fff3e0", "#e65100", "#ef6c00"),        # Orange
    "write": ("#e8f5e9", "#2e7d32", "#388e3c"),       # Green
    "bash": ("#263238", "#b0bec5", "#78909c"),         # Dark
    "search": ("#f3e5f5", "#6a1b9a", "#7b1fa2"),      # Purple
    "generic": ("#f5f5f5", "#424242", "#616161"),      # Grey
}


def _detect_language(file_path: str) -> str:
    """Detect programming language from file extension."""
    if not file_path:
        return ""
    ext = os.path.splitext(file_path)[1].lower()
    return EXTENSION_LANGUAGES.get(ext, "")


def _classify_tool(tool_name: str) -> str:
    """Classify a tool into a rendering category."""
    if tool_name in SEARCH_TOOLS:
        return "search"
    if tool_name in CODE_READ_TOOLS:
        return "read"
    if tool_name in CODE_EDIT_TOOLS:
        return "edit"
    if tool_name in CODE_WRITE_TOOLS:
        return "write"
    if tool_name in TERMINAL_TOOLS:
        return "bash"
    return "generic"


def _escape(text: str) -> str:
    """HTML-escape text."""
    return html.escape(str(text), quote=True)


def _truncate_output(text: str, max_lines: int) -> Tuple[str, bool]:
    """Truncate text to max_lines, return (text, was_truncated)."""
    if not text or max_lines <= 0:
        return text, False
    lines = text.split("\n")
    if len(lines) <= max_lines:
        return text, False
    return "\n".join(lines[:max_lines]), True


class CodingTraceDisplay(BaseDisplay):
    """
    Display type for coding agent traces with rich tool call rendering.

    Renders agent sessions with proper formatting for code diffs,
    terminal output, file reads, and search results.
    """

    name = "coding_trace"
    required_fields = ["key"]
    optional_fields = {
        "show_file_tree": True,
        "diff_view": "unified",           # "unified" or "side_by_side"
        "collapse_long_outputs": True,
        "max_output_lines": 50,
        "terminal_theme": "dark",         # "dark" or "light"
        "show_step_numbers": True,
        "show_tool_badges": True,
        "show_reasoning": True,
        "compact": False,
    }
    description = "Coding agent trace display with diff rendering, terminal blocks, and file tree"
    supports_span_target = True

    def render(self, field_config: Dict[str, Any], data: Any) -> str:
        if not data:
            return '<div class="coding-trace-empty">No trace data provided</div>'

        options = self.get_display_options(field_config)
        field_key = _escape(field_config.get("key", ""))
        is_span_target = field_config.get("span_target", False)

        # Parse turns from data
        turns = self._normalize_turns(data)
        if not turns:
            return '<div class="coding-trace-empty">No trace steps found</div>'

        # Build file tree
        file_tree_html = ""
        if options.get("show_file_tree", True):
            file_tree_html = self._build_file_tree(turns)

        # Build turn cards
        turns_html = self._build_turns(turns, options, field_key, is_span_target)

        # Build summary
        summary_html = self._build_summary(turns)

        # Wrap in span target if needed
        if is_span_target:
            plain_text = self._extract_plain_text(turns)
            reasoning_html = self._extract_reasoning_html(turns)
            # The span target wraps only the reasoning text portions
            inner = reasoning_html
            span_wrapper = self.render_span_wrapper(field_key, inner, plain_text)
        else:
            span_wrapper = ""

        layout_class = "coding-trace-with-sidebar" if file_tree_html else ""

        return f'''
        <div class="coding-trace-display {layout_class}" data-field-key="{field_key}">
            {summary_html}
            <div class="coding-trace-layout">
                {f'<div class="coding-trace-sidebar">{file_tree_html}</div>' if file_tree_html else ''}
                <div class="coding-trace-main">
                    {span_wrapper}
                    {turns_html}
                </div>
            </div>
        </div>
        '''

    def _normalize_turns(self, data: Any) -> List[Dict[str, Any]]:
        """Normalize various input formats to a list of structured turns."""
        if isinstance(data, list):
            turns = []
            for item in data:
                if isinstance(item, dict):
                    turns.append(self._normalize_single_turn(item))
                elif isinstance(item, str):
                    turns.append({"role": "user", "content": item, "tool_calls": []})
            return turns
        if isinstance(data, dict):
            # Single turn
            return [self._normalize_single_turn(data)]
        return []

    def _normalize_single_turn(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize a single turn dict."""
        role = item.get("role", "assistant")
        reasoning = item.get("reasoning", item.get("content", item.get("text", "")))
        tool_calls = item.get("tool_calls", [])

        # Handle string content (user messages)
        if isinstance(reasoning, list):
            # Content blocks format
            text_parts = []
            extracted_tools = []
            for block in reasoning:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        extracted_tools.append({
                            "tool": block.get("name", "unknown"),
                            "input": block.get("input", {}),
                            "output": "",
                            "output_type": "generic",
                        })
                elif isinstance(block, str):
                    text_parts.append(block)
            reasoning = "\n".join(text_parts)
            if extracted_tools and not tool_calls:
                tool_calls = extracted_tools

        return {
            "role": role,
            "content": str(reasoning) if reasoning else "",
            "tool_calls": tool_calls,
        }

    def _build_summary(self, turns: List[Dict[str, Any]]) -> str:
        """Build a summary header with counts."""
        total_tools = sum(len(t.get("tool_calls", [])) for t in turns)
        user_turns = sum(1 for t in turns if t.get("role") == "user")
        assistant_turns = sum(1 for t in turns if t.get("role") != "user")

        # Count tool types
        tool_counts: Dict[str, int] = {}
        for turn in turns:
            for tc in turn.get("tool_calls", []):
                tool_type = _classify_tool(tc.get("tool", ""))
                tool_counts[tool_type] = tool_counts.get(tool_type, 0) + 1

        badges = []
        for tool_type, count in sorted(tool_counts.items()):
            bg, fg, _ = TOOL_BADGE_COLORS.get(tool_type, TOOL_BADGE_COLORS["generic"])
            badges.append(
                f'<span class="ct-summary-badge" style="background:{bg};color:{fg}">'
                f'{count} {tool_type}</span>'
            )

        return f'''
        <div class="ct-summary">
            <span class="ct-summary-total">{assistant_turns} turn{"s" if assistant_turns != 1 else ""}</span>
            <span class="ct-summary-sep">&middot;</span>
            <span class="ct-summary-tools">{total_tools} tool call{"s" if total_tools != 1 else ""}</span>
            {" ".join(badges)}
        </div>
        '''

    def _build_turns(self, turns: List[Dict[str, Any]], options: Dict[str, Any],
                     field_key: str, is_span_target: bool) -> str:
        """Build HTML for all turns."""
        parts = []
        step_counter = 0
        show_numbers = options.get("show_step_numbers", True)
        max_lines = options.get("max_output_lines", 50)
        collapse = options.get("collapse_long_outputs", True)
        show_reasoning = options.get("show_reasoning", True)

        for i, turn in enumerate(turns):
            role = turn.get("role", "assistant")

            if role == "user":
                parts.append(self._render_user_message(turn, i))
                continue

            step_counter += 1

            # Assistant turn
            turn_parts = []

            # Step header
            if show_numbers:
                turn_parts.append(
                    f'<div class="ct-turn-header">'
                    f'<span class="ct-step-num">Step {step_counter}</span>'
                    f'</div>'
                )

            # Reasoning text
            content = turn.get("content", "")
            if content and show_reasoning:
                escaped = _escape(content)
                turn_parts.append(
                    f'<div class="ct-reasoning">{escaped}</div>'
                )

            # Tool calls
            tool_calls = turn.get("tool_calls", [])
            for j, tc in enumerate(tool_calls):
                tc_html = self._render_tool_call(tc, options, f"{i}-{j}")
                turn_parts.append(tc_html)

            parts.append(
                f'<div class="ct-turn ct-turn-assistant" data-turn-index="{i}">'
                f'{"".join(turn_parts)}'
                f'</div>'
            )

        return "\n".join(parts)

    def _render_user_message(self, turn: Dict[str, Any], index: int) -> str:
        """Render a user message bubble."""
        content = _escape(turn.get("content", ""))
        return (
            f'<div class="ct-turn ct-turn-user" data-turn-index="{index}">'
            f'<div class="ct-user-badge">User</div>'
            f'<div class="ct-user-text">{content}</div>'
            f'</div>'
        )

    def _render_tool_call(self, tc: Dict[str, Any], options: Dict[str, Any],
                          tc_id: str) -> str:
        """Render a single tool call with appropriate formatting."""
        tool_name = tc.get("tool", "unknown")
        tool_input = tc.get("input", {})
        tool_output = tc.get("output", "")
        output_type = tc.get("output_type", "")
        tool_type = _classify_tool(tool_name)

        # If output_type not specified, infer from tool
        if not output_type:
            output_type = tool_type

        # Badge
        bg, fg, border = TOOL_BADGE_COLORS.get(tool_type, TOOL_BADGE_COLORS["generic"])
        badge = (
            f'<span class="ct-tool-badge" style="background:{bg};color:{fg};'
            f'border:1px solid {border}">{_escape(tool_name)}</span>'
        )

        # File path header (if applicable)
        file_path = ""
        if isinstance(tool_input, dict):
            file_path = tool_input.get("file_path", tool_input.get("path", ""))

        file_header = ""
        if file_path:
            file_header = f'<span class="ct-file-path">{_escape(file_path)}</span>'

        # Render input/output based on tool type
        if tool_type == "edit":
            body = self._render_diff(tool_input, tool_output, options)
        elif tool_type == "bash":
            body = self._render_terminal(tool_input, tool_output, options)
        elif tool_type in ("read", "search"):
            body = self._render_code_output(tool_input, tool_output, options)
        elif tool_type == "write":
            body = self._render_write(tool_input, tool_output, options)
        else:
            body = self._render_generic(tool_input, tool_output, options)

        return (
            f'<div class="ct-tool-call ct-tool-{_escape(tool_type)}" data-tool-id="{_escape(tc_id)}">'
            f'<div class="ct-tool-header">{badge}{file_header}</div>'
            f'<div class="ct-tool-body">{body}</div>'
            f'</div>'
        )

    def _render_diff(self, tool_input: Any, tool_output: Any,
                     options: Dict[str, Any]) -> str:
        """Render an edit as a unified diff."""
        if not isinstance(tool_input, dict):
            return self._render_generic(tool_input, tool_output, options)

        old_string = tool_input.get("old_string", "")
        new_string = tool_input.get("new_string", "")
        file_path = tool_input.get("file_path", "")

        if not old_string and not new_string:
            return self._render_generic(tool_input, tool_output, options)

        # Build unified diff view
        old_lines = old_string.split("\n") if old_string else []
        new_lines = new_string.split("\n") if new_string else []

        diff_parts = []
        diff_parts.append('<div class="ct-diff">')

        # Removed lines
        for line in old_lines:
            escaped = _escape(line)
            diff_parts.append(
                f'<div class="ct-diff-line ct-diff-removed">'
                f'<span class="ct-diff-marker">-</span>'
                f'<span class="ct-diff-text">{escaped}</span>'
                f'</div>'
            )

        # Added lines
        for line in new_lines:
            escaped = _escape(line)
            diff_parts.append(
                f'<div class="ct-diff-line ct-diff-added">'
                f'<span class="ct-diff-marker">+</span>'
                f'<span class="ct-diff-text">{escaped}</span>'
                f'</div>'
            )

        diff_parts.append('</div>')

        # Status message
        status = ""
        if tool_output:
            output_str = str(tool_output)
            if output_str:
                status = f'<div class="ct-edit-status">{_escape(output_str)}</div>'

        return "\n".join(diff_parts) + status

    def _render_terminal(self, tool_input: Any, tool_output: Any,
                         options: Dict[str, Any]) -> str:
        """Render a terminal command and its output."""
        command = ""
        if isinstance(tool_input, dict):
            command = tool_input.get("command", tool_input.get("cmd", ""))
        elif isinstance(tool_input, str):
            command = tool_input

        output_str = str(tool_output) if tool_output else ""
        max_lines = options.get("max_output_lines", 50)
        collapse = options.get("collapse_long_outputs", True)

        parts = []
        parts.append('<div class="ct-terminal">')

        # Command line
        if command:
            parts.append(
                f'<div class="ct-terminal-cmd">'
                f'<span class="ct-terminal-prompt">$</span> '
                f'{_escape(command)}'
                f'</div>'
            )

        # Output
        if output_str:
            truncated, was_truncated = _truncate_output(output_str, max_lines)
            if was_truncated and collapse:
                parts.append(
                    f'<details class="ct-terminal-output-details">'
                    f'<summary>Output ({len(output_str.splitlines())} lines — click to expand)</summary>'
                    f'<pre class="ct-terminal-output">{_escape(output_str)}</pre>'
                    f'</details>'
                    f'<pre class="ct-terminal-output ct-terminal-truncated">{_escape(truncated)}</pre>'
                )
            else:
                parts.append(
                    f'<pre class="ct-terminal-output">{_escape(output_str)}</pre>'
                )

        parts.append('</div>')
        return "\n".join(parts)

    def _render_code_output(self, tool_input: Any, tool_output: Any,
                            options: Dict[str, Any]) -> str:
        """Render a code read/search result with line numbers."""
        file_path = ""
        if isinstance(tool_input, dict):
            file_path = tool_input.get("file_path", tool_input.get("path", ""))

        output_str = str(tool_output) if tool_output else ""
        language = _detect_language(file_path)
        max_lines = options.get("max_output_lines", 50)
        collapse = options.get("collapse_long_outputs", True)

        if not output_str:
            return '<div class="ct-code-empty">No output</div>'

        lines = output_str.split("\n")
        truncated, was_truncated = _truncate_output(output_str, max_lines)

        # Build line-numbered code block
        display_lines = truncated.split("\n") if was_truncated and collapse else lines

        code_parts = []
        code_parts.append(f'<div class="ct-code-block" data-language="{_escape(language)}">')
        code_parts.append('<table class="ct-code-table">')

        for i, line in enumerate(display_lines, 1):
            escaped = _escape(line) if line else "&nbsp;"
            code_parts.append(
                f'<tr class="ct-code-line">'
                f'<td class="ct-line-num">{i}</td>'
                f'<td class="ct-line-content"><code>{escaped}</code></td>'
                f'</tr>'
            )

        code_parts.append('</table>')

        if was_truncated and collapse:
            remaining = len(lines) - max_lines
            code_parts.append(
                f'<div class="ct-code-truncated">'
                f'... {remaining} more line{"s" if remaining != 1 else ""}'
                f'</div>'
            )

        code_parts.append('</div>')
        return "\n".join(code_parts)

    def _render_write(self, tool_input: Any, tool_output: Any,
                      options: Dict[str, Any]) -> str:
        """Render a file write operation."""
        content = ""
        file_path = ""
        if isinstance(tool_input, dict):
            content = tool_input.get("content", "")
            file_path = tool_input.get("file_path", "")

        if not content:
            return self._render_generic(tool_input, tool_output, options)

        language = _detect_language(file_path)
        max_lines = options.get("max_output_lines", 50)

        # Show as code block with "new file" styling
        lines = content.split("\n")
        truncated, was_truncated = _truncate_output(content, max_lines)
        display_lines = truncated.split("\n") if was_truncated else lines

        parts = []
        parts.append(f'<div class="ct-write-block" data-language="{_escape(language)}">')
        parts.append('<div class="ct-write-label">New file</div>')
        parts.append('<table class="ct-code-table">')

        for i, line in enumerate(display_lines, 1):
            escaped = _escape(line) if line else "&nbsp;"
            parts.append(
                f'<tr class="ct-code-line ct-diff-added">'
                f'<td class="ct-line-num">{i}</td>'
                f'<td class="ct-line-content"><code>{escaped}</code></td>'
                f'</tr>'
            )

        parts.append('</table>')

        if was_truncated:
            remaining = len(lines) - max_lines
            parts.append(
                f'<div class="ct-code-truncated">'
                f'... {remaining} more line{"s" if remaining != 1 else ""}'
                f'</div>'
            )

        parts.append('</div>')

        # Status
        if tool_output:
            parts.append(f'<div class="ct-edit-status">{_escape(str(tool_output))}</div>')

        return "\n".join(parts)

    def _render_generic(self, tool_input: Any, tool_output: Any,
                        options: Dict[str, Any]) -> str:
        """Render a generic tool call as formatted JSON."""
        parts = []

        if tool_input:
            try:
                if isinstance(tool_input, dict):
                    formatted = json.dumps(tool_input, indent=2, ensure_ascii=False)
                else:
                    formatted = str(tool_input)
            except (TypeError, ValueError):
                formatted = str(tool_input)
            parts.append(
                f'<div class="ct-generic-input">'
                f'<div class="ct-generic-label">Input</div>'
                f'<pre class="ct-generic-pre">{_escape(formatted)}</pre>'
                f'</div>'
            )

        if tool_output:
            output_str = str(tool_output)
            max_lines = options.get("max_output_lines", 50)
            truncated, was_truncated = _truncate_output(output_str, max_lines)

            truncated_div = '<div class="ct-code-truncated">... output truncated</div>' if was_truncated else ""
            parts.append(
                f'<div class="ct-generic-output">'
                f'<div class="ct-generic-label">Output</div>'
                f'<pre class="ct-generic-pre">{_escape(truncated if was_truncated else output_str)}</pre>'
                f'{truncated_div}'
                f'</div>'
            )

        return "\n".join(parts) if parts else '<div class="ct-generic-empty">No data</div>'

    def _build_file_tree(self, turns: List[Dict[str, Any]]) -> str:
        """Build a file tree sidebar from all tool calls."""
        files: Dict[str, Set[str]] = {}  # path -> set of operations

        for turn in turns:
            for tc in turn.get("tool_calls", []):
                tool_name = tc.get("tool", "")
                tool_type = _classify_tool(tool_name)
                tool_input = tc.get("input", {})

                if isinstance(tool_input, dict):
                    file_path = tool_input.get("file_path", tool_input.get("path", ""))
                    if file_path:
                        if file_path not in files:
                            files[file_path] = set()
                        files[file_path].add(tool_type)

        if not files:
            return ""

        # Group by operation type
        op_icons = {
            "read": ("eye", "#1976d2"),
            "edit": ("pencil", "#ef6c00"),
            "write": ("plus", "#388e3c"),
            "search": ("search", "#7b1fa2"),
            "bash": ("terminal", "#78909c"),
        }

        parts = []
        parts.append('<div class="ct-file-tree">')
        parts.append('<div class="ct-file-tree-header">Files</div>')
        parts.append('<ul class="ct-file-list">')

        for path in sorted(files.keys()):
            ops = files[path]
            # Pick the most significant operation for the icon
            op = "write" if "write" in ops else "edit" if "edit" in ops else "read"
            _, color = op_icons.get(op, ("file", "#666"))

            # Show just the filename with the directory as a tooltip
            basename = os.path.basename(path) or path
            dirname = os.path.dirname(path)

            op_badges = " ".join(
                f'<span class="ct-file-op" style="color:{op_icons.get(o, ("", "#666"))[1]}">'
                f'{o[0].upper()}</span>'
                for o in sorted(ops)
            )

            parts.append(
                f'<li class="ct-file-item" title="{_escape(path)}">'
                f'<span class="ct-file-name" style="color:{color}">{_escape(basename)}</span>'
                f'{op_badges}'
                f'</li>'
            )

        parts.append('</ul>')
        parts.append('</div>')
        return "\n".join(parts)

    def _extract_plain_text(self, turns: List[Dict[str, Any]]) -> str:
        """Extract plain text from reasoning for span annotation."""
        parts = []
        for turn in turns:
            content = turn.get("content", "")
            if content and turn.get("role") != "user":
                parts.append(content)
        return "\n".join(parts)

    def _extract_reasoning_html(self, turns: List[Dict[str, Any]]) -> str:
        """Extract reasoning HTML for span target wrapper."""
        parts = []
        for turn in turns:
            content = turn.get("content", "")
            if content and turn.get("role") != "user":
                parts.append(_escape(content))
        return "<br>".join(parts)

    def get_css_classes(self, field_config: Dict[str, Any]) -> List[str]:
        classes = super().get_css_classes(field_config)
        if field_config.get("span_target"):
            classes.append("span-target-field")
        return classes

    def get_data_attributes(self, field_config: Dict[str, Any], data: Any) -> Dict[str, str]:
        attrs = super().get_data_attributes(field_config, data)
        if field_config.get("span_target"):
            attrs["span-target"] = "true"
        return attrs
