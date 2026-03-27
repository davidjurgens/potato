"""
Coding Agent Backend Abstraction

Defines the interface for coding agent backends and common event types.
Backends implement the agent loop (LLM + tool execution) and yield
events that the CodingAgentRunner consumes.

Available backends:
- anthropic_tool_use: Custom agent loop using Anthropic API
- ollama_tool_use: Custom agent loop using Ollama (fully local, no API key)
- claude_sdk: Claude Agent SDK (subprocess with JSON-lines IPC)
- subprocess: Generic CLI agent (Phase 4)
- opencode: OpenCode SDK (Phase 4)
"""

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)


class CodingAgentEventType(str, Enum):
    """Event types emitted by coding agent backends."""
    THINKING = "thinking"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_END = "tool_call_end"
    TURN_END = "turn_end"
    ERROR = "error"
    COMPLETE = "complete"


@dataclass
class CodingAgentEvent:
    """Single event from a coding agent backend."""
    event_type: CodingAgentEventType
    timestamp: float = 0.0
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "data": self.data,
        }


# Tool definitions for custom tool-use backends
CODING_TOOLS = [
    {
        "name": "Read",
        "description": "Read a file from the filesystem. Returns the file contents.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute or relative path to the file"},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "Edit",
        "description": "Replace a specific string in a file with a new string.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the file to edit"},
                "old_string": {"type": "string", "description": "The exact text to find and replace"},
                "new_string": {"type": "string", "description": "The replacement text"},
            },
            "required": ["file_path", "old_string", "new_string"],
        },
    },
    {
        "name": "Write",
        "description": "Create or overwrite a file with the given content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the file to write"},
                "content": {"type": "string", "description": "The full file content"},
            },
            "required": ["file_path", "content"],
        },
    },
    {
        "name": "Bash",
        "description": "Execute a bash command and return its output.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The command to execute"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "Grep",
        "description": "Search for a pattern in files. Returns matching lines with file paths.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for"},
                "path": {"type": "string", "description": "Directory or file to search in"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "Glob",
        "description": "Find files matching a glob pattern.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern (e.g. '**/*.py')"},
            },
            "required": ["pattern"],
        },
    },
]

# Ollama-compatible tool format (OpenAI function calling style)
CODING_TOOLS_OLLAMA = [
    {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        },
    }
    for t in CODING_TOOLS
]


def execute_tool(tool_name: str, tool_input: dict, working_dir: str) -> str:
    """Execute a coding tool in the working directory.

    Args:
        tool_name: Tool name (Read, Edit, Write, Bash, Grep, Glob)
        tool_input: Tool input parameters
        working_dir: Working directory for file operations

    Returns:
        Tool output as a string
    """
    import glob as glob_module
    import subprocess

    try:
        if tool_name == "Read":
            file_path = tool_input["file_path"]
            abs_path = os.path.join(working_dir, file_path) if not os.path.isabs(file_path) else file_path
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()

        elif tool_name == "Edit":
            file_path = tool_input["file_path"]
            abs_path = os.path.join(working_dir, file_path) if not os.path.isabs(file_path) else file_path
            old_string = tool_input["old_string"]
            new_string = tool_input["new_string"]
            with open(abs_path, "r", encoding="utf-8") as f:
                content = f.read()
            if old_string not in content:
                return f"Error: old_string not found in {file_path}"
            content = content.replace(old_string, new_string, 1)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)
            return "Edit applied successfully."

        elif tool_name == "Write":
            file_path = tool_input["file_path"]
            abs_path = os.path.join(working_dir, file_path) if not os.path.isabs(file_path) else file_path
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(tool_input["content"])
            return f"File written: {file_path}"

        elif tool_name == "Bash":
            command = tool_input["command"]
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                cwd=working_dir, timeout=60,
            )
            output = result.stdout
            if result.stderr:
                output += "\n" + result.stderr
            if result.returncode != 0:
                output += f"\n[exit code: {result.returncode}]"
            return output.strip() or "(no output)"

        elif tool_name == "Grep":
            pattern = tool_input["pattern"]
            path = tool_input.get("path", ".")
            abs_path = os.path.join(working_dir, path) if not os.path.isabs(path) else path
            result = subprocess.run(
                ["grep", "-rn", pattern, abs_path],
                capture_output=True, text=True, cwd=working_dir, timeout=30,
            )
            return result.stdout.strip() or "(no matches)"

        elif tool_name == "Glob":
            pattern = tool_input["pattern"]
            matches = sorted(glob_module.glob(
                os.path.join(working_dir, pattern), recursive=True
            ))
            # Make paths relative to working_dir
            rel_matches = [os.path.relpath(m, working_dir) for m in matches]
            return "\n".join(rel_matches) or "(no matches)"

        else:
            return f"Unknown tool: {tool_name}"

    except FileNotFoundError as e:
        return f"Error: File not found: {e}"
    except PermissionError as e:
        return f"Error: Permission denied: {e}"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out (60s limit)"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


class CodingAgentBackend(ABC):
    """Abstract interface for coding agent backends."""

    @abstractmethod
    def start(self, task: str, working_dir: str, system_prompt: str = "") -> None:
        """Start the agent with a task description."""
        ...

    @abstractmethod
    def get_events(self) -> Iterator[CodingAgentEvent]:
        """Yield events as the agent works. Blocks until next event or completion."""
        ...

    @abstractmethod
    def pause(self) -> None:
        """Pause the agent between tool executions."""
        ...

    @abstractmethod
    def resume(self) -> None:
        """Resume a paused agent."""
        ...

    @abstractmethod
    def inject_instruction(self, text: str) -> None:
        """Send an instruction to the agent (appended as user message)."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Stop the agent."""
        ...

    @abstractmethod
    def get_conversation_history(self) -> List[Dict]:
        """Get the full conversation history."""
        ...

    @abstractmethod
    def get_state(self) -> str:
        """Get the current state: running, paused, completed, error."""
        ...

    def truncate_history(self, to_step: int) -> None:
        """Truncate conversation history to the given step (for rollback)."""
        pass  # Optional, backends that support rollback override this


# Backend registry
BACKEND_REGISTRY: Dict[str, type] = {}


def register_backend(name: str, cls: type) -> None:
    """Register a backend implementation."""
    BACKEND_REGISTRY[name] = cls


def create_backend(backend_type: str, config: dict) -> CodingAgentBackend:
    """Create a backend instance from config."""
    if backend_type not in BACKEND_REGISTRY:
        available = ", ".join(sorted(BACKEND_REGISTRY.keys()))
        raise ValueError(
            f"Unknown backend type '{backend_type}'. Available: {available}"
        )
    cls = BACKEND_REGISTRY[backend_type]
    return cls(config)


def _register_builtin_backends():
    """Register built-in backends. Called on import."""
    try:
        from .coding_agent_backends.anthropic_backend import AnthropicToolUseBackend
        register_backend("anthropic_tool_use", AnthropicToolUseBackend)
    except ImportError:
        logger.debug("Anthropic backend not available (missing anthropic package)")

    try:
        from .coding_agent_backends.ollama_backend import OllamaToolUseBackend
        register_backend("ollama_tool_use", OllamaToolUseBackend)
    except ImportError:
        logger.debug("Ollama backend not available")

    try:
        from .coding_agent_backends.claude_sdk_backend import ClaudeSDKBackend
        register_backend("claude_sdk", ClaudeSDKBackend)
    except ImportError:
        logger.debug("Claude SDK backend not available (missing claude-agent-sdk)")


_register_builtin_backends()
