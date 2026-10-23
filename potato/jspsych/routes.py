"""
Routes for `type: jspsych` phase pages.

``GET  /jspsych/<page>/timeline.js``        the author's timeline, served as-is
``GET  /jspsych/<page>/script/<idx>.js``     one of the page's extra_scripts
``GET  /jspsych/<page>/assets/<path>``       a file from the page's assets_dir
``POST /api/jspsych/trial``                  incremental save of one trial
``POST /api/jspsych/finish``                 the run's data; advances the phase
``POST /jspsych/<page>/continue``            leave a page already completed

The two API routes take JSON with the ``X-Potato-Navigation`` header. A
cross-site page cannot send either without a CORS preflight this server never
answers, so a session cookie alone is not enough to write data. Identity, phase
and page are stamped from the session, never taken from the body.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_registered_config: dict = {}

#: How far ahead of the stored trials an incremental save may land.
MAX_SEQ_GAP = 50


def _config() -> dict:
    return _registered_config


def _spec(page: str):
    from potato.jspsych.phase import jspsych_pages
    return jspsych_pages(_config()).get(page)


def _session_user():
    from flask import session
    from potato.user_state_management import get_user_state_manager
    username = session.get("username")
    if not username:
        return None, None
    usm = get_user_state_manager()
    return username, usm.get_user_state(username)


def _serve_js(path: str):
    from flask import send_file
    response = send_file(path, mimetype="text/javascript", max_age=0)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def jspsych_timeline(page: str):
    from flask import abort
    spec = _spec(page)
    username, user_state = _session_user()
    if spec is None or username is None:
        abort(404)
    return _serve_js(spec["timeline"])


def jspsych_extra_script(page: str, idx: int):
    from flask import abort
    spec = _spec(page)
    username, _ = _session_user()
    if spec is None or username is None or not (0 <= idx < len(spec["extra_scripts"])):
        abort(404)
    return _serve_js(spec["extra_scripts"][idx])


def jspsych_asset(page: str, path: str):
    from flask import abort, send_file
    from potato.jspsych.phase import ASSET_EXTENSIONS
    from potato.server_utils.config_module import ConfigSecurityError, validate_path_security
    spec = _spec(page)
    username, _ = _session_user()
    if spec is None or username is None or not spec.get("assets_dir") or not path:
        abort(404)
    if os.path.splitext(path)[1].lower() not in ASSET_EXTENSIONS:
        abort(404)
    base = spec["assets_dir"]
    try:
        resolved = validate_path_security(os.path.join(base, path), base)
    except ConfigSecurityError:
        abort(404)
    if not os.path.isfile(resolved):
        abort(404)
    response = send_file(resolved)
    response.headers["X-Content-Type-Options"] = "nosniff"
    # A stimulus file opened on its own (an SVG, say) must not run script on
    # this origin.
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; img-src 'self' data:; media-src 'self'; "
        "style-src 'unsafe-inline'; font-src 'self'; sandbox")
    return response


#: Ceiling for reading a body before the page's own max_data_mb is known.
READ_CEILING = 200 * 1024 * 1024


def _read_limited_json(limit: int):
    """(raw bytes, parsed JSON or None), reading at most ``limit + 1`` bytes.

    A chunked request has no Content-Length, so a header check alone lets it
    through; reading past the limit by one byte is how the caller tells.
    Cached on ``flask.g`` so the body is read once per request.
    """
    from flask import g, request
    cached = getattr(g, "_potato_jspsych_body", None)
    if cached is None:
        raw = request.stream.read(min(limit, READ_CEILING) + 1)
        try:
            import json as _json
            body = _json.loads(raw.decode("utf-8")) if raw else None
        except (ValueError, UnicodeDecodeError):
            body = None
        cached = (raw, body)
        g._potato_jspsych_body = cached
    return cached


def _api_preconditions(max_bytes_default: int = 10 * 1024 * 1024):
    """(username, user_state, body, page, spec) or a ready error response."""
    from flask import jsonify, request
    from potato.phase import UserPhase
    username, user_state = _session_user()
    if username is None or user_state is None:
        return None, (jsonify({"status": "error", "message": "No active session"}), 401)
    if request.headers.get("X-Potato-Navigation") != "1":
        return None, (jsonify({"status": "error", "message": "Missing navigation header"}), 400)
    if not request.is_json:
        return None, (jsonify({"status": "error", "message": "Expected JSON"}), 415)
    phase, page = user_state.get_current_phase_and_page()
    spec = _spec(page) if page else None
    max_bytes = (spec or {}).get("max_bytes", max_bytes_default)
    if request.content_length is not None and request.content_length > max_bytes:
        return None, (jsonify({"status": "error", "message": "Data exceeds max_data_mb"}), 413)
    raw, body = _read_limited_json(max_bytes)
    if len(raw) > max_bytes:
        return None, (jsonify({"status": "error", "message": "Data exceeds max_data_mb"}), 413)
    if not isinstance(body, dict):
        return None, (jsonify({"status": "error", "message": "Body must be a JSON object"}), 400)
    if spec is None or body.get("page") != page or phase in (UserPhase.DONE, UserPhase.ANNOTATION):
        return None, (jsonify({"status": "error",
                               "message": "That jsPsych page is not your current page"}), 409)
    from potato.jspsych.phase import run_summary
    if body.get("run_id") != run_summary(user_state, page).get("run_id"):
        return None, (jsonify({"status": "error",
                               "message": "This run was replaced by a newer one; reload the page"}), 409)
    return (username, user_state, body, page, spec), None


def _trial_list(value):
    return isinstance(value, list) and all(isinstance(t, dict) for t in value)


def jspsych_trial():
    """Store one trial as it finishes (``save: incremental``)."""
    from flask import jsonify
    from potato.jspsych import store
    ok, error = _api_preconditions()
    if error:
        return error
    username, user_state, body, page, spec = ok
    trial, seq = body.get("trial"), body.get("seq")
    if (not isinstance(trial, dict) or not isinstance(seq, int) or isinstance(seq, bool)
            or seq < 0):
        return jsonify({"status": "error", "message": "Expected {trial: {...}, seq: n}"}), 400
    task_dir = _config().get("task_dir") or "."
    run = store.get_run(task_dir, body["run_id"]) or {}
    if run.get("status") == "complete":
        return jsonify({"status": "ok", "ignored": "run already complete"})
    trials = run.get("trials") or []
    # Trials arrive in order, give or take a few still in flight. A far-off
    # seq would make the server allocate the gap.
    if seq > len(trials) + MAX_SEQ_GAP:
        return jsonify({"status": "error",
                        "message": f"seq {seq} is too far past the {len(trials)} trials stored"}), 400
    import json as _json
    if len(_json.dumps(trials)) + len(_json.dumps(trial)) > spec["max_bytes"]:
        return jsonify({"status": "error", "message": "Run data exceeds max_data_mb"}), 413
    if seq < len(trials):
        trials[seq] = trial
    else:
        trials.extend([{}] * (seq - len(trials)))
        trials.append(trial)
    store.save_trials(task_dir, body["run_id"], trials, complete=False)
    return jsonify({"status": "ok", "stored": len(trials)})


def jspsych_finish():
    """The whole run's data. Marks the page complete and moves the participant on."""
    from flask import jsonify, url_for
    from potato.jspsych import store
    from potato.jspsych.phase import run_summary
    from potato.user_state_management import get_user_state_manager
    import time
    from flask import request
    from potato.server_utils.phase_flow import flow_record
    # A retry of a finish that already went through (the response was lost):
    # answer as if it had just succeeded rather than with "not your page".
    username, user_state = _session_user()
    from potato.jspsych.phase import jspsych_pages
    _limit = max([spec_["max_bytes"] for spec_ in jspsych_pages(_config()).values()] or [0])
    _raw, body = (_read_limited_json(_limit) if request.is_json and _limit else (b"", None))
    if (user_state is not None and isinstance(body, dict)
            and request.headers.get("X-Potato-Navigation") == "1"):
        done = (flow_record(user_state).get("jspsych") or {}).get(str(body.get("page")), {})
        if done.get("status") == "complete" and done.get("run_id") == body.get("run_id"):
            return jsonify({"status": "ok", "redirect": url_for("home"), "duplicate": True})
    ok, error = _api_preconditions()
    if error:
        return error
    username, user_state, body, page, spec = ok
    trials = body.get("trials")
    if not _trial_list(trials):
        return jsonify({"status": "error", "message": "trials must be a list of objects"}), 400
    interaction = body.get("interaction")
    if interaction is not None and not _trial_list(interaction):
        interaction = None
    task_dir = _config().get("task_dir") or "."
    if not trials:
        logger.warning("jsPsych run %s for %s on '%s' finished with no trials; "
                       "check that the timeline records data", body["run_id"], username, page)
    store.save_trials(task_dir, body["run_id"], trials, complete=True, interaction=interaction)

    summary = run_summary(user_state, page)
    summary.update({"status": "complete", "n_trials": len(trials), "finished_at": time.time()})
    usm = get_user_state_manager()
    usm.advance_phase(username)
    usm.save_user_state(user_state)
    logger.info("jsPsych run %s for %s on '%s' stored (%d trials)",
                body["run_id"], username, page, len(trials))
    return jsonify({"status": "ok", "redirect": url_for("home")})


def jspsych_continue(page: str):
    """Leave a completed jsPsych page (reached again by back navigation)."""
    from flask import redirect, url_for
    from potato.jspsych.phase import is_complete
    from potato.user_state_management import get_user_state_manager
    username, user_state = _session_user()
    if username is None:
        return redirect(url_for("home"))
    _, current = user_state.get_current_phase_and_page()
    if current == page and is_complete(user_state, page):
        usm = get_user_state_manager()
        usm.advance_phase(username)
        usm.save_user_state(user_state)
    return redirect(url_for("home"))


def _add_csp_header(response):
    from flask import g
    csp = getattr(g, "potato_csp", None)
    if csp:
        response.headers["Content-Security-Policy"] = csp
    return response


def register_jspsych_routes(app, config) -> None:
    global _registered_config
    _registered_config = config
    if "jspsych_timeline" in app.view_functions:
        return
    app.add_url_rule("/jspsych/<page>/timeline.js", "jspsych_timeline", jspsych_timeline)
    app.add_url_rule("/jspsych/<page>/script/<int:idx>.js", "jspsych_extra_script",
                     jspsych_extra_script)
    app.add_url_rule("/jspsych/<page>/assets/<path:path>", "jspsych_asset", jspsych_asset)
    app.add_url_rule("/jspsych/<page>/assets/", "jspsych_asset_root", jspsych_asset,
                     defaults={"path": ""})
    app.add_url_rule("/jspsych/<page>/continue", "jspsych_continue", jspsych_continue,
                     methods=["POST"])
    app.add_url_rule("/api/jspsych/trial", "jspsych_trial", jspsych_trial, methods=["POST"])
    app.add_url_rule("/api/jspsych/finish", "jspsych_finish", jspsych_finish, methods=["POST"])
    app.after_request(_add_csp_header)
