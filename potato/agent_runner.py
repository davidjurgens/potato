"""
Live Agent Runner

Manages an AI agent that browses the web via Playwright, controlled by an LLM.
Annotators can observe, pause, instruct, or take over the agent in real time.

The agent loop runs in a background thread with its own asyncio event loop.
Communication with Flask routes happens through thread-safe state and queues.
"""

import asyncio
import base64
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from queue import Queue, Empty
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class AgentState(Enum):
    """States of the agent lifecycle."""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    TAKEOVER = "takeover"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class AgentStep:
    """A single step in the agent's execution."""
    step_index: int
    screenshot_path: str
    action: Dict[str, Any]
    thought: str
    observation: str
    timestamp: float
    url: str = ""
    viewport: Optional[Dict[str, int]] = None
    coordinates: Optional[Dict[str, int]] = None
    element: Optional[Dict[str, Any]] = None
    annotator_instruction: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "step_index": self.step_index,
            "screenshot_url": self.screenshot_path,
            "action_type": self.action.get("type", "unknown"),
            "action": self.action,
            "thought": self.thought,
            "observation": self.observation,
            "timestamp": self.timestamp,
            "url": self.url,
        }
        if self.viewport:
            d["viewport"] = self.viewport
        if self.coordinates:
            d["coordinates"] = self.coordinates
        if self.element:
            d["element"] = self.element
        if self.annotator_instruction:
            d["annotator_instruction"] = self.annotator_instruction
        return d


@dataclass
class AgentConfig:
    """Configuration for the agent runner."""
    max_steps: int = 30
    step_delay: float = 1.0
    viewport_width: int = 1280
    viewport_height: int = 720
    system_prompt: str = ""
    model: str = "claude-sonnet-4-20250514"
    api_key: str = ""
    max_tokens: int = 4096
    temperature: float = 0.3
    endpoint_type: str = "anthropic_vision"
    history_window: int = 5  # Number of recent steps to include in LLM context
    timeout: int = 60  # Per-request timeout in seconds

    base_url: str = ""  # For Ollama: server URL

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "AgentConfig":
        """Create AgentConfig from a live_agent YAML config dict."""
        ai_config = config.get("ai_config", {})
        viewport = config.get("viewport", {})
        endpoint_type = config.get("endpoint_type", "anthropic_vision")

        # API key: Ollama doesn't need one
        if endpoint_type == "ollama_vision":
            api_key = ai_config.get("api_key", "")
            default_model = "gemma3:4b"
        else:
            api_key = ai_config.get("api_key", os.environ.get("ANTHROPIC_API_KEY", ""))
            default_model = "claude-sonnet-4-20250514"

        return cls(
            max_steps=config.get("max_steps", 30),
            step_delay=config.get("step_delay", 1.0),
            viewport_width=viewport.get("width", 1280),
            viewport_height=viewport.get("height", 720),
            system_prompt=config.get("system_prompt", DEFAULT_SYSTEM_PROMPT),
            model=ai_config.get("model", default_model),
            api_key=api_key,
            max_tokens=ai_config.get("max_tokens", 4096),
            temperature=ai_config.get("temperature", 0.3),
            endpoint_type=endpoint_type,
            history_window=config.get("history_window", 5),
            timeout=ai_config.get("timeout", 60),
            base_url=ai_config.get("base_url", "http://localhost:11434"),
        )


DEFAULT_SYSTEM_PROMPT = """You are a web browsing agent. You can see screenshots of web pages and take actions to complete tasks.

For each step, analyze the current screenshot and respond with a JSON object:
{
  "thought": "Your reasoning about what you see and what to do next",
  "action": {
    "type": "click|type|scroll|navigate|wait|done",
    // For click: "x": 100, "y": 200
    // For type: "text": "hello world"
    // For scroll: "direction": "up|down", "amount": 300
    // For navigate: "url": "https://..."
    // For wait: (no extra fields)
    // For done: "summary": "Task completed because..."
  }
}

Always respond with valid JSON only. No markdown, no extra text."""


class AgentRunner:
    """
    Runs an AI agent that browses the web via Playwright.

    The agent loop:
    1. Takes a screenshot
    2. Sends it to the LLM with context/history
    3. Parses the LLM response for an action
    4. Executes the action via Playwright
    5. Emits events to all listeners (for SSE)
    6. Repeats until done, error, or max_steps

    Thread-safe control methods allow pause/resume/instruct/takeover.
    """

    def __init__(self, session_id: str, config: AgentConfig, screenshot_dir: str):
        self.session_id = session_id
        self.config = config
        self.screenshot_dir = screenshot_dir

        # State
        self._state = AgentState.IDLE
        self._state_lock = threading.Lock()
        self._steps: List[AgentStep] = []
        self._error: Optional[str] = None

        # Control
        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused initially
        self._stop_flag = threading.Event()
        self._instruction_queue: Queue = Queue()
        self._takeover_actions: Queue = Queue()

        # Listeners for SSE
        self._listeners: List[Callable] = []
        self._listeners_lock = threading.Lock()

        # Annotator interactions log
        self._interactions: List[Dict[str, Any]] = []

        # Playwright session (set during run)
        self._playwright_session = None
        self._llm_client = None

        # Background thread
        self._thread: Optional[threading.Thread] = None

    @property
    def state(self) -> AgentState:
        with self._state_lock:
            return self._state

    @state.setter
    def state(self, new_state: AgentState):
        with self._state_lock:
            old_state = self._state
            self._state = new_state
        self._emit_event("state_change", {
            "old_state": old_state.value,
            "new_state": new_state.value,
            "timestamp": time.time(),
        })

    @property
    def steps(self) -> List[AgentStep]:
        return list(self._steps)

    @property
    def step_count(self) -> int:
        return len(self._steps)

    @property
    def error(self) -> Optional[str]:
        return self._error

    # --- Control methods (thread-safe) ---

    def pause(self):
        """Pause the agent loop after the current step completes."""
        if self.state == AgentState.RUNNING:
            self._pause_event.clear()
            self.state = AgentState.PAUSED
            logger.info(f"[{self.session_id}] Agent paused")

    def resume(self):
        """Resume a paused agent."""
        if self.state == AgentState.PAUSED:
            self.state = AgentState.RUNNING
            self._pause_event.set()
            logger.info(f"[{self.session_id}] Agent resumed")

    def inject_instruction(self, instruction: str):
        """Send an instruction to the agent (processed at next step)."""
        self._instruction_queue.put(instruction)
        self._interactions.append({
            "type": "instruction",
            "text": instruction,
            "timestamp": time.time(),
            "step_index": self.step_count,
        })
        self._emit_event("instruction_received", {"instruction": instruction})
        logger.info(f"[{self.session_id}] Instruction injected: {instruction[:100]}")

    def enter_takeover(self):
        """Switch to manual takeover mode."""
        if self.state in (AgentState.RUNNING, AgentState.PAUSED):
            self._pause_event.clear()  # Pause the agent loop
            self.state = AgentState.TAKEOVER
            self._interactions.append({
                "type": "takeover_start",
                "timestamp": time.time(),
                "step_index": self.step_count,
            })
            logger.info(f"[{self.session_id}] Takeover mode entered")

    def exit_takeover(self):
        """Exit manual takeover and resume the agent."""
        if self.state == AgentState.TAKEOVER:
            self._interactions.append({
                "type": "takeover_end",
                "timestamp": time.time(),
                "step_index": self.step_count,
            })
            self.state = AgentState.RUNNING
            self._pause_event.set()
            logger.info(f"[{self.session_id}] Takeover mode exited")

    def submit_manual_action(self, action: Dict[str, Any]):
        """Submit a manual action during takeover mode."""
        if self.state == AgentState.TAKEOVER:
            self._takeover_actions.put(action)

    def stop(self):
        """Stop the agent loop."""
        self._stop_flag.set()
        self._pause_event.set()  # Unblock if paused
        logger.info(f"[{self.session_id}] Stop requested")

    # --- Listener management ---

    def add_listener(self, callback: Callable):
        """Add an SSE listener callback."""
        with self._listeners_lock:
            self._listeners.append(callback)

    def remove_listener(self, callback: Callable):
        """Remove an SSE listener callback."""
        with self._listeners_lock:
            self._listeners = [l for l in self._listeners if l is not callback]

    def _emit_event(self, event_type: str, data: Dict[str, Any]):
        """Emit an event to all listeners."""
        event = {"type": event_type, "data": data, "session_id": self.session_id}
        with self._listeners_lock:
            for listener in self._listeners:
                try:
                    listener(event)
                except Exception as e:
                    logger.warning(f"Listener error: {e}")

    # --- Main agent loop ---

    def start(self, task_description: str, start_url: str):
        """Start the agent in a background thread."""
        if self.state != AgentState.IDLE:
            raise RuntimeError(f"Cannot start agent in state {self.state}")

        self._thread = threading.Thread(
            target=self._run_thread,
            args=(task_description, start_url),
            daemon=True,
            name=f"agent-{self.session_id}",
        )
        self._thread.start()

    def _run_thread(self, task_description: str, start_url: str):
        """Thread target: runs the async agent loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run_async(task_description, start_url))
        except Exception as e:
            logger.error(f"[{self.session_id}] Agent thread error: {e}")
            self._error = str(e)
            self.state = AgentState.ERROR
            self._emit_event("error", {"message": str(e)})
        finally:
            loop.close()

    async def _run_async(self, task_description: str, start_url: str):
        """Async agent loop."""
        from potato.web_playwright import PlaywrightSession

        self.state = AgentState.RUNNING

        # Initialize Playwright
        self._playwright_session = PlaywrightSession(
            width=self.config.viewport_width,
            height=self.config.viewport_height,
        )
        started = await self._playwright_session.start(start_url)
        if not started:
            raise RuntimeError("Failed to start Playwright browser session")

        # Initialize LLM client
        self._init_llm_client()

        self._emit_event("started", {
            "task": task_description,
            "start_url": start_url,
            "max_steps": self.config.max_steps,
        })

        try:
            for step_index in range(self.config.max_steps):
                # Check stop flag
                if self._stop_flag.is_set():
                    logger.info(f"[{self.session_id}] Stopped by user")
                    break

                # Wait if paused (blocks until resume/stop)
                while not self._pause_event.is_set():
                    if self._stop_flag.is_set():
                        break
                    # Handle takeover actions while paused in takeover mode
                    if self.state == AgentState.TAKEOVER:
                        await self._process_takeover_actions()
                    await asyncio.sleep(0.1)

                if self._stop_flag.is_set():
                    break

                # Check for injected instructions
                instruction = None
                try:
                    instruction = self._instruction_queue.get_nowait()
                except Empty:
                    pass

                # Execute one agent step
                step = await self._agent_step(
                    step_index, task_description, instruction
                )
                self._steps.append(step)

                # Check if agent decided it's done
                if step.action.get("type") == "done":
                    logger.info(f"[{self.session_id}] Agent completed task")
                    break

                # Step delay
                if self.config.step_delay > 0:
                    await asyncio.sleep(self.config.step_delay)

            self.state = AgentState.COMPLETED
            self._emit_event("complete", {
                "total_steps": len(self._steps),
                "final_url": (await self._playwright_session.get_state()).get("url", ""),
            })

        finally:
            await self._playwright_session.stop()
            self._playwright_session = None

    async def _agent_step(
        self,
        step_index: int,
        task_description: str,
        instruction: Optional[str] = None,
    ) -> AgentStep:
        """Execute a single agent step: screenshot → LLM → action → emit."""

        # 1. Take screenshot
        screenshot_bytes = await self._playwright_session.screenshot()
        if not screenshot_bytes:
            raise RuntimeError("Failed to capture screenshot")

        screenshot_path = os.path.join(
            self.screenshot_dir, f"step_{step_index:03d}.png"
        )
        os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
        with open(screenshot_path, "wb") as f:
            f.write(screenshot_bytes)

        # 2. Get page state
        page_state = await self._playwright_session.get_state()

        # 3. Emit thinking event
        self._emit_event("thinking", {
            "step_index": step_index,
            "screenshot_url": screenshot_path,
            "url": page_state.get("url", ""),
        })

        # 4. Build messages and query LLM
        screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
        messages = self._build_llm_messages(
            screenshot_b64, task_description, instruction
        )
        llm_response = self._query_llm(messages)

        # 5. Parse action from response
        thought, action = self._parse_action(llm_response)

        # 6. Execute action
        observation = await self._execute_action(action)

        # 7. Build step
        step = AgentStep(
            step_index=step_index,
            screenshot_path=screenshot_path,
            action=action,
            thought=thought,
            observation=observation,
            timestamp=time.time(),
            url=page_state.get("url", ""),
            viewport=page_state.get("viewport"),
            coordinates=_extract_coordinates(action),
            annotator_instruction=instruction,
        )

        # 8. Emit step event
        self._emit_event("step", step.to_dict())

        return step

    def _build_llm_messages(
        self,
        screenshot_b64: str,
        task_description: str,
        instruction: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Build message list for the LLM vision API."""
        messages = []

        # System message
        system_prompt = self.config.system_prompt or DEFAULT_SYSTEM_PROMPT
        messages.append({"role": "system", "content": system_prompt})

        # Task description
        task_msg = f"Task: {task_description}"
        if instruction:
            task_msg += f"\n\nAnnotator instruction: {instruction}"

        # Include recent step history
        history_steps = self._steps[-self.config.history_window:]
        if history_steps:
            history_parts = []
            for s in history_steps:
                entry = f"Step {s.step_index}: thought='{s.thought}', action={json.dumps(s.action)}, observation='{s.observation}'"
                history_parts.append(entry)
            task_msg += "\n\nRecent history:\n" + "\n".join(history_parts)

        messages.append({"role": "user", "content": task_msg})

        # Current screenshot (as a separate user message with image)
        messages.append({
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": screenshot_b64,
                    },
                },
                {
                    "type": "text",
                    "text": f"Current page screenshot (step {len(self._steps)}). What action should I take next?",
                },
            ],
        })

        return messages

    def _init_llm_client(self):
        """Initialize the LLM client based on endpoint_type."""
        if self.config.endpoint_type == "anthropic_vision":
            try:
                import anthropic
            except ImportError:
                raise RuntimeError(
                    "anthropic package required. Install with: pip install anthropic"
                )
            api_key = self.config.api_key or os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "Anthropic API key required. Set in config or ANTHROPIC_API_KEY env var."
                )
            self._llm_client = anthropic.Anthropic(
                api_key=api_key, timeout=self.config.timeout
            )
        elif self.config.endpoint_type == "ollama_vision":
            try:
                import ollama
            except ImportError:
                raise RuntimeError(
                    "ollama package required. Install with: pip install ollama"
                )
            host = self.config.base_url or "http://localhost:11434"
            self._llm_client = ollama.Client(
                host=host, timeout=self.config.timeout
            )
            # Verify connectivity
            try:
                self._llm_client.list()
                logger.info(f"Connected to Ollama at {host}, model: {self.config.model}")
            except Exception as e:
                raise RuntimeError(f"Failed to connect to Ollama at {host}: {e}")
        else:
            raise RuntimeError(
                f"Unsupported endpoint_type: {self.config.endpoint_type}. "
                f"Supported: 'anthropic_vision', 'ollama_vision'."
            )

    def _query_llm(self, messages: List[Dict[str, Any]]) -> str:
        """Send messages to the LLM and return the text response."""
        if self.config.endpoint_type == "anthropic_vision":
            return self._query_anthropic(messages)
        elif self.config.endpoint_type == "ollama_vision":
            return self._query_ollama(messages)
        raise RuntimeError(f"Unsupported endpoint type: {self.config.endpoint_type}")

    def _query_anthropic(self, messages: List[Dict[str, Any]]) -> str:
        """Query Anthropic Claude with vision support."""
        # Separate system message
        system = ""
        api_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system = msg["content"]
            else:
                api_messages.append(msg)

        kwargs = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "messages": api_messages,
        }
        if system:
            kwargs["system"] = system

        response = self._llm_client.messages.create(**kwargs)
        return response.content[0].text

    def _query_ollama(self, messages: List[Dict[str, Any]]) -> str:
        """Query Ollama vision model.

        Converts Anthropic-format messages to Ollama format:
        - System messages are prepended to the prompt text
        - Multiple user messages are merged into a single message
        - Content blocks with images use Ollama's 'images' key
        """
        # Extract text and images from Anthropic-format messages
        all_text_parts = []
        all_images = []
        for msg in messages:
            content = msg.get("content", "")
            if msg["role"] == "system":
                if isinstance(content, str) and content:
                    all_text_parts.insert(0, content)
                continue
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            all_text_parts.append(block["text"])
                        elif block.get("type") == "image":
                            source = block.get("source", {})
                            if source.get("type") == "base64":
                                all_images.append(source["data"])
            elif isinstance(content, str) and content:
                all_text_parts.append(content)

        ollama_msg = {
            "role": "user",
            "content": "\n\n".join(all_text_parts),
        }
        if all_images:
            ollama_msg["images"] = all_images

        options = {
            "temperature": self.config.temperature,
            "num_predict": self.config.max_tokens,
        }

        # Use Ollama's format schema to force structured JSON output
        agent_schema = {
            "type": "object",
            "properties": {
                "thought": {"type": "string"},
                "action": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string"},
                        "x": {"type": "integer"},
                        "y": {"type": "integer"},
                        "text": {"type": "string"},
                        "url": {"type": "string"},
                        "direction": {"type": "string"},
                        "amount": {"type": "integer"},
                        "summary": {"type": "string"},
                    },
                    "required": ["type"],
                },
            },
            "required": ["thought", "action"],
        }

        response = self._llm_client.chat(
            model=self.config.model,
            messages=[ollama_msg],
            options=options,
            format=agent_schema,
        )

        # Extract content from response (handle both dict and Pydantic model)
        message = (
            response.get("message")
            if hasattr(response, "get")
            else getattr(response, "message", None)
        )
        if message is None:
            raise RuntimeError("No message in Ollama response")

        content = (
            message.get("content")
            if hasattr(message, "get")
            else getattr(message, "content", None)
        )

        # Some models (e.g. qwen3-vl) put responses in 'thinking' field
        # and leave content empty. Extract the agent JSON from thinking.
        if not content:
            thinking = (
                message.get("thinking")
                if hasattr(message, "get")
                else getattr(message, "thinking", None)
            )
            if thinking:
                content = _extract_agent_json(thinking)

        return content or ""

    def _parse_action(self, llm_response: str) -> tuple:
        """Parse thought and action from LLM JSON response.

        Returns:
            (thought, action_dict)
        """
        # Try to extract JSON from response
        text = llm_response.strip()

        # Handle markdown code blocks
        if "```json" in text:
            import re
            match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
            if match:
                text = match.group(1).strip()
        elif "```" in text:
            import re
            match = re.search(r"```\s*([\s\S]*?)\s*```", text)
            if match:
                text = match.group(1).strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse LLM response as JSON: {text[:200]}")
            return text, {"type": "wait"}

        thought = parsed.get("thought", "")
        action = parsed.get("action", {"type": "wait"})

        # Validate action has a type
        if "type" not in action:
            action["type"] = "wait"

        return thought, action

    async def _execute_action(self, action: Dict[str, Any]) -> str:
        """Execute an action via Playwright and return observation."""
        action_type = action.get("type", "wait")
        pw = self._playwright_session

        try:
            if action_type == "click":
                x = int(action.get("x", 0))
                y = int(action.get("y", 0))
                success = await pw.click(x, y)
                return f"Clicked at ({x}, {y})" if success else f"Click failed at ({x}, {y})"

            elif action_type == "type":
                text = action.get("text", "")
                success = await pw.type_text(text)
                return f"Typed '{text}'" if success else f"Type failed: '{text}'"

            elif action_type == "scroll":
                direction = action.get("direction", "down")
                amount = int(action.get("amount", 300))
                dy = amount if direction == "down" else -amount
                success = await pw.scroll(0, dy)
                return f"Scrolled {direction} by {amount}px" if success else "Scroll failed"

            elif action_type == "navigate":
                url = action.get("url", "")
                success = await pw.navigate(url)
                return f"Navigated to {url}" if success else f"Navigation failed: {url}"

            elif action_type == "wait":
                await asyncio.sleep(1)
                return "Waited 1 second"

            elif action_type == "done":
                summary = action.get("summary", "Task completed")
                return summary

            else:
                logger.warning(f"Unknown action type: {action_type}")
                return f"Unknown action: {action_type}"

        except Exception as e:
            logger.error(f"Action execution error: {e}")
            return f"Error executing {action_type}: {e}"

    async def _process_takeover_actions(self):
        """Process manual actions submitted during takeover mode."""
        try:
            action = self._takeover_actions.get_nowait()
        except Empty:
            return

        pw = self._playwright_session
        if not pw:
            return

        observation = await self._execute_action(action)

        # Take screenshot after manual action
        screenshot_bytes = await pw.screenshot()
        step_index = len(self._steps)
        screenshot_path = os.path.join(
            self.screenshot_dir, f"step_{step_index:03d}_manual.png"
        )
        if screenshot_bytes:
            with open(screenshot_path, "wb") as f:
                f.write(screenshot_bytes)

        page_state = await pw.get_state()

        step = AgentStep(
            step_index=step_index,
            screenshot_path=screenshot_path,
            action={**action, "_manual": True},
            thought="[Manual takeover action]",
            observation=observation,
            timestamp=time.time(),
            url=page_state.get("url", ""),
            viewport=page_state.get("viewport"),
            coordinates=_extract_coordinates(action),
        )
        self._steps.append(step)
        self._emit_event("step", step.to_dict())

    # --- Trace export ---

    def get_trace(self) -> Dict[str, Any]:
        """Export the session as a web_agent_trace-compatible dict."""
        return {
            "steps": [s.to_dict() for s in self._steps],
            "task_description": "",  # Set by caller
            "session_id": self.session_id,
            "agent_config": {
                "model": self.config.model,
                "endpoint_type": self.config.endpoint_type,
                "max_steps": self.config.max_steps,
            },
            "annotator_interactions": self._interactions,
            "state": self.state.value,
            "total_steps": len(self._steps),
        }

    def get_state_summary(self) -> Dict[str, Any]:
        """Get a summary of current state for API responses."""
        return {
            "session_id": self.session_id,
            "state": self.state.value,
            "step_count": len(self._steps),
            "error": self._error,
            "has_instructions_pending": not self._instruction_queue.empty(),
        }


def _extract_agent_json(text: str) -> str:
    """Extract the last valid JSON object containing 'thought' or 'action' from text.

    Some models (qwen3-vl) put their chain-of-thought in the thinking field
    with the actual JSON answer embedded in the text. This function finds
    that JSON, skipping any example/template JSON from the prompt.
    """
    import re

    # Find all JSON-like blocks (balanced braces)
    candidates = []
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                candidates.append(text[start : i + 1])
                start = None

    # Try each candidate (last first — most likely to be the final answer)
    for candidate in reversed(candidates):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict) and ("thought" in parsed or "action" in parsed):
                return candidate
        except (json.JSONDecodeError, ValueError):
            continue

    # Fallback: try greedy regex for any JSON
    match = re.search(r"\{[^{}]*\}", text)
    return match.group(0) if match else ""


def _extract_coordinates(action: Dict[str, Any]) -> Optional[Dict[str, int]]:
    """Extract x, y coordinates from an action if present."""
    if "x" in action and "y" in action:
        return {"x": int(action["x"]), "y": int(action["y"])}
    return None
