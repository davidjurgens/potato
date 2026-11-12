"""The external-backend protocol: an agent pulls work from Potato.

Pull, not push. The machine with the GPU polls this server, so it needs no
inbound port, no firewall rule and no reverse tunnel of its own. Cancellation
travels the same way, in the response to the agent's next ``/progress`` post,
never as a call into the agent.

Two kinds of agent use these routes:

* one that Potato started over ssh for a single run, holding a token minted
  for that run (see :class:`potato.training.launchers.SSHLauncher`);
* one someone started by hand with ``potato training agent``, holding the
  token ``potato training register`` issued for its backend name.

Routes, all under ``/api/training``:

=======  ==============================  =====================================
POST     /backends/register              admin API key; issues an agent token
POST     /backends/<name>/heartbeat      liveness while idle
GET      /jobs/next?wait=30              long-poll; 200 with a job, or 204
GET      /jobs/<id>                      the job, its spec and cancel flag
GET      /jobs/<id>/bundle               the bundle as tar.gz, media included
POST     /jobs/<id>/progress             ``{"events": [...]}``, v1 events
POST     /jobs/<id>/predictions          ``predictions.jsonl`` as NDJSON
POST     /jobs/<id>/complete             exit code and final events
=======  ==============================  =====================================

The ``spec`` a job carries is the ``spec.json`` the local worker reads. An
agent rewrites its two path fields, ``bundle_dir`` and ``workdir``, to where it
unpacked the bundle, and runs ``potato.training.worker`` on it unchanged.
"""

from __future__ import annotations

import gzip
import logging
import os
import tarfile
import threading
from typing import Any, Dict, Optional, Tuple

from flask import Blueprint, jsonify, request, send_file

logger = logging.getLogger(__name__)

training_api_bp = Blueprint("training_api", __name__,
                            url_prefix="/api/training")

#: Upload ceiling for predictions.jsonl, in megabytes.
DEFAULT_MAX_PREDICTIONS_MB = 512

_BUNDLE_LOCK = threading.Lock()


def _config():
    from potato.server_utils.config_module import config
    return config


def _manager():
    from potato.training.manager import get_training_manager
    return get_training_manager()


def _error(message: str, status: int):
    return jsonify({"error": message}), status


def _token() -> str:
    header = request.headers.get("Authorization", "") or ""
    if header.startswith("Bearer "):
        return header[len("Bearer "):].strip()
    return (request.headers.get("X-Potato-Training-Token") or "").strip()


def _identity() -> Tuple[Optional[Dict[str, Any]], Any]:
    """``(identity, None)`` for a valid token, else ``(None, response)``.

    A run's launch token is checked first and only against the job it was
    minted for. Anything else must be a registered agent's token.
    """
    manager = _manager()
    if manager is None:
        return None, _error("Training is not enabled", 404)
    token = _token()
    if not token:
        return None, _error("A bearer token is required", 401)

    job = manager.current_job()
    if job is not None and job.accepts_launch_token(token):
        return {"backend": job.backend, "launch_job": job.run_id}, None

    from potato.training import store
    try:
        name = store.backend_for_token(_config(), token)
    except Exception:
        logger.exception("Could not check a training token")
        name = None
    if name is None:
        return None, _error("Invalid token", 401)
    return {"backend": name, "launch_job": None}, None


def _job(identity: Dict[str, Any], run_id: str):
    """The job *identity* may act on, or an error response.

    404 rather than 403 for a job that exists but is someone else's, so a
    token cannot be used to probe which run ids are live.
    """
    job = _manager().current_job(run_id)
    if job is None:
        return None, _error("No such job: %s" % run_id, 404)
    if identity["launch_job"]:
        if identity["launch_job"] != run_id:
            return None, _error("No such job: %s" % run_id, 404)
    elif job.backend != identity["backend"] or job.backend_type != "agent":
        return None, _error("No such job: %s" % run_id, 404)
    elif job.state == "queued":
        return None, _error("Claim the job with GET /api/training/jobs/next "
                            "first", 409)
    return job, None


def _agent_info() -> Dict[str, Any]:
    body = request.get_json(silent=True) if request.is_json else None
    info = dict(body.get("agent") or {}) if isinstance(body, dict) else {}
    for key in ("host", "version", "device"):
        if request.args.get(key):
            info[key] = request.args.get(key)
    return {k: str(v)[:200] for k, v in info.items()}


# ------------------------------------------------------------- backends

@training_api_bp.route("/backends/register", methods=["POST"])
def register_backend():
    """Issue a token for a manually started agent.

    Needs the admin API key. The name must be a backend of ``type: agent``
    in the config, so a token cannot be minted for a backend nobody has
    agreed to run work on.
    """
    if _manager() is None:
        return _error("Training is not enabled", 404)
    from potato.server_utils.admin_key import validate_admin_api_key

    key = request.headers.get("X-API-Key") or ""
    if not validate_admin_api_key(key, _config()):
        return _error("The admin API key is required", 401)

    body = request.get_json(silent=True) or {}
    name = str(body.get("name") or "").strip()
    from potato.training.backends import load_backends
    backend = load_backends(_config()).get(name)
    if backend is None or backend.type != "agent":
        return _error("No backend named %r with type: agent under "
                      "model_training.backends" % name, 400)

    from potato.training import store
    token = store.register_backend(_config(), name)
    return jsonify({"backend": name, "token": token})


@training_api_bp.route("/backends/<name>/heartbeat", methods=["POST"])
def heartbeat(name):
    identity, failure = _identity()
    if failure:
        return failure
    if identity["backend"] != name or identity["launch_job"]:
        return _error("This token is not for backend %r" % name, 403)
    from potato.training import store
    store.touch_backend(_config(), name, _agent_info() or None)
    job = _manager().current_job()
    pending = bool(job and job.backend == name and job.state == "queued")
    return jsonify({"ok": True, "job_pending": pending})


# ----------------------------------------------------------------- jobs

@training_api_bp.route("/jobs/next", methods=["GET"])
def next_job():
    identity, failure = _identity()
    if failure:
        return failure
    if identity["launch_job"]:
        # A launched agent already knows its job.
        job = _manager().current_job(identity["launch_job"])
        if job is None:
            return "", 204
        _manager().touch_job(job, _agent_info())
        return jsonify(job.public())

    try:
        wait = float(request.args.get("wait", 0))
    except ValueError:
        wait = 0.0
    from potato.training import store
    store.touch_backend(_config(), identity["backend"], _agent_info() or None)
    job = _manager().claim_job(identity["backend"], _agent_info(), wait)
    if job is None:
        return "", 204
    return jsonify(job.public())


@training_api_bp.route("/jobs/<run_id>", methods=["GET"])
def get_job(run_id):
    identity, failure = _identity()
    if failure:
        return failure
    job, failure = _job(identity, run_id)
    if failure:
        return failure
    _manager().touch_job(job, _agent_info())
    return jsonify(job.public())


@training_api_bp.route("/jobs/<run_id>/bundle", methods=["GET"])
def get_bundle(run_id):
    identity, failure = _identity()
    if failure:
        return failure
    job, failure = _job(identity, run_id)
    if failure:
        return failure
    _manager().touch_job(job)

    bundle_dir = job.spec.get("bundle_dir", "")
    if not os.path.isdir(bundle_dir):
        return _error("The bundle for this job is gone", 410)
    archive = os.path.join(job.run_dir, "bundle.tar.gz")
    with _BUNDLE_LOCK:
        if not os.path.isfile(archive):
            _pack(bundle_dir, archive)
    return send_file(archive, mimetype="application/gzip",
                     as_attachment=True,
                     download_name="bundle-%s.tar.gz" % run_id)


def _pack(bundle_dir: str, archive: str) -> None:
    """Tar the bundle with media symlinks replaced by the files.

    The bundle links media rather than copying it, which is right on this
    machine and useless on another one.
    """
    partial = archive + ".partial"
    with tarfile.open(partial, "w:gz", dereference=True) as tar:
        for entry in sorted(os.listdir(bundle_dir)):
            tar.add(os.path.join(bundle_dir, entry), arcname=entry)
    os.replace(partial, archive)


@training_api_bp.route("/jobs/<run_id>/progress", methods=["POST"])
def post_progress(run_id):
    identity, failure = _identity()
    if failure:
        return failure
    job, failure = _job(identity, run_id)
    if failure:
        return failure
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("events", []),
                                                    list):
        return _error('Expected a JSON object {"events": [...]}', 400)
    events = [e for e in body.get("events", []) if isinstance(e, dict)]
    return jsonify(_manager().job_progress(job, events))


@training_api_bp.route("/jobs/<run_id>/predictions", methods=["POST"])
def post_predictions(run_id):
    """Receive predictions.jsonl. Replaces any earlier upload for the job.

    Written to a temporary name and renamed, so write-back never reads half
    a file, which is the reason predictions travel as a file at all.
    """
    identity, failure = _identity()
    if failure:
        return failure
    job, failure = _job(identity, run_id)
    if failure:
        return failure
    _manager().touch_job(job)

    training = _config().get("model_training", {}) or {}
    limit = int(training.get("max_predictions_mb",
                             DEFAULT_MAX_PREDICTIONS_MB)) * 1024 * 1024
    from potato.training.worker import PREDICTIONS_FILE

    artifacts = os.path.join(job.run_dir, "artifacts")
    os.makedirs(artifacts, exist_ok=True)
    target = os.path.join(artifacts, PREDICTIONS_FILE)
    partial = target + ".partial"

    stream = request.stream
    if (request.headers.get("Content-Encoding") or "").lower() == "gzip":
        stream = gzip.GzipFile(fileobj=request.stream)

    written = 0
    try:
        with open(partial, "wb") as fh:
            while True:
                chunk = stream.read(1 << 16)
                if not chunk:
                    break
                written += len(chunk)
                if written > limit:
                    raise ValueError("over the %d MB limit"
                                     % (limit // (1024 * 1024)))
                fh.write(chunk)
    except (ValueError, OSError, EOFError) as exc:
        try:
            os.remove(partial)
        except OSError:
            pass
        return _error("Could not store predictions: %s" % exc, 413
                      if "limit" in str(exc) else 400)
    os.replace(partial, target)
    return jsonify({"ok": True, "bytes": written})


@training_api_bp.route("/jobs/<run_id>/complete", methods=["POST"])
def post_complete(run_id):
    identity, failure = _identity()
    if failure:
        return failure
    job, failure = _job(identity, run_id)
    if failure:
        return failure
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _error("Expected a JSON object", 400)
    return jsonify(_manager().complete_job(job, body))
