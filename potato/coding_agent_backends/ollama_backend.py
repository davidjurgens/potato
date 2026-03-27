"""
Ollama Tool Use Backend

Custom agent loop using Ollama's API with local models.
No API key required — fully local execution.
Uses Ollama's tool/function calling support.
"""

import json
import logging
import time
import threading
from typing import Any, Dict, Iterator, List, Optional

import requests as http_requests

from ..coding_agent_backend import (
    CodingAgentBackend,
    CodingAgentEvent,
    CodingAgentEventType,
    CODING_TOOLS_OLLAMA,
    CODING_TOOLS,
    execute_tool,
)

logger = logging.getLogger(__name__)


class OllamaToolUseBackend(CodingAgentBackend):
    """Agent loop using Ollama API with tool/function calling."""

    def __init__(self, config: dict):
        self._config = config
        ai = config.get("ai_config", {})
        self._model = ai.get("model", "qwen2.5-coder:14b")
        self._base_url = ai.get("base_url", "http://localhost:11434")
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
        self._pause_event.set()
        self._stop_flag = False
        self._instruction_queue: list = []
        self._lock = threading.Lock()

    def start(self, task: str, working_dir: str, system_prompt: str = "") -> None:
        self._working_dir = working_dir
        self._system_prompt = system_prompt or (
            "You are a coding agent. You have access to tools for reading, "
            "editing, and creating files, running bash commands, and searching code. "
            "Use these tools to complete the task. When you are done, stop calling tools "
            "and summarize what you did."
        )
        self._messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": task},
        ]
        self._state = "running"
        self._stop_flag = False
        self._events = []
        self._event_idx = 0

        thread = threading.Thread(target=self._run_loop, daemon=True)
        thread.start()

    def _run_loop(self):
        """Main agent loop using Ollama's chat API with tools."""
        turn_index = 0
        try:
            while not self._stop_flag and turn_index < self._max_turns:
                self._pause_event.wait()
                if self._stop_flag:
                    break

                # Check for injected instructions
                with self._lock:
                    if self._instruction_queue:
                        instruction = self._instruction_queue.pop(0)
                        self._messages.append({"role": "user", "content": instruction})

                self._emit(CodingAgentEventType.THINKING, {
                    "turn_index": turn_index,
                    "text": "Thinking...",
                })

                # Query Ollama
                try:
                    resp = http_requests.post(
                        f"{self._base_url}/api/chat",
                        json={
                            "model": self._model,
                            "messages": self._messages,
                            "tools": CODING_TOOLS_OLLAMA,
                            "stream": False,
                            "options": {
                                "num_predict": self._max_tokens,
                                "temperature": self._temperature,
                            },
                        },
                        timeout=120,
                    )
                    resp.raise_for_status()
                    result = resp.json()
                except Exception as e:
                    self._emit(CodingAgentEventType.ERROR, {"message": f"Ollama error: {e}"})
                    self._state = "error"
                    return

                message = result.get("message", {})
                content = message.get("content", "")
                tool_calls_raw = message.get("tool_calls", [])

                # Emit thinking
                if content:
                    self._emit(CodingAgentEventType.THINKING, {
                        "turn_index": turn_index,
                        "text": content,
                    })

                # Add assistant message to history
                self._messages.append(message)

                # Execute tool calls
                tool_calls = []
                for tc_raw in tool_calls_raw:
                    if self._stop_flag:
                        break
                    self._pause_event.wait()
                    if self._stop_flag:
                        break

                    func = tc_raw.get("function", {})
                    tool_name = func.get("name", "unknown")
                    tool_input = func.get("arguments", {})
                    if isinstance(tool_input, str):
                        try:
                            tool_input = json.loads(tool_input)
                        except json.JSONDecodeError:
                            tool_input = {"command": tool_input}

                    self._emit(CodingAgentEventType.TOOL_CALL_START, {
                        "turn_index": turn_index,
                        "tool": tool_name,
                        "input": tool_input,
                    })

                    output = execute_tool(tool_name, tool_input, self._working_dir)
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

                    # Add tool result to messages (Ollama format)
                    self._messages.append({
                        "role": "tool",
                        "content": output,
                    })

                # Emit turn_end
                self._emit(CodingAgentEventType.TURN_END, {
                    "turn_index": turn_index,
                    "content": content,
                    "tool_calls": tool_calls,
                })

                turn_index += 1

                # If no tool calls, agent is done
                if not tool_calls_raw:
                    break

            self._state = "completed"
            self._emit(CodingAgentEventType.COMPLETE, {"total_turns": turn_index})

        except Exception as e:
            logger.exception("Ollama agent loop error")
            self._state = "error"
            self._emit(CodingAgentEventType.ERROR, {"message": str(e)})

    def _classify_output_type(self, tool_name: str) -> str:
        name = tool_name.lower()
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
        with self._lock:
            self._instruction_queue.append(text)

    def stop(self) -> None:
        self._stop_flag = True
        self._pause_event.set()
        self._state = "completed"

    def get_conversation_history(self) -> List[Dict]:
        with self._lock:
            return list(self._messages)

    def get_state(self) -> str:
        return self._state

    def truncate_history(self, to_step: int) -> None:
        with self._lock:
            # Keep system + initial user + 2 messages per turn
            keep = 2 + (to_step * 2)
            self._messages = self._messages[:keep]
            new_events = [e for e in self._events if e.data.get("turn_index", -1) < to_step or e.data.get("turn_index", -1) == -1]
            self._events = new_events
            self._event_idx = min(self._event_idx, len(self._events))
