"""
Automation action executors.

Each action is a ``{"type": ..., ...params}`` dict. Actions are split into:

  - FAST actions, run synchronously in the ingestion path (cheap, in-process):
    ``add_to_queue``, ``add_to_dataset``, ``notify``.
  - HEAVY actions, dispatched to the background worker (network / model calls):
    ``run_evaluator``, ``fire_webhook``.

Every executor returns an outcome dict ``{action, status, detail}`` and must
never raise into the ingestion path — failures are caught and logged as
``status: "error"`` outcomes.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger("potato.automation")

FAST_ACTIONS = {"add_to_queue", "add_to_dataset", "notify", "enroll_review"}
HEAVY_ACTIONS = {"run_evaluator", "fire_webhook", "refresh_topics"}


def is_heavy(action: Dict[str, Any]) -> bool:
    return action.get("type") in HEAVY_ACTIONS


def _outcome(action_type: str, status: str, detail: str = "") -> Dict[str, Any]:
    return {"action": action_type, "status": status, "detail": detail}


# ----- FAST actions -----

def _add_to_queue(action, ctx) -> Dict[str, Any]:
    """Surface the item in the annotation queue by boosting its triage priority."""
    from potato.item_state_management import get_item_state_manager
    ism = get_item_state_manager()
    if ism is None:
        return _outcome("add_to_queue", "skipped", "no item state manager")
    try:
        item = ism.get_item(ctx["item_id"])
    except KeyError:
        return _outcome("add_to_queue", "skipped", "item not found")
    priority = float(action.get("priority", 100))
    item.metadata["triage_priority"] = priority
    item.metadata.setdefault("triage_reason", action.get("reason", "automation"))
    item.metadata["automation_queued"] = True
    # ``:g`` drops a trailing .0 so whole priorities read "priority=100".
    return _outcome("add_to_queue", "ok", f"priority={priority:g}")


def _add_to_dataset(action, ctx) -> Dict[str, Any]:
    from potato.eval_datasets.manager import get_datasets_manager
    from potato.eval_datasets.models import Example
    mgr = get_datasets_manager()
    if mgr is None:
        return _outcome("add_to_dataset", "skipped", "datasets not enabled")
    dataset = action.get("dataset")
    if not dataset:
        return _outcome("add_to_dataset", "error", "missing 'dataset'")
    data = ctx["item_data"]
    inputs = data if isinstance(data, dict) else {"text": data}
    mgr.store.create_dataset(dataset)
    mgr.store.add_examples(dataset, [Example(
        id=str(ctx["item_id"]), inputs=inputs,
        metadata={"source": "automation", "rule": ctx.get("rule")},
    )], note=f"automation rule '{ctx.get('rule')}'")
    return _outcome("add_to_dataset", "ok", dataset)


def _notify(action, ctx) -> Dict[str, Any]:
    try:
        from potato.routes_trace_ingestion import _sse_notifier
    except Exception:
        return _outcome("notify", "skipped", "no SSE notifier")
    try:
        _sse_notifier.notify_new_trace(
            trace_id=str(ctx["item_id"]),
            task_description=action.get("message", f"automation: {ctx.get('rule')}"),
            source="automation",
        )
        return _outcome("notify", "ok", "")
    except Exception as e:
        return _outcome("notify", "error", str(e))


def _enroll_review(action, ctx) -> Dict[str, Any]:
    """Enroll a runtime-ingested item into the review workflow board (D4),
    applying the configured routing rules. Idempotent."""
    from potato.server_utils.config_module import config
    from potato.review_workflow import enroll_with_routing, review_enabled
    if not review_enabled(config):
        return _outcome("enroll_review", "skipped", "review workflow not enabled")
    data = ctx.get("item_data")
    created = enroll_with_routing(
        config, str(ctx["item_id"]),
        data if isinstance(data, dict) else {}, actor="automation")
    return _outcome("enroll_review", "ok",
                    "enrolled" if created else "already enrolled")


# ----- HEAVY actions (run in the worker) -----

def _run_evaluator(action, ctx) -> Dict[str, Any]:
    from potato.evaluators.registry import build_evaluator
    name = action.get("evaluator")
    if not name:
        return _outcome("run_evaluator", "error", "missing 'evaluator'")
    try:
        ev = build_evaluator(name, action.get("params"))
        result = ev.evaluate(outputs=ctx["item_data"], reference_outputs=None,
                             inputs=ctx["item_data"])
    except Exception as e:
        return _outcome("run_evaluator", "error", f"{name}: {e}")
    # Store the score back on the item as automation feedback.
    from potato.item_state_management import get_item_state_manager
    ism = get_item_state_manager()
    if ism is not None:
        try:
            item = ism.get_item(ctx["item_id"])
            item.metadata.setdefault("automation_eval", {})[result.key] = result.score
        except KeyError:
            pass
    return _outcome("run_evaluator", "ok", f"{result.key}={result.score}")


def _refresh_topics(action, ctx) -> Dict[str, Any]:
    """Re-discover trace clusters and persist them as topics (D2 Topics).

    Heavy (embeddings + optional LLM naming). Typical rule: sample a small
    fraction of ingested traces so topics refresh periodically as production
    data drifts, e.g. ``{"type": "refresh_topics", "k": 8, "min_indexed": 20}``.
    """
    from potato.curation.manager import get_curation_manager
    mgr = get_curation_manager()
    if mgr is None:
        return _outcome("refresh_topics", "skipped", "curation not enabled")
    min_indexed = int(action.get("min_indexed", 10))
    if len(mgr.index) < min_indexed:
        return _outcome("refresh_topics", "skipped",
                        f"only {len(mgr.index)} indexed (< {min_indexed})")
    from datetime import datetime, timezone
    try:
        topics = mgr.refresh_topics(
            k=int(action.get("k", 6)),
            use_llm=bool(action.get("use_llm", True)),
            refreshed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    except Exception as e:
        return _outcome("refresh_topics", "error", str(e))
    return _outcome("refresh_topics", "ok", f"{len(topics)} topics")


def _fire_webhook(action, ctx) -> Dict[str, Any]:
    url = action.get("url")
    if not url:
        return _outcome("fire_webhook", "error", "missing 'url'")
    try:
        import requests
        payload = {
            "rule": ctx.get("rule"),
            "item_id": ctx["item_id"],
            "item_data": ctx["item_data"],
        }
        headers = {"Content-Type": "application/json", **(action.get("headers") or {})}
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        return _outcome("fire_webhook", "ok" if resp.status_code < 300 else "error",
                        f"{resp.status_code}")
    except Exception as e:
        return _outcome("fire_webhook", "error", str(e))


_EXECUTORS = {
    "add_to_queue": _add_to_queue,
    "add_to_dataset": _add_to_dataset,
    "notify": _notify,
    "enroll_review": _enroll_review,
    "run_evaluator": _run_evaluator,
    "fire_webhook": _fire_webhook,
    "refresh_topics": _refresh_topics,
}


def execute_action(action: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Run one action, never raising. Returns an outcome dict."""
    atype = action.get("type")
    fn = _EXECUTORS.get(atype)
    if fn is None:
        return _outcome(str(atype), "error", "unknown action type")
    try:
        return fn(action, ctx)
    except Exception as e:  # belt-and-suspenders: nothing reaches the caller
        logger.error("Automation action %s failed: %s", atype, e)
        return _outcome(str(atype), "error", str(e))
