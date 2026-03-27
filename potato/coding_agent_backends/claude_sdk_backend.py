"""
Claude Agent SDK Backend

Spawns Claude Code as a subprocess via the official Agent SDK.
Communicates via JSON-lines over stdin/stdout.
Inherits CLAUDE.md, hooks, MCP servers from the working directory.

Requires: pip install claude-agent-sdk
"""

import json
import logging
import subprocess
import threading
import time
from typing import Any, Dict, Iterator, List, Optional

from ..coding_agent_backend import (
    CodingAgentBackend,
    CodingAgentEvent,
    CodingAgentEventType,
)

logger = logging.getLogger(__name__)


class ClaudeSDKBackend(CodingAgentBackend):
    """Backend using Claude Agent SDK (subprocess with JSON-lines IPC)."""

    def __init__(self, config: dict):
        self._config = config
        self._state = "idle"
        self._working_dir = ""
        self._events: list = []
        self._event_idx = 0
        self._lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None
        self._stop_flag = False
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._messages: List[Dict] = []

    def start(self, task: str, working_dir: str, system_prompt: str = "") -> None:
        self._working_dir = working_dir
        self._state = "running"
        self._stop_flag = False
        self._events = []
        self._event_idx = 0

        thread = threading.Thread(target=self._run_sdk, args=(task,), daemon=True)
        thread.start()

    def _run_sdk(self, task: str):
        """Run Claude Code via the Agent SDK."""
        try:
            # Try to use the Agent SDK
            try:
                from claude_agent_sdk import query
                self._run_with_sdk(task)
                return
            except ImportError:
                pass

            # Fallback: spawn claude CLI directly
            self._run_with_cli(task)

        except Exception as e:
            logger.exception("Claude SDK backend error")
            self._state = "error"
            self._emit(CodingAgentEventType.ERROR, {"message": str(e)})

    def _run_with_sdk(self, task: str):
        """Use the claude-agent-sdk Python package."""
        import asyncio
        from claude_agent_sdk import query

        async def _run():
            turn_index = 0
            current_reasoning = []
            current_tool_calls = []

            async for message in query(prompt=task, options={"cwd": self._working_dir}):
                if self._stop_flag:
                    break

                self._pause_event.wait()
                if self._stop_flag:
                    break

                msg_type = message.get("type", "")

                if msg_type == "assistant":
                    # Assistant reasoning
                    content = message.get("message", {}).get("content", [])
                    for block in content:
                        if isinstance(block, dict):
                            if block.get("type") == "text":
                                text = block.get("text", "")
                                current_reasoning.append(text)
                                self._emit(CodingAgentEventType.THINKING, {
                                    "turn_index": turn_index,
                                    "text": text,
                                })
                            elif block.get("type") == "tool_use":
                                tool_name = block.get("name", "unknown")
                                tool_input = block.get("input", {})
                                self._emit(CodingAgentEventType.TOOL_CALL_START, {
                                    "turn_index": turn_index,
                                    "tool": tool_name,
                                    "input": tool_input,
                                })

                elif msg_type == "result":
                    # Tool result
                    result = message.get("result", "")
                    tool_name = message.get("tool_name", "")
                    tool_input = message.get("tool_input", {})
                    output_type = self._classify_output_type(tool_name)

                    tc = {
                        "tool": tool_name,
                        "input": tool_input,
                        "output": str(result),
                        "output_type": output_type,
                    }
                    current_tool_calls.append(tc)

                    self._emit(CodingAgentEventType.TOOL_CALL_END, {
                        "turn_index": turn_index,
                        "tool_index": len(current_tool_calls) - 1,
                        **tc,
                    })

                # Check if turn ended (no more tool calls pending)
                if msg_type in ("assistant",) and not message.get("message", {}).get("content", []):
                    if current_reasoning or current_tool_calls:
                        self._emit(CodingAgentEventType.TURN_END, {
                            "turn_index": turn_index,
                            "content": "\n".join(current_reasoning),
                            "tool_calls": current_tool_calls,
                        })
                        turn_index += 1
                        current_reasoning = []
                        current_tool_calls = []

            # Final turn
            if current_reasoning or current_tool_calls:
                self._emit(CodingAgentEventType.TURN_END, {
                    "turn_index": turn_index,
                    "content": "\n".join(current_reasoning),
                    "tool_calls": current_tool_calls,
                })
                turn_index += 1

            self._state = "completed"
            self._emit(CodingAgentEventType.COMPLETE, {"total_turns": turn_index})

        asyncio.run(_run())

    def _run_with_cli(self, task: str):
        """Fallback: spawn claude CLI as subprocess."""
        try:
            self._process = subprocess.Popen(
                ["claude", "--bare", "-p", task],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self._working_dir,
                text=True,
            )
        except FileNotFoundError:
            self._emit(CodingAgentEventType.ERROR, {
                "message": "claude CLI not found. Install Claude Code or claude-agent-sdk."
            })
            self._state = "error"
            return

        turn_index = 0
        output_lines = []

        for line in self._process.stdout:
            if self._stop_flag:
                break

            line = line.strip()
            if not line:
                continue

            # Try to parse as JSON-lines
            try:
                msg = json.loads(line)
                msg_type = msg.get("type", "")

                if msg_type in ("text", "content"):
                    text = msg.get("text", msg.get("content", ""))
                    self._emit(CodingAgentEventType.THINKING, {
                        "turn_index": turn_index,
                        "text": text,
                    })
                elif msg_type == "tool_use":
                    self._emit(CodingAgentEventType.TOOL_CALL_START, {
                        "turn_index": turn_index,
                        "tool": msg.get("name", ""),
                        "input": msg.get("input", {}),
                    })
                elif msg_type == "tool_result":
                    self._emit(CodingAgentEventType.TOOL_CALL_END, {
                        "turn_index": turn_index,
                        "tool": msg.get("name", ""),
                        "input": msg.get("input", {}),
                        "output": msg.get("output", ""),
                        "output_type": self._classify_output_type(msg.get("name", "")),
                    })
            except json.JSONDecodeError:
                # Plain text output
                output_lines.append(line)

        self._process.wait()
        self._state = "completed"
        self._emit(CodingAgentEventType.COMPLETE, {"total_turns": turn_index + 1})

    def _classify_output_type(self, tool_name: str) -> str:
        name = (tool_name or "").lower()
        if name in ("bash", "terminal", "shell"):
            return "terminal"
        if name in ("edit", "replace"):
            return "diff"
        return "code"

    def _emit(self, event_type: CodingAgentEventType, data: dict):
        event = CodingAgentEvent(event_type=event_type, timestamp=time.time(), data=data)
        with self._lock:
            self._events.append(event)

    def get_events(self) -> Iterator[CodingAgentEvent]:
        while True:
            with self._lock:
                if self._event_idx < len(self._events):
                    event = self._events[self._event_idx]
                    self._event_idx += 1
                    yield event
                    if event.event_type in (CodingAgentEventType.COMPLETE, CodingAgentEventType.ERROR):
                        return
                    continue
            if self._state in ("completed", "error"):
                return
            time.sleep(0.1)

    def pause(self) -> None:
        self._pause_event.clear()
        self._state = "paused"

    def resume(self) -> None:
        self._state = "running"
        self._pause_event.set()

    def inject_instruction(self, text: str) -> None:
        # Claude SDK doesn't support mid-session instruction injection
        # This would require restarting with appended context
        logger.warning("inject_instruction not fully supported in Claude SDK backend")

    def stop(self) -> None:
        self._stop_flag = True
        self._pause_event.set()
        if self._process and self._process.poll() is None:
            self._process.terminate()
        self._state = "completed"

    def get_conversation_history(self) -> List[Dict]:
        return list(self._messages)

    def get_state(self) -> str:
        return self._state
