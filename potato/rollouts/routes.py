"""
``GET /api/rollout/set?schema=<name>`` — the rollout set for the current item.

## Why the client asks for "the current item's set" and not for a path

Two things about a rollout set are decided *per annotator*, and neither can be
decided in the browser:

- **Panel order.** Preference judgements have a position bias, so the order is
  permuted per annotator. It has to be the same permutation every time that
  annotator sees that item, or their own second look disagrees with their
  first, and the stored answers become unpoolable. A client-side shuffle
  reshuffles on reload; a server-side one, seeded from the username, does not.
- **Blinding.** The generator names are on the item, and a client that received
  them would put them in a caption.

So the route reads the session's current instance itself and returns a manifest
that is already ordered and already stripped of display names.

**What blinding does and does not do.** The stream *ids* still travel, because
they are what annotations reference and what agreement joins on. So a
determined annotator can read ``value="gen_a"`` off a radio button in devtools.
This is deliberate. Blinding here defeats the bias that actually occurs —
seeing "GPT-video 2" next to a clip and rating it accordingly — and does not
defeat a trusted annotator who sets out to defeat it. Closing that hole would
mean storing opaque per-set aliases, which makes every exported annotation
uninterpretable without the config and buys protection against a threat that is
deliberate sabotage of the annotator's own study. If a project genuinely needs
the stronger property, give the streams non-revealing ids in the config
(``id: s1``, ``id: s2``) and keep the mapping outside Potato.

Registered from ``configure_routes()``: a bare ``@app.route`` decorator 404s
under ``potato start`` (invariant 4).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

#: The live config, captured at registration time. NOT re-imported per request:
#: see the note in potato/media/routes.py for what that breaks.
_registered_config: dict = {}


def _config() -> dict:
    return _registered_config


def _schema_config(name: str):
    """The annotation scheme block for ``name``, or None."""
    config = _config()
    schemes = config.get("annotation_schemes") or []
    if not schemes:
        for phase in (config.get("phases") or {}).values():
            if isinstance(phase, dict):
                schemes.extend(phase.get("annotation_schemes") or [])
    for scheme in schemes:
        if isinstance(scheme, dict) and scheme.get("name") == name:
            return scheme
    return None


def rollout_set():
    """Build and return the current item's rollout manifest."""
    from flask import jsonify, request, session

    from potato.rollouts.models import RolloutError, stable_order
    from potato.rollouts.registry import read_rollout_set

    if "username" not in session:
        return jsonify({"error": "No active session"}), 401
    username = session["username"]

    schema_name = request.args.get("schema") or ""
    scheme = _schema_config(schema_name)
    if scheme is None:
        return jsonify({
            "error": f"no annotation scheme named '{schema_name}' is "
                     f"configured"}), 404
    if (scheme.get("annotation_type") or "") != "rollout_evaluation":
        return jsonify({
            "error": f"'{schema_name}' is a "
                     f"{scheme.get('annotation_type')} schema, not "
                     f"rollout_evaluation"}), 400

    item_data, instance_id, error = _current_item(username)
    if error is not None:
        return error

    try:
        rollout = read_rollout_set(
            item_data, scheme, set_id=str(instance_id),
            resolve_manifest=_manifest_resolver())
    except RolloutError as exc:
        # 415, not 500: the request is well formed and the *data* cannot be
        # read, and the message names what to change.
        return jsonify({"error": str(exc)}), 415

    order = None
    if scheme.get("shuffle", True):
        # Keyed on the annotator and the item, so two annotators see different
        # orders and one annotator sees the same order twice. Including the
        # schema name as well would mean two rollout schemas on one page
        # disagreed about which panel is which, which is worse than the
        # position bias the shuffle exists to break.
        order = stable_order([s.stream_id for s in rollout.streams],
                             f"{username}\x00{instance_id}")

    return jsonify(rollout.to_json(order=order,
                                   blind=bool(scheme.get("blind", True))))


def rollout_judge():
    """
    Ask a vision model where each rollout stops making sense.

    POST, because it costs a model call per stream. Nothing here writes an
    annotation: a judge verdict is a prediction to be *scored against* the
    annotator's own marks, never merged into them. Writing it into the
    annotation would destroy the only thing it is for — an independent
    comparison.
    """
    from flask import jsonify, request, session

    from potato.rollouts.models import RolloutError
    from potato.rollouts.registry import read_rollout_set

    if "username" not in session:
        return jsonify({"error": "No active session"}), 401
    username = session["username"]

    data = request.get_json(silent=True) or {}
    schema_name = data.get("schema") or ""
    scheme = _schema_config(schema_name)
    if scheme is None or scheme.get("annotation_type") != "rollout_evaluation":
        return jsonify({
            "error": f"no rollout_evaluation schema named "
                     f"'{schema_name}'"}), 404

    item_data, instance_id, error = _current_item(username)
    if error is not None:
        return error

    try:
        rollout = read_rollout_set(item_data, scheme, set_id=str(instance_id),
                                   resolve_manifest=_manifest_resolver())
    except RolloutError as exc:
        return jsonify({"error": str(exc)}), 415

    endpoint = _visual_endpoint()
    if endpoint is None:
        return jsonify({
            "error": "No vision-capable AI endpoint is configured. Judging a "
                     "rollout needs a model that can see the frames."}), 503

    from potato.ai.rollout_judge import RolloutJudge

    types = [t.get("name") if isinstance(t, dict) else str(t)
             for t in (scheme.get("violation_types") or _default_types())]
    options = dict((scheme.get("ai_support") or {}).get("judge") or {})
    judge = RolloutJudge(_config(), endpoint, options)

    # Only the streams asked for. Judging every panel of a four-way comparison
    # is four model calls, and the usual question is about one generator.
    wanted = data.get("streams")
    predictions = []
    for stream in rollout.streams:
        if wanted and stream.stream_id not in wanted:
            continue
        path = _local_path(stream.url)
        if path is None:
            predictions.append({
                "stream_id": stream.stream_id,
                "error": (f"{stream.name} is not a local file, so its frames "
                          f"cannot be sampled.")})
            continue
        prediction = judge.judge_stream(
            path, stream.duration or rollout.duration, types,
            instance_id=str(instance_id), schema_name=schema_name,
            stream_id=stream.stream_id, prompt=rollout.prompt,
            prompt_version=data.get("prompt_version", ""))
        predictions.append(prediction.to_dict())

    return jsonify({"instance_id": instance_id, "schema": schema_name,
                    "predictions": predictions})


def _default_types():
    from potato.server_utils.schemas.rollout_evaluation import (
        DEFAULT_VIOLATION_TYPES)
    return DEFAULT_VIOLATION_TYPES


def _visual_endpoint():
    """The configured vision endpoint, or None. Never raises."""
    try:
        from potato.flask_server import get_ai_cache_manager

        manager = get_ai_cache_manager()
        if manager is None:
            return None
        endpoint = manager._get_visual_endpoint()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not resolve a vision endpoint: %s", exc)
        return None
    if endpoint is None or not hasattr(endpoint, "query_with_image"):
        return None
    return endpoint


def _local_path(url: str):
    """
    The file on disk behind a stream URL, or None for a remote one.

    A rollout served from an external host cannot be frame-sampled — ffmpeg
    would have to fetch it, and doing that on a URL that came out of a data
    file is a server-side request-forgery primitive. Refusing is the correct
    behaviour, and it is reported per stream rather than failing the request,
    because a set can legitimately mix local and remote sources.
    """
    from potato.media.paths import resolve_media_path

    raw = str(url or "")
    if raw.startswith(("http://", "https://")):
        return None
    if raw.startswith("/media/"):
        raw = raw[len("/media/"):]
    _root, absolute = resolve_media_path(_config(), raw, context="Rollout")
    if absolute is None or not os.path.exists(absolute):
        return None
    return absolute


def _current_item(username: str):
    """``(item_data, instance_id, None)`` or ``(None, None, error_response)``."""
    from flask import jsonify

    from potato.flask_server import get_user_state

    user_state = get_user_state(username)
    if not user_state:
        return None, None, (jsonify({"error": "User state not found"}), 404)
    instance = user_state.get_current_instance()
    if not instance:
        return None, None, (jsonify({"error": "No current instance"}), 404)
    data = instance.get_data() or {}
    if not isinstance(data, dict):
        data = {}
    return data, instance.get_id(), None


def _manifest_resolver():
    """
    A ``path -> absolute path or None`` callable over the media directory.

    Injected into the reader rather than imported by it, so the traversal guard
    lives in exactly one place and the reader stays testable without a Flask
    config.
    """
    from potato.media.paths import resolve_media_path

    def resolve(path: str):
        _root, absolute = resolve_media_path(_config(), path,
                                             context="Rollout")
        return absolute

    return resolve


def register_rollout_routes(app, config: dict) -> None:
    """
    Wire the rollout routes.

    Called from ``configure_routes``; ``config`` is passed in rather than
    imported so these handlers read the same object ``serve_media`` does.
    """
    global _registered_config
    _registered_config = config

    app.add_url_rule("/api/rollout/set", "rollout_set", rollout_set,
                     methods=["GET"])
    app.add_url_rule("/api/rollout/judge", "rollout_judge", rollout_judge,
                     methods=["POST"])
