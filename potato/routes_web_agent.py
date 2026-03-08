"""
Web Agent Recording API Routes

Provides endpoints for the web agent creation mode:
- Session management (start/end recording sessions)
- Step saving (capture individual interaction steps)
- Screenshot capture and storage
"""

import json
import logging
import os
import threading
import time
import uuid
from typing import Dict, Any

from flask import Blueprint, request, jsonify, current_app, session as flask_session, redirect, url_for

logger = logging.getLogger(__name__)

web_agent_bp = Blueprint('web_agent', __name__)

# In-memory session storage (per-process), protected by a lock
_sessions: Dict[str, Dict[str, Any]] = {}
_sessions_lock = threading.Lock()

# Session TTL: 2 hours
_SESSION_TTL_SECONDS = 2 * 60 * 60


def _login_required(f):
    """Require user authentication for web agent routes."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'username' not in flask_session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def _cleanup_expired_sessions():
    """Remove sessions older than TTL. Must be called with _sessions_lock held."""
    now = time.time()
    expired = [
        sid for sid, sdata in _sessions.items()
        if now - sdata.get('start_time', 0) > _SESSION_TTL_SECONDS
    ]
    for sid in expired:
        del _sessions[sid]
        logger.info(f"Cleaned up expired recording session {sid}")


@web_agent_bp.route('/api/web_agent/start_session', methods=['POST'])
@_login_required
def start_session():
    """Initialize a new web agent recording session."""
    data = request.get_json(silent=True) or {}
    url = data.get('url', '')

    session_id = str(uuid.uuid4())[:8]

    # Create screenshots directory
    task_dir = current_app.config.get('task_dir', '.')
    screenshots_dir = os.path.join(task_dir, 'recordings', session_id, 'screenshots')
    os.makedirs(screenshots_dir, exist_ok=True)

    with _sessions_lock:
        _cleanup_expired_sessions()
        _sessions[session_id] = {
            'id': session_id,
            'start_url': url,
            'start_time': time.time(),
            'steps': [],
            'screenshots_dir': screenshots_dir,
        }

    logger.info(f"Started recording session {session_id} for {url}")

    return jsonify({
        'session_id': session_id,
        'status': 'recording',
    })


@web_agent_bp.route('/api/web_agent/save_step', methods=['POST'])
@_login_required
def save_step():
    """Save a recorded interaction step."""
    data = request.get_json(silent=True) or {}
    session_id = data.get('session_id', '')
    step = data.get('step', {})

    with _sessions_lock:
        session = _sessions.get(session_id)
        if not session:
            return jsonify({'error': 'Unknown session'}), 404

        session['steps'].append(step)
        step_count = len(session['steps'])

    return jsonify({
        'status': 'ok',
        'step_count': step_count,
    })


@web_agent_bp.route('/api/web_agent/save_screenshot', methods=['POST'])
@_login_required
def save_screenshot():
    """Upload a screenshot for a recording step."""
    session_id = request.form.get('session_id', request.args.get('session_id', ''))
    step_index = request.form.get('step_index', request.args.get('step_index', '0'))

    with _sessions_lock:
        session = _sessions.get(session_id)
        if not session:
            return jsonify({'error': 'Unknown session'}), 404
        screenshots_dir = session.get('screenshots_dir', '')

    if not screenshots_dir:
        return jsonify({'error': 'No screenshots directory'}), 500

    # Handle file upload
    if 'screenshot' in request.files:
        file = request.files['screenshot']
        filename = f'step_{int(step_index):03d}.png'
        filepath = os.path.join(screenshots_dir, filename)
        file.save(filepath)
        rel_path = os.path.relpath(filepath, current_app.config.get('task_dir', '.'))
        return jsonify({'screenshot_url': rel_path, 'status': 'ok'})

    # Handle base64 data
    data = request.get_json(silent=True) or {}
    b64_data = data.get('screenshot_data', '')
    if b64_data:
        import base64
        filename = f'step_{int(step_index):03d}.png'
        filepath = os.path.join(screenshots_dir, filename)
        with open(filepath, 'wb') as f:
            f.write(base64.b64decode(b64_data))
        rel_path = os.path.relpath(filepath, current_app.config.get('task_dir', '.'))
        return jsonify({'screenshot_url': rel_path, 'status': 'ok'})

    return jsonify({'error': 'No screenshot data'}), 400


@web_agent_bp.route('/api/web_agent/end_session', methods=['POST'])
@_login_required
def end_session():
    """Finalize a recording session and save trace data."""
    data = request.get_json(silent=True) or {}
    session_id = data.get('session_id', '')
    final_steps = data.get('steps', None)

    with _sessions_lock:
        session = _sessions.get(session_id)
        if not session:
            return jsonify({'error': 'Unknown session'}), 404

        # Use provided steps or session's accumulated steps
        steps = final_steps if final_steps is not None else list(session['steps'])
        start_url = session.get('start_url', '')

        # Clean up session
        del _sessions[session_id]

    # Build trace data
    trace = {
        'id': f'recording_{session_id}',
        'task_description': data.get('task_description', ''),
        'site': start_url,
        'steps': steps,
    }

    # Save to file
    task_dir = current_app.config.get('task_dir', '.')
    recordings_dir = os.path.join(task_dir, 'recordings', session_id)
    os.makedirs(recordings_dir, exist_ok=True)
    trace_path = os.path.join(recordings_dir, 'trace.json')

    with open(trace_path, 'w', encoding='utf-8') as f:
        json.dump(trace, f, indent=2)

    logger.info(f"Ended recording session {session_id}, saved {len(steps)} steps")

    return jsonify({
        'status': 'saved',
        'trace_path': trace_path,
        'step_count': len(steps),
    })
