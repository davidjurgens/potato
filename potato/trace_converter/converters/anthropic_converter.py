"""
Anthropic Claude Messages Converter

Converts Anthropic Messages API traces to Potato's canonical format.

Supported input formats:

1. Single conversation (messages array with content blocks):
{
    "id": "msg_abc123",
    "model": "claude-sonnet-4-20250514",
    "messages": [
        {"role": "user", "content": "What is the weather?"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "Let me check the weather."},
            {"type": "tool_use", "id": "toolu_1", "name": "get_weather", "input": {"location": "NYC"}},
        ]}
    ],
    "usage": {"input_tokens": 100, "output_tokens": 50}
}

2. Request/response pairs:
{
    "id": "trace_001",
    "request": {
        "model": "claude-sonnet-4-20250514",
        "messages": [...]
    },
    "response": {
        "content": [...],
        "usage": {...}
    }
}

3. Conversation with tool_result blocks inline:
{
    "messages": [
        {"role": "user", "content": "Analyze this data"},
        {"role": "assistant", "content": [{"type": "tool_use", "name": "python", "input": {...}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "..."}]}
    ]
}
"""

import json
from typing import Any, Dict, List, Optional

from ..base import BaseTraceConverter, CanonicalTrace


class AnthropicConverter(BaseTraceConverter):
    """Converter for Anthropic Claude Messages API traces."""

    format_name = "anthropic"
    description = "Anthropic Claude Messages API traces (content blocks with tool_use/tool_result)"
    file_extensions = [".json", ".jsonl"]

    def convert(self, data: Any, options: Optional[Dict] = None) -> List[CanonicalTrace]:
        options = options or {}
        traces = data if isinstance(data, list) else [data]
        results = []

        for item in traces:
            if self._is_request_response_format(item):
                results.append(self._convert_request_response(item, len(results)))
            else:
                results.append(self._convert_messages(item, len(results)))

        return results

    def _convert_messages(self, item: dict, index: int) -> CanonicalTrace:
        """Convert a standard messages-format trace."""
        trace_id = item.get("id", f"anthropic_{index}")
        model = item.get("model", "")
        messages = item.get("messages", [])
        usage = item.get("usage", {})
        system = item.get("system", "")

        conversation = []
        task_description = ""

        # System prompt as task description
        if system:
            if isinstance(system, str):
                task_description = system
            elif isinstance(system, list):
                # System can be a list of content blocks
                task_description = " ".join(
                    b.get("text", "") for b in system if isinstance(b, dict) and b.get("type") == "text"
                )

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "user":
                self._process_content(content, conversation, is_user=True)
                # Use first user message as task description if not set
                if not task_description:
                    if isinstance(content, str):
                        task_description = content
                    elif isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                task_description = block.get("text", "")
                                break

            elif role == "assistant":
                self._process_content(content, conversation, is_user=False)

        # Build metadata table
        metadata_table = []
        if model:
            metadata_table.append({"Property": "Model", "Value": model})
        if usage:
            for key, value in usage.items():
                metadata_table.append({"Property": key, "Value": str(value)})

        return CanonicalTrace(
            id=trace_id,
            task_description=task_description,
            conversation=conversation,
            agent_name=model,
            metadata_table=metadata_table,
        )

    def _convert_request_response(self, item: dict, index: int) -> CanonicalTrace:
        """Convert a request/response pair format trace."""
        trace_id = item.get("id", f"anthropic_rr_{index}")
        request = item.get("request", {})
        response = item.get("response", {})

        model = request.get("model", response.get("model", ""))
        messages = request.get("messages", [])
        usage = response.get("usage", {})
        system = request.get("system", "")

        # Build a combined item and delegate to _convert_messages
        combined = {
            "id": trace_id,
            "model": model,
            "messages": messages,
            "usage": usage,
            "system": system,
        }

        # Also process response content if present
        trace = self._convert_messages(combined, index)

        # Append response content blocks to conversation
        response_content = response.get("content", [])
        if response_content:
            self._process_content(response_content, trace.conversation, is_user=False)

        return trace

    def _process_content(self, content: Any, conversation: list, is_user: bool):
        """Process a content field (string or list of blocks) into conversation turns."""
        if isinstance(content, str):
            if content:
                speaker = "User" if is_user else "Agent"
                conversation.append({"speaker": speaker, "text": content})
            return

        if not isinstance(content, list):
            return

        for block in content:
            if not isinstance(block, dict):
                if is_user:
                    conversation.append({"speaker": "User", "text": str(block)})
                continue

            block_type = block.get("type", "")

            if block_type == "text":
                text = block.get("text", "")
                if text:
                    speaker = "User" if is_user else "Agent"
                    conversation.append({"speaker": speaker, "text": text})

            elif block_type == "tool_use":
                name = block.get("name", "unknown")
                tool_input = block.get("input", {})
                try:
                    args_str = json.dumps(tool_input, ensure_ascii=False)
                except (TypeError, ValueError):
                    args_str = str(tool_input)
                conversation.append({
                    "speaker": "Agent (Action)",
                    "text": f"{name}({args_str})"
                })

            elif block_type == "tool_result":
                result_content = block.get("content", "")
                if isinstance(result_content, str):
                    text = result_content
                elif isinstance(result_content, list):
                    # tool_result content can be a list of blocks
                    parts = []
                    for sub in result_content:
                        if isinstance(sub, dict) and sub.get("type") == "text":
                            parts.append(sub.get("text", ""))
                        elif isinstance(sub, str):
                            parts.append(sub)
                    text = "\n".join(parts)
                else:
                    text = str(result_content)
                if text:
                    is_error = block.get("is_error", False)
                    speaker = "Environment (Error)" if is_error else "Environment"
                    conversation.append({"speaker": speaker, "text": text})

            elif block_type == "thinking":
                text = block.get("thinking", "")
                if text:
                    conversation.append({"speaker": "Agent (Thought)", "text": text})

    def _is_request_response_format(self, item: dict) -> bool:
        """Check if this item uses the request/response pair format."""
        return "request" in item and "response" in item

    def detect(self, data: Any) -> bool:
        items = data if isinstance(data, list) else [data]
        if not items:
            return False
        first = items[0]
        if not isinstance(first, dict):
            return False

        # Request/response pair format
        if "request" in first and "response" in first:
            req = first.get("request", {})
            if isinstance(req, dict) and "messages" in req:
                messages = req["messages"]
                if isinstance(messages, list) and messages:
                    return self._has_content_blocks(messages)

        # Direct messages format
        messages = first.get("messages")
        if not isinstance(messages, list) or not messages:
            return False

        return self._has_content_blocks(messages)

    def _has_content_blocks(self, messages: list) -> bool:
        """Check if messages contain Anthropic-style typed content blocks."""
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            # Anthropic format: content is a list of typed blocks
            if isinstance(content, list) and content:
                if isinstance(content[0], dict) and "type" in content[0]:
                    return True
        return False
