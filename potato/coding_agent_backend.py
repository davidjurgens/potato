"""
Coding Agent Backend Abstraction

Defines the interface for coding agent backends and common event types.
Backends implement the agent loop (LLM + tool execution) and yield
events that the CodingAgentRunner consumes.

Available backends:
- anthropic_tool_use: Custom agent loop using Anthropic API
- ollama_tool_use: Custom agent loop using Ollama (fully local, no API key)
- openai_tool_use: Custom agent loop using any OpenAI-compatible server
  (OpenAI, vLLM, llama.cpp, ...) with tool calling
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
                "file_path": {"type": "string", "description": "Path to the file, relative to the workspace root"},
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


def execute_tool(tool_name: str, tool_input: dict, sandbox) -> str:
    """Execute a coding tool inside a sandbox.

    Args:
        tool_name: Tool name (Read, Edit, Write, Bash, Grep, Glob)
        tool_input: Tool input parameters
        sandbox: A :class:`potato.sandbox.SandboxBackend`. Annotators can edit
            tool calls freely, so this boundary is the security control -- see
            ``potato/sandbox/__init__.py`` for the ladder of backends.

    Returns:
        Tool output as a string. Errors are returned rather than raised: the
        output is fed back to the agent as a tool result, and an exception here
        would kill the session instead of letting the model recover.
    """
    import glob as glob_module

    from potato.sandbox import SandboxError, resolve_within

    if isinstance(sandbox, str):
        # Used to be a working-directory path, and tools ran on the host with
        # `shell=True`. Failing loudly beats quietly reconstructing a sandbox,
        # which is how "docker" used to end up meaning "no isolation".
        raise TypeError(
            "execute_tool() now takes a SandboxBackend, not a working "
            "directory path. Build one with potato.sandbox.create_backend()."
        )

    workspace = sandbox.workspace

    try:
        if tool_name == "Read":
            return sandbox.read_file(tool_input["file_path"])

        elif tool_name == "Edit":
            file_path = tool_input["file_path"]
            old_string = tool_input["old_string"]
            new_string = tool_input["new_string"]
            content = sandbox.read_file(file_path)
            if old_string not in content:
                return f"Error: old_string not found in {file_path}"
            content = content.replace(old_string, new_string, 1)
            sandbox.write_file(file_path, content)
            return "Edit applied successfully."

        elif tool_name == "Write":
            file_path = tool_input["file_path"]
            sandbox.write_file(file_path, tool_input["content"])
            return f"File written: {file_path}"

        elif tool_name == "Bash":
            command = tool_input["command"]
            # A shell *inside* the sandbox is the point of this tool. In a
            # network-less, read-only, unprivileged container it is the
            # contained case; what must not exist is a shell on the host.
            result = sandbox.exec(["/bin/sh", "-c", command], timeout=60)
            return result.as_tool_output()

        elif tool_name == "Grep":
            pattern = tool_input["pattern"]
            path = tool_input.get("path", ".")
            # Validate before running, then pass the path through relative so
            # it resolves against the sandbox's own working directory.
            resolve_within(workspace, path)
            result = sandbox.exec(["grep", "-rn", pattern, path], timeout=30)
            return (result.stdout or "").strip() or "(no matches)"

        elif tool_name == "Glob":
            # Matched on the host against the sandbox workspace, which every
            # backend exposes as a real directory. Each hit is re-checked, so a
            # pattern that escapes via `..` or a symlink yields nothing rather
            # than reaching outside.
            pattern = tool_input["pattern"]
            matches = sorted(glob_module.glob(
                os.path.join(workspace, pattern), recursive=True
            ))
            rel_matches = []
            for m in matches:
                rel = os.path.relpath(m, workspace)
                try:
                    resolve_within(workspace, rel)
                except SandboxError:
                    continue
                rel_matches.append(rel)
            return "\n".join(rel_matches) or "(no matches)"

        else:
            return f"Unknown tool: {tool_name}"

    except SandboxError as e:
        return f"Error: {e}"
    except FileNotFoundError as e:
        return f"Error: File not found: {e}"
    except PermissionError as e:
        return f"Error: Permission denied: {e}"
    except KeyError as e:
        return f"Error: missing required tool input {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


class CodingAgentBackend(ABC):
    """Abstract interface for coding agent backends."""

    #: Sandbox the agent's own tool calls run inside. Set by the runner before
    #: :meth:`start`. The agent drives the same executor annotators do, so it
    #: needs the same boundary -- a backend left without one cannot run tools.
    _sandbox = None

    def set_sandbox(self, sandbox) -> None:
        """Attach the sandbox this backend's tool calls execute inside."""
        self._sandbox = sandbox

    @property
    def sandbox(self):
        if self._sandbox is None:
            raise RuntimeError(
                "No sandbox attached to this backend. The runner must call "
                "set_sandbox() before start()."
            )
        return self._sandbox

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
        from .coding_agent_backends.openai_backend import OpenAIToolUseBackend
        register_backend("openai_tool_use", OpenAIToolUseBackend)
    except ImportError:
        logger.debug("OpenAI backend not available (missing openai package)")

    try:
        from .coding_agent_backends.claude_sdk_backend import ClaudeSDKBackend
        register_backend("claude_sdk", ClaudeSDKBackend)
    except ImportError:
        logger.debug("Claude SDK backend not available (missing claude-agent-sdk)")


_register_builtin_backends()
