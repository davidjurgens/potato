"""
Cost / token / latency analytics for ingested agent traces, plus regression alerts.

Aggregates the operational metrics every trace already carries — token usage,
latency, error status, and (optionally) cost — into totals, per-model breakdowns,
and latency percentiles, then flags **regressions** (cost spike, latency increase,
error-rate jump) between a recent window and a baseline.

Potato sits *offline* in the human-in-the-loop path, so this **flags** — it never
blocks a live request. Pure Python (stdlib only); metric extraction is tolerant of
the many shapes traces arrive in (dotted paths + a `metadata_table` fallback).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Default places to look for each metric, in priority order. Dotted paths descend
# into nested dicts; the converters' ``metadata_table`` (list of {Property, Value})
# is also consulted as a fallback.
DEFAULT_SPEC = {
    "model": ["model", "metadata.model", "gen_ai.request.model", "llm.model_name"],
    "prompt_tokens": ["usage.prompt_tokens", "usage.input_tokens", "prompt_tokens"],
    "completion_tokens": ["usage.completion_tokens", "usage.output_tokens", "completion_tokens"],
    "total_tokens": ["usage.total_tokens", "usage.totalTokens", "total_tokens", "tokens"],
    "latency_ms": ["latency_ms", "metadata.latency_ms", "duration_ms", "latencyMs"],
    "cost": ["cost", "metadata.cost", "usage.cost"],
    "status": ["status", "outcome", "metadata.status", "error"],
}


def _dotted(data: Any, path: str) -> Any:
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _from_table(data: Any, names: List[str]) -> Any:
    """Look a value up in a converter ``metadata_table`` (list of {Property, Value})."""
    table = data.get("metadata_table") if isinstance(data, dict) else None
    if not isinstance(table, list):
        return None
    wanted = {n.lower() for n in names}
    for row in table:
        if isinstance(row, dict):
            prop = str(row.get("Property", row.get("property", ""))).lower()
            if prop in wanted or any(w in prop for w in wanted):
                return row.get("Value", row.get("value"))
    return None


def _first(data: Any, paths: List[str], table_names: List[str] = None) -> Any:
    for p in paths:
        v = _dotted(data, p)
        if v is not None:
            return v
    return _from_table(data, table_names or [])


def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _is_error(status_val: Any) -> bool:
    if status_val is None:
        return False
    s = str(status_val).strip().lower()
    return s in {"error", "failed", "failure", "exception"} or (s not in {"", "ok", "success", "succeeded", "none", "false"} and "error" in s)


@dataclass
class TraceMetrics:
    model: str = "unknown"
    prompt_tokens: float = 0.0
    completion_tokens: float = 0.0
    total_tokens: float = 0.0
    latency_ms: Optional[float] = None
    cost: Optional[float] = None
    is_error: bool = False


def extract_metrics(item_data: Dict[str, Any], spec: Dict[str, List[str]] = None,
                    pricing: Dict[str, Dict[str, float]] = None) -> TraceMetrics:
    """Pull operational metrics out of one trace's data dict.

    ``pricing`` (optional): ``{model: {"in": $/1k prompt tok, "out": $/1k completion}}``.
    When cost isn't recorded but pricing + token counts are, cost is computed.
    """
    spec = spec or DEFAULT_SPEC
    model = _first(item_data, spec["model"], ["model"]) or "unknown"
    pt = _num(_first(item_data, spec["prompt_tokens"], ["prompt tokens"])) or 0.0
    ct = _num(_first(item_data, spec["completion_tokens"], ["completion tokens"])) or 0.0
    tt = _num(_first(item_data, spec["total_tokens"], ["total tokens", "tokens"]))
    if tt is None:
        tt = pt + ct
    latency = _num(_first(item_data, spec["latency_ms"], ["latency"]))
    cost = _num(_first(item_data, spec["cost"], ["cost"]))
    if cost is None and pricing:
        rate = pricing.get(str(model)) or pricing.get("default")
        if rate:
            cost = (pt / 1000.0) * rate.get("in", 0.0) + (ct / 1000.0) * rate.get("out", 0.0)
    status = _first(item_data, spec["status"], ["status", "outcome"])
    return TraceMetrics(model=str(model), prompt_tokens=pt, completion_tokens=ct,
                        total_tokens=tt or 0.0, latency_ms=latency, cost=cost,
                        is_error=_is_error(status))


def _percentile(values: List[float], pct: float) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 2)


def compute_analytics(items: List[Dict[str, Any]], spec=None, pricing=None) -> Dict[str, Any]:
    """Aggregate metrics across trace items: totals, per-model, latency percentiles."""
    metrics = [extract_metrics(it, spec, pricing) for it in items]
    n = len(metrics)
    latencies = [m.latency_ms for m in metrics if m.latency_ms is not None]
    costs = [m.cost for m in metrics if m.cost is not None]
    errors = sum(1 for m in metrics if m.is_error)

    per_model: Dict[str, Dict[str, Any]] = {}
    for m in metrics:
        d = per_model.setdefault(m.model, {"count": 0, "total_tokens": 0.0,
                                           "cost": 0.0, "errors": 0, "_lat": []})
        d["count"] += 1
        d["total_tokens"] += m.total_tokens
        if m.cost is not None:
            d["cost"] += m.cost
        if m.is_error:
            d["errors"] += 1
        if m.latency_ms is not None:
            d["_lat"].append(m.latency_ms)
    for d in per_model.values():
        d["avg_latency_ms"] = round(sum(d["_lat"]) / len(d["_lat"]), 1) if d["_lat"] else None
        d["cost"] = round(d["cost"], 6)
        d["total_tokens"] = int(d["total_tokens"])
        del d["_lat"]

    return {
        "count": n,
        "total_tokens": int(sum(m.total_tokens for m in metrics)),
        "total_cost": round(sum(costs), 6) if costs else None,
        "error_rate": round(errors / n, 4) if n else 0.0,
        "errors": errors,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
        "p50_latency_ms": _percentile(latencies, 0.5),
        "p95_latency_ms": _percentile(latencies, 0.95),
        "per_model": per_model,
    }


def detect_regressions(recent: Dict[str, Any], baseline: Dict[str, Any],
                       thresholds: Dict[str, float] = None) -> List[Dict[str, Any]]:
    """Flag regressions of ``recent`` vs ``baseline`` analytics.

    thresholds (fractional increase that trips an alert):
      cost_per_trace (0.5 = +50%), avg_latency_ms (0.3), error_rate (absolute pp, 0.05).
    Returns a list of ``{metric, severity, baseline, recent, message}`` alerts.
    """
    th = {"cost_per_trace": 0.5, "avg_latency_ms": 0.3, "error_rate": 0.05}
    th.update(thresholds or {})
    alerts: List[Dict[str, Any]] = []

    def per_trace(a, key):
        c = a.get("count") or 0
        v = a.get(key)
        return (v / c) if (c and v is not None) else None

    # cost per trace
    b_cpt, r_cpt = per_trace(baseline, "total_cost"), per_trace(recent, "total_cost")
    if b_cpt and r_cpt is not None and b_cpt > 0:
        inc = (r_cpt - b_cpt) / b_cpt
        if inc >= th["cost_per_trace"]:
            alerts.append({"metric": "cost_per_trace", "severity": "high" if inc >= 1.0 else "medium",
                           "baseline": round(b_cpt, 6), "recent": round(r_cpt, 6),
                           "message": f"Cost per trace up {inc*100:.0f}%"})

    # average latency
    b_lat, r_lat = baseline.get("avg_latency_ms"), recent.get("avg_latency_ms")
    if b_lat and r_lat is not None and b_lat > 0:
        inc = (r_lat - b_lat) / b_lat
        if inc >= th["avg_latency_ms"]:
            alerts.append({"metric": "avg_latency_ms", "severity": "high" if inc >= 0.75 else "medium",
                           "baseline": b_lat, "recent": r_lat,
                           "message": f"Avg latency up {inc*100:.0f}%"})

    # error rate (absolute percentage-point increase)
    b_err, r_err = baseline.get("error_rate", 0.0), recent.get("error_rate", 0.0)
    if (r_err - b_err) >= th["error_rate"]:
        alerts.append({"metric": "error_rate", "severity": "high" if (r_err - b_err) >= 0.15 else "medium",
                       "baseline": b_err, "recent": r_err,
                       "message": f"Error rate up {(r_err-b_err)*100:.1f} points"})
    return alerts
