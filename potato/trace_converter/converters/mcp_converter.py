"""
MCP (Model Context Protocol) Interaction Log Converter

Converts MCP session logs to Potato's canonical format.

Expected input format:
{
    "id": "session_001",
    "server": "my-mcp-server",
    "interactions": [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "search", "arguments": {"query": "test"}},
            "result": {"content": [{"type": "text", "text": "Found 5 results"}]},
            "timestamp": "2024-01-01T00:00:00Z"
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "resources/read",
            "params": {"uri": "file:///path/to/file.txt"},
            "result": {"contents": [{"text": "file contents here"}]}
        },
        {
            "jsonrpc": "2.0",
            "method": "notifications/progress",
            "params": {"progressToken": "abc", "progress": 50, "total": 100}
        }
    ]
}

Also supports flat arrays of JSON-RPC messages (without wrapper object).
"""

import json
from typing import Any, Dict, List, Optional

from ..base import BaseTraceConverter, CanonicalTrace


class MCPConverter(BaseTraceConverter):
    """Converter for MCP (Model Context Protocol) interaction logs."""

    format_name = "mcp"
    description = "MCP (Model Context Protocol) interaction logs (JSON-RPC 2.0)"
    file_extensions = [".json", ".jsonl"]

    # MCP method categories
    _TOOL_METHODS = ("tools/call", "tools/list")
    _RESOURCE_METHODS = ("resources/read", "resources/list", "resources/subscribe")
    _PROMPT_METHODS = ("prompts/get", "prompts/list")
    _NOTIFICATION_METHODS = ("notifications/progress", "notifications/message",
                             "notifications/resources/updated", "notifications/tools/updated")

    def convert(self, data: Any, options: Optional[Dict] = None) -> List[CanonicalTrace]:
        options = options or {}
        traces = data if isinstance(data, list) else [data]
        results = []

        for item in traces:
            if self._is_session_format(item):
                results.append(self._convert_session(item, len(results)))
            else:
                # Flat array of interactions - treat as single session
                if isinstance(item, list):
                    wrapper = {"id": f"mcp_session_{len(results)}", "interactions": item}
                    results.append(self._convert_session(wrapper, len(results)))
                else:
                    # Single interaction object
                    wrapper = {"id": f"mcp_session_{len(results)}", "interactions": [item]}
                    results.append(self._convert_session(wrapper, len(results)))

        return results

    def _convert_session(self, item: dict, index: int) -> CanonicalTrace:
        """Convert an MCP session log."""
        trace_id = item.get("id", f"mcp_{index}")
        server = item.get("server", "")
        interactions = item.get("interactions", [])

        conversation = []
        task_description = ""
        tool_calls = 0
        resource_reads = 0

        for interaction in interactions:
            if not isinstance(interaction, dict):
                continue

            method = interaction.get("method", "")
            params = interaction.get("params", {})
            result = interaction.get("result", {})
            error = interaction.get("error", {})

            if not isinstance(params, dict):
                params = {}
            if not isinstance(result, dict):
                result = {}

            # Tools
            if method == "tools/call":
                tool_calls += 1
                tool_name = params.get("name", "unknown_tool")
                arguments = params.get("arguments", {})
                try:
                    args_str = json.dumps(arguments, ensure_ascii=False) if isinstance(arguments, dict) else str(arguments)
                except (TypeError, ValueError):
                    args_str = str(arguments)

                conversation.append({
                    "speaker": "Agent (Action)",
                    "text": f"{tool_name}({args_str})"
                })

                # Add result
                result_text = self._extract_result_text(result)
                if result_text:
                    conversation.append({
                        "speaker": "Environment",
                        "text": result_text
                    })

                if error:
                    conversation.append({
                        "speaker": "Environment (Error)",
                        "text": f"Error {error.get('code', '')}: {error.get('message', '')}"
                    })

            elif method == "tools/list":
                tools = result.get("tools", [])
                if tools:
                    tool_names = [t.get("name", "") for t in tools if isinstance(t, dict)]
                    conversation.append({
                        "speaker": "System",
                        "text": f"Available tools: {', '.join(tool_names)}"
                    })

            # Resources
            elif method == "resources/read":
                resource_reads += 1
                uri = params.get("uri", "")
                conversation.append({
                    "speaker": "Agent (Action)",
                    "text": f"read_resource({uri})"
                })

                contents = result.get("contents", [])
                for content_item in contents:
                    if isinstance(content_item, dict):
                        text = content_item.get("text", content_item.get("blob", ""))
                        if text:
                            conversation.append({
                                "speaker": "Environment",
                                "text": str(text)
                            })

            elif method == "resources/list":
                resources = result.get("resources", [])
                if resources:
                    names = [r.get("name", r.get("uri", "")) for r in resources if isinstance(r, dict)]
                    conversation.append({
                        "speaker": "System",
                        "text": f"Available resources: {', '.join(names)}"
                    })

            # Prompts
            elif method == "prompts/get":
                prompt_name = params.get("name", "")
                messages = result.get("messages", [])
                if prompt_name:
                    conversation.append({
                        "speaker": "Agent (Action)",
                        "text": f"get_prompt({prompt_name})"
                    })
                for msg in messages:
                    if isinstance(msg, dict):
                        role = msg.get("role", "")
                        content = msg.get("content", {})
                        text = ""
                        if isinstance(content, dict):
                            text = content.get("text", "")
                        elif isinstance(content, str):
                            text = content
                        if text:
                            speaker = "User" if role == "user" else "System"
                            conversation.append({"speaker": speaker, "text": text})

            # Notifications
            elif method and method.startswith("notifications/"):
                notification_type = method.split("/", 1)[1] if "/" in method else method
                msg = params.get("message", params.get("data", ""))
                if not msg and "progress" in params:
                    progress = params.get("progress", 0)
                    total = params.get("total", 0)
                    msg = f"Progress: {progress}/{total}" if total else f"Progress: {progress}"
                if msg:
                    conversation.append({
                        "speaker": "System",
                        "text": f"[{notification_type}] {msg}" if isinstance(msg, str) else str(msg)
                    })

            if not task_description and method == "tools/call":
                task_description = f"MCP session: {params.get('name', '')} call"

        if not task_description:
            task_description = f"MCP session with {server}" if server else f"MCP session ({trace_id})"

        # Build metadata
        metadata_table = [
            {"Property": "Interactions", "Value": str(len(interactions))},
        ]
        if server:
            metadata_table.append({"Property": "Server", "Value": server})
        if tool_calls:
            metadata_table.append({"Property": "Tool Calls", "Value": str(tool_calls)})
        if resource_reads:
            metadata_table.append({"Property": "Resource Reads", "Value": str(resource_reads)})

        return CanonicalTrace(
            id=trace_id,
            task_description=task_description,
            conversation=conversation,
            agent_name=server or "MCP",
            metadata_table=metadata_table,
        )

    def _extract_result_text(self, result: dict) -> str:
        """Extract text from an MCP tool call result."""
        # MCP tool results have content array
        content = result.get("content", [])
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        parts.append(item.get("text", ""))
                    elif item.get("type") == "image":
                        parts.append("[image]")
                    elif item.get("type") == "resource":
                        parts.append(item.get("text", "[resource]"))
                elif isinstance(item, str):
                    parts.append(item)
            return "\n".join(parts)
        elif isinstance(content, str):
            return content
        return ""

    def _is_session_format(self, item: Any) -> bool:
        """Check if item is a session wrapper (vs. raw interaction)."""
        return isinstance(item, dict) and "interactions" in item

    def detect(self, data: Any) -> bool:
        items = data if isinstance(data, list) else [data]
        if not items:
            return False
        first = items[0]
        if not isinstance(first, dict):
            return False

        # Session format: has interactions array with MCP methods
        interactions = first.get("interactions", [])
        if isinstance(interactions, list) and interactions:
            return self._has_mcp_methods(interactions)

        # Flat format: item itself is an interaction with MCP method
        method = first.get("method", "")
        if isinstance(method, str):
            return self._is_mcp_method(method)

        return False

    def _has_mcp_methods(self, interactions: list) -> bool:
        """Check if interaction list contains MCP methods."""
        for interaction in interactions:
            if isinstance(interaction, dict):
                method = interaction.get("method", "")
                if self._is_mcp_method(method):
                    return True
        return False

    def _is_mcp_method(self, method: str) -> bool:
        """Check if a method string is a recognized MCP method."""
        if not method:
            return False
        return any(
            method.startswith(prefix)
            for prefix in ("tools/", "resources/", "prompts/", "notifications/")
        )
