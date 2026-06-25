"""
Multi-model arena: fan one prompt out to N providers, side by side.

Provider-agnostic — every model is built through ``AIEndpointFactory`` (the same
11-provider abstraction the rest of Potato uses), so the arena works with
OpenAI / Anthropic / Ollama / vLLM / Gemini / … not just one vendor. Calls run
concurrently; one model failing never aborts the others (its error is captured).
``endpoint_builder`` / ``query_fn`` are injectable for testing.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

from potato.arena.config import ArenaModel

logger = logging.getLogger("potato.arena")


def _default_endpoint_builder(m: ArenaModel):
    from potato.ai.ai_endpoint import AIEndpointFactory
    ai_config = dict(m.ai_config)
    if m.model:
        ai_config.setdefault("model", m.model)
    if m.temperature is not None:
        ai_config.setdefault("temperature", m.temperature)
    if m.base_url:
        ai_config.setdefault("base_url", m.base_url)
    return AIEndpointFactory.create_endpoint({
        "ai_support": {"enabled": True, "endpoint_type": m.endpoint_type,
                       "ai_config": ai_config},
    })


def _default_query(endpoint, prompt: str) -> str:
    """Query an endpoint for a free-text response (provider-agnostic)."""
    resp = endpoint.query(prompt, None)
    if isinstance(resp, str):
        return resp
    if hasattr(resp, "model_dump"):
        d = resp.model_dump()
        return d.get("response") or d.get("text") or str(d)
    return str(resp)


def run_arena(
    prompt: str,
    models: List[ArenaModel],
    endpoint_builder: Optional[Callable[[ArenaModel], Any]] = None,
    query_fn: Optional[Callable[[Any, str], str]] = None,
    max_workers: int = 8,
) -> List[Dict[str, Any]]:
    """Run ``prompt`` against every model concurrently.

    Returns one ordered dict per model: ``{label, model, response, latency_ms,
    error}``. Order matches ``models`` regardless of completion order.
    """
    builder = endpoint_builder or _default_endpoint_builder
    query = query_fn or _default_query

    def _one(idx_model):
        idx, m = idx_model
        t0 = time.time()
        try:
            endpoint = builder(m)
            if endpoint is None:
                raise RuntimeError("endpoint could not be created (check config)")
            text = query(endpoint, prompt)
            err = None
        except Exception as e:  # never let one model abort the arena
            text, err = "", str(e)
        return {
            "index": idx, "label": m.label, "model": m.model,
            "response": text, "latency_ms": round((time.time() - t0) * 1000), "error": err,
        }

    if not models:
        return []
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(models)))) as ex:
        results = list(ex.map(_one, enumerate(models)))
    results.sort(key=lambda r: r["index"])
    for r in results:
        r.pop("index", None)
    return results
