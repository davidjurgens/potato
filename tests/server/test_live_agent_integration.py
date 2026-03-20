"""
Live Agent Integration Tests

End-to-end tests that exercise the live agent feature with real
Playwright (headless Chromium) and Ollama (gemma3:4b) vision model.

These tests require:
    pip install playwright ollama
    playwright install chromium
    ollama pull gemma3:4b
    # Ollama server must be running on localhost:11434

Tests are marked with @pytest.mark.integration so they can be
selectively run: pytest tests/server/test_live_agent_integration.py -v

Covered:
    1. AgentRunner direct: LLM init, single step, full loop, trace export
    2. AgentRunner controls: pause/resume, instruction injection, stop
    3. REST API via FlaskTestServer: start, state, pause, resume, instruct, stop, sessions
    4. SSE stream: event types, step events, completion
"""

import base64
import json
import os
import struct
import tempfile
import threading
import time
import zlib

import pytest
import requests

from potato.agent_runner import (
    AgentConfig,
    AgentRunner,
    AgentState,
    _extract_agent_json,
)
from potato.agent_runner_manager import AgentRunnerManager

# ---------------------------------------------------------------------------
# Markers & skip conditions
# ---------------------------------------------------------------------------

def _ollama_available():
    """Check if Ollama is running and gemma3:4b is pulled."""
    try:
        import ollama
        client = ollama.Client(host="http://localhost:11434", timeout=5)
        resp = client.list()
        models = [m.get("name", m.get("model", "")) for m in resp.get("models", [])]
        return any("gemma3:4b" in m for m in models)
    except Exception:
        return False


def _playwright_available():
    """Check if Playwright + Chromium are installed."""
    try:
        import playwright
        return True
    except ImportError:
        return False


OLLAMA_OK = _ollama_available()
PLAYWRIGHT_OK = _playwright_available()

skip_no_ollama = pytest.mark.skipif(
    not OLLAMA_OK,
    reason="Ollama not running or gemma3:4b not available",
)
skip_no_playwright = pytest.mark.skipif(
    not PLAYWRIGHT_OK,
    reason="Playwright not installed (pip install playwright && playwright install chromium)",
)
skip_no_deps = pytest.mark.skipif(
    not (OLLAMA_OK and PLAYWRIGHT_OK),
    reason="Requires both Ollama (gemma3:4b) and Playwright",
)

# All tests in this module need at least Ollama
pytestmark = [pytest.mark.integration]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**overrides):
    """Build an AgentConfig for Ollama testing."""
    defaults = dict(
        max_steps=2,
        step_delay=0.2,
        viewport_width=800,
        viewport_height=600,
        model="gemma3:4b",
        endpoint_type="ollama_vision",
        base_url="http://localhost:11434",
        max_tokens=512,
        temperature=0.3,
        timeout=120,
    )
    defaults.update(overrides)
    return AgentConfig(**defaults)


def _create_test_png(width=200, height=150):
    """Create a minimal PNG for LLM screenshot testing."""
    sig = b'\x89PNG\r\n\x1a\n'
    ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    ihdr_crc = zlib.crc32(b'IHDR' + ihdr_data) & 0xffffffff
    ihdr = struct.pack('>I', 13) + b'IHDR' + ihdr_data + struct.pack('>I', ihdr_crc)
    raw = b''
    for y in range(height):
        raw += b'\x00'
        for x in range(width):
            if y < 30:
                raw += b'\x33\x33\x33'
            elif 50 <= y <= 80 and 20 <= x <= 180:
                raw += b'\x42\x87\xf5'
            else:
                raw += b'\xff\xff\xff'
    compressed = zlib.compress(raw)
    idat_crc = zlib.crc32(b'IDAT' + compressed) & 0xffffffff
    idat = struct.pack('>I', len(compressed)) + b'IDAT' + compressed + struct.pack('>I', idat_crc)
    iend_crc = zlib.crc32(b'IEND') & 0xffffffff
    iend = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', iend_crc)
    return sig + ihdr + idat + iend


def _collect_events(runner, timeout=120):
    """Attach a listener and collect events until complete/error or timeout."""
    events = []
    done = threading.Event()

    def on_event(evt):
        events.append(evt)
        if evt.get("type") in ("complete", "error"):
            done.set()

    runner.add_listener(on_event)
    done.wait(timeout=timeout)
    runner.remove_listener(on_event)
    return events


# ---------------------------------------------------------------------------
# 1. AgentRunner LLM integration (Ollama only, no Playwright)
# ---------------------------------------------------------------------------

@skip_no_ollama
class TestAgentRunnerOllamaLLM:
    """Test LLM query + response parsing with a real Ollama model."""

    def test_init_llm_client(self):
        """_init_llm_client should connect to Ollama successfully."""
        config = _make_config()
        runner = AgentRunner("test-init", config, tempfile.mkdtemp())
        runner._init_llm_client()
        assert runner._llm_client is not None

    def test_query_with_synthetic_screenshot(self):
        """Query Ollama with a synthetic screenshot and get valid JSON."""
        config = _make_config()
        runner = AgentRunner("test-query", config, tempfile.mkdtemp())
        runner._init_llm_client()

        png_bytes = _create_test_png()
        b64 = base64.b64encode(png_bytes).decode("utf-8")

        messages = runner._build_llm_messages(
            b64, "Describe the image"
        )
        response = runner._query_llm(messages)

        assert response, "LLM returned empty response"

        thought, action = runner._parse_action(response)
        assert isinstance(thought, str)
        assert isinstance(action, dict)
        assert "type" in action

    def test_multiple_action_types_parseable(self):
        """Verify _parse_action handles all expected JSON formats."""
        config = _make_config()
        runner = AgentRunner("test-parse", config, tempfile.mkdtemp())

        # Standard response
        resp = json.dumps({"thought": "I see a button", "action": {"type": "click", "x": 100, "y": 50}})
        thought, action = runner._parse_action(resp)
        assert thought == "I see a button"
        assert action["type"] == "click"
        assert action["x"] == 100

        # Markdown-wrapped
        resp2 = '```json\n{"thought": "scrolling", "action": {"type": "scroll", "direction": "down", "amount": 300}}\n```'
        thought2, action2 = runner._parse_action(resp2)
        assert action2["type"] == "scroll"

        # Done action
        resp3 = json.dumps({"thought": "Task done", "action": {"type": "done", "summary": "Finished"}})
        thought3, action3 = runner._parse_action(resp3)
        assert action3["type"] == "done"

    def test_extract_agent_json_from_thinking(self):
        """Test _extract_agent_json extracts JSON from thinking text."""
        thinking = (
            'Let me analyze the screenshot. I see a webpage with a header and a button.\n'
            'The button appears to be in the middle of the page.\n'
            '{"thought": "I see a blue button", "action": {"type": "click", "x": 100, "y": 65}}'
        )
        result = _extract_agent_json(thinking)
        parsed = json.loads(result)
        assert parsed["thought"] == "I see a blue button"
        assert parsed["action"]["type"] == "click"

    def test_from_config_ollama(self):
        """AgentConfig.from_config should handle ollama_vision config."""
        cfg = {
            "endpoint_type": "ollama_vision",
            "ai_config": {
                "model": "gemma3:4b",
                "base_url": "http://localhost:11434",
                "max_tokens": 256,
                "timeout": 90,
            },
            "max_steps": 5,
            "step_delay": 0.5,
            "viewport": {"width": 640, "height": 480},
        }
        ac = AgentConfig.from_config(cfg)
        assert ac.endpoint_type == "ollama_vision"
        assert ac.model == "gemma3:4b"
        assert ac.base_url == "http://localhost:11434"
        assert ac.max_steps == 5
        assert ac.viewport_width == 640
        assert ac.timeout == 90


# ---------------------------------------------------------------------------
# 2. Full agent loop (Playwright + Ollama)
# ---------------------------------------------------------------------------

@skip_no_deps
class TestAgentRunnerFullLoop:
    """Test the full agent loop with real Playwright + Ollama."""

    def test_agent_runs_and_completes(self):
        """Start agent on example.com, verify it runs steps and completes."""
        config = _make_config(max_steps=3, step_delay=0.5)
        screenshot_dir = tempfile.mkdtemp(prefix="agent_test_")
        runner = AgentRunner("test-loop", config, screenshot_dir)

        events = []
        done = threading.Event()

        def on_event(evt):
            events.append(evt)
            if evt.get("type") in ("complete", "error"):
                done.set()

        runner.add_listener(on_event)
        runner.start("Describe what you see on this page", "https://example.com")

        # Wait for completion (generous timeout for LLM calls)
        done.wait(timeout=180)

        assert runner.state in (AgentState.COMPLETED, AgentState.ERROR), (
            f"Agent ended in unexpected state: {runner.state}"
        )

        # Should have executed at least 1 step
        assert runner.step_count >= 1, "Agent completed 0 steps"

        # Verify event stream
        event_types = [e["type"] for e in events]
        assert "started" in event_types, "Missing 'started' event"
        assert "step" in event_types, "Missing 'step' event"
        assert "thinking" in event_types, "Missing 'thinking' event"

        # Verify step data
        steps = runner.steps
        for step in steps:
            assert step.screenshot_path, "Step missing screenshot_path"
            assert os.path.isfile(step.screenshot_path), (
                f"Screenshot not on disk: {step.screenshot_path}"
            )
            assert step.action, "Step missing action"
            assert "type" in step.action, "Step action missing type"

    def test_trace_export(self):
        """get_trace() should return a valid web_agent_trace-compatible dict."""
        config = _make_config(max_steps=2, step_delay=0.3)
        screenshot_dir = tempfile.mkdtemp(prefix="agent_trace_")
        runner = AgentRunner("test-trace", config, screenshot_dir)

        done = threading.Event()
        runner.add_listener(lambda e: done.set() if e["type"] in ("complete", "error") else None)
        runner.start("Look at this page", "https://example.com")
        done.wait(timeout=120)

        trace = runner.get_trace()
        assert "steps" in trace
        assert "session_id" in trace
        assert trace["session_id"] == "test-trace"
        assert "agent_config" in trace
        assert trace["agent_config"]["endpoint_type"] == "ollama_vision"
        assert trace["total_steps"] == len(trace["steps"])
        assert trace["total_steps"] >= 1

        # Each step in trace should have required fields
        for step_dict in trace["steps"]:
            assert "step_index" in step_dict
            assert "action_type" in step_dict
            assert "action" in step_dict
            assert "thought" in step_dict
            assert "timestamp" in step_dict

    def test_agent_stop_mid_run(self):
        """stop() should cleanly terminate the agent during execution."""
        config = _make_config(max_steps=10, step_delay=2.0)
        screenshot_dir = tempfile.mkdtemp(prefix="agent_stop_")
        runner = AgentRunner("test-stop", config, screenshot_dir)

        started = threading.Event()
        runner.add_listener(lambda e: started.set() if e["type"] == "started" else None)

        runner.start("Browse this page slowly", "https://example.com")
        started.wait(timeout=60)

        # Let it run for a bit then stop
        time.sleep(2)
        runner.stop()

        # Wait for thread to finish
        if runner._thread:
            runner._thread.join(timeout=10)

        assert runner.state in (AgentState.COMPLETED, AgentState.ERROR), (
            f"Expected terminal state after stop, got: {runner.state}"
        )
        # Should have fewer steps than max
        assert runner.step_count < 10


@skip_no_deps
class TestAgentRunnerControls:
    """Test pause/resume and instruction injection with real agent."""

    def test_pause_and_resume(self):
        """Pause agent, verify paused state, resume, verify it continues."""
        config = _make_config(max_steps=5, step_delay=1.0)
        screenshot_dir = tempfile.mkdtemp(prefix="agent_pause_")
        runner = AgentRunner("test-pause", config, screenshot_dir)

        first_step = threading.Event()
        done = threading.Event()

        def on_event(evt):
            if evt["type"] == "step":
                first_step.set()
            elif evt["type"] in ("complete", "error"):
                done.set()

        runner.add_listener(on_event)
        runner.start("Explore this page", "https://example.com")

        # Wait for first step
        first_step.wait(timeout=90)

        # Pause
        runner.pause()
        assert runner.state == AgentState.PAUSED

        steps_at_pause = runner.step_count
        time.sleep(2)
        # Should not have advanced while paused
        assert runner.step_count == steps_at_pause, "Agent advanced while paused"

        # Resume
        runner.resume()
        assert runner.state == AgentState.RUNNING

        # Wait for completion
        done.wait(timeout=120)
        assert runner.step_count > steps_at_pause, "Agent didn't advance after resume"

    def test_inject_instruction(self):
        """inject_instruction should be recorded in trace interactions."""
        config = _make_config(max_steps=3, step_delay=1.0)
        screenshot_dir = tempfile.mkdtemp(prefix="agent_instr_")
        runner = AgentRunner("test-instr", config, screenshot_dir)

        first_step = threading.Event()
        done = threading.Event()

        def on_event(evt):
            if evt["type"] == "step":
                first_step.set()
            elif evt["type"] in ("complete", "error"):
                done.set()

        runner.add_listener(on_event)
        runner.start("Navigate this page", "https://example.com")

        first_step.wait(timeout=90)

        # Inject instruction
        runner.inject_instruction("Click on the 'More information' link")

        done.wait(timeout=120)

        # Check the trace for the instruction
        trace = runner.get_trace()
        interactions = trace.get("annotator_interactions", [])
        instruction_interactions = [i for i in interactions if i["type"] == "instruction"]
        assert len(instruction_interactions) >= 1, "Instruction not recorded in trace"
        assert "More information" in instruction_interactions[0]["text"]


# ---------------------------------------------------------------------------
# 3. AgentRunnerManager tests with real sessions
# ---------------------------------------------------------------------------

@skip_no_deps
class TestAgentRunnerManagerIntegration:
    """Test session management with real agent sessions."""

    def setup_method(self):
        AgentRunnerManager.clear_instance()

    def teardown_method(self):
        AgentRunnerManager.clear_instance()

    def test_create_and_list_sessions(self):
        """Create a session, verify it appears in list, then clean up."""
        manager = AgentRunnerManager.get_instance()
        config = _make_config(max_steps=2, step_delay=0.3)
        screenshot_dir = tempfile.mkdtemp(prefix="mgr_test_")

        runner = manager.create_session("user1", "inst1", config, screenshot_dir)
        assert runner.session_id

        sessions = manager.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["user_id"] == "user1"
        assert sessions[0]["instance_id"] == "inst1"

        # Start and wait
        done = threading.Event()
        runner.add_listener(lambda e: done.set() if e["type"] in ("complete", "error") else None)
        runner.start("Test task", "https://example.com")
        done.wait(timeout=120)

        # Verify session still accessible
        found = manager.get_session(runner.session_id)
        assert found is runner

    def test_remove_session(self):
        """Remove a session and verify it's gone."""
        manager = AgentRunnerManager.get_instance()
        config = _make_config(max_steps=1)
        screenshot_dir = tempfile.mkdtemp(prefix="mgr_rm_")

        runner = manager.create_session("user2", "inst2", config, screenshot_dir)
        sid = runner.session_id

        manager.remove_session(sid)
        assert manager.get_session(sid) is None
        assert len(manager.list_sessions()) == 0


# ---------------------------------------------------------------------------
# 4. REST API integration tests via FlaskTestServer
# ---------------------------------------------------------------------------

@skip_no_deps
class TestLiveAgentAPI:
    """Test live agent REST API endpoints with a running Flask server."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Start Flask server with live agent config."""
        from tests.helpers.test_utils import create_test_directory, create_test_data_file
        from tests.helpers.flask_test_setup import FlaskTestServer
        import yaml

        test_dir = create_test_directory("live_agent_api_test")

        # Create test data with task descriptions and start URLs
        test_data = [
            {
                "id": "task_01",
                "task_description": "Describe what you see on the page",
                "start_url": "https://example.com",
                "text": "Describe example.com",
            },
        ]
        data_file = create_test_data_file(test_dir, test_data, "tasks.json")

        # Build config with live_agent section
        config = {
            "annotation_task_name": "Live Agent API Test",
            "data_files": [{"type": "json", "path": data_file}],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "task_dir": test_dir,
            "user_config": {"allow_all_users": True},
            "output_annotation_dir": os.path.join(test_dir, "annotation_output"),
            "output_annotation_format": "json",
            "live_agent": {
                "endpoint_type": "ollama_vision",
                "ai_config": {
                    "model": "gemma3:4b",
                    "base_url": "http://localhost:11434",
                    "max_tokens": 512,
                    "temperature": 0.3,
                    "timeout": 120,
                },
                "max_steps": 3,
                "step_delay": 0.5,
                "viewport": {"width": 800, "height": 600},
            },
            "instance_display": {
                "fields": [
                    {"key": "task_description", "type": "text", "label": "Task"},
                    {"key": "start_url", "type": "text", "label": "URL"},
                    {
                        "key": "agent_trace",
                        "type": "live_agent",
                        "label": "Live Agent",
                        "display_options": {
                            "show_controls": True,
                            "show_thought": True,
                        },
                    },
                ]
            },
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "task_completion",
                    "description": "Did the agent complete the task?",
                    "labels": [
                        {"name": "Yes"},
                        {"name": "No"},
                    ],
                }
            ],
        }

        config_path = os.path.join(test_dir, "config.yaml")
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        server = FlaskTestServer(config=config_path)
        if not server.start():
            pytest.fail("Failed to start Flask server for live agent API test")

        request.cls.server = server
        yield server
        server.stop()

    @pytest.fixture()
    def session(self, flask_server):
        """Authenticated requests.Session."""
        s = requests.Session()
        # Register + login
        s.post(f"{flask_server.base_url}/register",
               data={"email": "testuser", "pass": "testpass"})
        s.post(f"{flask_server.base_url}/auth",
               data={"email": "testuser", "pass": "testpass"})
        yield s
        s.close()

    def test_sessions_list_initially_empty(self, session, flask_server):
        """GET /api/live_agent/sessions should return empty list."""
        resp = session.get(f"{flask_server.base_url}/api/live_agent/sessions", timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert "sessions" in data
        assert isinstance(data["sessions"], list)

    def test_start_requires_fields(self, session, flask_server):
        """POST /api/live_agent/start should reject missing fields."""
        resp = session.post(
            f"{flask_server.base_url}/api/live_agent/start",
            json={},
            timeout=10,
        )
        assert resp.status_code == 400

        resp2 = session.post(
            f"{flask_server.base_url}/api/live_agent/start",
            json={"task_description": "test"},
            timeout=10,
        )
        assert resp2.status_code == 400

    def test_start_and_state(self, session, flask_server):
        """Start a session, check its state, then stop it."""
        # Start
        resp = session.post(
            f"{flask_server.base_url}/api/live_agent/start",
            json={
                "task_description": "Describe this page",
                "start_url": "https://example.com",
                "instance_id": "task_01",
            },
            timeout=30,
        )
        assert resp.status_code == 200, f"Start failed: {resp.text}"
        data = resp.json()
        sid = data["session_id"]
        assert sid

        # Give the agent a moment to initialize
        time.sleep(3)

        # State
        state_resp = session.get(
            f"{flask_server.base_url}/api/live_agent/state/{sid}",
            timeout=10,
        )
        assert state_resp.status_code == 200
        state_data = state_resp.json()
        assert state_data["session_id"] == sid
        assert state_data["state"] in ("running", "paused", "completed", "error")

        # Sessions list
        list_resp = session.get(
            f"{flask_server.base_url}/api/live_agent/sessions",
            timeout=10,
        )
        assert list_resp.status_code == 200
        sessions_list = list_resp.json()["sessions"]
        assert any(s["session_id"] == sid for s in sessions_list)

        # Stop
        stop_resp = session.post(
            f"{flask_server.base_url}/api/live_agent/stop/{sid}",
            timeout=30,
        )
        assert stop_resp.status_code == 200
        stop_data = stop_resp.json()
        assert stop_data["status"] == "stopped"
        assert "trace" in stop_data

    def test_start_pause_resume_stop(self, session, flask_server):
        """Exercise the full control flow: start → pause → resume → stop."""
        # Start
        resp = session.post(
            f"{flask_server.base_url}/api/live_agent/start",
            json={
                "task_description": "Test controls",
                "start_url": "https://example.com",
                "instance_id": "task_01",
            },
            timeout=30,
        )
        assert resp.status_code == 200
        sid = resp.json()["session_id"]

        # Wait for agent to start running
        time.sleep(3)

        # Pause
        pause_resp = session.post(
            f"{flask_server.base_url}/api/live_agent/pause/{sid}",
            timeout=10,
        )
        assert pause_resp.status_code == 200
        assert pause_resp.json()["state"] in ("paused", "completed", "error")

        # Resume (only if still paused)
        if pause_resp.json()["state"] == "paused":
            resume_resp = session.post(
                f"{flask_server.base_url}/api/live_agent/resume/{sid}",
                timeout=10,
            )
            assert resume_resp.status_code == 200

        # Stop
        time.sleep(1)
        stop_resp = session.post(
            f"{flask_server.base_url}/api/live_agent/stop/{sid}",
            timeout=30,
        )
        assert stop_resp.status_code == 200

    def test_instruct_endpoint(self, session, flask_server):
        """POST /api/live_agent/instruct should accept an instruction."""
        # Start session
        resp = session.post(
            f"{flask_server.base_url}/api/live_agent/start",
            json={
                "task_description": "Test instruction",
                "start_url": "https://example.com",
                "instance_id": "task_01",
            },
            timeout=30,
        )
        assert resp.status_code == 200
        sid = resp.json()["session_id"]

        time.sleep(3)

        # Instruct
        instr_resp = session.post(
            f"{flask_server.base_url}/api/live_agent/instruct/{sid}",
            json={"instruction": "Click on 'More information'"},
            timeout=10,
        )
        assert instr_resp.status_code == 200

        # Missing instruction should fail
        instr_resp2 = session.post(
            f"{flask_server.base_url}/api/live_agent/instruct/{sid}",
            json={},
            timeout=10,
        )
        assert instr_resp2.status_code == 400

        # Cleanup
        session.post(f"{flask_server.base_url}/api/live_agent/stop/{sid}", timeout=30)

    def test_unknown_session_returns_404(self, session, flask_server):
        """Endpoints should return 404 for non-existent session IDs."""
        fake_sid = "nonexistent123"
        resp = session.get(
            f"{flask_server.base_url}/api/live_agent/state/{fake_sid}",
            timeout=10,
        )
        assert resp.status_code == 404

    def test_full_session_with_trace(self, session, flask_server):
        """Start a session, let it run to completion, verify trace."""
        resp = session.post(
            f"{flask_server.base_url}/api/live_agent/start",
            json={
                "task_description": "Describe this page briefly",
                "start_url": "https://example.com",
                "instance_id": "task_01",
            },
            timeout=30,
        )
        assert resp.status_code == 200
        sid = resp.json()["session_id"]

        # Poll until completion (max_steps=3, generous timeout)
        deadline = time.time() + 180
        final_state = None
        while time.time() < deadline:
            state_resp = session.get(
                f"{flask_server.base_url}/api/live_agent/state/{sid}",
                timeout=10,
            )
            if state_resp.status_code == 200:
                final_state = state_resp.json()["state"]
                if final_state in ("completed", "error"):
                    break
            time.sleep(2)

        assert final_state in ("completed", "error"), (
            f"Agent did not finish within timeout, state: {final_state}"
        )

        # Get trace via stop (even if already completed, stop returns trace)
        stop_resp = session.post(
            f"{flask_server.base_url}/api/live_agent/stop/{sid}",
            timeout=30,
        )
        assert stop_resp.status_code == 200
        trace = stop_resp.json().get("trace", {})
        assert trace.get("total_steps", 0) >= 1
        assert len(trace.get("steps", [])) >= 1

        # Verify trace structure
        for step in trace["steps"]:
            assert "step_index" in step
            assert "action" in step
            assert "thought" in step


# ---------------------------------------------------------------------------
# 5. SSE stream test
# ---------------------------------------------------------------------------

@skip_no_deps
class TestLiveAgentSSE:
    """Test SSE event streaming from a live agent session."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Start Flask server with live agent config."""
        from tests.helpers.test_utils import create_test_directory, create_test_data_file
        from tests.helpers.flask_test_setup import FlaskTestServer
        import yaml

        test_dir = create_test_directory("live_agent_sse_test")

        test_data = [
            {
                "id": "sse_task",
                "task_description": "Describe page",
                "start_url": "https://example.com",
                "text": "SSE test",
            },
        ]
        data_file = create_test_data_file(test_dir, test_data, "tasks.json")

        config = {
            "annotation_task_name": "Live Agent SSE Test",
            "data_files": [{"type": "json", "path": data_file}],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "task_dir": test_dir,
            "user_config": {"allow_all_users": True},
            "output_annotation_dir": os.path.join(test_dir, "annotation_output"),
            "output_annotation_format": "json",
            "live_agent": {
                "endpoint_type": "ollama_vision",
                "ai_config": {
                    "model": "gemma3:4b",
                    "base_url": "http://localhost:11434",
                    "max_tokens": 512,
                    "temperature": 0.3,
                    "timeout": 120,
                },
                "max_steps": 2,
                "step_delay": 0.3,
                "viewport": {"width": 800, "height": 600},
            },
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "rating",
                    "description": "Rate it",
                    "labels": [{"name": "Good"}, {"name": "Bad"}],
                }
            ],
        }

        config_path = os.path.join(test_dir, "config.yaml")
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        server = FlaskTestServer(config=config_path)
        if not server.start():
            pytest.fail("Failed to start Flask server for SSE test")

        request.cls.server = server
        yield server
        server.stop()

    def test_sse_stream_receives_events(self, flask_server):
        """Connect to SSE stream and verify events arrive."""
        s = requests.Session()
        base = flask_server.base_url
        s.post(f"{base}/register", data={"email": "sseuser", "pass": "pass"})
        s.post(f"{base}/auth", data={"email": "sseuser", "pass": "pass"})

        # Start session
        start_resp = s.post(
            f"{base}/api/live_agent/start",
            json={
                "task_description": "Describe this page",
                "start_url": "https://example.com",
                "instance_id": "sse_task",
            },
            timeout=30,
        )
        assert start_resp.status_code == 200
        sid = start_resp.json()["session_id"]

        # Connect to SSE stream
        sse_resp = s.get(
            f"{base}/api/live_agent/stream/{sid}",
            stream=True,
            timeout=120,
        )
        assert sse_resp.status_code == 200
        assert "text/event-stream" in sse_resp.headers.get("Content-Type", "")

        # Collect events
        event_types = set()
        event_count = 0
        for line in sse_resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            if line.startswith("event: "):
                etype = line[7:].strip()
                event_types.add(etype)
                event_count += 1
            # Stop after we see complete/error or enough events
            if "complete" in event_types or "error" in event_types:
                break
            if event_count > 30:
                break

        sse_resp.close()

        # Verify we got the expected event types
        assert "connected" in event_types, f"Missing 'connected' event. Got: {event_types}"
        # At minimum we expect connected + some agent events
        assert len(event_types) >= 2, f"Only got event types: {event_types}"

        # Cleanup
        s.post(f"{base}/api/live_agent/stop/{sid}", timeout=30)
        s.close()
