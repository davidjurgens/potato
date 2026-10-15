"""
REST API for the labeling engine: ``/api/engine/v1/...``.

Reads need the admin dashboard permission; actions (certify, run the
planner) need assignment management. The shared admin API key passes both,
so a pipeline or an agent can drive a study over HTTP.
"""

from __future__ import annotations

import logging
from functools import wraps

from flask import Blueprint, Response, jsonify, request

from potato.server_utils.rbac import Permission, require_permission

logger = logging.getLogger(__name__)

engine_bp = Blueprint("labeling_engine", __name__, url_prefix="/api/engine/v1")


def _engine():
    from ..integration.hooks import get_engine
    return get_engine()


def _enabled(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if _engine() is None:
            return jsonify({"error": "The labeling engine is not enabled for this study "
                                     "(labeling_engine.enabled)"}), 404
        return f(*args, **kwargs)
    return wrapper


def _scheme(name):
    eng = _engine()
    for s in eng.schemes():
        if s.name == name:
            return s
    return None


class _BadParam(ValueError):
    pass


def _int_arg(name, default, lo, hi):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return min(hi, max(lo, int(raw)))
    except ValueError:
        raise _BadParam(f"{name} must be an integer, got {raw!r}")


def _list_arg(name, allowed):
    """A repeated parameter (``?purpose=a&purpose=b``) or a comma-separated
    one (``?purpose=a,b``). An unknown value is an error, not an empty result."""
    values = [v.strip() for raw in request.args.getlist(name)
              for v in raw.split(",") if v.strip()]
    unknown = [v for v in values if v not in allowed]
    if unknown:
        raise _BadParam(f"unknown {name} {', '.join(map(repr, unknown))}; "
                        f"expected one of: {', '.join(allowed)}")
    return values or None


@engine_bp.errorhandler(_BadParam)
def _bad_param(exc):
    return jsonify({"error": str(exc)}), 400


def _json(obj, status=200):
    from potato.server_utils.iaa.dispatcher import json_safe
    return jsonify(json_safe(obj)), status


@engine_bp.route("/status", methods=["GET"])
@require_permission(Permission.VIEW_ADMIN_DASHBOARD)
@_enabled
def status():
    from ..integration.hooks import get_planner
    eng = _engine()
    out = eng.status()
    planner = get_planner()
    out["last_tick"] = getattr(planner, "last_tick", None)
    return _json(out)


@engine_bp.route("/schemes/<name>/contracts", methods=["GET"])
@require_permission(Permission.VIEW_ADMIN_DASHBOARD)
@_enabled
def contracts(name):
    s = _scheme(name)
    if s is None:
        return jsonify({"error": f"no engine scheme {name!r}"}), 404
    return _json(_engine().contract_status(s))


@engine_bp.route("/certify", methods=["POST"])
@require_permission(Permission.MANAGE_ASSIGNMENT)
@_enabled
def certify():
    eng = _engine()
    body = request.get_json(silent=True) or {}
    retest = request.args.get("retest") in ("1", "true") or body.get("retest") is True
    return _json({s.name: eng.certify(s, retest=retest) for s in eng.schemes()})


@engine_bp.route("/plan", methods=["POST"])
@require_permission(Permission.MANAGE_ASSIGNMENT)
@_enabled
def plan():
    """Run one planner pass now, instead of waiting for the next tick."""
    from ..integration.hooks import get_planner
    planner = get_planner()
    if planner is None:
        return jsonify({"error": "no planner is running"}), 409
    return _json(planner.tick())


@engine_bp.route("/requests", methods=["GET"])
@require_permission(Permission.VIEW_ADMIN_DASHBOARD)
@_enabled
def requests_list():
    from ..model.records import PURPOSES, REQUEST_STATUSES
    eng = _engine()
    purpose = _list_arg("purpose", PURPOSES)
    status_ = _list_arg("status", REQUEST_STATUSES)
    limit = _int_arg("limit", 200, 1, 1000)
    rows = eng.store.requests(status=status_, purpose=purpose,
                              schema=request.args.get("schema"), limit=limit)
    return _json({"counts": eng.store.request_counts(),
                  "requests": [r.__dict__ for r in rows]})


@engine_bp.route("/calls", methods=["GET"])
@require_permission(Permission.VIEW_ADMIN_DASHBOARD)
@_enabled
def calls():
    eng = _engine()
    limit = _int_arg("limit", 50, 1, 500)
    offset = _int_arg("offset", 0, 0, 2 ** 62)
    return _json({"totals": eng.store.call_totals(),
                  "calls": [c.__dict__ for c in eng.store.calls(limit=limit,
                                                                offset=offset)]})


CERTIFICATE_FORMATS = ("json", "md", "html")


@engine_bp.route("/certificate", methods=["GET"])
@require_permission(Permission.EXPORT_DATA)
@_enabled
def certificate():
    from ..certificate import build_certificate, render_html, render_markdown
    fmt = request.args.get("format", "json")
    if fmt not in CERTIFICATE_FORMATS:
        raise _BadParam(f"format must be one of {', '.join(CERTIFICATE_FORMATS)}, "
                        f"got {fmt!r}")
    cert = build_certificate(_engine(), save=request.args.get("save") == "1")
    if fmt == "md":
        return Response(render_markdown(cert), mimetype="text/markdown")
    if fmt == "html":
        return Response(render_html(cert), mimetype="text/html")
    return _json(cert)


@engine_bp.route("/schemes/<name>/reliability", methods=["GET"])
@require_permission(Permission.VIEW_ADMIN_DASHBOARD)
@_enabled
def reliability(name):
    """Reliability bins and ECE per tier, over the human calibration labels."""
    from ..calibrate.metrics import (brier_score, expected_calibration_error,
                                     reliability_bins)
    s = _scheme(name)
    if s is None:
        return jsonify({"error": f"no engine scheme {name!r}"}), 404
    view = _engine().view(s, population_ids=[])
    out = {}
    for t, tid in enumerate(view.tier_ids):
        pairs = [(c.tiers[t].conf, view.correct(c.tiers[t].value, c.human))
                 for c in view.cal if t < len(c.tiers) and c.tiers[t] is not None
                 and c.tiers[t].answered]
        confs = [p[0] for p in pairs]
        oks = [p[1] for p in pairs]
        out[tid] = {"n": len(pairs), "bins": reliability_bins(confs, oks),
                    "ece": expected_calibration_error(confs, oks),
                    "brier": brier_score(confs, oks)}
    return _json(out)


@engine_bp.route("/schemes/<name>/risk_coverage", methods=["GET"])
@require_permission(Permission.VIEW_ADMIN_DASHBOARD)
@_enabled
def risk_coverage(name):
    """For each threshold of the last tier: the share accepted on the cert
    labels, the observed error, and the guaranteed upper bound on error."""
    from ..contracts import stats
    s = _scheme(name)
    if s is None:
        return jsonify({"error": f"no engine scheme {name!r}"}), 404
    eng = _engine()
    view = eng.view(s, population_ids=[])
    if not view.tier_ids:
        return _json({"points": []})
    t = len(view.tier_ids) - 1
    cert = [c for c in view.cal if c.split == "cert" and t < len(c.tiers)
            and c.tiers[t] is not None and c.tiers[t].answered]
    alpha = None
    for c in eng.cfg.contracts:
        if c.kind == "selective_risk" and c.schema == name:
            alpha = 1 - c.confidence
    alpha = alpha or 0.1
    cert.sort(key=lambda c: -c.tiers[t].conf)
    points, wrong = [], 0
    for k, c in enumerate(cert, start=1):
        wrong += 0 if view.correct(c.tiers[t].value, c.human) else 1
        nxt = cert[k].tiers[t].conf if k < len(cert) else None
        if nxt is not None and nxt == c.tiers[t].conf:
            continue
        points.append({"threshold": c.tiers[t].conf, "coverage": k / len(cert),
                       "error": wrong / k,
                       "upper_bound": stats.clopper_pearson(wrong, k, 1 - 2 * alpha)[1]})
    return _json({"tier": view.tier_ids[t], "n_cert": len(cert), "points": points})


@engine_bp.route("/schemes/<name>/drift", methods=["GET"])
@require_permission(Permission.VIEW_ADMIN_DASHBOARD)
@_enabled
def drift(name):
    s = _scheme(name)
    if s is None:
        return jsonify({"error": f"no engine scheme {name!r}"}), 404
    return _json(_engine().drift(s))


@engine_bp.route("/schemes/<name>/optimize", methods=["GET"])
@require_permission(Permission.VIEW_ADMIN_DASHBOARD)
@_enabled
def optimize_report(name):
    """The planner's latest cheaper-cascade report (features.optimize), or a
    fresh one: dev labels only, so it spends no look at the cert labels."""
    from ..integration.hooks import get_planner
    from ..optimize import cascade_report
    s = _scheme(name)
    if s is None:
        return jsonify({"error": f"no engine scheme {name!r}"}), 404
    planner = get_planner()
    rep = (getattr(planner, "last_optimize", None) or {}).get(name)
    return _json(rep or cascade_report(_engine(), s))


@engine_bp.route("/crowd", methods=["GET"])
@require_permission(Permission.VIEW_ADMIN_DASHBOARD)
@_enabled
def crowd():
    from ..integration.hooks import get_planner
    planner = get_planner()
    return _json(getattr(planner, "last_crowd", None) or {"action": "not run yet"})
