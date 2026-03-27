"""
Live Coding Agent Routes

REST API endpoints for controlling live coding agent sessions.
Mirrors routes_live_agent.py but adapted for coding agents.
"""

import json
import logging
import os
import queue
import time
from flask import Blueprint, Response, jsonify, request, stream_with_context

logger = logging.getLogger(__name__)

live_coding_agent_bp = Blueprint("live_coding_agent", __name__)


def _get_manager():
    from .coding_agent_runner_manager import CodingAgentRunnerManager
    return CodingAgentRunnerManager.get_instance()


def _get_config():
    from .server_utils.config_module import config
    return config


@live_coding_agent_bp.route("/api/live_coding_agent/start", methods=["POST"])
def start_session():
    """Start a new coding agent session."""
    from .coding_agent_runner import CodingAgentConfig

    data = request.get_json() or {}
    task_description = data.get("task_description", "")
    instance_id = data.get("instance_id", "")
    user_id = data.get("user_id", request.cookies.get("user_id", "anonymous"))

    if not task_description:
        return jsonify({"error": "task_description is required"}), 400

    config = _get_config()
    agent_config = CodingAgentConfig.from_config(config)

    # Override with request config if provided
    if "config" in data:
        req_config = data["config"]
        if "backend_type" in req_config:
            agent_config.backend_type = req_config["backend_type"]
        if "ai_config" in req_config:
            agent_config.ai_config.update(req_config["ai_config"])
        if "working_dir" in req_config:
            agent_config.working_dir = req_config["working_dir"]

    # Set up trace directory
    task_dir = config.get("task_dir", ".")
    trace_dir = os.path.join(
        task_dir, "live_coding_sessions",
        f"{user_id}_{instance_id}_{int(time.time())}",
    )

    manager = _get_manager()
    runner = manager.create_session(user_id, instance_id, agent_config, trace_dir)

    try:
        runner.start(task_description)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "session_id": runner.session_id,
        "state": runner.state.value,
        "backend": agent_config.backend_type,
    })


@live_coding_agent_bp.route("/api/live_coding_agent/stream/<session_id>")
def stream_events(session_id):
    """SSE event stream for a coding agent session."""
    manager = _get_manager()
    runner = manager.get_session(session_id)
    if not runner:
        return jsonify({"error": "Session not found"}), 404

    event_queue = queue.Queue()

    def listener(event_type, data):
        event_queue.put((event_type, data))

    runner.add_listener(listener)

    def generate():
        # Send initial connection event
        yield _sse_event("connected", {
            "session_id": session_id,
            "state": runner.state.value,
            "turns": len(runner.get_structured_turns()),
        })

        try:
            while True:
                try:
                    event_type, data = event_queue.get(timeout=30)
                    yield _sse_event(event_type, data)

                    if event_type in ("complete", "error"):
                        break
                except queue.Empty:
                    # Keepalive
                    yield ": keepalive\n\n"
        finally:
            runner.remove_listener(listener)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@live_coding_agent_bp.route("/api/live_coding_agent/pause/<session_id>", methods=["POST"])
def pause_session(session_id):
    manager = _get_manager()
    runner = manager.get_session(session_id)
    if not runner:
        return jsonify({"error": "Session not found"}), 404
    runner.pause()
    return jsonify({"state": runner.state.value})


@live_coding_agent_bp.route("/api/live_coding_agent/resume/<session_id>", methods=["POST"])
def resume_session(session_id):
    manager = _get_manager()
    runner = manager.get_session(session_id)
    if not runner:
        return jsonify({"error": "Session not found"}), 404
    runner.resume()
    return jsonify({"state": runner.state.value})


@live_coding_agent_bp.route("/api/live_coding_agent/instruct/<session_id>", methods=["POST"])
def instruct_session(session_id):
    manager = _get_manager()
    runner = manager.get_session(session_id)
    if not runner:
        return jsonify({"error": "Session not found"}), 404

    data = request.get_json() or {}
    instruction = data.get("instruction", "")
    if not instruction:
        return jsonify({"error": "instruction is required"}), 400

    runner.inject_instruction(instruction)
    return jsonify({"state": runner.state.value, "instruction": instruction})


@live_coding_agent_bp.route("/api/live_coding_agent/stop/<session_id>", methods=["POST"])
def stop_session(session_id):
    manager = _get_manager()
    runner = manager.get_session(session_id)
    if not runner:
        return jsonify({"error": "Session not found"}), 404
    runner.stop()
    return jsonify({
        "state": runner.state.value,
        "trace": runner.get_trace(),
    })


@live_coding_agent_bp.route("/api/live_coding_agent/state/<session_id>")
def get_state(session_id):
    manager = _get_manager()
    runner = manager.get_session(session_id)
    if not runner:
        return jsonify({"error": "Session not found"}), 404
    return jsonify(runner.get_state_summary())


@live_coding_agent_bp.route("/api/live_coding_agent/trace/<session_id>")
def get_trace(session_id):
    manager = _get_manager()
    runner = manager.get_session(session_id)
    if not runner:
        return jsonify({"error": "Session not found"}), 404
    return jsonify(runner.get_trace())


@live_coding_agent_bp.route("/api/live_coding_agent/sessions")
def list_sessions():
    manager = _get_manager()
    return jsonify({"sessions": manager.list_sessions()})


def _sse_event(event_type: str, data: dict) -> str:
    """Format a Server-Sent Event."""
    json_data = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {json_data}\n\n"
