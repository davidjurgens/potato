"""
Claude Code Trace Converter

Converts Claude Code session traces to Potato's canonical format,
preserving the structured tool call information in extra_fields["structured_turns"].

Unlike the AnthropicConverter which flattens everything to speaker/text pairs,
this converter preserves tool name, input parameters, output, and output_type
so that the CodingTraceDisplay can render them with proper formatting.

Supported input formats:

1. Claude Code session format (structured_turns already present):
{
    "id": "session_001",
    "task_description": "Fix the auth bug",
    "structured_turns": [
        {
            "role": "assistant",
            "reasoning": "I'll investigate...",
            "tool_calls": [
                {"tool": "Read", "input": {"file_path": "..."}, "output": "..."}
            ]
        }
    ]
}

2. Anthropic Messages API format with tool_use/tool_result blocks:
{
    "id": "msg_abc",
    "model": "claude-sonnet-4-20250514",
    "messages": [
        {"role": "user", "content": "Fix the bug"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "I'll look into it."},
            {"type": "tool_use", "id": "toolu_1", "name": "Read", "input": {"file_path": "src/main.py"}}
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": "def main():..."}
        ]}
    ]
}

3. Generic coding agent format with turns/steps:
{
    "id": "trace_001",
    "task": "Fix auth",
    "turns": [
        {
            "role": "assistant",
            "content": "Reasoning text",
            "tool_calls": [{"tool": "Read", "input": {...}, "output": "..."}]
        }
    ]
}
"""

import json
import os
from typing import Any, Dict, List, Optional

from ..base import BaseTraceConverter, CanonicalTrace


# Known coding agent tool names
CODING_TOOLS = {
    "Read", "Write", "Edit", "Bash", "Grep", "Glob", "Search",
    "read", "write", "edit", "bash", "grep", "glob", "search",
    "Terminal", "terminal", "Shell", "shell", "Run", "run",
    "Find", "find", "Replace", "replace", "Create", "create",
    # Claude Code specific
    "Agent", "WebSearch", "WebFetch", "NotebookEdit",
}

# File extension to language mapping
EXTENSION_LANGUAGES = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".jsx": "jsx", ".tsx": "tsx", ".rb": "ruby", ".go": "go",
    ".rs": "rust", ".java": "java", ".c": "c", ".cpp": "cpp",
    ".sh": "bash", ".yaml": "yaml", ".yml": "yaml", ".json": "json",
    ".html": "html", ".css": "css", ".sql": "sql", ".md": "markdown",
}


def _detect_language(file_path: str) -> str:
    """Detect programming language from file extension."""
    if not file_path:
        return ""
    ext = os.path.splitext(file_path)[1].lower()
    return EXTENSION_LANGUAGES.get(ext, "")


def _classify_output_type(tool_name: str, tool_input: dict) -> str:
    """Classify the output type based on tool name."""
    name_lower = tool_name.lower() if tool_name else ""
    if name_lower in ("bash", "terminal", "shell", "run"):
        return "terminal"
    if name_lower in ("edit", "replace"):
        return "diff"
    if name_lower in ("write", "create"):
        return "code"
    if name_lower in ("read", "grep", "glob", "search", "find"):
        return "code"
    return "generic"


class ClaudeCodeConverter(BaseTraceConverter):
    """Converter for Claude Code and similar coding agent traces.

    Preserves structured tool call information in extra_fields["structured_turns"]
    for use with the CodingTraceDisplay.
    """

    format_name = "claude_code"
    description = (
        "Claude Code and coding agent traces with structured tool calls "
        "(Read, Edit, Bash, Grep, Glob, Write)"
    )
    file_extensions = [".json", ".jsonl"]

    def convert(self, data: Any, options: Optional[Dict] = None) -> List[CanonicalTrace]:
        options = options or {}
        traces = data if isinstance(data, list) else [data]
        results = []

        for item in traces:
            if not isinstance(item, dict):
                continue
            results.append(self._convert_item(item, len(results)))

        return results

    def _convert_item(self, item: dict, index: int) -> CanonicalTrace:
        """Convert a single trace item."""
        trace_id = item.get("id", f"claude_code_{index}")

        # Detect format and extract structured turns
        if "structured_turns" in item:
            # Already in structured format
            structured_turns = item["structured_turns"]
            task_desc = item.get("task_description", item.get("task", ""))
            model = item.get("model", item.get("agent_name", ""))
        elif "messages" in item:
            # Anthropic Messages API format
            structured_turns = self._extract_from_messages(item.get("messages", []))
            task_desc = self._extract_task_description(item)
            model = item.get("model", "")
        elif "turns" in item:
            # Generic turns format
            structured_turns = item["turns"]
            task_desc = item.get("task_description", item.get("task", ""))
            model = item.get("model", item.get("agent_name", ""))
        elif "steps" in item:
            # Steps format (SWE-Agent style)
            structured_turns = self._normalize_steps(item.get("steps", []))
            task_desc = item.get("task_description", item.get("task", ""))
            model = item.get("model", "")
        else:
            # Try to use the item itself as a single turn
            structured_turns = [item]
            task_desc = item.get("task_description", item.get("task", ""))
            model = item.get("model", "")

        # Enrich tool calls with output_type and language
        structured_turns = self._enrich_tool_calls(structured_turns)

        # Also produce flattened conversation for backward compatibility
        conversation = self._flatten_to_conversation(structured_turns)

        # Build metadata
        metadata_table = []
        if model:
            metadata_table.append({"Property": "Model", "Value": str(model)})

        usage = item.get("usage", {})
        if usage:
            for key, value in usage.items():
                metadata_table.append({"Property": key, "Value": str(value)})

        # Count files and tools
        file_count, tool_count = self._count_files_and_tools(structured_turns)
        if file_count:
            metadata_table.append({"Property": "Files touched", "Value": str(file_count)})
        if tool_count:
            metadata_table.append({"Property": "Tool calls", "Value": str(tool_count)})

        return CanonicalTrace(
            id=str(trace_id),
            task_description=task_desc,
            conversation=conversation,
            agent_name=model,
            metadata_table=metadata_table,
            extra_fields={"structured_turns": structured_turns},
        )

    def _extract_from_messages(self, messages: list) -> List[Dict[str, Any]]:
        """Extract structured turns from Anthropic Messages API format."""
        turns = []
        pending_tool_results = {}  # tool_use_id -> result

        # First pass: collect tool results
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            content = msg.get("content", "")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        tool_use_id = block.get("tool_use_id", "")
                        result_content = block.get("content", "")
                        if isinstance(result_content, list):
                            parts = []
                            for sub in result_content:
                                if isinstance(sub, dict) and sub.get("type") == "text":
                                    parts.append(sub.get("text", ""))
                                elif isinstance(sub, str):
                                    parts.append(sub)
                            result_content = "\n".join(parts)
                        is_error = block.get("is_error", False)
                        pending_tool_results[tool_use_id] = {
                            "content": result_content,
                            "is_error": is_error,
                        }

        # Second pass: build structured turns
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "user":
                # Extract plain text from user messages
                if isinstance(content, str) and content:
                    turns.append({"role": "user", "content": content, "tool_calls": []})
                elif isinstance(content, list):
                    text_parts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                    if text_parts:
                        turns.append({"role": "user", "content": "\n".join(text_parts), "tool_calls": []})

            elif role == "assistant":
                reasoning_parts = []
                tool_calls = []

                if isinstance(content, str):
                    reasoning_parts.append(content)
                elif isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        block_type = block.get("type", "")

                        if block_type == "text":
                            reasoning_parts.append(block.get("text", ""))
                        elif block_type == "thinking":
                            # Include thinking as part of reasoning
                            thinking = block.get("thinking", "")
                            if thinking:
                                reasoning_parts.append(f"[Thinking] {thinking}")
                        elif block_type == "tool_use":
                            tool_use_id = block.get("id", "")
                            tool_name = block.get("name", "unknown")
                            tool_input = block.get("input", {})

                            # Match with tool result
                            result = pending_tool_results.get(tool_use_id, {})
                            output = result.get("content", "")

                            tool_calls.append({
                                "tool": tool_name,
                                "input": tool_input,
                                "output": str(output) if output else "",
                            })

                turns.append({
                    "role": "assistant",
                    "content": "\n".join(reasoning_parts),
                    "tool_calls": tool_calls,
                })

        return turns

    def _normalize_steps(self, steps: list) -> List[Dict[str, Any]]:
        """Normalize SWE-Agent style steps to structured turns."""
        turns = []
        for step in steps:
            if not isinstance(step, dict):
                continue

            thought = step.get("thought", step.get("reasoning", ""))
            action = step.get("action", "")
            observation = step.get("observation", step.get("output", ""))

            tool_calls = []
            if action:
                if isinstance(action, dict):
                    tool_calls.append({
                        "tool": action.get("tool", action.get("name", "unknown")),
                        "input": action.get("input", action.get("params", {})),
                        "output": str(observation) if observation else "",
                    })
                else:
                    # Parse "tool_name(args)" format
                    action_str = str(action)
                    match = None
                    if "(" in action_str:
                        paren_idx = action_str.index("(")
                        tool_name = action_str[:paren_idx].strip()
                        tool_calls.append({
                            "tool": tool_name,
                            "input": {"command": action_str},
                            "output": str(observation) if observation else "",
                        })
                    else:
                        tool_calls.append({
                            "tool": "Bash",
                            "input": {"command": action_str},
                            "output": str(observation) if observation else "",
                        })

            turns.append({
                "role": "assistant",
                "content": str(thought) if thought else "",
                "tool_calls": tool_calls,
            })

        return turns

    def _enrich_tool_calls(self, turns: list) -> list:
        """Add output_type and language to tool calls."""
        for turn in turns:
            if not isinstance(turn, dict):
                continue
            for tc in turn.get("tool_calls", []):
                if not isinstance(tc, dict):
                    continue
                tool_name = tc.get("tool", "")
                tool_input = tc.get("input", {})

                if "output_type" not in tc:
                    tc["output_type"] = _classify_output_type(tool_name, tool_input)

                if "language" not in tc and isinstance(tool_input, dict):
                    file_path = tool_input.get("file_path", tool_input.get("path", ""))
                    if file_path:
                        tc["language"] = _detect_language(file_path)

        return turns

    def _flatten_to_conversation(self, turns: list) -> List[Dict[str, str]]:
        """Flatten structured turns to speaker/text conversation for backward compatibility."""
        conversation = []

        for turn in turns:
            if not isinstance(turn, dict):
                continue

            role = turn.get("role", "assistant")

            if role == "user":
                content = turn.get("content", "")
                if content:
                    conversation.append({"speaker": "User", "text": content})
                continue

            # Assistant turn
            content = turn.get("content", turn.get("reasoning", ""))
            if content:
                conversation.append({"speaker": "Agent", "text": content})

            for tc in turn.get("tool_calls", []):
                tool_name = tc.get("tool", "unknown")
                tool_input = tc.get("input", {})

                # Format tool call
                try:
                    if isinstance(tool_input, dict):
                        args_str = json.dumps(tool_input, ensure_ascii=False)
                    else:
                        args_str = str(tool_input)
                except (TypeError, ValueError):
                    args_str = str(tool_input)

                conversation.append({
                    "speaker": f"Agent ({tool_name})",
                    "text": f"{tool_name}({args_str})",
                })

                # Tool output
                output = tc.get("output", "")
                if output:
                    conversation.append({
                        "speaker": "Environment",
                        "text": str(output),
                    })

        return conversation

    def _extract_task_description(self, item: dict) -> str:
        """Extract task description from various fields."""
        # Check explicit fields first
        for key in ("task_description", "task", "description", "prompt"):
            if key in item and item[key]:
                return str(item[key])

        # Check system prompt
        system = item.get("system", "")
        if system:
            return str(system) if isinstance(system, str) else ""

        # Use first user message
        messages = item.get("messages", [])
        for msg in messages:
            if isinstance(msg, dict) and msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            return block.get("text", "")
        return ""

    def _count_files_and_tools(self, turns: list) -> tuple:
        """Count unique files and total tool calls."""
        files = set()
        tool_count = 0

        for turn in turns:
            if not isinstance(turn, dict):
                continue
            for tc in turn.get("tool_calls", []):
                tool_count += 1
                tool_input = tc.get("input", {})
                if isinstance(tool_input, dict):
                    file_path = tool_input.get("file_path", tool_input.get("path", ""))
                    if file_path:
                        files.add(file_path)

        return len(files), tool_count

    def detect(self, data: Any) -> bool:
        """Detect if data is a coding agent trace."""
        items = data if isinstance(data, list) else [data]
        if not items:
            return False

        first = items[0]
        if not isinstance(first, dict):
            return False

        # Direct structured_turns format
        if "structured_turns" in first:
            return True

        # Check for coding tool names in messages
        messages = first.get("messages", [])
        if isinstance(messages, list):
            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                content = msg.get("content")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            name = block.get("name", "")
                            if name in CODING_TOOLS:
                                return True

        # Check turns format with tool_calls
        turns = first.get("turns", first.get("steps", []))
        if isinstance(turns, list):
            for turn in turns:
                if isinstance(turn, dict):
                    for tc in turn.get("tool_calls", []):
                        if isinstance(tc, dict) and tc.get("tool", "") in CODING_TOOLS:
                            return True

        return False
