"""
Unit tests for potato/agent_runner.py.

Covers:
- AgentState enum values
- AgentStep dataclass and to_dict()
- AgentConfig.from_config() with various configs
- AgentRunner state machine (initial state, pause/resume/stop)
- AgentRunner._parse_action() with valid JSON, markdown-wrapped JSON, invalid JSON
- AgentRunner.get_trace() output format
- AgentRunner.inject_instruction() queuing
- Thread-safe control methods

No actual LLM or Playwright calls are made; external dependencies are mocked.
"""

import json
import threading
import time
from queue import Queue
from unittest.mock import MagicMock, Mock, patch

import pytest

from potato.agent_runner import (
    AgentConfig,
    AgentRunner,
    AgentState,
    AgentStep,
    DEFAULT_SYSTEM_PROMPT,
    _extract_coordinates,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_runner(session_id="test-session", screenshot_dir="/tmp/screenshots"):
    """Build an AgentRunner with a minimal AgentConfig, no real I/O."""
    config = AgentConfig()
    return AgentRunner(session_id=session_id, config=config, screenshot_dir=screenshot_dir)


def make_step(
    step_index=0,
    screenshot_path="/tmp/step_000.png",
    action=None,
    thought="thinking",
    observation="done",
    timestamp=None,
    url="https://example.com",
):
    return AgentStep(
        step_index=step_index,
        screenshot_path=screenshot_path,
        action=action or {"type": "click", "x": 10, "y": 20},
        thought=thought,
        observation=observation,
        timestamp=timestamp or time.time(),
        url=url,
    )


# ===========================================================================
# 1. AgentState enum values
# ===========================================================================

class TestAgentState:
    """Verify all expected enum members exist and have the correct string values."""

    def test_idle_value(self):
        assert AgentState.IDLE.value == "idle"

    def test_running_value(self):
        assert AgentState.RUNNING.value == "running"

    def test_paused_value(self):
        assert AgentState.PAUSED.value == "paused"

    def test_takeover_value(self):
        assert AgentState.TAKEOVER.value == "takeover"

    def test_completed_value(self):
        assert AgentState.COMPLETED.value == "completed"

    def test_error_value(self):
        assert AgentState.ERROR.value == "error"

    def test_all_six_states_exist(self):
        expected = {"idle", "running", "paused", "takeover", "completed", "error"}
        actual = {s.value for s in AgentState}
        assert actual == expected

    def test_enum_identity(self):
        assert AgentState("idle") is AgentState.IDLE
        assert AgentState("error") is AgentState.ERROR


# ===========================================================================
# 2. AgentStep dataclass and to_dict()
# ===========================================================================

class TestAgentStep:
    """Tests for AgentStep construction and serialisation."""

    def test_basic_fields_stored(self):
        ts = 1234567890.0
        step = AgentStep(
            step_index=3,
            screenshot_path="/shots/step_003.png",
            action={"type": "navigate", "url": "https://example.com"},
            thought="Going home",
            observation="Navigation succeeded",
            timestamp=ts,
            url="https://example.com",
        )
        assert step.step_index == 3
        assert step.screenshot_path == "/shots/step_003.png"
        assert step.thought == "Going home"
        assert step.observation == "Navigation succeeded"
        assert step.timestamp == ts
        assert step.url == "https://example.com"

    def test_optional_fields_default_to_none(self):
        step = make_step()
        assert step.viewport is None
        assert step.coordinates is None
        assert step.element is None
        assert step.annotator_instruction is None

    def test_optional_fields_can_be_set(self):
        step = AgentStep(
            step_index=0,
            screenshot_path="/shot.png",
            action={"type": "click", "x": 5, "y": 10},
            thought="t",
            observation="o",
            timestamp=1.0,
            viewport={"width": 1280, "height": 720},
            coordinates={"x": 5, "y": 10},
            element={"tag": "button"},
            annotator_instruction="Click the button",
        )
        assert step.viewport == {"width": 1280, "height": 720}
        assert step.coordinates == {"x": 5, "y": 10}
        assert step.element == {"tag": "button"}
        assert step.annotator_instruction == "Click the button"

    # --- to_dict() ---

    def test_to_dict_required_keys_present(self):
        step = make_step()
        d = step.to_dict()
        for key in ("step_index", "screenshot_url", "action_type", "action",
                    "thought", "observation", "timestamp", "url"):
            assert key in d, f"Missing key: {key}"

    def test_to_dict_screenshot_url_maps_to_screenshot_path(self):
        step = make_step(screenshot_path="/shots/step_000.png")
        assert step.to_dict()["screenshot_url"] == "/shots/step_000.png"

    def test_to_dict_action_type_extracted(self):
        step = make_step(action={"type": "scroll", "direction": "down", "amount": 200})
        assert step.to_dict()["action_type"] == "scroll"

    def test_to_dict_action_type_unknown_when_missing(self):
        step = make_step(action={"direction": "down"})
        assert step.to_dict()["action_type"] == "unknown"

    def test_to_dict_optional_fields_absent_when_none(self):
        step = make_step()
        d = step.to_dict()
        assert "viewport" not in d
        assert "coordinates" not in d
        assert "element" not in d
        assert "annotator_instruction" not in d

    def test_to_dict_optional_fields_present_when_set(self):
        step = AgentStep(
            step_index=1,
            screenshot_path="/s.png",
            action={"type": "click", "x": 1, "y": 2},
            thought="t",
            observation="o",
            timestamp=1.0,
            viewport={"width": 800, "height": 600},
            coordinates={"x": 1, "y": 2},
            element={"id": "btn"},
            annotator_instruction="Do it",
        )
        d = step.to_dict()
        assert d["viewport"] == {"width": 800, "height": 600}
        assert d["coordinates"] == {"x": 1, "y": 2}
        assert d["element"] == {"id": "btn"}
        assert d["annotator_instruction"] == "Do it"

    def test_to_dict_step_index_matches(self):
        step = make_step(step_index=7)
        assert step.to_dict()["step_index"] == 7

    def test_to_dict_action_dict_preserved(self):
        action = {"type": "type", "text": "hello"}
        step = make_step(action=action)
        assert step.to_dict()["action"] == action


# ===========================================================================
# 3. AgentConfig.from_config()
# ===========================================================================

class TestAgentConfigFromConfig:
    """Tests for AgentConfig.from_config() parsing of various config dicts."""

    def test_empty_config_uses_defaults(self):
        cfg = AgentConfig.from_config({})
        assert cfg.max_steps == 30
        assert cfg.step_delay == 1.0
        assert cfg.viewport_width == 1280
        assert cfg.viewport_height == 720
        assert cfg.model == "claude-sonnet-4-20250514"
        assert cfg.max_tokens == 4096
        assert cfg.temperature == 0.3
        assert cfg.endpoint_type == "anthropic_vision"
        assert cfg.history_window == 5
        assert cfg.timeout == 60

    def test_top_level_overrides(self):
        cfg = AgentConfig.from_config({
            "max_steps": 10,
            "step_delay": 0.5,
            "endpoint_type": "custom",
            "history_window": 3,
        })
        assert cfg.max_steps == 10
        assert cfg.step_delay == 0.5
        assert cfg.endpoint_type == "custom"
        assert cfg.history_window == 3

    def test_viewport_nested_config(self):
        cfg = AgentConfig.from_config({
            "viewport": {"width": 1920, "height": 1080}
        })
        assert cfg.viewport_width == 1920
        assert cfg.viewport_height == 1080

    def test_viewport_partial_override(self):
        """Only specifying width should leave height at default."""
        cfg = AgentConfig.from_config({
            "viewport": {"width": 1024}
        })
        assert cfg.viewport_width == 1024
        assert cfg.viewport_height == 720

    def test_ai_config_nested(self):
        cfg = AgentConfig.from_config({
            "ai_config": {
                "model": "gpt-4o",
                "max_tokens": 2048,
                "temperature": 0.7,
                "timeout": 30,
            }
        })
        assert cfg.model == "gpt-4o"
        assert cfg.max_tokens == 2048
        assert cfg.temperature == 0.7
        assert cfg.timeout == 30

    def test_api_key_from_config(self):
        cfg = AgentConfig.from_config({
            "ai_config": {"api_key": "sk-test-123"}
        })
        assert cfg.api_key == "sk-test-123"

    def test_api_key_falls_back_to_env(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "env-key-456"}):
            cfg = AgentConfig.from_config({"ai_config": {}})
        assert cfg.api_key == "env-key-456"

    def test_api_key_empty_when_no_env_or_config(self):
        with patch.dict("os.environ", {}, clear=True):
            # Ensure ANTHROPIC_API_KEY is absent
            import os
            os.environ.pop("ANTHROPIC_API_KEY", None)
            cfg = AgentConfig.from_config({"ai_config": {}})
        assert cfg.api_key == ""

    def test_system_prompt_from_config(self):
        cfg = AgentConfig.from_config({"system_prompt": "You are a helpful agent."})
        assert cfg.system_prompt == "You are a helpful agent."

    def test_system_prompt_defaults_to_default_prompt(self):
        cfg = AgentConfig.from_config({})
        assert cfg.system_prompt == DEFAULT_SYSTEM_PROMPT

    def test_full_config_all_fields(self):
        full = {
            "max_steps": 20,
            "step_delay": 2.0,
            "endpoint_type": "anthropic_vision",
            "history_window": 8,
            "system_prompt": "Custom prompt",
            "viewport": {"width": 1600, "height": 900},
            "ai_config": {
                "model": "claude-opus-4-6",
                "api_key": "my-key",
                "max_tokens": 8192,
                "temperature": 0.1,
                "timeout": 120,
            },
        }
        cfg = AgentConfig.from_config(full)
        assert cfg.max_steps == 20
        assert cfg.step_delay == 2.0
        assert cfg.viewport_width == 1600
        assert cfg.viewport_height == 900
        assert cfg.system_prompt == "Custom prompt"
        assert cfg.model == "claude-opus-4-6"
        assert cfg.api_key == "my-key"
        assert cfg.max_tokens == 8192
        assert cfg.temperature == 0.1
        assert cfg.timeout == 120
        assert cfg.history_window == 8


# ===========================================================================
# 4. AgentRunner state machine
# ===========================================================================

class TestAgentRunnerStateMachine:
    """Tests for AgentRunner initial state and state transitions."""

    def test_initial_state_is_idle(self):
        runner = make_runner()
        assert runner.state == AgentState.IDLE

    def test_initial_step_count_is_zero(self):
        runner = make_runner()
        assert runner.step_count == 0

    def test_initial_steps_is_empty_list(self):
        runner = make_runner()
        assert runner.steps == []

    def test_initial_error_is_none(self):
        runner = make_runner()
        assert runner.error is None

    # --- pause ---

    def test_pause_from_running_sets_paused(self):
        runner = make_runner()
        # Manually force RUNNING state (bypasses thread start)
        with runner._state_lock:
            runner._state = AgentState.RUNNING
        runner.pause()
        assert runner.state == AgentState.PAUSED

    def test_pause_clears_pause_event(self):
        runner = make_runner()
        with runner._state_lock:
            runner._state = AgentState.RUNNING
        runner.pause()
        assert not runner._pause_event.is_set()

    def test_pause_from_non_running_does_nothing(self):
        runner = make_runner()
        # IDLE — pause should be a no-op
        runner.pause()
        assert runner.state == AgentState.IDLE

    def test_pause_from_paused_does_nothing(self):
        runner = make_runner()
        with runner._state_lock:
            runner._state = AgentState.PAUSED
        runner._pause_event.clear()
        runner.pause()
        # Still PAUSED, no state change
        assert runner.state == AgentState.PAUSED

    # --- resume ---

    def test_resume_from_paused_sets_running(self):
        runner = make_runner()
        with runner._state_lock:
            runner._state = AgentState.PAUSED
        runner._pause_event.clear()
        runner.resume()
        assert runner.state == AgentState.RUNNING

    def test_resume_sets_pause_event(self):
        runner = make_runner()
        with runner._state_lock:
            runner._state = AgentState.PAUSED
        runner._pause_event.clear()
        runner.resume()
        assert runner._pause_event.is_set()

    def test_resume_from_non_paused_does_nothing(self):
        runner = make_runner()
        # IDLE — resume should be a no-op
        runner.resume()
        assert runner.state == AgentState.IDLE

    # --- stop ---

    def test_stop_sets_stop_flag(self):
        runner = make_runner()
        runner.stop()
        assert runner._stop_flag.is_set()

    def test_stop_unblocks_pause_event(self):
        """stop() must set the pause event so a blocked loop can exit."""
        runner = make_runner()
        runner._pause_event.clear()
        runner.stop()
        assert runner._pause_event.is_set()

    def test_stop_does_not_change_state_directly(self):
        """stop() signals the loop to exit but does not set state itself."""
        runner = make_runner()
        runner.stop()
        # State stays IDLE because the async loop isn't running
        assert runner.state == AgentState.IDLE

    # --- start raises if not IDLE ---

    def test_start_raises_when_not_idle(self):
        runner = make_runner()
        with runner._state_lock:
            runner._state = AgentState.RUNNING
        with pytest.raises(RuntimeError, match="Cannot start agent"):
            runner.start("task", "https://example.com")

    # --- takeover ---

    def test_enter_takeover_from_running(self):
        runner = make_runner()
        with runner._state_lock:
            runner._state = AgentState.RUNNING
        runner.enter_takeover()
        assert runner.state == AgentState.TAKEOVER

    def test_enter_takeover_from_paused(self):
        runner = make_runner()
        with runner._state_lock:
            runner._state = AgentState.PAUSED
        runner.enter_takeover()
        assert runner.state == AgentState.TAKEOVER

    def test_enter_takeover_pauses_event(self):
        runner = make_runner()
        with runner._state_lock:
            runner._state = AgentState.RUNNING
        runner.enter_takeover()
        assert not runner._pause_event.is_set()

    def test_enter_takeover_from_idle_does_nothing(self):
        runner = make_runner()
        runner.enter_takeover()
        assert runner.state == AgentState.IDLE

    def test_exit_takeover_sets_running(self):
        runner = make_runner()
        with runner._state_lock:
            runner._state = AgentState.TAKEOVER
        runner.exit_takeover()
        assert runner.state == AgentState.RUNNING

    def test_exit_takeover_sets_pause_event(self):
        runner = make_runner()
        with runner._state_lock:
            runner._state = AgentState.TAKEOVER
        runner._pause_event.clear()
        runner.exit_takeover()
        assert runner._pause_event.is_set()

    def test_exit_takeover_from_non_takeover_does_nothing(self):
        runner = make_runner()
        runner.exit_takeover()
        assert runner.state == AgentState.IDLE


# ===========================================================================
# 5. AgentRunner._parse_action()
# ===========================================================================

class TestParseAction:
    """Tests for LLM response parsing logic."""

    def _runner(self):
        return make_runner()

    def test_valid_json_with_thought_and_action(self):
        runner = self._runner()
        payload = json.dumps({
            "thought": "I should click the button",
            "action": {"type": "click", "x": 100, "y": 200},
        })
        thought, action = runner._parse_action(payload)
        assert thought == "I should click the button"
        assert action == {"type": "click", "x": 100, "y": 200}

    def test_valid_json_missing_thought_defaults_to_empty_string(self):
        runner = self._runner()
        payload = json.dumps({"action": {"type": "wait"}})
        thought, action = runner._parse_action(payload)
        assert thought == ""

    def test_valid_json_missing_action_defaults_to_wait(self):
        runner = self._runner()
        payload = json.dumps({"thought": "hmm"})
        thought, action = runner._parse_action(payload)
        assert thought == "hmm"
        assert action == {"type": "wait"}

    def test_action_without_type_gets_wait_injected(self):
        runner = self._runner()
        payload = json.dumps({"thought": "t", "action": {"x": 5, "y": 10}})
        _, action = runner._parse_action(payload)
        assert action["type"] == "wait"

    def test_done_action_parsed(self):
        runner = self._runner()
        payload = json.dumps({
            "thought": "finished",
            "action": {"type": "done", "summary": "All done"},
        })
        thought, action = runner._parse_action(payload)
        assert action["type"] == "done"
        assert action["summary"] == "All done"

    def test_navigate_action_parsed(self):
        runner = self._runner()
        payload = json.dumps({
            "thought": "going to google",
            "action": {"type": "navigate", "url": "https://google.com"},
        })
        _, action = runner._parse_action(payload)
        assert action["type"] == "navigate"
        assert action["url"] == "https://google.com"

    # --- markdown-wrapped JSON ---

    def test_markdown_json_fenced_block(self):
        """Response wrapped in ```json ... ``` should be parsed."""
        runner = self._runner()
        payload = '```json\n{"thought": "wrapped", "action": {"type": "wait"}}\n```'
        thought, action = runner._parse_action(payload)
        assert thought == "wrapped"
        assert action["type"] == "wait"

    def test_markdown_plain_fenced_block(self):
        """Response wrapped in ``` ... ``` (no json tag) should be parsed."""
        runner = self._runner()
        payload = '```\n{"thought": "plain", "action": {"type": "wait"}}\n```'
        thought, action = runner._parse_action(payload)
        assert thought == "plain"
        assert action["type"] == "wait"

    def test_markdown_json_with_extra_surrounding_text(self):
        """Only the code block content should be used."""
        runner = self._runner()
        payload = (
            'Here is my response:\n'
            '```json\n{"thought": "inner", "action": {"type": "click", "x": 1, "y": 2}}\n```\n'
            'Hope that helps!'
        )
        thought, action = runner._parse_action(payload)
        assert thought == "inner"
        assert action["type"] == "click"

    # --- invalid JSON ---

    def test_invalid_json_returns_wait_action(self):
        runner = self._runner()
        thought, action = runner._parse_action("This is not JSON at all!")
        assert action == {"type": "wait"}

    def test_invalid_json_returns_raw_text_as_thought(self):
        runner = self._runner()
        raw = "Not JSON"
        thought, action = runner._parse_action(raw)
        # thought should be the raw (stripped) text
        assert thought == raw

    def test_partial_json_returns_wait_action(self):
        runner = self._runner()
        _, action = runner._parse_action('{"thought": "incomplete"')
        assert action == {"type": "wait"}

    def test_whitespace_stripped_before_parsing(self):
        runner = self._runner()
        payload = '  \n  {"thought": "spaces", "action": {"type": "scroll", "direction": "down", "amount": 100}}  \n  '
        thought, action = runner._parse_action(payload)
        assert thought == "spaces"
        assert action["type"] == "scroll"


# ===========================================================================
# 6. AgentRunner.get_trace()
# ===========================================================================

class TestGetTrace:
    """Tests for the get_trace() export format."""

    def test_get_trace_keys_present(self):
        runner = make_runner(session_id="trace-session")
        trace = runner.get_trace()
        for key in ("steps", "task_description", "session_id", "agent_config",
                    "annotator_interactions", "state", "total_steps"):
            assert key in trace, f"Missing key: {key}"

    def test_get_trace_session_id(self):
        runner = make_runner(session_id="my-session-42")
        assert runner.get_trace()["session_id"] == "my-session-42"

    def test_get_trace_state_reflects_current_state(self):
        runner = make_runner()
        assert runner.get_trace()["state"] == "idle"
        with runner._state_lock:
            runner._state = AgentState.COMPLETED
        assert runner.get_trace()["state"] == "completed"

    def test_get_trace_empty_steps(self):
        runner = make_runner()
        trace = runner.get_trace()
        assert trace["steps"] == []
        assert trace["total_steps"] == 0

    def test_get_trace_steps_after_injection(self):
        runner = make_runner()
        step = make_step(step_index=0)
        runner._steps.append(step)
        trace = runner.get_trace()
        assert trace["total_steps"] == 1
        assert len(trace["steps"]) == 1
        assert trace["steps"][0]["step_index"] == 0

    def test_get_trace_steps_serialised_via_to_dict(self):
        runner = make_runner()
        step = make_step(action={"type": "navigate", "url": "https://example.com"})
        runner._steps.append(step)
        trace = runner.get_trace()
        step_dict = trace["steps"][0]
        assert step_dict["action_type"] == "navigate"
        assert "screenshot_url" in step_dict

    def test_get_trace_agent_config_fields(self):
        runner = make_runner()
        cfg_section = runner.get_trace()["agent_config"]
        assert "model" in cfg_section
        assert "endpoint_type" in cfg_section
        assert "max_steps" in cfg_section

    def test_get_trace_agent_config_values(self):
        runner = make_runner()
        cfg_section = runner.get_trace()["agent_config"]
        assert cfg_section["model"] == runner.config.model
        assert cfg_section["endpoint_type"] == runner.config.endpoint_type
        assert cfg_section["max_steps"] == runner.config.max_steps

    def test_get_trace_annotator_interactions_empty_initially(self):
        runner = make_runner()
        assert runner.get_trace()["annotator_interactions"] == []

    def test_get_trace_annotator_interactions_after_inject(self):
        runner = make_runner()
        # inject_instruction emits an event — mock listeners to avoid side-effects
        runner.inject_instruction("Please click Login")
        interactions = runner.get_trace()["annotator_interactions"]
        assert len(interactions) == 1
        assert interactions[0]["type"] == "instruction"
        assert interactions[0]["text"] == "Please click Login"

    def test_get_trace_task_description_is_empty_string(self):
        """task_description is intentionally left empty (set by caller per docs)."""
        runner = make_runner()
        assert runner.get_trace()["task_description"] == ""

    def test_get_trace_multiple_steps(self):
        runner = make_runner()
        for i in range(5):
            runner._steps.append(make_step(step_index=i))
        trace = runner.get_trace()
        assert trace["total_steps"] == 5
        assert len(trace["steps"]) == 5


# ===========================================================================
# 7. inject_instruction() queuing
# ===========================================================================

class TestInjectInstruction:
    """Tests for inject_instruction() and queue behaviour."""

    def test_instruction_added_to_queue(self):
        runner = make_runner()
        runner.inject_instruction("Go to Settings")
        assert not runner._instruction_queue.empty()

    def test_instruction_value_in_queue(self):
        runner = make_runner()
        runner.inject_instruction("Click Search")
        item = runner._instruction_queue.get_nowait()
        assert item == "Click Search"

    def test_multiple_instructions_queued_in_order(self):
        runner = make_runner()
        runner.inject_instruction("first")
        runner.inject_instruction("second")
        runner.inject_instruction("third")
        assert runner._instruction_queue.get_nowait() == "first"
        assert runner._instruction_queue.get_nowait() == "second"
        assert runner._instruction_queue.get_nowait() == "third"

    def test_interaction_log_updated(self):
        runner = make_runner()
        runner.inject_instruction("hello")
        assert len(runner._interactions) == 1
        entry = runner._interactions[0]
        assert entry["type"] == "instruction"
        assert entry["text"] == "hello"

    def test_interaction_log_has_timestamp(self):
        runner = make_runner()
        before = time.time()
        runner.inject_instruction("test")
        after = time.time()
        ts = runner._interactions[0]["timestamp"]
        assert before <= ts <= after

    def test_interaction_log_has_step_index(self):
        runner = make_runner()
        # No steps yet → step_index should be 0
        runner.inject_instruction("check")
        assert runner._interactions[0]["step_index"] == 0

    def test_interaction_log_step_index_reflects_current_count(self):
        runner = make_runner()
        runner._steps.append(make_step(step_index=0))
        runner._steps.append(make_step(step_index=1))
        runner.inject_instruction("after two steps")
        assert runner._interactions[0]["step_index"] == 2

    def test_inject_emits_event_to_listeners(self):
        runner = make_runner()
        received = []
        runner.add_listener(received.append)
        runner.inject_instruction("ping")
        events = [e for e in received if e["type"] == "instruction_received"]
        assert len(events) == 1
        assert events[0]["data"]["instruction"] == "ping"


# ===========================================================================
# 8. Thread-safe control methods
# ===========================================================================

class TestThreadSafeControl:
    """Concurrency tests for state transitions and event mechanisms."""

    def test_state_property_is_consistent_under_concurrent_reads(self):
        """Multiple threads reading state should never see a torn value."""
        runner = make_runner()
        with runner._state_lock:
            runner._state = AgentState.RUNNING

        results = []

        def read_state():
            for _ in range(100):
                results.append(runner.state)

        threads = [threading.Thread(target=read_state) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All observed states should be valid AgentState members
        assert all(isinstance(s, AgentState) for s in results)

    def test_pause_and_resume_from_multiple_threads(self):
        """Rapid pause/resume should not leave the runner in an inconsistent state."""
        runner = make_runner()
        with runner._state_lock:
            runner._state = AgentState.RUNNING

        def toggle():
            for _ in range(20):
                runner.pause()
                with runner._state_lock:
                    runner._state = AgentState.RUNNING  # reset for next pause
                runner._pause_event.set()

        threads = [threading.Thread(target=toggle) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No assertion on final state — just confirm no exceptions were raised

    def test_inject_instruction_from_multiple_threads(self):
        """Concurrent instruction injection should queue all messages safely."""
        runner = make_runner()
        n_threads = 10
        n_per_thread = 50

        def inject(tid):
            for i in range(n_per_thread):
                runner.inject_instruction(f"thread-{tid}-msg-{i}")

        threads = [threading.Thread(target=inject, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Queue size should equal total injections
        assert runner._instruction_queue.qsize() == n_threads * n_per_thread
        # Interactions log should also have the same count
        assert len(runner._interactions) == n_threads * n_per_thread

    def test_stop_flag_set_is_atomic(self):
        """stop() can be called safely from multiple threads simultaneously."""
        runner = make_runner()
        threads = [threading.Thread(target=runner.stop) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert runner._stop_flag.is_set()

    def test_add_and_remove_listener_thread_safe(self):
        """Concurrent listener add/remove should not corrupt the list."""
        runner = make_runner()
        listeners = [Mock() for _ in range(20)]

        def add_all():
            for l in listeners:
                runner.add_listener(l)

        def remove_all():
            for l in listeners:
                runner.remove_listener(l)

        add_thread = threading.Thread(target=add_all)
        remove_thread = threading.Thread(target=remove_all)
        add_thread.start()
        add_thread.join()
        remove_thread.start()
        remove_thread.join()

        # After all removals the list should be empty
        with runner._listeners_lock:
            remaining = list(runner._listeners)
        assert remaining == []

    def test_emit_event_calls_all_listeners(self):
        runner = make_runner()
        events_a = []
        events_b = []
        runner.add_listener(events_a.append)
        runner.add_listener(events_b.append)
        runner._emit_event("test_event", {"value": 42})
        assert len(events_a) == 1
        assert len(events_b) == 1
        assert events_a[0]["type"] == "test_event"
        assert events_a[0]["data"]["value"] == 42

    def test_emit_event_tolerates_failing_listener(self):
        """A crashing listener should not prevent other listeners from receiving events."""
        runner = make_runner()
        good_events = []

        def bad_listener(event):
            raise RuntimeError("listener crash")

        runner.add_listener(bad_listener)
        runner.add_listener(good_events.append)
        # Should not raise
        runner._emit_event("test", {})
        assert len(good_events) == 1

    def test_state_setter_emits_state_change_event(self):
        runner = make_runner()
        events = []
        runner.add_listener(events.append)
        runner.state = AgentState.RUNNING
        state_events = [e for e in events if e["type"] == "state_change"]
        assert len(state_events) == 1
        assert state_events[0]["data"]["new_state"] == "running"
        assert state_events[0]["data"]["old_state"] == "idle"

    def test_get_state_summary_reflects_current_state(self):
        runner = make_runner()
        summary = runner.get_state_summary()
        assert summary["session_id"] == runner.session_id
        assert summary["state"] == "idle"
        assert summary["step_count"] == 0
        assert summary["error"] is None
        assert summary["has_instructions_pending"] is False

    def test_get_state_summary_has_instructions_pending(self):
        runner = make_runner()
        runner.inject_instruction("do something")
        summary = runner.get_state_summary()
        assert summary["has_instructions_pending"] is True

    def test_submit_manual_action_queued_in_takeover(self):
        runner = make_runner()
        with runner._state_lock:
            runner._state = AgentState.TAKEOVER
        action = {"type": "click", "x": 50, "y": 75}
        runner.submit_manual_action(action)
        assert not runner._takeover_actions.empty()
        assert runner._takeover_actions.get_nowait() == action

    def test_submit_manual_action_ignored_outside_takeover(self):
        runner = make_runner()
        runner.submit_manual_action({"type": "click", "x": 1, "y": 1})
        assert runner._takeover_actions.empty()


# ===========================================================================
# 9. _extract_coordinates() helper
# ===========================================================================

class TestExtractCoordinates:
    """Tests for the module-level _extract_coordinates helper."""

    def test_returns_coords_when_x_and_y_present(self):
        action = {"type": "click", "x": 100, "y": 200}
        result = _extract_coordinates(action)
        assert result == {"x": 100, "y": 200}

    def test_returns_none_when_no_coords(self):
        action = {"type": "navigate", "url": "https://example.com"}
        assert _extract_coordinates(action) is None

    def test_returns_none_when_only_x(self):
        assert _extract_coordinates({"x": 5}) is None

    def test_returns_none_when_only_y(self):
        assert _extract_coordinates({"y": 5}) is None

    def test_converts_to_int(self):
        result = _extract_coordinates({"x": "42", "y": "99"})
        assert result == {"x": 42, "y": 99}
        assert isinstance(result["x"], int)
        assert isinstance(result["y"], int)

    def test_zero_coordinates(self):
        result = _extract_coordinates({"x": 0, "y": 0})
        assert result == {"x": 0, "y": 0}


# ===========================================================================
# 10. AgentConfig dataclass defaults (direct construction)
# ===========================================================================

class TestAgentConfigDefaults:
    """Verify AgentConfig() defaults when constructed directly."""

    def test_default_max_steps(self):
        assert AgentConfig().max_steps == 30

    def test_default_step_delay(self):
        assert AgentConfig().step_delay == 1.0

    def test_default_viewport(self):
        cfg = AgentConfig()
        assert cfg.viewport_width == 1280
        assert cfg.viewport_height == 720

    def test_default_model(self):
        assert AgentConfig().model == "claude-sonnet-4-20250514"

    def test_default_max_tokens(self):
        assert AgentConfig().max_tokens == 4096

    def test_default_temperature(self):
        assert AgentConfig().temperature == 0.3

    def test_default_endpoint_type(self):
        assert AgentConfig().endpoint_type == "anthropic_vision"

    def test_default_history_window(self):
        assert AgentConfig().history_window == 5

    def test_default_timeout(self):
        assert AgentConfig().timeout == 60


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
