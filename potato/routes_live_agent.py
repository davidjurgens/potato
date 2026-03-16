"""
Live Agent API Routes

Provides SSE streaming and REST control endpoints for the live agent interaction mode.
Annotators can observe an AI agent browse the web in real time, pause/resume it,
send instructions, or take over manual control.

Endpoints:
- POST /api/live_agent/start          - Create and start an agent session
- GET  /api/live_agent/stream/<id>    - SSE event stream
- POST /api/live_agent/pause/<id>     - Pause agent
- POST /api/live_agent/resume/<id>    - Resume agent
- POST /api/live_agent/instruct/<id>  - Send instruction to agent
- POST /api/live_agent/takeover/<id>  - Toggle manual control
- POST /api/live_agent/manual_action/<id> - Execute manual Playwright action
- POST /api/live_agent/stop/<id>      - Stop and save trace
- GET  /api/live_agent/screenshot/<id>/<step> - Serve screenshot
- GET  /api/live_agent/state/<id>     - Current state
"""

import json
import logging
import os
import time
from functools import wraps
from queue import Queue, Empty

from flask import (
    Blueprint,
    Response,
    current_app,
    jsonify,
    request,
    send_file,
    session as flask_session,
    redirect,
    url_for,
)

from potato.agent_runner import AgentConfig, AgentState
from potato.agent_runner_manager import AgentRunnerManager

logger = logging.getLogger(__name__)

live_agent_bp = Blueprint("live_agent", __name__)


def _login_required(f):
    """Require user authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "username" not in flask_session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def _get_manager() -> AgentRunnerManager:
    """Get the AgentRunnerManager singleton."""
    return AgentRunnerManager.get_instance()


def _get_runner(session_id: str):
    """Get an AgentRunner by session_id, or return (None, error_response)."""
    runner = _get_manager().get_session(session_id)
    if not runner:
        return None, (jsonify({"error": f"Unknown session: {session_id}"}), 404)
    return runner, None


@live_agent_bp.route("/api/live_agent/start", methods=["POST"])
@_login_required
def start_session():
    """
    Start a new live agent session.

    Request JSON:
        task_description: str - What the agent should do
        start_url: str - URL to begin at
        instance_id: str - Annotation instance ID
        config: dict (optional) - Override live_agent config

    Returns:
        session_id, state
    """
    data = request.get_json(silent=True) or {}
    task_description = data.get("task_description", "")
    start_url = data.get("start_url", "")
    instance_id = data.get("instance_id", "")
    user_id = flask_session.get("username", "anonymous")

    if not task_description:
        return jsonify({"error": "task_description is required"}), 400
    if not start_url:
        return jsonify({"error": "start_url is required"}), 400

    # Build config from server config + request overrides
    server_config = current_app.config.get("live_agent", {})
    override_config = data.get("config", {})
    merged = {**server_config, **override_config}
    agent_config = AgentConfig.from_config(merged)

    # Screenshot directory
    task_dir = current_app.config.get("task_dir", ".")
    session_key = f"{user_id}_{instance_id}_{int(time.time())}"
    screenshot_dir = os.path.join(
        task_dir, "live_sessions", session_key, "screenshots"
    )
    os.makedirs(screenshot_dir, exist_ok=True)

    try:
        manager = _get_manager()
        runner = manager.create_session(
            user_id=user_id,
            instance_id=instance_id,
            config=agent_config,
            screenshot_dir=screenshot_dir,
        )
        runner.start(task_description, start_url)

        return jsonify({
            "session_id": runner.session_id,
            "state": runner.state.value,
        })

    except RuntimeError as e:
        return jsonify({"error": str(e)}), 409


@live_agent_bp.route("/api/live_agent/stream/<session_id>")
@_login_required
def stream_events(session_id):
    """
    SSE event stream for a live agent session.

    Streams events: thinking, step, state_change, error, complete.
    Client connects with EventSource.
    """
    runner, error = _get_runner(session_id)
    if error:
        return error

    def event_stream():
        q = Queue()

        def listener(event):
            q.put(event)

        runner.add_listener(listener)

        try:
            # Send initial state
            yield _sse_format("connected", {
                "session_id": session_id,
                "state": runner.state.value,
                "step_count": runner.step_count,
            })

            while True:
                try:
                    event = q.get(timeout=30)
                    event_type = event.get("type", "message")
                    event_data = event.get("data", {})
                    yield _sse_format(event_type, event_data)

                    # Stop streaming when session completes
                    if event_type in ("complete", "error"):
                        break

                except Empty:
                    # Send keepalive
                    yield ": keepalive\n\n"

        finally:
            runner.remove_listener(listener)

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@live_agent_bp.route("/api/live_agent/pause/<session_id>", methods=["POST"])
@_login_required
def pause_session(session_id):
    """Pause the agent loop."""
    runner, error = _get_runner(session_id)
    if error:
        return error

    runner.pause()
    return jsonify(runner.get_state_summary())


@live_agent_bp.route("/api/live_agent/resume/<session_id>", methods=["POST"])
@_login_required
def resume_session(session_id):
    """Resume a paused agent."""
    runner, error = _get_runner(session_id)
    if error:
        return error

    runner.resume()
    return jsonify(runner.get_state_summary())


@live_agent_bp.route("/api/live_agent/instruct/<session_id>", methods=["POST"])
@_login_required
def instruct_session(session_id):
    """Send an instruction to the agent."""
    runner, error = _get_runner(session_id)
    if error:
        return error

    data = request.get_json(silent=True) or {}
    instruction = data.get("instruction", "")
    if not instruction:
        return jsonify({"error": "instruction is required"}), 400

    runner.inject_instruction(instruction)
    return jsonify(runner.get_state_summary())


@live_agent_bp.route("/api/live_agent/takeover/<session_id>", methods=["POST"])
@_login_required
def toggle_takeover(session_id):
    """Toggle manual takeover mode."""
    runner, error = _get_runner(session_id)
    if error:
        return error

    if runner.state == AgentState.TAKEOVER:
        runner.exit_takeover()
    else:
        runner.enter_takeover()

    return jsonify(runner.get_state_summary())


@live_agent_bp.route("/api/live_agent/manual_action/<session_id>", methods=["POST"])
@_login_required
def manual_action(session_id):
    """Execute a manual Playwright action during takeover mode."""
    runner, error = _get_runner(session_id)
    if error:
        return error

    if runner.state != AgentState.TAKEOVER:
        return jsonify({"error": "Not in takeover mode"}), 400

    data = request.get_json(silent=True) or {}
    action = data.get("action", {})
    if not action or "type" not in action:
        return jsonify({"error": "action with type is required"}), 400

    runner.submit_manual_action(action)
    return jsonify({"status": "submitted", "action": action})


@live_agent_bp.route("/api/live_agent/stop/<session_id>", methods=["POST"])
@_login_required
def stop_session(session_id):
    """Stop the agent and return the trace."""
    runner, error = _get_runner(session_id)
    if error:
        return error

    runner.stop()

    # Wait briefly for the agent to clean up
    import threading
    if runner._thread:
        runner._thread.join(timeout=5)

    trace = runner.get_trace()

    # Save trace to disk
    task_dir = current_app.config.get("task_dir", ".")
    trace_dir = os.path.join(task_dir, "live_sessions", session_id)
    os.makedirs(trace_dir, exist_ok=True)
    trace_path = os.path.join(trace_dir, "trace.json")
    with open(trace_path, "w", encoding="utf-8") as f:
        json.dump(trace, f, indent=2)

    return jsonify({
        "status": "stopped",
        "trace": trace,
        "trace_path": trace_path,
    })


@live_agent_bp.route("/api/live_agent/screenshot/<session_id>/<int:step>")
@_login_required
def get_screenshot(session_id, step):
    """Serve a screenshot file for a given step."""
    runner, error = _get_runner(session_id)
    if error:
        return error

    steps = runner.steps
    if step < 0 or step >= len(steps):
        return jsonify({"error": f"Step {step} not found"}), 404

    screenshot_path = steps[step].screenshot_path
    if not os.path.isfile(screenshot_path):
        return jsonify({"error": "Screenshot file not found"}), 404

    return send_file(screenshot_path, mimetype="image/png")


@live_agent_bp.route("/api/live_agent/state/<session_id>")
@_login_required
def get_state(session_id):
    """Get current session state."""
    runner, error = _get_runner(session_id)
    if error:
        return error

    return jsonify(runner.get_state_summary())


@live_agent_bp.route("/api/live_agent/sessions")
@_login_required
def list_sessions():
    """List all active live agent sessions (admin use)."""
    manager = _get_manager()
    return jsonify({"sessions": manager.list_sessions()})


def _sse_format(event_type: str, data: dict) -> str:
    """Format an SSE message."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
