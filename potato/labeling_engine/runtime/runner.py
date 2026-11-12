"""
Running a source over items: chunked, resumable, cancellable, capped.

``Runner.predict`` labels ``items`` for one scheme with one source:

- Items that already have a prediction from this exact source version are
  skipped, so a run that was killed resumes where it stopped and a second
  run with nothing changed does no work.
- Work is committed per chunk of ``runtime.batch_size`` items. A chunk that
  dies part-way commits nothing, but its calls are already in the call log
  (they were made, and may have been paid for), and their replies are in the
  cache, so the retry costs nothing for the items that had answered.
- Before each chunk the project-wide ``ai_budget.cap_usd`` is checked against
  that chunk's projected cost. Each call is also checked against the engine's
  own ``budgets.model_usd`` (``RunContext.call``).
- ``cancel(run_id)`` from another thread stops the run at the next chunk.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from ..items import ItemView
from ..model.records import Run
from ..schemes import SchemeSpec
from ..sources.base import Source, SourceError
from .calls import BudgetExhausted, RunContext

logger = logging.getLogger(__name__)


@dataclass
class RunSummary:
    run_id: int
    source_id: str
    scheme: str
    source_version_id: str
    status: str
    n_requested: int = 0
    n_skipped: int = 0
    n_predicted: int = 0
    n_ok: int = 0
    n_abstain: int = 0
    n_error: int = 0
    message: Optional[str] = None

    def to_dict(self) -> Dict:
        return dict(self.__dict__)


class Runner:

    def __init__(self, store, app_config, engine_cfg=None):
        self.store = store
        self.app_config = app_config or {}
        self.engine_cfg = engine_cfg
        self._contexts: Dict[int, RunContext] = {}
        self._lock = threading.Lock()

    @property
    def batch_size(self) -> int:
        return self.engine_cfg.runtime.batch_size if self.engine_cfg else 32

    def cancel(self, run_id: int) -> None:
        self.store.update_run(run_id, status="cancelled")
        with self._lock:
            ctx = self._contexts.get(run_id)
        if ctx is not None:
            ctx.cancel()

    def _check_cap(self, source: Source, scheme: SchemeSpec,
                   chunk: Sequence[ItemView]) -> None:
        from potato.ai import cost
        if cost.cap_for(self.app_config) is None:
            return
        prompt_chars = len(source.prompt_template(scheme))
        calls = 1
        method = (source.cfg.confidence or {}).get("method")
        if method == "k_sample":
            calls = max(2, int((source.cfg.confidence or {}).get("samples", 5)))
        projected = cost.estimate(
            [it.text for it in chunk], model=source.cfg.model,
            endpoint_type=source.cfg.endpoint_type, prompt_overhead_chars=prompt_chars,
            max_output_tokens=0 if source.kind == "decision" else source.cfg.max_tokens,
            calls_per_item=calls,
            price_overrides=(self.app_config.get("ai_budget") or {}).get("prices"))
        spent = cost.total_spend(self.app_config).get("cost_usd", 0.0) or 0.0
        cost.check_before_running(self.app_config, projected, spent)

    def predict(self, source: Source, scheme: SchemeSpec, items: Sequence[ItemView],
                *, resume: bool = True, max_items: Optional[int] = None) -> RunSummary:
        if not source.supports(scheme):
            raise SourceError(source.unsupported_reason(scheme))
        sv = source.version(scheme)
        self.store.register_source_version(sv)
        done = (self.store.predicted_item_ids(scheme.name, sv.version_id)
                if resume else set())
        todo = [it for it in items if it.item_id not in done]
        if max_items is not None:
            todo = todo[:max(0, int(max_items))]
        if not todo:
            # Nothing to label: no run row. An idle planner pass otherwise
            # wrote two empty runs every interval.
            return RunSummary(run_id=0, source_id=source.id, scheme=scheme.name,
                              source_version_id=sv.version_id, status="done",
                              n_requested=len(items), n_skipped=len(items))

        run = Run(kind="predict", source_version_id=sv.version_id,
                  config_hash=self.engine_cfg.config_hash() if self.engine_cfg else "",
                  cursor={"scheme": scheme.name, "source": source.id,
                          "total": len(todo), "done": 0})
        run_id = self.store.start_run(run)
        ctx = RunContext(self.store, self.app_config, self.engine_cfg, run_id=run_id)
        with self._lock:
            self._contexts[run_id] = ctx
        summary = RunSummary(run_id=run_id, source_id=source.id, scheme=scheme.name,
                             source_version_id=sv.version_id, status="running",
                             n_requested=len(items), n_skipped=len(items) - len(todo))
        self.store.upsert_items([{"item_id": it.item_id,
                                  "content_hash": it.content_hash(),
                                  "stratum": it.stratum} for it in todo])
        from ..families import family_for
        family = family_for(scheme)
        off_scheme: List[str] = []
        try:
            for start in range(0, len(todo), self.batch_size):
                if ctx.cancelled or self.store.run_status(run_id) == "cancelled":
                    summary.status = "cancelled"
                    break
                chunk = todo[start:start + self.batch_size]
                self._check_cap(source, scheme, chunk)
                preds = source.predict_batch(chunk, scheme, ctx, sv)
                for p in preds:
                    p.run_id = run_id
                    if p.status == "ok":
                        value, why = family.coerce(p.value)
                        if why is not None:
                            p.status, p.value = "error", None
                            p.reasoning = f"not a valid answer for {scheme.name}: {why}"
                            off_scheme.append(why)
                        else:
                            p.value = value
                self.store.add_predictions(preds)
                ctx.flush_spend(len(chunk))
                summary.n_predicted += len(preds)
                for p in preds:
                    if p.status == "ok":
                        summary.n_ok += 1
                    elif p.status == "abstain":
                        summary.n_abstain += 1
                    else:
                        summary.n_error += 1
                self.store.update_run(run_id, cursor={**run.cursor,
                                                      "done": summary.n_predicted})
            else:
                summary.status = "done"
        except BudgetExhausted as e:
            summary.status, summary.message = "paused", str(e)
        except Exception as e:
            from potato.ai.cost import SpendCapExceeded
            if isinstance(e, SpendCapExceeded):
                summary.status, summary.message = "paused", str(e)
            else:
                summary.status, summary.message = "failed", f"{type(e).__name__}: {e}"
                if isinstance(e, SourceError):
                    # A configuration problem the message names in full.
                    logger.error("Labeling run %s failed: %s", run_id, e)
                else:
                    logger.exception("Labeling run %s failed", run_id)
        finally:
            ctx.flush_spend(0)
            with self._lock:
                self._contexts.pop(run_id, None)
        if off_scheme and not summary.message:
            summary.message = (f"{len(off_scheme)} answer(s) were not valid for "
                               f"{scheme.name} and count as errors; first: {off_scheme[0]}")
        self.store.update_run(run_id, status=summary.status, error=summary.message)
        return summary
