"""
OpenAI Tool Use Backend

Custom coding-agent loop using any OpenAI-compatible chat-completions
server (OpenAI, vLLM, llama.cpp, etc.) with function/tool calling.

vLLM ignores the API key but the OpenAI SDK rejects an empty string, so
a non-empty placeholder is substituted for local servers. A configured
base_url is honored and normalized to the ".../v1" form the SDK expects
(accepts either the server root or an explicit "/v1" base_url).
"""

import json
import logging
import time
import threading
from typing import Dict, Iterator, List

from ..coding_agent_backend import (
    CodingAgentBackend,
    CodingAgentEvent,
    CodingAgentEventType,
    CODING_TOOLS,
    execute_tool,
)

logger = logging.getLogger(__name__)


def _to_openai_tools(tools: list) -> list:
    """CODING_TOOLS is in Anthropic shape ({name, description,
    input_schema}); the OpenAI/vLLM API needs
    {type:"function", function:{name, description, parameters}}."""
    converted = []
    for t in tools:
        if t.get("type") == "function" and "function" in t:
            converted.append(t)  # already OpenAI shape
            continue
        converted.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        })
    return converted


def _normalize_base_url(raw: str) -> str:
    """The OpenAI SDK appends '/chat/completions' to base_url, so bare host
    URLs (vLLM/local servers) need the conventional '/v1' suffix. URLs that
    already carry a path (e.g. Gemini's /v1beta/openai/) are left intact."""
    if not raw:
        return raw
    from urllib.parse import urlparse
    u = raw.rstrip("/")
    if not urlparse(u).path:
        u = u + "/v1"
    return u


class OpenAIToolUseBackend(CodingAgentBackend):
    """Agent loop using an OpenAI-compatible API with tool calling."""

    def __init__(self, config: dict):
        self._config = config
        ai = config.get("ai_config", {})
        self._model = ai.get("model", "gpt-4o-mini")
        self._base_url = _normalize_base_url(ai.get("base_url", "")) or None
        # vLLM/local servers ignore the key; SDK requires non-empty.
        import os
        self._api_key = (
            ai.get("api_key")
            or os.environ.get("OPENAI_API_KEY")
            or "EMPTY"
        )
        self._max_tokens = ai.get("max_tokens", 8192)
        self._temperature = ai.get("temperature", 0.3)
        self._timeout = ai.get("timeout", 120)
        self._max_turns = config.get("max_turns", 50)
        self._tools = _to_openai_tools(CODING_TOOLS)

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
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        from openai import OpenAI

        kwargs = {"api_key": self._api_key, "timeout": self._timeout}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        self._client = OpenAI(**kwargs)
        return self._client

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
        """Main agent loop using the OpenAI chat API with tools."""
        turn_index = 0
        try:
            client = self._get_client()
            while not self._stop_flag and turn_index < self._max_turns:
                self._pause_event.wait()
                if self._stop_flag:
                    break

                with self._lock:
                    if self._instruction_queue:
                        instruction = self._instruction_queue.pop(0)
                        self._messages.append({"role": "user", "content": instruction})

                self._emit(CodingAgentEventType.THINKING, {
                    "turn_index": turn_index,
                    "text": "Thinking...",
                })

                try:
                    resp = client.chat.completions.create(
                        model=self._model,
                        messages=self._messages,
                        tools=self._tools,
                        tool_choice="auto",
                        max_tokens=self._max_tokens,
                        temperature=self._temperature,
                    )
                except Exception as e:
                    # Includes models/servers that don't support tools --
                    # surface a clear error instead of stalling the loop.
                    self._emit(CodingAgentEventType.ERROR, {
                        "message": f"OpenAI-compatible request failed: {e}"
                    })
                    self._state = "error"
                    return

                choice = resp.choices[0].message
                content = choice.content or ""
                tool_calls_raw = choice.tool_calls or []

                if content:
                    self._emit(CodingAgentEventType.THINKING, {
                        "turn_index": turn_index,
                        "text": content,
                    })

                # Append the assistant message verbatim (must include
                # tool_calls so the following tool messages pair by id).
                try:
                    assistant_msg = choice.model_dump(exclude_none=True)
                except Exception:
                    assistant_msg = {"role": "assistant", "content": content}
                self._messages.append(assistant_msg)

                tool_calls = []
                for tc_raw in tool_calls_raw:
                    if self._stop_flag:
                        break
                    self._pause_event.wait()
                    if self._stop_flag:
                        break

                    fn = tc_raw.function
                    tool_name = fn.name or "unknown"
                    raw_args = fn.arguments
                    if isinstance(raw_args, str):
                        try:
                            tool_input = json.loads(raw_args) if raw_args else {}
                        except json.JSONDecodeError:
                            tool_input = {"command": raw_args}
                    elif isinstance(raw_args, dict):
                        tool_input = raw_args
                    else:
                        tool_input = {}

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

                    # OpenAI requires the tool result to reference the
                    # originating tool_call_id.
                    self._messages.append({
                        "role": "tool",
                        "tool_call_id": tc_raw.id,
                        "content": output,
                    })

                self._emit(CodingAgentEventType.TURN_END, {
                    "turn_index": turn_index,
                    "content": content,
                    "tool_calls": tool_calls,
                })

                turn_index += 1

                if not tool_calls_raw:
                    break

            self._state = "completed"
            self._emit(CodingAgentEventType.COMPLETE, {"total_turns": turn_index})

        except Exception as e:
            logger.exception("OpenAI agent loop error")
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
            # Best-effort: keep system + initial user, then drop events
            # for turns >= to_step. (Messages vary per turn with tool
            # calls; keep them since OpenAI needs tool_call_id pairing.)
            new_events = [
                e for e in self._events
                if e.data.get("turn_index", -1) < to_step
                or e.data.get("turn_index", -1) == -1
            ]
            self._events = new_events
            self._event_idx = min(self._event_idx, len(self._events))
