"""
``GET /api/grounding/expressions?schema=<name>`` — the current item's phrases.

Fetched rather than rendered into the page for the same reason the rollout
manifest is: the schema generator runs without the item, so it cannot know what
the expressions are. Serving them lets the item shape stay flexible — a list of
strings, a list of objects with ids, or a mapping — without the schema having to
guess at render time.

Predictions, when a project is reviewing a model rather than creating ground
truth, come back on the same response. They are **labelled as predictions all
the way through** and never merged into the annotator's own regions: a
prediction the annotator has not accepted is evidence about the model, and
folding it into the ground truth would destroy the only thing it is for.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_registered_config: dict = {}


def _config() -> dict:
    return _registered_config


def _schema_config(name: str):
    config = _config()
    schemes = list(config.get("annotation_schemes") or [])
    for phase in (config.get("phases") or {}).values():
        if isinstance(phase, dict):
            schemes.extend(phase.get("annotation_schemes") or [])
    for scheme in schemes:
        if isinstance(scheme, dict) and scheme.get("name") == name:
            return scheme
    return None


def normalize_expressions(raw):
    """
    Accept any of the shapes a benchmark actually uses, return one.

    RefCOCO exports a list of strings; other sets carry objects with their own
    ids; a hand-written file may use a mapping. Normalizing here rather than in
    the client means the browser sees one shape and a new source format is a
    change in one place.

    Ids are **positional when the data does not supply them**, which is stated
    because it matters: reordering the expressions in the data file then
    re-points existing annotations. A source with stable ids should use them.
    """
    expressions = []
    if isinstance(raw, dict):
        for key, value in raw.items():
            expressions.append({"id": str(key), "text": str(value)})
        return expressions

    if not isinstance(raw, (list, tuple)):
        return expressions

    for index, entry in enumerate(raw):
        if isinstance(entry, dict):
            text = entry.get("text") or entry.get("expression") or entry.get("phrase")
            expressions.append({
                "id": str(entry.get("id") or entry.get("expression_id") or index),
                "text": str(text or ""),
                "metadata": {k: v for k, v in entry.items()
                             if k not in ("id", "expression_id", "text",
                                          "expression", "phrase")},
            })
        else:
            expressions.append({"id": str(index), "text": str(entry)})
    return expressions


def grounding_expressions():
    """The current item's referring expressions, and any model predictions."""
    from flask import jsonify, request, session

    if "username" not in session:
        return jsonify({"error": "No active session"}), 401
    username = session["username"]

    schema_name = request.args.get("schema") or ""
    scheme = _schema_config(schema_name)
    if scheme is None:
        return jsonify({
            "error": f"no annotation scheme named '{schema_name}' is "
                     f"configured"}), 404
    if (scheme.get("annotation_type") or "") != "grounding_eval":
        return jsonify({
            "error": f"'{schema_name}' is a {scheme.get('annotation_type')} "
                     f"schema, not grounding_eval"}), 400

    from potato.flask_server import get_user_state

    user_state = get_user_state(username)
    if not user_state:
        return jsonify({"error": "User state not found"}), 404
    instance = user_state.get_current_instance()
    if not instance:
        return jsonify({"error": "No current instance"}), 404

    data = instance.get_data() or {}
    if not isinstance(data, dict):
        data = {}

    field = scheme.get("expressions_field", "expressions")
    expressions = normalize_expressions(data.get(field))

    payload = {
        "instance_id": instance.get_id(),
        "schema": schema_name,
        "region_type": scheme.get("region_type", "box"),
        "expression_source": scheme.get("expression_source", "field"),
        "expressions": expressions,
    }

    if payload["expression_source"] == "spans":
        # Hallucination localization: the phrases are not given, they are
        # selected out of the model's own text. The caption travels with the
        # response so the client does not have to scrape it out of the rendered
        # instance, which would break the moment a display type wrapped it.
        caption_field = scheme.get("caption_field", "caption")
        payload["caption"] = str(data.get(caption_field) or "")
        payload["expressions"] = []
        if not payload["caption"]:
            payload["warning"] = (
                f"This item has no caption to ground. The schema reads it from "
                f"the '{caption_field}' field; set `caption_field` if it lives "
                f"somewhere else.")
        return jsonify(payload)

    predictions_field = scheme.get("predictions_field") or ""
    if predictions_field:
        raw = data.get(predictions_field)
        payload["predictions"] = raw if isinstance(raw, dict) else {}

    if not expressions:
        # Not a 404: the item exists and is simply unusable for this schema,
        # and the annotator needs to be told which field was looked at rather
        # than shown an empty list.
        payload["warning"] = (
            f"This item has no referring expressions. The schema reads them "
            f"from the '{field}' field; set `expressions_field` if they live "
            f"somewhere else.")

    return jsonify(payload)


def register_grounding_routes(app, config: dict) -> None:
    """Wire the grounding routes. Called from ``configure_routes``."""
    global _registered_config
    _registered_config = config

    app.add_url_rule("/api/grounding/expressions", "grounding_expressions",
                     grounding_expressions, methods=["GET"])
