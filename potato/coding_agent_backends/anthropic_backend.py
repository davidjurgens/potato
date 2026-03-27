"""
Anthropic Tool Use Backend

Custom agent loop using the Anthropic Messages API with tool_use.
Defines Read/Edit/Write/Bash/Grep/Glob tools and executes them
in the working directory.
"""

import json
import logging
import time
import threading
from typing import Any, Dict, Iterator, List, Optional

from ..coding_agent_backend import (
    CodingAgentBackend,
    CodingAgentEvent,
    CodingAgentEventType,
    CODING_TOOLS,
    execute_tool,
)

logger = logging.getLogger(__name__)


class AnthropicToolUseBackend(CodingAgentBackend):
    """Agent loop using Anthropic Messages API with tool_use."""

    def __init__(self, config: dict):
        self._config = config
        ai = config.get("ai_config", {})
        self._model = ai.get("model", "claude-sonnet-4-20250514")
        self._api_key = ai.get("api_key", "")
        self._max_tokens = ai.get("max_tokens", 8192)
        self._temperature = ai.get("temperature", 0.3)
        self._max_turns = config.get("max_turns", 50)

        self._state = "idle"
        self._working_dir = ""
        self._messages: List[Dict] = []
        self._system_prompt = ""
        self._events: list = []
        self._event_idx = 0
        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused initially
        self._stop_flag = False
        self._instruction_queue: list = []
        self._lock = threading.Lock()
        self._client = None

    def start(self, task: str, working_dir: str, system_prompt: str = "") -> None:
        self._working_dir = working_dir
        self._system_prompt = system_prompt or (
            "You are a coding agent. You have access to tools for reading, "
            "editing, and creating files, running bash commands, and searching code. "
            "Use these tools to complete the task. When you are done, stop calling tools "
            "and summarize what you did."
        )
        self._messages = [{"role": "user", "content": task}]
        self._state = "running"
        self._stop_flag = False
        self._events = []
        self._event_idx = 0

        # Initialize Anthropic client
        try:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self._api_key or None)
        except ImportError:
            self._emit(CodingAgentEventType.ERROR, {"message": "anthropic package not installed"})
            self._state = "error"
            return

        # Run the agent loop in a thread
        thread = threading.Thread(target=self._run_loop, daemon=True)
        thread.start()

    def _run_loop(self):
        """Main agent loop: query LLM → execute tools → repeat."""
        turn_index = 0
        try:
            while not self._stop_flag and turn_index < self._max_turns:
                # Check for pause
                self._pause_event.wait()
                if self._stop_flag:
                    break

                # Check for injected instructions
                with self._lock:
                    if self._instruction_queue:
                        instruction = self._instruction_queue.pop(0)
                        self._messages.append({"role": "user", "content": instruction})

                # Convert tools to Anthropic format
                tools = [
                    {"name": t["name"], "description": t["description"],
                     "input_schema": t["input_schema"]}
                    for t in CODING_TOOLS
                ]

                # Query LLM
                self._emit(CodingAgentEventType.THINKING, {
                    "turn_index": turn_index,
                    "text": "Thinking...",
                })

                try:
                    response = self._client.messages.create(
                        model=self._model,
                        max_tokens=self._max_tokens,
                        temperature=self._temperature,
                        system=self._system_prompt,
                        messages=self._messages,
                        tools=tools,
                    )
                except Exception as e:
                    self._emit(CodingAgentEventType.ERROR, {"message": str(e)})
                    self._state = "error"
                    return

                # Process response
                reasoning_parts = []
                tool_calls = []
                tool_use_blocks = []

                for block in response.content:
                    if block.type == "text":
                        reasoning_parts.append(block.text)
                        self._emit(CodingAgentEventType.THINKING, {
                            "turn_index": turn_index,
                            "text": block.text,
                        })
                    elif block.type == "tool_use":
                        tool_use_blocks.append(block)

                # Add assistant message to history
                self._messages.append({
                    "role": "assistant",
                    "content": [b.model_dump() for b in response.content],
                })

                # Execute tool calls
                tool_results = []
                for block in tool_use_blocks:
                    if self._stop_flag:
                        break

                    # Check for pause between tool executions
                    self._pause_event.wait()
                    if self._stop_flag:
                        break

                    tool_name = block.name
                    tool_input = block.input if isinstance(block.input, dict) else {}

                    self._emit(CodingAgentEventType.TOOL_CALL_START, {
                        "turn_index": turn_index,
                        "tool": tool_name,
                        "input": tool_input,
                    })

                    # Execute the tool
                    output = execute_tool(tool_name, tool_input, self._working_dir)

                    # Classify output type
                    output_type = self._classify_output_type(tool_name)

                    tc = {
                        "tool": tool_name,
                        "input": tool_input,
                        "output": output,
                        "output_type": output_type,
                    }
                    tool_calls.append(tc)

                    self._emit(CodingAgentEventType.TOOL_CALL_END, {
                        "turn_index": turn_index,
                        "tool_index": len(tool_calls) - 1,
                        **tc,
                    })

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output,
                    })

                # Add tool results to history
                if tool_results:
                    self._messages.append({
                        "role": "user",
                        "content": tool_results,
                    })

                # Emit turn_end
                self._emit(CodingAgentEventType.TURN_END, {
                    "turn_index": turn_index,
                    "content": "\n".join(reasoning_parts),
                    "tool_calls": tool_calls,
                })

                turn_index += 1

                # If no tool calls, the agent is done
                if not tool_use_blocks or response.stop_reason == "end_turn":
                    break

            self._state = "completed"
            self._emit(CodingAgentEventType.COMPLETE, {"total_turns": turn_index})

        except Exception as e:
            logger.exception("Agent loop error")
            self._state = "error"
            self._emit(CodingAgentEventType.ERROR, {"message": str(e)})

    def _classify_output_type(self, tool_name: str) -> str:
        name = tool_name.lower()
        if name in ("bash", "terminal", "shell"):
            return "terminal"
        if name in ("edit", "replace"):
            return "diff"
        if name in ("read", "grep", "glob", "search", "write"):
            return "code"
        return "generic"

    def _emit(self, event_type: CodingAgentEventType, data: dict):
        event = CodingAgentEvent(
            event_type=event_type,
            timestamp=time.time(),
            data=data,
        )
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
            # No new events, wait a bit
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
        with self._lock:
            self._instruction_queue.append(text)

    def stop(self) -> None:
        self._stop_flag = True
        self._pause_event.set()  # Unblock if paused
        self._state = "completed"

    def get_conversation_history(self) -> List[Dict]:
        with self._lock:
            return list(self._messages)

    def get_state(self) -> str:
        return self._state

    def truncate_history(self, to_step: int) -> None:
        """Truncate conversation to the given turn index."""
        with self._lock:
            # Keep initial user message + 2 messages per turn (assistant + tool_results)
            keep = 1 + (to_step * 2)
            self._messages = self._messages[:keep]
            # Also truncate events
            new_events = []
            for e in self._events:
                ti = e.data.get("turn_index", -1)
                if ti < to_step or ti == -1:
                    new_events.append(e)
            self._events = new_events
            self._event_idx = min(self._event_idx, len(self._events))
