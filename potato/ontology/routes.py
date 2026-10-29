"""
``GET /api/ontology/search?schema=<name>&q=<text>``
    Matching terms for a scheme with ``label_source``. For ``service: ols4``
    Potato makes the call to OLS4 (with a timeout, a result cap and a cache);
    the browser only ever talks to Potato.
``GET /api/ontology/terms?schema=<name>&ids=CL:1,CL:2``
    Records for term ids already on the page (span chips, image shapes), from
    the .obo file or, for OLS4, the terms that server has returned before.

Both need a signed-in user and name the scheme, so a request can only reach
an ontology the config set up.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_config: dict = {}

MAX_QUERY_CHARS = 200
MAX_IDS = 200


def _source_or_abort(schema_name: str):
    from flask import abort, session
    from potato.ontology.source import find_scheme, source_for_scheme
    if not session.get("username"):
        abort(401)
    scheme = find_scheme(_config, schema_name)
    if scheme is None:
        abort(404)
    return scheme, source_for_scheme(scheme, _config)


def ontology_search():
    from flask import jsonify, request
    from potato.ontology.obo import OboError
    from potato.ontology.source import MIN_QUERY_LENGTH, OntologyServiceError
    schema = request.args.get("schema", "")
    query = " ".join((request.args.get("q") or "").split())[:MAX_QUERY_CHARS]
    scheme, source = _source_or_abort(schema)
    ls = scheme["label_source"]
    base = {"schema": schema, "ontology": ls.get("ontology"), "service": source.service,
            "query": query}
    if len(query) < MIN_QUERY_LENGTH:
        return jsonify({**base, "results": [], "total": 0, "truncated": False,
                        "version": ""})
    try:
        found = source.search(query)
    except OntologyServiceError as e:
        logger.warning("Ontology search for %s failed: %s", schema, e)
        return jsonify({**base, "error": str(e)}), 502
    except (OboError, OSError) as e:
        logger.error("Ontology file for %s could not be read: %s", schema, e)
        return jsonify({**base, "error": "The ontology file could not be read"}), 500
    results = found["results"]
    response = jsonify({**base, "results": results, "total": found["total"],
                        "truncated": found["total"] > len(results),
                        "version": found.get("version", "")})
    response.headers["Cache-Control"] = "private, max-age=300"
    return response


def ontology_terms():
    from flask import jsonify, request
    schema = request.args.get("schema", "")
    ids = [i.strip() for i in (request.args.get("ids") or "").split(",") if i.strip()][:MAX_IDS]
    _scheme, source = _source_or_abort(schema)
    terms = {}
    for obo_id in ids:
        try:
            record = source.get_term(obo_id)
        except Exception as e:  # unreadable file: say nothing rather than 500
            logger.debug("Term %s not resolved: %s", obo_id, e)
            record = None
        if record:
            terms[obo_id] = record
    return jsonify({"schema": schema, "terms": terms})


def register_ontology_routes(app, config) -> None:
    global _config
    _config = config
    if "ontology_search" in app.view_functions:
        return
    app.add_url_rule("/api/ontology/search", "ontology_search", ontology_search,
                     methods=["GET"])
    app.add_url_rule("/api/ontology/terms", "ontology_terms", ontology_terms,
                     methods=["GET"])
