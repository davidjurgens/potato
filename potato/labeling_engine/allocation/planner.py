"""
The planner: one pass that moves every scheme forward.

``Planner.tick`` does, per scheme:

1. register new items and let the cascade label what it has not;
2. draw the first calibration sample, if there is none;
3. give items that arrived after a draw the same inclusion probability as
   the rest of their stratum (a top-up wave), so the sample stays uniform and
   the binomial tests stay valid as live data comes in;
4. certify, when there are new human labels;
5. resolve: accept what the certified rule allows, open requests for the rest;
6. if a contract says more labels would let it certify, draw them, within
   ``budgets.human_labels``;
7. release requests a person has held too long.

The server runs it on a thread every ``runtime.planner_interval`` seconds;
``potato label run`` calls ``tick`` in a loop.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from . import designs

logger = logging.getLogger(__name__)

#: A held request goes back to the pool after this long unanswered.
STALE_AFTER_S = 3600.0


class Planner:

    def __init__(self, engine, item_source: Callable[[Any], List[Any]]):
        self.engine = engine
        self.item_source = item_source
        self._last_done: Dict[str, int] = {}
        self.last_tick: Optional[Dict[str, Any]] = None
        #: scheme -> the latest cascade report, with features.optimize on.
        self.last_optimize: Dict[str, Any] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _no_rule_reason(engine, scheme) -> Optional[str]:
        """Why no machine label can be accepted on this scheme now, or None
        when a rule is in force (or the scheme has no selective_risk
        contract, so there are no machine labels to accept anyway)."""
        status = engine.contract_status(scheme)
        sr = {cid: c for cid, c in status.items() if c.get("kind") == "selective_risk"}
        unmet = [cid for cid, c in sr.items() if c.get("status") != "met"]
        return ("not met: " + ", ".join(unmet)) if unmet else None

    def _people_fallback(self, scheme, ids) -> Optional[Dict[str, Any]]:
        """When no rule accepts machine labels and this pass left nothing
        random open (the sample is complete, nothing could be projected, or
        audits breached), the unlabeled items go to people within the
        budget, as with no machine at all. Without it the study stalled:
        nothing open, items unlabeled, budget unspent, and annotators told
        to come back forever."""
        reason = self._no_rule_reason(self.engine, scheme)
        if reason is None:
            return None
        if self.engine.store.requests(
                schema=scheme.name, status=["open", "assigned"],
                purpose=["calibration", "certification", "distribution"], limit=1):
            return None
        counts = self.engine.resolve(scheme, ids or None, to_people=True)
        return {"reason": reason, "requests_opened": counts.get("requests_opened", 0)}

    def _done_count(self, scheme: str) -> int:
        return self.engine.store.conn.execute(
            "SELECT COUNT(*) FROM human_request WHERE schema_name = ? AND status = 'done'",
            (scheme,)).fetchone()[0]

    def tick(self, predict: bool = True) -> Dict[str, Any]:
        with self._lock:
            started = time.time()
            report: Dict[str, Any] = {"schemes": {}}
            items = self.item_source(self.engine)
            report["items"] = len(items)
            if items:
                self.engine.register_items(items)
            ids = [it.item_id for it in items]
            # One seed per pass, shared by every scheme's top-up wave, so the
            # schemes keep sampling the same items (see designs.draw).
            self._tick_seed = int(started)
            for scheme in self.engine.schemes():
                r: Dict[str, Any] = {}
                try:
                    if predict and items:
                        r["predict"] = self.engine.predict(scheme, items)
                    r["calibration"] = self._ensure_sample(scheme, ids)
                    if predict and items and r["calibration"].get("requests"):
                        # Later tiers label the random sample; it was just
                        # drawn, so run the cascade again (tier 0 skips all).
                        r["predict_sample"] = self.engine.predict(scheme, items)
                    done = self._done_count(scheme.name)
                    if done != self._last_done.get(scheme.name):
                        r["certify"] = {k: v.get("status") for k, v in
                                        self.engine.certify(scheme, auto=True).items()}
                        self._last_done[scheme.name] = done
                    r["resolve"] = self.engine.resolve(scheme, ids or None)
                    r["adjudication"] = self._route_contested(scheme)
                    r["audit"] = len(self.engine.draw_audit(scheme, seed=self._tick_seed))
                    from .. import distill
                    if items and distill.due(self.engine, scheme):
                        entry = distill.distill_scheme(self.engine, scheme, items)
                        if entry:
                            r["distilled"] = {"source": entry["id"],
                                              "n_train": entry["n_train"]}
                            # The new tier labels everything on the next pass.
                            r["predict_distilled"] = self.engine.predict(scheme, items)
                    if self.engine.drift_breached(scheme):
                        r["drift"] = "breach"
                        open_cal = self.engine.store.requests(
                            schema=scheme.name, purpose=["calibration"],
                            status=["open", "assigned"])
                        if not open_cal and ids:
                            _, reqs = self.engine.draw_calibration(
                                scheme, ids, seed=self._tick_seed)
                            r["recalibration_requests"] = len(reqs)
                    r["more"] = self._top_up(scheme, ids)
                    fallback = self._people_fallback(scheme, ids)
                    if fallback:
                        r["to_people"] = fallback
                    if self.engine.cfg.feature("optimize"):
                        # Dev labels only, no model calls: a report of
                        # cheaper cascades, never applied here (applying one
                        # is a config change and a new certification).
                        from ..optimize import cascade_report
                        rep = cascade_report(self.engine, scheme)
                        self.last_optimize[scheme.name] = rep
                        best = rep.get("recommended") or {}
                        r["optimize"] = {"recommended": best.get("tiers"),
                                         "current": list(self.engine.tiers(scheme))}
                except Exception as e:
                    logger.exception("labeling engine: planner failed on %s", scheme.name)
                    r["error"] = f"{type(e).__name__}: {e}"
                report["schemes"][scheme.name] = r
            report["released"] = self.engine.release_stale(
                float(getattr(self.engine.cfg.runtime, "hold_minutes", 60)) * 60
                if self.engine.cfg.runtime else STALE_AFTER_S)
            # A full pass: items registered, every scheme sampled and
            # resolved. Until one has run, nobody can be finished.
            self.engine.planner_passes += 1
            try:
                from .crowd import plan_crowd
                report["crowd"] = plan_crowd(self.engine)
            except Exception as e:
                logger.exception("labeling engine: crowd planning failed")
                report["crowd"] = {"action": "error", "error": str(e)}
            self.last_crowd = report["crowd"]
            report["seconds"] = round(time.time() - started, 3)
            self.last_tick = report
            return report

    def _route_contested(self, scheme) -> int:
        """Send calibration items where people tied to the adjudication queue.

        Only when adjudication is enabled; the queue applies its own
        agreement threshold and participant filters.
        """
        try:
            from potato.adjudication import get_adjudication_manager
            adj = get_adjudication_manager()
        except Exception:
            return 0
        if adj is None or not getattr(adj.adj_config, "enabled", False):
            return 0
        n = 0
        for iid in self.engine.contested_items(scheme):
            try:
                n += bool(adj.try_enqueue_item(iid))
            except Exception:
                logger.debug("could not route %s to adjudication", iid, exc_info=True)
        return n

    def _ensure_sample(self, scheme, ids: List[str]) -> Dict[str, Any]:
        """First draw; then a top-up wave for items that arrived since."""
        store = self.engine.store
        pis = store.get_items_meta(ids, "pi")
        have = {i: (pis.get(i) or {}).get(scheme.name) for i in ids}
        sampled_before = [p for p in have.values() if p]
        new = [i for i, p in have.items() if not p]
        if not sampled_before:
            if not ids:
                return {}
            design_id, reqs = self.engine.draw_calibration(scheme, ids)
            return {"design": design_id, "requests": len(reqs)}
        if not new:
            return {}
        # Bring newcomers to the inclusion probability the others have.
        target = max(sampled_before)
        design_id, reqs = designs.draw(
            store, scheme.name, new, designs.rates_uniform(new, target),
            seed=getattr(self, "_tick_seed", 0), params={"top_up_to": target},
            purpose="calibration", dev_fraction=self.engine.cfg.humans.dev_fraction,
            pool=self.engine.cfg.humans.pools[0], visibility="blind", priority=5.0,
            shared_key="newcomers", max_requests=self.engine.calibration_cap(scheme))
        self.engine._sync_human_spend()
        return {"design": design_id, "requests": len(reqs), "top_up_to": target}

    def _top_up(self, scheme, ids: List[str]) -> Optional[Dict[str, Any]]:
        """Draw more calibration labels when a contract says they would help."""
        status = self.engine.contract_status(scheme)
        wanted, overlap_wanted = 0, 0
        for res in status.values():
            if res.get("status") in ("insufficient",):
                proj = res.get("projection") or {}
                wanted = max(wanted, int(proj.get("more_calibration_labels", 0) or 0))
                overlap_wanted = max(overlap_wanted, int(proj.get("more_overlap_items", 0) or 0))
        if overlap_wanted and not wanted:
            open_cal = len(self.engine.store.requests(
                schema=scheme.name, purpose=["calibration"], status=["open", "assigned"]))
            if open_cal:
                return {"waiting_on": open_cal}
            added = self.engine.widen_overlap(scheme, overlap_wanted,
                                              seed=getattr(self, "_tick_seed", 0))
            return {"overlap_requests": len(added)}
        if wanted <= 0 or not ids:
            return None
        store = self.engine.store
        open_cal = len(store.requests(schema=scheme.name, purpose=["calibration"],
                                      status=["open", "assigned"]))
        if open_cal:
            return {"waiting_on": open_cal}   # finish the current wave first
        left = self.engine.calibration_cap(scheme)
        if left is not None:
            wanted = min(wanted, left)
        if wanted <= 0:
            return {"budget_exhausted": True}
        pis = store.get_items_meta(ids, "pi")
        cur = max(((pis.get(i) or {}).get(scheme.name) or 0.0) for i in ids)
        target = min(1.0, designs.combine(cur, wanted / max(1, len(ids))))
        rate = designs.wave_rate_for_target(cur, target)
        design_id, reqs = designs.draw(
            store, scheme.name, ids, designs.rates_uniform(ids, rate),
            seed=getattr(self, "_tick_seed", 0), params={"rate": rate, "reason": "projection"},
            purpose="calibration", dev_fraction=self.engine.cfg.humans.dev_fraction,
            pool=self.engine.cfg.humans.pools[0], visibility="blind", priority=5.0,
            shared_key="projection", max_requests=left)
        self.engine._sync_human_spend()
        return {"design": design_id, "requests": len(reqs), "rate": rate}


class BackgroundPlanner(Planner):
    """``Planner.tick`` on a daemon thread, every ``runtime.planner_interval``."""

    def __init__(self, engine, item_source):
        super().__init__(engine, item_source)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.holder = engine.store.writer_name("server")

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="labeling-engine-planner",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.engine.store.release_writer(self.holder)

    def _loop(self) -> None:
        interval = self.engine.cfg.runtime.planner_interval
        # Let the server finish loading its items before the first pass.
        self._stop.wait(min(2.0, interval))
        while not self._stop.is_set():
            try:
                if self.engine.store.acquire_writer(self.holder):
                    with self.engine.store.holding_writer(self.holder):
                        self.tick()
            except Exception:
                logger.exception("labeling engine: planner tick failed")
            self._stop.wait(interval)
