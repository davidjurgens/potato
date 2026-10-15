"""
``RunContext.call``: the only path from the engine to a model.

Every model request a source makes goes through here, in this order:

1. PII redaction, when enabled and the endpoint is remote.
2. The response cache, keyed by source version, input, scheme and sample.
3. The engine's ``model_usd`` budget, checked before the call is made.
4. A per-endpoint concurrency limit.
5. The call itself, timed, with the provider's token counts when it reports
   them.
6. A row in the ``model_call`` audit log, written whether the call succeeded,
   failed or was served from the cache.

A source that called an endpoint directly would produce predictions with no
call record, no cost and no cache, and the certificate could not say what
produced them. ``tests/unit/labeling_engine/test_runtime.py`` asserts that
every prediction a run writes cites calls that exist.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, TypeVar
from urllib.parse import urlparse

from ..model.records import ModelCall, SourceVersion, canonical_json, content_hash
from ..governance.redact import redact

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


class BudgetExhausted(RuntimeError):
    """A call was refused because it would take spending past a budget."""


@dataclass
class CallResult:
    reply: Any
    call_id: Optional[int]
    cache_hit: bool = False
    error: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class SpendTally:
    """Calls and cost per model since the last flush to ``ai_spend``."""
    n_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Optional[float] = None
    any_estimated: bool = False
    endpoint_type: str = ""


def _is_transient(exc: Exception) -> bool:
    """A failure worth retrying: a timeout, a dropped connection, a 5xx or 429.

    Anything else (a bad request, an unparseable reply, a refused key) fails
    the same way again, so retrying it only spends money.
    """
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if any(w in name for w in ("timeout", "connection", "temporarily")):
        return True
    if any(w in text for w in ("timed out", "timeout", "connection reset",
                               "connection aborted", "temporarily unavailable",
                               "status 429", "status 500", "status 502", "status 503",
                               "status 504", "rate limit")):
        return True
    return False


def _is_local(endpoint_type: str, base_url: Optional[str]) -> bool:
    """Whether the request stays with servers the study runs itself.

    Self-hosted endpoint types (vLLM, Ollama, in-process models) count as
    local wherever they run: redaction is for text sent to a third-party API.
    Any endpoint reached on this machine (a tunnel to a self-hosted server)
    is local too.
    """
    from potato.ai.cost import LOCAL_ENDPOINTS
    if (endpoint_type or "").lower() in LOCAL_ENDPOINTS:
        return True
    if base_url:
        host = (urlparse(base_url).hostname or "").lower()
        return host in ("localhost", "127.0.0.1", "::1") or host.endswith(".localhost")
    return False


_SEMAPHORES: Dict[str, threading.BoundedSemaphore] = {}
_SEM_GUARD = threading.Lock()


def endpoint_semaphore(key: str, limit: int) -> threading.BoundedSemaphore:
    """One semaphore per endpoint, shared by every run in the process.

    Two sources on the same server (a jury, or a judge and a labeler) share
    its concurrency instead of each assuming they have all of it.
    """
    with _SEM_GUARD:
        sem = _SEMAPHORES.get(key)
        if sem is None:
            sem = threading.BoundedSemaphore(max(1, int(limit)))
            _SEMAPHORES[key] = sem
        return sem


class RunContext:
    """Per-run services: the call pipeline, the store, budgets, parallelism."""

    def __init__(self, store, app_config: Dict[str, Any], engine_cfg=None,
                 run_id: Optional[int] = None):
        self.store = store
        self.app_config = app_config or {}
        self.engine_cfg = engine_cfg
        self.run_id = run_id
        self._tally: Dict[str, SpendTally] = {}
        self._tally_lock = threading.Lock()
        self._budget_lock = threading.Lock()
        self._cancelled = threading.Event()
        self._payload_lock = threading.Lock()

    # === Settings ==========================================================

    def _feature(self, name: str) -> bool:
        return bool(self.engine_cfg and self.engine_cfg.feature(name))

    @property
    def cache_enabled(self) -> bool:
        return bool(self.engine_cfg is None or self.engine_cfg.runtime.cache)

    @property
    def default_concurrency(self) -> int:
        return self.engine_cfg.runtime.concurrency if self.engine_cfg else 4

    def cancel(self) -> None:
        self._cancelled.set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    # === Parallelism ========================================================

    def parallel(self, items: Sequence[T], fn: Callable[[T], R],
                 concurrency: Optional[int] = None) -> List[R]:
        """``[fn(x) for x in items]`` on a thread pool, in input order.

        An exception in one item propagates after the others finish, so a
        failing call does not orphan calls already in flight.
        """
        n = max(1, int(concurrency or self.default_concurrency))
        if n == 1 or len(items) <= 1:
            return [fn(x) for x in items]
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(n, len(items))) as pool:
            futures = [pool.submit(fn, x) for x in items]
            return [f.result() for f in futures]

    # === The call pipeline =================================================

    def call(self, sv: SourceVersion, endpoint, prompt: str, output_format=None, *,
             schema_hash: str = "", sample_idx: int = 0, max_output_tokens: int = 256,
             base_url: Optional[str] = None, concurrency: Optional[int] = None,
             invoke: Optional[Callable[[str], Any]] = None,
             cacheable: bool = True) -> CallResult:
        """Make one model request and log it.

        ``invoke`` replaces ``endpoint.query_with_usage`` for backends that are
        not generative (decision models take questions, detectors take an
        image); it receives the possibly redacted prompt and returns the reply,
        or ``(reply, usage)``.
        """
        endpoint_type = sv.endpoint_type
        model = sv.model
        redaction = None
        if self._feature("pii_redaction") and not _is_local(endpoint_type, base_url):
            cats = (self.engine_cfg.redaction or {}).get("categories")
            prompt, redaction = redact(prompt, cats)

        input_hash = content_hash(prompt)[:32]
        prompt_hash = sv.prompt_template_hash or ""
        key = content_hash([sv.version_id, input_hash, schema_hash, sample_idx])
        if cacheable and self.cache_enabled:
            hit = self.store.cache_get(key)
            if hit is not None:
                reply = json.loads(hit.decode("utf-8"))
                call_id = self._log(ModelCall(
                    source_version_id=sv.version_id, endpoint_type=endpoint_type,
                    model=model, revision=sv.revision, prompt_hash=prompt_hash,
                    input_hash=input_hash, response_hash=content_hash(reply)[:32],
                    run_id=self.run_id, sample_idx=sample_idx, latency_ms=0.0,
                    input_tokens=0, output_tokens=0, cost_usd=0.0, estimated=False,
                    cache_hit=True, redaction=redaction))
                return CallResult(reply=reply, call_id=call_id, cache_hit=True)

        projected = self._projected_cost(prompt, model, endpoint_type, max_output_tokens)
        self._reserve(projected)

        sem = endpoint_semaphore(f"{endpoint_type}|{base_url or model}",
                                 concurrency or self.default_concurrency)
        attempts = 1 + max(0, self.retries)
        for attempt in range(attempts):
            started = time.time()
            reply, usage, error, transient = None, None, None, False
            with sem:
                try:
                    if invoke is not None:
                        out = invoke(prompt)
                    else:
                        out = endpoint.query_with_usage(prompt, output_format)
                    if isinstance(out, tuple) and len(out) == 2 and (
                            out[1] is None or isinstance(out[1], dict)):
                        reply, usage = out
                    else:
                        reply = out
                except Exception as e:  # the reason goes in the log and the result
                    error = f"{type(e).__name__}: {e}"[:500]
                    transient = _is_transient(e)
            latency_ms = (time.time() - started) * 1000.0
            last = attempt == attempts - 1 or not transient
            call_id = self._finish_call(
                sv, prompt, reply, usage, error, started, latency_ms, input_hash,
                prompt_hash, sample_idx, redaction, max_output_tokens,
                projected if attempt == 0 else None, base_url=base_url)
            if error is None or last:
                break
            time.sleep(min(8.0, 0.5 * 2 ** attempt))
        if error is None and cacheable and self.cache_enabled:
            try:
                self.store.cache_put(key, canonical_json(reply).encode("utf-8"))
            except (TypeError, ValueError):
                logger.debug("Reply not cacheable for %s", sv.version_id)
        return CallResult(reply=reply, call_id=call_id, error=error, usage=usage)

    @property
    def retries(self) -> int:
        return self.engine_cfg.runtime.retries if self.engine_cfg else 2

    def _finish_call(self, sv, prompt, reply, usage, error, started, latency_ms,
                     input_hash, prompt_hash, sample_idx, redaction, max_output_tokens,
                     projected, base_url: Optional[str] = None) -> int:
        """Cost, settle the budget, and log one attempt."""
        endpoint_type, model = sv.endpoint_type, sv.model
        cost_usd, tin, tout, estimated = self._actual_cost(
            prompt, model, endpoint_type, max_output_tokens, usage, failed=error is not None,
            base_url=base_url)
        if projected is not None or self._budget_limit() is None:
            self._settle(projected, cost_usd)
        elif cost_usd:
            # A retry was not reserved up front; charge what it cost.
            self.store.add_spend("model_usd", cost_usd)
        call_id = self._log(ModelCall(
            source_version_id=sv.version_id, endpoint_type=endpoint_type, model=model,
            revision=sv.revision, prompt_hash=prompt_hash, input_hash=input_hash,
            response_hash=content_hash(reply)[:32] if reply is not None else "",
            run_id=self.run_id, sample_idx=sample_idx, started_at=started,
            latency_ms=latency_ms, input_tokens=tin, output_tokens=tout,
            cost_usd=cost_usd, estimated=estimated, cache_hit=False,
            redaction=redaction, error=error,
            payload_ref=self._capture(prompt, reply, input_hash)))
        self._add_tally(model, endpoint_type, tin, tout, cost_usd, estimated)
        return call_id

    # === Cost and budget ===================================================

    def _price_overrides(self):
        return (self.app_config.get("ai_budget") or {}).get("prices")

    def _projected_cost(self, prompt, model, endpoint_type, max_out) -> Optional[float]:
        from potato.ai import cost
        est = cost.estimate([prompt], model=model, endpoint_type=endpoint_type,
                            max_output_tokens=max_out,
                            price_overrides=self._price_overrides())
        return est.cost_usd

    def _actual_cost(self, prompt, model, endpoint_type, max_out, usage, failed,
                     base_url: Optional[str] = None):
        from potato.ai import cost
        prices = cost.price_for(model, endpoint_type, self._price_overrides())
        if prices is None and _is_local(endpoint_type, base_url):
            # A server on this machine (or a tunnel to one the study runs)
            # costs nothing per call; "unpriced" would read as a missing price.
            prices = (0.0, 0.0)
        if usage and (usage.get("input_tokens") is not None
                      or usage.get("output_tokens") is not None):
            tin = int(usage.get("input_tokens") or 0)
            tout = int(usage.get("output_tokens") or 0)
            estimated = False
        else:
            tin, tout = cost.estimate_tokens([prompt], 0, 0 if failed else max_out)
            estimated = True
        cost_usd = None if prices is None else round(
            tin / 1e6 * prices[0] + tout / 1e6 * prices[1], 8)
        return cost_usd, tin, tout, estimated

    def _budget_limit(self) -> Optional[float]:
        if self.engine_cfg is None:
            return None
        return self.engine_cfg.budgets.get("model_usd")

    def _reserve(self, projected: Optional[float]) -> None:
        limit = self._budget_limit()
        if limit is None or projected is None:
            return
        with self._budget_lock:
            b = self.store.get_budget("model_usd")
            spent = b.spent if b else 0.0
            if spent + projected > limit + 1e-12:
                raise BudgetExhausted(
                    f"The next call is projected at ${projected:.6f}, which would take "
                    f"model spend to ${spent + projected:.4f} against "
                    f"budgets.model_usd ${limit:.2f}. Nothing was sent.")
            # Hold the projection until the call settles, so concurrent calls
            # cannot all pass the check against the same balance.
            self.store.add_spend("model_usd", projected)

    def _settle(self, projected: Optional[float], actual: Optional[float]) -> None:
        if self._budget_limit() is None:
            if actual:
                self.store.add_spend("model_usd", actual)
            return
        if projected is None:
            if actual:
                self.store.add_spend("model_usd", actual)
            return
        delta = (actual or 0.0) - projected
        if delta:
            self.store.add_spend("model_usd", delta)

    def _add_tally(self, model, endpoint_type, tin, tout, cost_usd, estimated):
        with self._tally_lock:
            t = self._tally.setdefault(model, SpendTally(endpoint_type=endpoint_type))
            t.n_calls += 1
            t.input_tokens += tin or 0
            t.output_tokens += tout or 0
            if cost_usd is not None:
                t.cost_usd = (t.cost_usd or 0.0) + cost_usd
            t.any_estimated = t.any_estimated or estimated

    def flush_spend(self, n_items: int, action: str = "labeling_engine") -> None:
        """Write the calls since the last flush to the project's ``ai_spend``.

        One row per model per chunk. ``estimated`` is false only when every
        call in the row reported measured usage.
        """
        from potato.ai import cost
        with self._tally_lock:
            tally, self._tally = self._tally, {}
        for model, t in tally.items():
            local = (t.endpoint_type or "").lower() in cost.LOCAL_ENDPOINTS
            cost.record_spend(self.app_config, action, cost.CostEstimate(
                n_items=n_items, input_tokens=t.input_tokens,
                output_tokens=t.output_tokens, model=model,
                cost_usd=t.cost_usd if t.cost_usd is not None else (0.0 if local else None),
                priced=t.cost_usd is not None or local, local=local),
                estimated=t.any_estimated)

    # === Logging ===========================================================

    def _log(self, call: ModelCall) -> int:
        [cid] = self.store.add_calls([call])
        return cid

    def _capture(self, prompt: str, reply: Any, input_hash: str) -> Optional[str]:
        """Keep the full prompt and reply, when payload_capture is on."""
        if not self._feature("payload_capture"):
            return None
        directory = os.path.join(self.store.task_dir, "engine_payloads")
        os.makedirs(directory, exist_ok=True)
        name = f"run-{self.run_id or 0}.jsonl"
        with self._payload_lock:
            with open(os.path.join(directory, name), "a", encoding="utf-8") as f:
                f.write(json.dumps({"input_hash": input_hash, "prompt": prompt,
                                    "reply": reply}, default=str) + "\n")
        return f"engine_payloads/{name}#{input_hash}"
