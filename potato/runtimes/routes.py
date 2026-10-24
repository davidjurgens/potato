"""
Routes for runtime phase pages.

``GET  /runtime/<page>/study``               the study file, served as-is
``GET  /runtime/<page>/study/<path>``        a file of a study that is a directory
``GET  /runtime/<page>/script/<idx>.js``     one of the page's extra_scripts
``GET  /runtime/<page>/assets/<path>``       a file from the page's assets_dir
``POST /api/runtime/trial``                  incremental save of one trial
``POST /api/runtime/finish``                 the run's data; advances the phase
``GET  /runtime/<page>/stimulus/<n>.wav``    a sound the server made for trial n
``POST /runtime/<page>/continue``            leave a page already completed

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

#: Ceiling for reading a body before the page's own max_data_mb is known.
READ_CEILING = 200 * 1024 * 1024

#: Sent with every file a participant could open on its own (an SVG, an
#: HTML file in a study directory): nothing in it may run script on this
#: origin outside the runtime page.
SANDBOX_CSP = ("default-src 'none'; img-src 'self' data:; media-src 'self'; "
               "style-src 'unsafe-inline'; font-src 'self'; sandbox")


def _config() -> dict:
    return _registered_config


def _spec(page: str):
    from potato.runtimes.phase import runtime_pages
    return runtime_pages(_config()).get(page)


def _session_user():
    from flask import session
    from potato.user_state_management import get_user_state_manager
    username = session.get("username")
    if not username:
        return None, None
    usm = get_user_state_manager()
    return username, usm.get_user_state(username)


def _no_store(response, *, sandbox: bool = False):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    if sandbox:
        response.headers["Content-Security-Policy"] = SANDBOX_CSP
    return response


def _serve_js(path: str):
    from flask import send_file
    return _no_store(send_file(path, mimetype="text/javascript", max_age=0))


def _safe_file(base: str, path: str, allowed_exts) -> str:
    """Absolute path of ``path`` inside ``base``, or abort(404)."""
    from flask import abort
    from potato.server_utils.config_module import ConfigSecurityError, validate_path_security
    if not path or os.path.splitext(path)[1].lower() not in allowed_exts:
        abort(404)
    try:
        resolved = validate_path_security(os.path.join(base, path), base)
    except ConfigSecurityError:
        abort(404)
    if not os.path.isfile(resolved):
        abort(404)
    return resolved


def runtime_main(page: str):
    from flask import abort, send_file
    from potato.runtimes.registry import get_adapter
    spec = _spec(page)
    username, _ = _session_user()
    if spec is None or username is None or not spec.get("main"):
        abort(404)
    adapter = get_adapter(spec["kind"])
    if adapter.main_is_dir:
        abort(404)
    if adapter.main_mimetype == "text/javascript":
        return _serve_js(spec["main"])
    return _no_store(send_file(spec["main"], mimetype=adapter.main_mimetype, max_age=0),
                     sandbox=True)


def runtime_main_file(page: str, path: str):
    """A file inside a study that is a directory (an unzipped export)."""
    from flask import abort, send_file
    from potato.runtimes.registry import get_adapter
    spec = _spec(page)
    username, _ = _session_user()
    if spec is None or username is None:
        abort(404)
    adapter = get_adapter(spec["kind"])
    if not adapter.main_is_dir:
        abort(404)
    resolved = _safe_file(spec["main"], path, adapter.dir_extensions)
    if resolved.endswith((".js", ".mjs")):
        return _serve_js(resolved)
    return _no_store(send_file(resolved, max_age=0), sandbox=True)


def runtime_extra_script(page: str, idx: int):
    from flask import abort
    spec = _spec(page)
    username, _ = _session_user()
    if spec is None or username is None or not (0 <= idx < len(spec["extra_scripts"])):
        abort(404)
    return _serve_js(spec["extra_scripts"][idx])


def runtime_asset(page: str, path: str):
    from flask import abort, send_file
    from potato.runtimes.phase import ASSET_EXTENSIONS
    from potato.runtimes.registry import get_adapter
    spec = _spec(page)
    username, _ = _session_user()
    if spec is None or username is None or not spec.get("assets_dir") or not path:
        abort(404)
    allowed = ASSET_EXTENSIONS | get_adapter(spec["kind"]).extra_asset_extensions
    resolved = _safe_file(spec["assets_dir"], path, allowed)
    response = send_file(resolved)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = SANDBOX_CSP
    return response


def _read_limited_json(limit: int):
    """(raw bytes, parsed JSON or None), reading at most ``limit + 1`` bytes.

    A chunked request has no Content-Length, so a header check alone lets it
    through; reading past the limit by one byte is how the caller tells.
    Cached on ``flask.g`` so the body is read once per request.
    """
    from flask import g, request
    cached = getattr(g, "_potato_runtime_body", None)
    if cached is None:
        raw = request.stream.read(min(limit, READ_CEILING) + 1)
        try:
            import json as _json
            body = _json.loads(raw.decode("utf-8")) if raw else None
        except (ValueError, UnicodeDecodeError):
            body = None
        cached = (raw, body)
        g._potato_runtime_body = cached
    return cached


def _api_preconditions(max_bytes_default: int = 10 * 1024 * 1024):
    """(username, user_state, body, page, spec) or a ready error response."""
    from flask import jsonify, request
    from potato.phase import UserPhase
    from potato.runtimes.phase import run_summary
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
                               "message": "That task page is not your current page"}), 409)
    if body.get("run_id") != run_summary(user_state, page).get("run_id"):
        return None, (jsonify({"status": "error",
                               "message": "This run was replaced by a newer one; reload the page"}), 409)
    return (username, user_state, body, page, spec), None


def _trial_list(value):
    return isinstance(value, list) and all(isinstance(t, dict) for t in value)


def runtime_trial():
    """Store one trial as it finishes (``save: incremental``)."""
    from flask import jsonify
    from potato.runtimes import store
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


def runtime_finish():
    """The whole run's data. Marks the page complete and moves the participant on."""
    import time
    from flask import jsonify, request, url_for
    from potato.runtimes import store
    from potato.runtimes.phase import page_summary, run_summary, runtime_pages
    from potato.user_state_management import get_user_state_manager
    # A retry of a finish that already went through (the response was lost):
    # answer as if it had just succeeded rather than with "not your page".
    username, user_state = _session_user()
    _limit = max([spec_["max_bytes"] for spec_ in runtime_pages(_config()).values()] or [0])
    _raw, body = (_read_limited_json(_limit) if request.is_json and _limit else (b"", None))
    if (user_state is not None and isinstance(body, dict)
            and request.headers.get("X-Potato-Navigation") == "1"):
        done = page_summary(user_state, str(body.get("page")))
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
    from potato.runtimes.registry import get_adapter
    trials = get_adapter(spec["kind"]).finalize_trials(spec, trials, user_state)
    if not trials:
        logger.warning("%s run %s for %s on '%s' finished with no trials; "
                       "check that the study records data", spec["kind"], body["run_id"],
                       username, page)
    store.save_trials(task_dir, body["run_id"], trials, complete=True, interaction=interaction)

    # What the run means for the rest of the study (a headphone check's
    # pass), read by show_when / exit_when through collect_flow_answers.
    from potato.server_utils.phase_flow import flow_record
    answers = get_adapter(spec["kind"]).summarize(spec, trials)
    if answers:
        flow_record(user_state).setdefault("runtime_answers", {}).update(answers)

    summary = run_summary(user_state, page)
    summary.update({"status": "complete", "n_trials": len(trials), "finished_at": time.time()})
    usm = get_user_state_manager()
    usm.advance_phase(username)
    usm.save_user_state(user_state)
    logger.info("%s run %s for %s on '%s' stored (%d trials)",
                spec["kind"], body["run_id"], username, page, len(trials))
    return jsonify({"status": "ok", "redirect": url_for("home")})


def runtime_stimulus(page: str, idx: int):
    """A sound the server made for one trial of the participant's current run
    (the headphone check), so the page never holds the answer."""
    from flask import Response, abort
    from potato.runtimes.registry import get_adapter
    username, user_state = _session_user()
    spec = _spec(page)
    if username is None or spec is None:
        abort(404)
    _, current = user_state.get_current_phase_and_page()
    if current != page:
        abort(409)
    data = get_adapter(spec["kind"]).stimulus(spec, user_state, idx)
    if data is None:
        abort(404)
    return _no_store(Response(data, mimetype="audio/wav"))


def runtime_continue(page: str):
    """Leave a completed task page (reached again by back navigation)."""
    from flask import redirect, url_for
    from potato.runtimes.phase import is_complete
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


def runtime_return(page: str):
    """Back from a ``type: external`` task: store what it sent and move on."""
    import time
    from flask import redirect, render_template, request, url_for
    from potato.runtimes import store
    from potato.runtimes.phase import is_complete, run_summary
    from potato.runtimes.registry import get_adapter
    from potato.server_utils.phase_flow import flow_record
    from potato.user_state_management import get_user_state_manager
    spec = _spec(page)
    username, user_state = _session_user()
    if username is None:
        return redirect(url_for("home"))
    adapter = get_adapter(spec["kind"]) if spec else None
    if adapter is None or not callable(getattr(adapter, "link", None)):
        return redirect(url_for("home"))
    summary = run_summary(user_state, page)
    run_id = request.args.get("run", "")
    if is_complete(user_state, page) and summary.get("run_id") == run_id:
        return redirect(url_for("home"))          # a reload of the return link
    _, current = user_state.get_current_phase_and_page()
    if current != page or not run_id or run_id != summary.get("run_id"):
        logger.warning("%s came back to '%s' with a run that is not their current one",
                       username, page)
        return (render_template("runtime_return_refused.html",
                                annotation_task_name=_config().get("annotation_task_name", ""),
                                home_url=url_for("home")), 409)
    check = getattr(adapter, "return_problem", None)
    problem = check(spec, run_id, request.args) if callable(check) else None
    if problem:
        logger.warning("%s came back to '%s' and was refused: %s", username, page, problem)
        return (render_template("runtime_return_refused.html",
                                annotation_task_name=_config().get("annotation_task_name", ""),
                                home_url=url_for("home"), unsigned=True), 409)
    params = {p: request.args.get(p, "")[:500] for p in spec.get("return_params") or []
              if p in request.args}
    trials = [{"params": params, "returned_at": time.time()}]
    task_dir = _config().get("task_dir") or "."
    store.save_trials(task_dir, run_id, trials, complete=True)
    answers = adapter.summarize(spec, trials)
    flow_record(user_state).setdefault("runtime_answers", {}).update(answers)
    summary.update({"status": "complete", "n_trials": 1, "finished_at": time.time()})
    usm = get_user_state_manager()
    usm.advance_phase(username)
    usm.save_user_state(user_state)
    return redirect(url_for("home"))


def _add_page_headers(response):
    from flask import g
    csp = getattr(g, "potato_csp", None)
    if csp:
        response.headers["Content-Security-Policy"] = csp
    policy = getattr(g, "potato_permissions_policy", None)
    if policy:
        response.headers["Permissions-Policy"] = policy
    return response


_MOVED = {"timeline": "study", "assets": "assets", "script": "script", "continue": "continue"}


def jspsych_moved(page: str = "", rest: str = ""):
    """The jsPsych phase's URLs from before runtime phases (/jspsych/<page>/...,
    /api/jspsych/...): a 410 naming the new address, not a bare 404."""
    from flask import jsonify, request
    if request.path.startswith("/api/jspsych/"):
        new = "/api/runtime/" + request.path[len("/api/jspsych/"):]
    else:
        head, _, tail = rest.partition("/")
        head = head or "timeline"         # /jspsych/<page> itself was the timeline
        new = f"/runtime/{page}/{_MOVED.get(head, head)}" + (f"/{tail}" if tail else "")
    response = jsonify({"error": "This address moved when jsPsych pages became runtime pages.",
                        "moved_to": new})
    response.status_code = 410
    return response


def register_runtime_routes(app, config) -> None:
    global _registered_config
    _registered_config = config
    if "runtime_main" in app.view_functions:
        return
    app.add_url_rule("/runtime/<page>/study", "runtime_main", runtime_main)
    app.add_url_rule("/runtime/<page>/study/<path:path>", "runtime_main_file", runtime_main_file)
    app.add_url_rule("/runtime/<page>/script/<int:idx>.js", "runtime_extra_script",
                     runtime_extra_script)
    app.add_url_rule("/runtime/<page>/assets/<path:path>", "runtime_asset", runtime_asset)
    app.add_url_rule("/runtime/<page>/assets/", "runtime_asset_root", runtime_asset,
                     defaults={"path": ""})
    app.add_url_rule("/runtime/<page>/continue", "runtime_continue", runtime_continue,
                     methods=["POST"])
    app.add_url_rule("/runtime/<page>/return", "runtime_return", runtime_return)
    app.add_url_rule("/runtime/<page>/stimulus/<int:idx>.wav", "runtime_stimulus",
                     runtime_stimulus)
    app.add_url_rule("/api/runtime/trial", "runtime_trial", runtime_trial, methods=["POST"])
    app.add_url_rule("/api/runtime/finish", "runtime_finish", runtime_finish, methods=["POST"])
    app.add_url_rule("/jspsych/<page>/<path:rest>", "jspsych_moved", jspsych_moved,
                     methods=["GET", "POST"])
    app.add_url_rule("/jspsych/<page>", "jspsych_page_moved", jspsych_moved,
                     methods=["GET", "POST"], strict_slashes=False)
    app.add_url_rule("/api/jspsych/<path:rest>", "jspsych_api_moved", jspsych_moved,
                     methods=["GET", "POST"])
    app.after_request(_add_page_headers)
