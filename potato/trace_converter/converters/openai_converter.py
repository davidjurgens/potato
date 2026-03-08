"""
OpenAI Chat/Assistants Converter

Converts OpenAI Chat Completions and Assistants API traces
to Potato's canonical format.

Supported input formats:

1. Chat Completions (messages array):
{
    "id": "chatcmpl-abc123",
    "messages": [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is the weather?"},
        {"role": "assistant", "content": "Let me check.", "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": "{\"location\":\"NYC\"}"}}
        ]},
        {"role": "tool", "tool_call_id": "call_1", "content": "Sunny, 72F"},
        {"role": "assistant", "content": "It's sunny and 72F in NYC."}
    ],
    "model": "gpt-4",
    "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
}

2. Assistants API (thread with steps):
{
    "id": "run_abc123",
    "assistant_id": "asst_abc123",
    "thread_id": "thread_abc123",
    "instructions": "Help with travel planning",
    "steps": [
        {"type": "message_creation", "message": {"content": [{"text": {"value": "..."}}]}},
        {"type": "tool_calls", "tool_calls": [{"type": "function", "function": {"name": "...", "arguments": "..."}}]}
    ]
}

3. Batch/list of conversations (array of the above)
"""

import json
from typing import Any, Dict, List, Optional

from ..base import BaseTraceConverter, CanonicalTrace


class OpenAIConverter(BaseTraceConverter):
    """Converter for OpenAI Chat Completions and Assistants API traces."""

    format_name = "openai"
    description = "OpenAI Chat Completions and Assistants API traces"
    file_extensions = [".json", ".jsonl"]

    def convert(self, data: Any, options: Optional[Dict] = None) -> List[CanonicalTrace]:
        options = options or {}
        traces = data if isinstance(data, list) else [data]
        results = []

        for item in traces:
            if self._is_assistants_format(item):
                results.append(self._convert_assistants(item, len(results)))
            else:
                results.append(self._convert_chat(item, len(results)))

        return results

    def _convert_chat(self, item: dict, index: int) -> CanonicalTrace:
        """Convert a Chat Completions format trace."""
        trace_id = item.get("id", f"openai_chat_{index}")
        messages = item.get("messages", [])
        model = item.get("model", "")
        usage = item.get("usage", {})

        conversation = []
        task_description = ""

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "system":
                # System messages stored as metadata, not conversation turns
                if not task_description:
                    task_description = content if isinstance(content, str) else str(content)
                continue

            if role == "user":
                text = content if isinstance(content, str) else str(content)
                if not task_description:
                    task_description = text
                conversation.append({"speaker": "User", "text": text})

            elif role == "assistant":
                # Check for tool_calls
                tool_calls = msg.get("tool_calls", [])
                # Also handle legacy function_call field
                function_call = msg.get("function_call")

                if tool_calls:
                    for tc in tool_calls:
                        func = tc.get("function", {})
                        name = func.get("name", "unknown")
                        args = func.get("arguments", "{}")
                        # Try to pretty-format the arguments
                        try:
                            parsed_args = json.loads(args) if isinstance(args, str) else args
                            args_str = json.dumps(parsed_args, ensure_ascii=False)
                        except (json.JSONDecodeError, TypeError):
                            args_str = str(args)
                        conversation.append({
                            "speaker": "Agent (Action)",
                            "text": f"{name}({args_str})"
                        })

                if function_call:
                    name = function_call.get("name", "unknown")
                    args = function_call.get("arguments", "{}")
                    try:
                        parsed_args = json.loads(args) if isinstance(args, str) else args
                        args_str = json.dumps(parsed_args, ensure_ascii=False)
                    except (json.JSONDecodeError, TypeError):
                        args_str = str(args)
                    conversation.append({
                        "speaker": "Agent (Action)",
                        "text": f"{name}({args_str})"
                    })

                # Add text content if present
                if content:
                    text = content if isinstance(content, str) else str(content)
                    if tool_calls or function_call:
                        conversation.append({"speaker": "Agent (Thought)", "text": text})
                    else:
                        conversation.append({"speaker": "Agent", "text": text})

            elif role == "tool":
                text = content if isinstance(content, str) else str(content)
                conversation.append({"speaker": "Environment", "text": text})

            elif role == "function":
                # Legacy function response
                text = content if isinstance(content, str) else str(content)
                conversation.append({"speaker": "Environment", "text": text})

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

    def _convert_assistants(self, item: dict, index: int) -> CanonicalTrace:
        """Convert an Assistants API format trace."""
        trace_id = item.get("id", f"openai_asst_{index}")
        assistant_id = item.get("assistant_id", "")
        instructions = item.get("instructions", "")
        steps = item.get("steps", [])
        model = item.get("model", "")

        conversation = []
        task_description = instructions

        for step in steps:
            step_type = step.get("type", "")

            if step_type == "message_creation":
                message = step.get("message", {})
                content_blocks = message.get("content", [])
                for block in content_blocks:
                    if isinstance(block, dict) and "text" in block:
                        text_val = block["text"]
                        if isinstance(text_val, dict):
                            text_val = text_val.get("value", str(text_val))
                        conversation.append({"speaker": "Agent", "text": str(text_val)})

            elif step_type == "tool_calls":
                tool_calls = step.get("tool_calls", [])
                for tc in tool_calls:
                    tc_type = tc.get("type", "function")
                    if tc_type == "function":
                        func = tc.get("function", {})
                        name = func.get("name", "unknown")
                        args = func.get("arguments", "{}")
                        try:
                            parsed = json.loads(args) if isinstance(args, str) else args
                            args_str = json.dumps(parsed, ensure_ascii=False)
                        except (json.JSONDecodeError, TypeError):
                            args_str = str(args)
                        conversation.append({
                            "speaker": "Agent (Action)",
                            "text": f"{name}({args_str})"
                        })
                        # Add output if present
                        output = func.get("output") or tc.get("output")
                        if output:
                            conversation.append({
                                "speaker": "Environment",
                                "text": str(output)
                            })
                    elif tc_type == "code_interpreter":
                        ci = tc.get("code_interpreter", {})
                        code_input = ci.get("input", "")
                        if code_input:
                            conversation.append({
                                "speaker": "Agent (Action)",
                                "text": f"```python\n{code_input}\n```"
                            })
                        outputs = ci.get("outputs", [])
                        for out in outputs:
                            if out.get("type") == "logs":
                                conversation.append({
                                    "speaker": "Environment",
                                    "text": out.get("logs", "")
                                })

        metadata_table = []
        if model:
            metadata_table.append({"Property": "Model", "Value": model})
        if assistant_id:
            metadata_table.append({"Property": "Assistant ID", "Value": assistant_id})
        metadata_table.append({"Property": "Steps", "Value": str(len(steps))})

        return CanonicalTrace(
            id=trace_id,
            task_description=task_description,
            conversation=conversation,
            agent_name=model or assistant_id,
            metadata_table=metadata_table,
        )

    def _is_assistants_format(self, item: dict) -> bool:
        """Check if this item uses the Assistants API format."""
        return "assistant_id" in item and "steps" in item

    def detect(self, data: Any) -> bool:
        items = data if isinstance(data, list) else [data]
        if not items:
            return False
        first = items[0]
        if not isinstance(first, dict):
            return False

        # Assistants format: has assistant_id + steps
        if "assistant_id" in first and "steps" in first:
            return True

        # Chat Completions format: messages array with role+content (content is string)
        messages = first.get("messages")
        if not isinstance(messages, list) or not messages:
            return False

        # Must have role field - distinguishes from other formats
        msg = messages[0]
        if not isinstance(msg, dict) or "role" not in msg:
            return False

        # Also reject if messages have sender/receiver (AutoGen format)
        if "sender" in msg:
            return False

        # OpenAI: content is a string (or None for tool-call-only messages)
        # Anthropic: content is a list of typed blocks
        # Check ALL messages to ensure none have Anthropic-style content blocks
        for m in messages:
            if not isinstance(m, dict):
                continue
            content = m.get("content")
            if isinstance(content, list) and content and isinstance(content[0], dict) and "type" in content[0]:
                return False  # This is Anthropic format

        return True
