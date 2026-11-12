"""
The engine for one study: predict, sample, certify, resolve.

``Engine`` is the one object the server, the CLI and the SDK drive. It owns
no long-lived threads; a caller decides when to predict, when to draw a
calibration sample and when to certify. The planner (``allocation/planner``)
is one such caller.

The lifecycle for a scheme:

1. ``register_items`` and ``predict``: every cascade tier labels what it is
   asked to (tier 0 everything; later tiers the calibration sample and
   whatever earlier tiers escalate).
2. ``draw_calibration``: a random, blind sample of items is opened as human
   requests, each recording its inclusion probability and dev/cert split.
3. Humans answer through the normal annotation pages; ``record_human_label``
   closes their requests.
4. ``certify``: each contract evaluates the calibration view. Results are
   stored per contract and cascade version.
5. ``resolve``: the certified rule decides which machine labels are accepted;
   the rest become verify/resolve requests for humans.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import Counter
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .allocation import designs
from .families import Family, family_for
from .config import EngineConfig, parse_engine_config
from .contracts import (CalibrationView, CalItem, PopItem, TierPred, build_contract)
from .items import ItemView
from .model.records import (ContractVersion, HumanRequest, RANDOM_PURPOSES,
                            ResolvedLabel, content_hash)
from .runtime import Runner
from .schemes import SchemeSpec, scheme_specs
from .sources import Source, SourceError, build_source
from .store import EngineStore

logger = logging.getLogger(__name__)


def _majority(values: Sequence[Any]) -> Any:
    """The most common label; ties go to the earliest given."""
    if not values:
        return None
    counts = Counter(_hashable(v) for v in values)
    best = max(counts.values())
    for v in values:
        if counts[_hashable(v)] == best:
            return v


def _hashable(v):
    import json
    return v if isinstance(v, (str, int, float, bool, type(None))) else json.dumps(
        v, sort_keys=True, default=str)


def _threshold(rule: Dict[str, Any], tier_id: str, key: str) -> Optional[float]:
    """A rule's threshold for this tier and class. A contract that is not
    per-class keys its thresholds "*"; on a scheme where another contract is
    per-class, items are looked up by class, so fall back to "*". Without it
    an overall contract that was met accepted nothing."""
    cells = rule.get(tier_id) or {}
    return cells[key] if key in cells else cells.get("*")


def unsupported_schemes(app_config: Dict[str, Any], cfg: EngineConfig,
                        source_for=None, every_scheme: bool = False) -> Dict[str, List[str]]:
    """{scheme name: [why each cascade source cannot label it]} for every
    scheme a contract names (or, with ``every_scheme``, every scheme the
    engine would take) and no cascade source supports."""
    named = {c.schema for c in cfg.contracts}
    taken = set(cfg.schemas) if cfg.schemas else None
    out: Dict[str, List[str]] = {}
    for spec in scheme_specs(app_config):
        if every_scheme:
            if taken is not None and spec.name not in taken:
                continue
        elif spec.name not in named:
            continue
        reasons = []
        for sid in cfg.cascade:
            scfg = cfg.source(sid)
            if scfg is None:
                continue
            if scfg.schemas and spec.name not in scfg.schemas:
                reasons.append(f"source {sid!r} is limited to {scfg.schemas}")
                continue
            try:
                src = source_for(sid) if source_for else build_source(scfg, app_config, cfg)
                if src.supports(spec):
                    reasons = None
                    break
                reasons.append(src.unsupported_reason(spec))
            except SourceError as e:
                reasons.append(str(e))
        if reasons is not None:
            out[spec.name] = reasons or ["the cascade is empty"]
    return out


class Engine:

    def __init__(self, app_config: Dict[str, Any], task_dir: Optional[str] = None,
                 engine_cfg: Optional[EngineConfig] = None):
        self.app_config = app_config
        self.cfg = engine_cfg or parse_engine_config(app_config)
        self.task_dir = task_dir or app_config.get("task_dir", ".")
        self.store = EngineStore(self.task_dir)
        self.runner = Runner(self.store, app_config, self.cfg)
        self._sources: Dict[str, Source] = {}
        self._lock = threading.RLock()
        #: Completed planner passes in this process (Planner.tick).
        self.planner_passes = 0
        #: user id -> {field: value}: annotator attributes for distributional
        #: ``groups_by`` (the server reads prestudy answers; SDK users set it).
        self.user_attributes: Optional[Callable[[str], Dict[str, str]]] = None
        #: Called with (user_id, item_id) for each hold release_stale frees.
        self.release_listeners: List[Callable[[str, str], None]] = []
        from .model.records import Budget
        for kind, limit in self.cfg.budgets.items():
            self.store.set_budget(Budget(kind=kind, limit=limit))
        for kind in ("model_usd", "human_usd", "human_labels"):
            # A limit the config no longer sets (one `label run --budget-usd`
            # override, or a removed key) does not linger in the store and
            # bind later runs; the spend recorded so far stays.
            if kind not in self.cfg.budgets:
                old = self.store.get_budget(kind)
                if old is not None and old.limit is not None:
                    self.store.set_budget(Budget(kind=kind, limit=None))
        self._configured_cascade = list(self.cfg.cascade)
        self.reload_distilled()

    def reload_distilled(self) -> None:
        """Put distilled tiers (``distill.py``) ahead of the configured cascade.

        Only with ``features.distill`` on; turning it off goes back to the
        configured cascade, and its certificates are the ones that apply.
        """
        from .config.schema import SourceConfig
        self.cfg.sources = [s for s in self.cfg.sources if s.kind != "trained"
                            or not str(s.id).startswith("distilled-")]
        self.cfg.cascade = list(self._configured_cascade)
        with self._lock:
            self._sources = {k: v for k, v in self._sources.items()
                             if not k.startswith("distilled-")}
        if not self.cfg.feature("distill"):
            return
        from .distill import KV_KEY
        for scheme_name, entry in sorted((self.store.kv_get(KV_KEY, {}) or {}).items()):
            raw = {k: entry[k] for k in ("id", "kind", "schemas", "options")}
            self.cfg.sources.append(SourceConfig(
                id=raw["id"], kind="trained", endpoint_type="trained",
                schemas=raw["schemas"], options=dict(raw["options"]), raw=raw))
            self.cfg.cascade.insert(0, raw["id"])

    # === Schemes, sources, tiers ===========================================

    def schemes(self) -> List[SchemeSpec]:
        specs = scheme_specs(self.app_config, self.cfg.schemas)
        return [s for s in specs if self.tiers(s)]

    def unsupported_schemes(self) -> Dict[str, List[str]]:
        """Schemes a contract names that no cascade source can label, with each
        source's reason. They are not in ``schemes()``, so nothing would
        otherwise say why their contracts never run."""
        return unsupported_schemes(self.app_config, self.cfg,
                                   lambda sid: self.source(sid))

    def scheme(self, name: str) -> SchemeSpec:
        for s in scheme_specs(self.app_config):
            if s.name == name:
                return s
        raise KeyError(f"no annotation scheme {name!r}")

    def source(self, source_id: str) -> Source:
        with self._lock:
            if source_id not in self._sources:
                cfg = self.cfg.source(source_id)
                if cfg is None:
                    raise SourceError(f"no source {source_id!r}")
                self._sources[source_id] = build_source(cfg, self.app_config, self.cfg)
            return self._sources[source_id]

    def tiers(self, scheme: SchemeSpec) -> List[str]:
        """Cascade source ids that can label this scheme, in order."""
        out = []
        for sid in self.cfg.cascade:
            cfg = self.cfg.source(sid)
            if cfg is None or (cfg.schemas and scheme.name not in cfg.schemas):
                continue
            try:
                if self.source(sid).supports(scheme):
                    out.append(sid)
            except SourceError as e:
                logger.warning("%s", e)
        return out

    def family(self, scheme: SchemeSpec) -> Family:
        """The scheme's correctness notion, with the tolerance its contracts set."""
        tol = None
        for c in self.cfg.contracts:
            if c.schema == scheme.name and c.tolerance is not None:
                tol = c.tolerance if tol is None else min(tol, c.tolerance)
        return family_for(scheme, tol)

    def tier_versions(self, scheme: SchemeSpec) -> List[str]:
        return [self.source(sid).version(scheme).version_id for sid in self.tiers(scheme)]

    def cascade_hash(self, scheme: SchemeSpec) -> str:
        return content_hash({"tiers": self.tier_versions(scheme),
                             "scheme": scheme.schema_hash()})[:32]

    # === Items and predictions =============================================

    def _by_fields(self) -> List[str]:
        return sorted({c.raw.get("by") for c in self.cfg.contracts
                       if c.kind == "ppi" and c.raw.get("by")})

    def register_items(self, items: Iterable[ItemView]) -> int:
        """Record items; with a ppi ``by``, also the item fields it groups by
        (the engine keeps hashes, not item data, so they are copied here)."""
        by = self._by_fields()

        def row(it):
            r = {"item_id": it.item_id, "content_hash": it.content_hash(),
                 "stratum": it.stratum}
            fields = {f: str((it.data or {}).get(f)) for f in by
                      if (it.data or {}).get(f) is not None}
            if fields:
                r["meta"] = {"fields": fields}
            return r
        return self.store.upsert_items(row(it) for it in items)

    def random_request_items(self, scheme: str) -> set:
        return {r.item_id for r in self.store.requests(schema=scheme,
                                                       purpose=list(RANDOM_PURPOSES))}

    def predict(self, scheme: SchemeSpec, items: Sequence[ItemView],
                max_items: Optional[int] = None) -> List[Dict[str, Any]]:
        """Run the cascade. Tier 0 labels every item; later tiers label the
        random sample and whatever the current rule escalates to them."""
        summaries = []
        tiers = self.tiers(scheme)
        route = self._current_route(scheme)
        sampled = self.random_request_items(scheme.name)
        failed_before = False
        for t, sid in enumerate(tiers):
            if t == 0 or failed_before:
                # Every item reaches the first tier that runs: a failed tier
                # escalates nothing, so after one the next labels everything.
                todo = list(items)
            else:
                todo = [it for it in items
                        if it.item_id in sampled or self._escalated(scheme, it.item_id,
                                                                    t, tiers, route)]
            s = self.runner.predict(self.source(sid), scheme, todo, max_items=max_items)
            summaries.append(s.to_dict())
            if s.status in ("paused", "cancelled"):
                # A spend cap or a cancel applies to every tier.
                break
            # A failed tier (a misconfigured endpoint) does not stop the
            # others; its items go on, and run and status report it.
            failed_before = failed_before or s.status == "failed"
        return summaries

    #: Dev labels a tier needs in a class before "no threshold" is taken to
    #: mean "this tier cannot be trusted here, escalate" rather than "too
    #: early to tell, wait for calibration labels".
    MIN_DEV_TO_ESCALATE = 30

    def _current_route(self, scheme: SchemeSpec):
        """(route, cells) from the latest selective-risk result, or None."""
        for c in self.cfg.contracts:
            if c.kind == "selective_risk" and c.schema == scheme.name:
                cv = self.store.latest_contract_version(c.id)
                if cv and cv.cascade_hash == self.cascade_hash(scheme):
                    m = cv.result.get("metrics", {})
                    return m.get("route") or {}, m.get("cells") or {}
        return None

    def route_stop(self, tiers: Sequence[str], tier_preds: Sequence[Any], route,
                   per_class: bool, class_of=None) -> Tuple[Optional[int], bool]:
        """Where the cascade stops for one item: ``(tier index, complete)``.

        The one routing rule, used both to decide which items later tiers
        label and to compute the cascade's output for the estimators. A tier
        keeps an item when it answered with confidence at or above its routing
        threshold, or when it has no threshold yet because too few dev labels
        have measured it (the expensive tiers wait until the cheap ones are
        judged). Otherwise the item goes on. Past the last tier the item stays
        with the last tier that answered.

        ``tier_preds[j]`` is tier j's prediction (with ``status``, ``value``
        and ``raw_conf`` or ``conf``) or None. ``complete`` is False when the
        route reaches a tier that has not labeled the item yet.
        """
        if not route:
            route = ({}, {})
        rmap, cells = route
        last_answer = None
        for j, tid in enumerate(tiers):
            p = tier_preds[j] if j < len(tier_preds) else None
            if p is None:
                return last_answer, False
            status = getattr(p, "status", "ok")
            if status != "ok" or getattr(p, "value", None) is None:
                continue
            last_answer = j
            key = (class_of(p.value) if class_of else str(p.value)) if per_class else "*"
            lam = _threshold(rmap, tid, key)
            conf = float(getattr(p, "raw_conf", None) if hasattr(p, "raw_conf")
                         else getattr(p, "conf", 0.0) or 0.0)
            if lam is None:
                n_dev = (cells.get(f"{tid}:{key}") or {}).get("n_dev", 0)
                if n_dev < self.MIN_DEV_TO_ESCALATE:
                    return j, True
                continue
            if conf >= lam:
                return j, True
        return last_answer, True

    def _escalated(self, scheme, item_id, t, tiers, route) -> bool:
        """Whether the route carries this item to tier ``t``."""
        if not route:
            return False
        per_class = self._per_class(scheme)
        versions = self.tier_versions(scheme)
        preds = []
        for j in range(t):
            p = self.store.current_predictions(scheme.name, versions[j], [item_id]).get(item_id)
            preds.append(p)
        preds.append(None)  # tier t itself has not been asked yet
        stop, complete = self.route_stop(tiers[:t + 1], preds, route, per_class,
                                         self.family(scheme).class_of)
        return not complete or (stop is not None and stop >= t)

    def _per_class(self, scheme: SchemeSpec) -> bool:
        """Per-class routing, if a selective-risk contract asks for it and the
        family has classes (a box set or a number does not)."""
        return self.family(scheme).per_class_ok and any(
            c.per_class for c in self.cfg.contracts
            if c.kind == "selective_risk" and c.schema == scheme.name)

    # === Human-label budget ================================================

    def human_labels_remaining(self) -> Optional[int]:
        """Requests the engine may still open under ``budgets.human_labels``
        (None: no cap). Counted when a request is opened, so the cap holds
        however many of them are later answered."""
        cap = self.cfg.budgets.get("human_labels")
        if cap is None:
            return None
        return max(0, int(cap) - self.store.count_opened_requests())

    def human_work_remaining(self) -> Optional[str]:
        """Why people may still be asked for something, or None when nothing
        more will be opened: no request is open or held, and either the
        human-label budget is spent or every item has its final label.

        Annotators who have caught up wait on a "come back later" page only
        while this is not None; otherwise their part of the study is over and
        they go on to the completion page (and a crowd worker gets a code)."""
        # Nothing can be finished before the planner has looked: a person who
        # opened the link in the first seconds of a study was otherwise told
        # they were done, with a completion code, before any request existed.
        if not self.planner_passes:
            return "the planner has not run yet"
        n_items = self.store.item_count()
        if not n_items:
            return "no items are registered yet"
        if self.store.requests(status=["open", "assigned"], limit=1):
            return "requests are open"
        remaining = self.human_labels_remaining()
        if remaining is not None and remaining <= 0:
            return None
        for s in self.schemes():
            if not self.store.requests(schema=s.name, purpose=list(RANDOM_PURPOSES),
                                       limit=1):
                return f"no {s.name} sample has been drawn yet"
            done = self.store.conn.execute(
                "SELECT COUNT(DISTINCT item_id) FROM resolved_label WHERE schema_name = ?"
                " AND status = 'accepted'", (s.name,)).fetchone()[0]
            if done < n_items:
                return f"{n_items - done} {s.name} items have no final label yet"
        return None

    def _sync_human_spend(self) -> None:
        if self.cfg.budgets.get("human_labels") is None:
            return
        b = self.store.get_budget("human_labels")
        n = float(self.store.count_opened_requests())
        if b is not None and b.spent != n:
            self.store.add_spend("human_labels", n - b.spent)

    def open_requests(self, requests: Sequence[HumanRequest],
                      order_key=None) -> List[int]:
        """Open non-random requests within the human-label budget.

        Random-sample requests go through ``designs.draw(max_requests=...)``,
        which keeps their inclusion probabilities exact under the cap; this
        is for the rest (overlap copies, resolve, verify, audit), cut in
        ``order_key`` order when the budget runs short.
        """
        reqs = list(requests)
        left = self.human_labels_remaining()
        if left is not None and len(reqs) > left:
            if order_key is not None:
                reqs.sort(key=order_key)
            reqs = reqs[:left]
        ids = self.store.add_requests(reqs) if reqs else []
        self._sync_human_spend()
        return ids

    def _overlap_plan(self, scheme: SchemeSpec) -> Tuple[float, int]:
        """(share of calibration items sent to more people, people per item)."""
        frac, k = self.cfg.humans.overlap, self.cfg.humans.overlap_k
        if any(c.kind == "distributional" and c.schema == scheme.name
               for c in self.cfg.contracts):
            # Every calibration item needs a distribution of people.
            frac, k = 1.0, max(k, self.cfg.humans.distribution_k)
        if frac <= 0 or k < 2:
            return 0.0, 1
        return frac, k

    def calibration_cap(self, scheme: SchemeSpec) -> Optional[int]:
        """How many new calibration items fit in the human-label budget,
        leaving room for each one's overlap copies."""
        left = self.human_labels_remaining()
        if left is None:
            return None
        frac, k = self._overlap_plan(scheme)
        return int(left // (1 + frac * (k - 1)))

    # === Calibration sample ================================================

    def calibration_rate(self, scheme: SchemeSpec, n_items: int) -> float:
        rate = self.cfg.humans.calibration_rate
        if rate != "auto":
            return float(rate)
        # Auto: enough labels for each class to be checkable, without asking
        # humans for more than a fifth of a small study.
        per_class = self._per_class(scheme)
        k = len(scheme.labels) if per_class else 1
        target = max(200, 80 * k)
        cap = self.cfg.budgets.get("human_labels")
        if cap is not None:
            target = min(target, int(cap * 0.8))
        return min(0.2 if n_items > 1000 else 0.5, target / max(1, n_items))

    def draw_calibration(self, scheme: SchemeSpec, item_ids: Sequence[str],
                         rate: Optional[float] = None, seed: int = 0) -> Tuple[int, List[int]]:
        """Open blind random calibration requests (one Bernoulli wave)."""
        rate = self.calibration_rate(scheme, len(item_ids)) if rate is None else rate
        pool = self.cfg.humans.pools[0]
        design_id, ids = designs.draw(
            self.store, scheme.name, list(item_ids), designs.rates_uniform(item_ids, rate),
            seed=seed, params={"rate": rate, "overlap": self.cfg.humans.overlap,
                               "overlap_k": self.cfg.humans.overlap_k},
            purpose="calibration", dev_fraction=self.cfg.humans.dev_fraction, pool=pool,
            visibility="blind", priority=5.0, shared_key="calibration",
            max_requests=self.calibration_cap(scheme))
        self._sync_human_spend()
        ids += self._add_overlap(scheme, ids, seed)
        return design_id, ids

    def widen_overlap(self, scheme: SchemeSpec, n_items: int, seed: int = 0) -> List[int]:
        """Send ``n_items`` more calibration items, already labeled once, to
        ``overlap_k`` people in all. Cheaper than new items when what is short
        is items labeled by several people (the alt-test)."""
        k = max(2, self.cfg.humans.overlap_k)
        per_item: Dict[str, List[HumanRequest]] = {}
        for r in self.store.requests(schema=scheme.name, purpose=["calibration"]):
            if r.status != "cancelled":
                per_item.setdefault(r.item_id, []).append(r)
        singles = sorted((iid for iid, rs in per_item.items() if len(rs) < k),
                         key=lambda iid: designs.uniform(seed, "widen", iid))
        extra = []
        for iid in singles[:max(0, n_items)]:
            r = per_item[iid][0]
            for _ in range(k - len(per_item[iid])):
                extra.append(HumanRequest(
                    item_id=iid, schema=r.schema, purpose="calibration",
                    inclusion_prob=r.inclusion_prob, design_id=r.design_id, split=r.split,
                    visibility="blind", pool=r.pool, priority=r.priority))
        return self.open_requests(extra)

    def _add_overlap(self, scheme: SchemeSpec, request_ids: Sequence[int],
                     seed: int) -> List[int]:
        """Send a share of the new calibration items to more people.

        The extra requests copy the original's design, inclusion probability
        and split, so estimators see one item labeled by several people. The
        claim rule keeps one person from taking two requests on an item.
        """
        frac, k = self._overlap_plan(scheme)
        if frac <= 0:
            return []
        extra = []
        for rid in request_ids:
            r = self.store.get_request(rid)
            if r is None or designs.uniform(seed, "overlap", r.item_id) >= frac:
                continue
            for _ in range(k - 1):
                extra.append(HumanRequest(
                    item_id=r.item_id, schema=r.schema, purpose=r.purpose,
                    inclusion_prob=r.inclusion_prob, design_id=r.design_id,
                    split=r.split, visibility=r.visibility, pool=r.pool,
                    priority=r.priority))
        return self.open_requests(
            extra, order_key=lambda r: designs.uniform(seed, "overlap-cap", r.item_id))

    # === Human labels ======================================================

    def open_request_for(self, user_id: str, item_id: str, scheme: str
                         ) -> Optional[HumanRequest]:
        """The request a save by ``user_id`` answers: one the engine served
        them and they still hold. An unassigned request is not theirs to
        close. They were never shown it as a request (a blind one in
        particular was not blind to them: they may have reached the item by
        go_to or a stale tab, with suggestions on), and an overlap copy of an
        item they already answered would make one person count as two
        raters. Such a save is their own label: an edit of their earlier
        answer, or organic."""
        held = self.store.requests(schema=scheme, item_id=str(item_id),
                                   status=["assigned"], user=user_id)
        return held[0] if held else None

    def record_human_label(self, item_id: str, scheme: str, label: Any, user_id: str,
                           request_id: Optional[int] = None) -> Optional[int]:
        """Close the request this label answers, or record it as organic.

        Without ``request_id`` the label answers a request only if the engine
        served it to this person and they still hold it (``claim_requests``).
        A label with no such request (an annotator labeling outside the
        engine's queue) is kept as ``purpose='organic'`` with no inclusion
        probability: it can train and resolve, never estimate or certify.
        """
        req = self.store.get_request(request_id) if request_id else \
            self.open_request_for(user_id, item_id, scheme)
        now = time.time()
        if req is not None and req.status in ("open", "assigned"):
            self.store.update_request(req.id, status="done", label=label, user_id=user_id,
                                      completed_at=now, assigned_user=user_id)
            return req.id
        # A person saving an item they already answered (every navigation
        # saves) is the same answer, or an edit of it. An edit replaces the
        # label on their request, so a changed cert label is seen by certify;
        # it is not a second, organic label.
        mine = [r for r in self.store.requests(schema=scheme, item_id=str(item_id),
                                               status=["done"])
                if r.user_id == user_id]
        if mine:
            prior = mine[0]
            if prior.label != label:
                self.store.update_request(prior.id, label=label, completed_at=now)
            return prior.id
        [rid] = self.store.add_requests([HumanRequest(
            item_id=str(item_id), schema=scheme, purpose="organic", inclusion_prob=None,
            visibility="shown", status="done", label=label, user_id=user_id,
            assigned_user=user_id, completed_at=now)])
        return rid

    # === Serving requests to people =======================================

    #: Order in which a person's next request is chosen. Adjudication unblocks
    #: a decision; certification requests (a contract asking for more
    #: held-out labels) decide whether anything can be accepted at all;
    #: calibration (dev and cert mixed) fits and tests the thresholds; then
    #: the items the machines could not do; audit last, at its own rate.
    PURPOSE_ORDER = ("adjudicate", "certification", "calibration", "distribution",
                     "resolve", "verify", "audit", "gold")

    def _purpose_rank(self, r: HumanRequest) -> Tuple[int, float, str]:
        # Calibration requests of both splits share one rank, so dev and cert
        # fill together. Serving cert first left dev empty for the first
        # half of the sample: no threshold could be chosen and no projection
        # made until the cert split was complete.
        purpose = r.purpose
        try:
            rank = self.PURPOSE_ORDER.index(purpose)
        except ValueError:
            rank = len(self.PURPOSE_ORDER)
        # Within a purpose, a fixed random order rather than file order: the
        # requests answered so far are then a random subset of the sample,
        # so a threshold chosen and a projection made before the sample is
        # finished come from random labels, not the first rows of the file.
        # Salted by study, so two studies of one corpus are not served the
        # same prefix.
        import hashlib
        study = self.app_config.get("annotation_task_name") or ""
        shuffle = hashlib.sha256(f"serve:{study}:{r.id}".encode()).hexdigest()
        return rank, -(r.priority or 0.0), shuffle

    def _labeled_by(self, user_id: str) -> set:
        return {(r.item_id, r.schema) for r in self.store.requests(status=["done"])
                if r.user_id == user_id}

    def claim_requests(self, user_id: str, n: int = 1, pool: Optional[str] = None,
                       exclude: Iterable[str] = ()) -> List[HumanRequest]:
        """Assign up to ``n`` open requests to ``user_id`` and return them.

        Requests already assigned to this user come first, so a reload serves
        the same item. A person never gets an item they have already labeled
        for that scheme: a second label from the same person is not an
        independent check.

        ``n`` counts items. Taking an item takes every open request on it
        that this person can answer, one per scheme: the page asks every
        question at once, and a second person sent the same item for its
        other scheme had their answer to the first recorded as organic while
        the first person's request for it sat held.
        """
        with self._lock:
            mine = [r for r in self.store.requests(status=["assigned"], user=user_id)]
            excluded = set(exclude)
            done = self._labeled_by(user_id)
            out, taken = [], set()
            # One request per (item, scheme) per person: an overlap copy is for
            # someone else.
            held_pairs = {(r.item_id, r.schema) for r in mine}
            for r in mine:
                if r.item_id in excluded or r.item_id in taken or len(out) >= n:
                    continue
                out.append(r)
                taken.add(r.item_id)
            candidates = self.store.requests(status=["open"], pool=pool)
            candidates.sort(key=self._purpose_rank)
            by_item: Dict[str, List[HumanRequest]] = {}
            for r in candidates:
                by_item.setdefault(r.item_id, []).append(r)
            now = time.time()

            def take(r):
                self.store.update_request(r.id, status="assigned", assigned_user=user_id,
                                          assigned_at=now)
                r.status, r.assigned_user = "assigned", user_id
                held_pairs.add((r.item_id, r.schema))

            for r in candidates:
                if r.status != "open" or (r.item_id, r.schema) in done \
                        or (r.item_id, r.schema) in held_pairs:
                    continue
                if r.item_id in taken:
                    # An item already in hand: its other schemes come along.
                    take(r)
                    continue
                if len(out) >= n or r.item_id in excluded:
                    continue
                take(r)
                out.append(r)
                taken.add(r.item_id)
            return out

    def has_work_for(self, user_id: str, pool: Optional[str] = None,
                     exclude: Iterable[str] = ()) -> bool:
        excluded = set(exclude)
        # A request this person holds is work whatever the page thinks of the
        # item: on an item with several schemes they may have saved one
        # question while the request is for another. Excluding held items
        # here showed them "nothing to label" with an unanswered blind
        # request in their hands.
        if self.store.requests(status=["assigned"], user=user_id, limit=1):
            return True
        done = self._labeled_by(user_id)
        return any(r.item_id not in excluded and (r.item_id, r.schema) not in done
                   for r in self.store.requests(status=["open"], pool=pool))

    def work_item_ids_for(self, user_id: str, pool: Optional[str] = None) -> List[str]:
        """Items this person holds or could still take: their progress
        counter's "remaining". The ledger is bounded by the human budget, so
        this stays small however large the corpus is."""
        done = self._labeled_by(user_id)
        ids = {r.item_id for r in self.store.requests(status=["assigned"], user=user_id)}
        ids |= {r.item_id for r in self.store.requests(status=["open"], pool=pool)
                if (r.item_id, r.schema) not in done}
        return sorted(ids)

    def release_stale(self, older_than_s: float = 3600.0) -> int:
        """Return assigned-but-unanswered requests to the open pool.

        Each ``release_listeners`` callable gets ``(user_id, item_id)`` for a
        hold that was released, so the server can take the item off that
        person's page too. Otherwise a tab left open past the timeout still
        shows the item, now with no request behind it: no longer blind."""
        cutoff = time.time() - older_than_s
        n = 0
        released = set()
        for r in self.store.requests(status=["assigned"]):
            if (r.assigned_at or r.created_at) < cutoff:
                self.store.update_request(r.id, status="open", assigned_user=None,
                                          assigned_at=None)
                n += 1
                if r.assigned_user:
                    released.add((r.assigned_user, r.item_id))
        for user_id, item_id in sorted(released):
            for listener in self.release_listeners:
                try:
                    listener(user_id, item_id)
                except Exception:
                    logger.exception("labeling engine: release listener failed")
        return n

    def requests_of(self, user_id: str, item_id: str) -> List[HumanRequest]:
        """This person's engine requests on this item: the ones they hold,
        then the ones they answered. Organic labels are not requests."""
        rows = self.store.requests(item_id=str(item_id), status=["assigned", "done"])
        held = [r for r in rows if r.status == "assigned" and r.assigned_user == user_id]
        done = [r for r in rows if r.status == "done" and r.user_id == user_id
                and r.purpose != "organic"]
        return held + done

    def visibility_for(self, user_id: str, item_id: str) -> Optional[str]:
        """``blind`` or ``shown`` for this person's requests on this item, or
        None when they have none (they are labeling outside the engine's
        queue).

        An answered request counts as well as a held one. The first save of a
        blind item closes its request, and the page keeps autosaving and can
        be revisited with Back; were it blind only while held, the machine's
        answer would appear after the first click and the edits that follow
        would be written into the blind label. Once blind for a person, the
        item stays blind for them, on every scheme."""
        mine = self.requests_of(user_id, item_id)
        if not mine:
            return None
        return "blind" if any(r.visibility == "blind" for r in mine) else "shown"

    def record_adjudication(self, item_id: str, scheme: str, value: Any,
                            adjudicator: str) -> None:
        """An adjudicated label: final, and the truth for that item from now on."""
        now = time.time()
        for r in self.store.requests(item_id=str(item_id), schema=scheme,
                                     status=["open", "assigned"], purpose=["adjudicate"]):
            self.store.update_request(r.id, status="done", label=value, user_id=adjudicator,
                                      completed_at=now)
        self.store.set_resolved([ResolvedLabel(
            str(item_id), scheme, value, "adjudicated", "accepted",
            request_ids=[r.id for r in self.store.requests(item_id=str(item_id),
                                                           schema=scheme)])])

    # === Audit and drift ===================================================

    def draw_audit(self, scheme: SchemeSpec, seed: int = 0) -> List[int]:
        """Send a random ``audit_rate`` share of newly accepted machine labels
        back to a person, blind. Each request remembers which prediction it
        checks."""
        rate = self.cfg.humans.audit_rate
        if rate <= 0:
            return []
        accepted = [r for r in self.store.resolved(schema=scheme.name, status=["accepted"])
                    if r.origin == "auto" and r.source_version_id]
        if not accepted:
            return []
        meta = self.store.get_items_meta([r.item_id for r in accepted], "audit_drawn")
        fresh = [r for r in accepted if not (meta.get(r.item_id) or {}).get(scheme.name)]
        if not fresh:
            return []
        out = []
        by_version: Dict[str, List[ResolvedLabel]] = {}
        for r in fresh:
            by_version.setdefault(r.source_version_id, []).append(r)
        for version, labs in by_version.items():
            preds = self.store.current_predictions(scheme.name, version,
                                                   [r.item_id for r in labs])
            reqs = []
            for r in labs:
                if designs.uniform(seed, "audit", r.item_id) < rate and r.item_id in preds:
                    reqs.append(HumanRequest(
                        item_id=r.item_id, schema=scheme.name, purpose="audit",
                        inclusion_prob=rate, split="audit", visibility="blind",
                        shown_prediction_id=preds[r.item_id].id,
                        pool=self.cfg.humans.pools[0], priority=1.0))
            if reqs:
                out += self.open_requests(
                    reqs, order_key=lambda r: designs.uniform(seed, "audit-cap", r.item_id))
        self.store.upsert_items([{"item_id": r.item_id, "meta": {"audit_drawn": {
            **(meta.get(r.item_id) or {}), scheme.name: True}}} for r in fresh])
        return out

    def _certified_since(self, contract_id: str, cascade_hash: str) -> Optional[float]:
        """When the met result now in force was first established: the
        earliest stored version at its look (later copies of the same look,
        such as an edit mark, do not restart anything)."""
        versions = self.store.contract_versions(contract_id, cascade_hash)
        if not versions or versions[0].status != "met":
            return None
        look = versions[0].looks
        return min(v.created_at for v in versions if v.looks == look and v.status == "met")

    def drift(self, scheme: SchemeSpec) -> Dict[str, Any]:
        """The drift monitor over this scheme's answered audits, per
        selective-risk contract.

        Each certification starts a fresh sequence: only audits answered
        after the met result now in force, of predictions from the current
        cascade, count. Over every audit ever answered, one breach was
        permanent, and re-certifying after fixing the cascade (as the
        violated note tells people to) changed nothing."""
        from .audit.drift import monitor
        fam = self.family(scheme)
        h = self.cascade_hash(scheme)
        current = set(self.tier_versions(scheme))
        audits = sorted((r for r in self.store.requests(schema=scheme.name, purpose=["audit"],
                                                       status=["done"])),
                        key=lambda r: r.completed_at or 0)
        answered = []
        for r in audits:
            p = self.store.get_prediction(r.shown_prediction_id) if r.shown_prediction_id else None
            if p is not None and p.source_version_id in current:
                answered.append((r.completed_at or 0, 0 if fam.correct(p.value, r.label) else 1))
        out = {}
        for c in self.cfg.contracts:
            if c.kind == "selective_risk" and c.schema == scheme.name:
                since = self._certified_since(c.id, h)
                outcomes = [o for t, o in answered if since is None or t >= since]
                res = monitor(outcomes, float(c.error), float(c.confidence))
                earlier = [o for t, o in answered if since is not None and t < since]
                if earlier:
                    old = monitor(earlier, float(c.error), float(c.confidence))
                    if old.get("breach"):
                        res["earlier_breach"] = (
                            f"Audits before the current certification breached the target "
                            f"at audit {old['breach_at']}; it was certified again since.")
                out[c.id] = res
        return out

    def drift_breached(self, scheme: SchemeSpec) -> bool:
        return self.cfg.feature("drift") and any(
            m.get("breach") for m in self.drift(scheme).values())

    def contested_items(self, scheme: SchemeSpec) -> List[str]:
        """Calibration items whose people split evenly: candidates for adjudication."""
        from .inference import majority
        by_item: Dict[str, Dict[str, Any]] = {}
        for r in self.store.requests(schema=scheme.name, status=["done"],
                                     purpose=["calibration", "certification"]):
            by_item.setdefault(r.item_id, {})[str(r.user_id or r.id)] = r.label
        settled = {r.item_id for r in self.store.resolved(schema=scheme.name)
                   if r.origin == "adjudicated"}
        return [iid for iid, people in by_item.items()
                if len(people) >= 2 and iid not in settled and majority(people)[1] <= 0.5]

    # === Certification =====================================================

    def view(self, scheme: SchemeSpec, population_ids: Optional[Sequence[str]] = None
             ) -> CalibrationView:
        tiers = self.tiers(scheme)
        versions = self.tier_versions(scheme)
        ids = list(population_ids) if population_ids is not None else self.store.all_item_ids()
        preds_by_tier = [self.store.current_predictions(scheme.name, v) for v in versions]

        def tier_preds(iid):
            out = []
            for preds in preds_by_tier:
                p = preds.get(iid)
                out.append(None if p is None else TierPred(
                    p.value, float(p.raw_conf or 0.0), p.status, p.conf))
            return out

        route = self._current_route(scheme)
        per_class = self._per_class(scheme)
        family = self.family(scheme)

        def output(tp):
            stop, complete = self.route_stop(tiers, tp, route, per_class, family.class_of)
            return (tp[stop] if stop is not None else None), complete

        pis = self.store.get_items_meta(ids, "pi")
        pop, complete_all = [], True
        for iid in ids:
            tp = tier_preds(iid)
            out, complete = output(tp)
            complete_all = complete_all and complete
            pop.append(PopItem(iid, tp, pi=(pis.get(iid) or {}).get(scheme.name, 0.0),
                               output=out))
        done = self.store.requests(schema=scheme.name, status=["done"],
                                   purpose=["calibration", "certification"])
        by_item: Dict[str, List[HumanRequest]] = {}
        for r in done:
            by_item.setdefault(r.item_id, []).append(r)
        from .inference import infer
        people = {iid: {str(r.user_id or r.id): r.label for r in sorted(rs, key=lambda r: r.id)}
                  for iid, rs in by_item.items()}
        adjudicated = {r.item_id: r.value for r in self.store.resolved(schema=scheme.name)
                       if r.origin == "adjudicated" and r.item_id in by_item}
        truth = infer(people, self.cfg.humans.truth, adjudicated)
        cal = []
        for iid, reqs in by_item.items():
            reqs.sort(key=lambda r: r.id)
            cur_pi = (pis.get(iid) or {}).get(scheme.name, reqs[0].inclusion_prob)
            tp = tier_preds(iid)
            cal.append(CalItem(item_id=iid, human=truth[iid][0],
                               split=reqs[0].split, pi=cur_pi, tiers=tp,
                               output=output(tp)[0],
                               humans={str(r.user_id): r.label for r in reqs
                                       if r.user_id is not None}))
        item_fields = ({iid: f for iid, f in self.store.get_items_meta(ids, "fields").items()
                        if f} if self._by_fields() else {})
        user_groups = {}
        if self.user_attributes is not None and any(
                c.kind == "distributional" and c.groups_by and c.schema == scheme.name
                for c in self.cfg.contracts):
            for c in cal:
                for u in c.humans:
                    if u not in user_groups:
                        try:
                            user_groups[u] = self.user_attributes(u) or {}
                        except Exception:
                            logger.exception("labeling engine: user attributes for %s", u)
                            user_groups[u] = {}
        return CalibrationView(scheme=scheme.name, labels=family.classes(),
                               item_fields=item_fields, user_groups=user_groups,
                               tier_ids=tiers, cal=cal, population=pop,
                               correct=family.correct, class_of=family.class_of,
                               truth_note={"majority": "majority of the people who "
                                                       "labeled the item",
                                           "dawid_skene": "Dawid-Skene consensus of the "
                                                          "people"}[self.cfg.humans.truth],
                               output_complete=complete_all)

    #: Between planner passes a contract that is not met yet is tested again
    #: only once its calibration labels have grown by this factor, and by at
    #: least LOOK_MIN_STEP labels. Without it every planner pass with one new
    #: label spent a look, and alpha shrank while people labeled.
    LOOK_GROWTH = 1.25
    LOOK_MIN_STEP = 10
    #: Contracts that never test anything: they spend no look.
    _NO_LOOK_KINDS = ("budget_first", "threshold_legacy")

    @staticmethod
    def _cert_labels(view: CalibrationView) -> Dict[str, str]:
        import hashlib
        import json as _json
        return {c.item_id: hashlib.sha256(_json.dumps(c.human, sort_keys=True, default=str)
                                          .encode()).hexdigest()[:10]
                for c in view.split("cert")}

    @staticmethod
    def _signature(kind: str, view: CalibrationView, raw: Dict[str, Any],
                   res: Dict[str, Any]) -> Optional[List[Any]]:
        """What a selective-risk evaluation tested, beyond the cert labels:
        the tiers, the per-class split, each cell's starting threshold and
        whether it was tested. Two evaluations with the same signature on the
        same cert labels are the same test. Other kinds read every
        calibration label, so any new label is new data (None)."""
        if kind != "selective_risk":
            return None
        import hashlib
        import json as _json
        cells = (res.get("metrics") or {}).get("cells") or {}
        # The machine answers on the cert items are the test's data too.
        preds = hashlib.sha256(_json.dumps(sorted(
            [c.item_id, [None if t is None else [t.value, round(t.conf, 9), t.status]
                         for t in c.tiers]] for c in view.split("cert")),
            default=str).encode()).hexdigest()[:16]
        return [list(view.tier_ids), bool(raw.get("per_class", True)), preds,
                sorted([k, v.get("lam_dev"), "tests" in v] for k, v in cells.items()),
                (res.get("metrics") or {}).get("tested_cells")]

    def _next_test_at(self, result: Dict[str, Any]) -> Optional[int]:
        n = result.get("n_at_look")
        if not result.get("looks_spent") or n is None:
            return None
        return max(int(math.ceil(n * self.LOOK_GROWTH)), n + self.LOOK_MIN_STEP)

    def certify(self, scheme: SchemeSpec, auto: bool = False,
                retest: bool = False) -> Dict[str, Dict[str, Any]]:
        # One certify at a time: a REST or MCP certify racing a planner pass
        # would both read the same look count and both spend the next look.
        with self._lock:
            return self._certify(scheme, auto=auto, retest=retest)

    @staticmethod
    def _edit_adds_no_errors(prev: Dict[str, Any], res: Dict[str, Any]) -> bool:
        """Selective risk: whether every test the stored result ran still sees
        the same number of cert items and no more errors. Fewer errors at the
        same n is the same test passing at least as well, so it needs no new
        look."""
        old_cells = (prev.get("metrics") or {}).get("cells") or {}
        new_cells = (res.get("metrics") or {}).get("cells") or {}
        if set(old_cells) != set(new_cells):
            return False
        for key, old in old_cells.items():
            new = new_cells[key]
            if old.get("lam_dev") != new.get("lam_dev"):
                return False
            old_tests, new_tests = old.get("tests") or [], new.get("tests") or []
            for i, t in enumerate(old_tests):
                if i >= len(new_tests):
                    return False
                u = new_tests[i]
                if u["threshold"] != t["threshold"] or u["n"] != t["n"] \
                        or u["errors"] > t["errors"]:
                    return False
        return True

    def _certify(self, scheme: SchemeSpec, auto: bool = False,
                 retest: bool = False) -> Dict[str, Dict[str, Any]]:
        """Evaluate every contract on this scheme; store and return results.

        A look (one test at a stricter level) is spent only when the test
        differs from the last one: new or changed cert labels, new
        predictions, or (with ``retest``) a different rule chosen on dev.

        Dev labels alone do not spend a look unless ``retest`` asks for it.
        Each spent look lowers the level, which moves dev's choice, so
        testing whenever dev's choice moved spent a look per call: polling
        certify to watch progress drained a met contract on unchanged cert
        labels. Without ``retest`` the stored result comes back with a note
        that dev now picks another rule.

        ``auto`` is the planner's pass: a met contract is not tested again
        unless one of its cert labels changed, and one that is not met waits
        until its labels have grown by LOOK_GROWTH.

        An edited cert label is new data, but a correction should not cost
        more than new labels do. Labels edited back to a state already tested
        get that test's result again. An edit after which no test sees more
        errors keeps the result and its look. Any other edit is re-tested at
        the next look: at once on an explicit certify, and by the planner
        once the labels reach the next milestone. Until then the result
        stands, with a note, and accepted labels stay accepted.
        """
        view = self.view(scheme)
        h = self.cascade_hash(scheme)
        n_cert, n_dev = view.n_cert, len(view.split("dev"))
        n_total = n_cert + n_dev
        cert_labels = self._cert_labels(view)
        # Any new prediction changes coverage and the PPI machine term, so a
        # stored result is reused only if no prediction arrived since.
        pred_mark = self.store.conn.execute(
            "SELECT COALESCE(MAX(id), 0) FROM prediction WHERE schema_name = ?",
            (scheme.name,)).fetchone()[0]
        out = {}
        for c in self.cfg.contracts:
            if c.schema != scheme.name:
                continue
            contract = build_contract(c)
            contract.dev_fraction = self.cfg.humans.dev_fraction
            latest = self.store.latest_contract_version(c.id)
            prev = latest.result if latest is not None else {}
            same_base = (latest is not None and latest.cascade_hash == h
                         and prev.get("code_version") == contract.VERSION
                         and latest.params == c.raw)
            prev_cert = prev.get("cert_labels")
            same_cert = same_base and prev_cert == cert_labels
            if same_cert and prev.get("n_dev") == n_dev and prev.get("pred_mark") == pred_mark:
                # The same data under the same procedure: not a new look.
                out[c.id] = prev
                continue
            # A cert label someone changed (not one added) is new data even
            # for a met contract.
            edited = same_base and prev_cert is not None and any(
                cert_labels.get(i) != v for i, v in prev_cert.items())
            # Looks a renamed contract spent under its old id count too.
            used = max(self.store.looks_used(c.id), self.store.looks_used_by_others(
                c.kind, scheme.name, [x.id for x in self.cfg.contracts]))

            def store(res, look, n_at_look):
                res.update(n_cert=n_cert, n_dev=n_dev, kind=c.kind, scheme=scheme.name,
                           code_version=contract.VERSION, looks_spent=look,
                           cert_labels=cert_labels, n_at_look=n_at_look, pred_mark=pred_mark,
                           signature=self._signature(c.kind, view, c.raw, res))
                self.store.add_contract_version(ContractVersion(
                    contract_id=c.id, kind=c.kind, params=c.raw, cascade_hash=h,
                    status=res["status"], looks=look, result=res))
                out[c.id] = res

            if c.kind in self._NO_LOOK_KINDS:
                store(contract.evaluate(view, look=max(1, used)).to_dict(), used,
                      prev.get("n_at_look"))
                continue

            if same_base and used:
                # The same data as a state tested earlier (a label edited and
                # then edited back): that test's result, not a new look.
                earlier = next((cv for cv in self.store.contract_versions(c.id, h)
                                if cv.result.get("cert_labels") == cert_labels
                                and cv.result.get("n_dev") == n_dev
                                and cv.result.get("pred_mark") == pred_mark
                                and cv.result.get("code_version") == contract.VERSION
                                and cv.params == c.raw), None)
                if earlier is not None:
                    store(dict(earlier.result), earlier.looks,
                          earlier.result.get("n_at_look"))
                    continue

            if edited and used and prev.get("pred_mark") == pred_mark:
                edit_note = (f"Cert labels were edited after look {prev.get('looks_spent')}.")
                if c.kind == "selective_risk":
                    res = contract.evaluate(view, look=used).to_dict()
                    if self._signature(c.kind, view, c.raw, res) is not None and \
                            self._edit_adds_no_errors(prev, res):
                        kept = dict(prev)
                        kept["notes"] = [n for n in prev.get("notes") or []
                                         if not n.startswith("Cert labels were edited")] + \
                            [edit_note + " No test sees more errors, so the result stands."]
                        store(kept, used, prev.get("n_at_look"))
                        continue
                due = self._next_test_at(prev)
                if auto and prev.get("status") == "met":
                    # A met contract is not re-tested on growth, so growth
                    # since its look must not make an edit look overdue: the
                    # milestone counts from the first edit since that look,
                    # and a burst of corrections becomes one test.
                    edit_n = prev.get("edit_n")
                    if edit_n is None:
                        edit_n = n_total
                    due = max(int(math.ceil(edit_n * self.LOOK_GROWTH)),
                              edit_n + self.LOOK_MIN_STEP)
                    # Unless no more random labels are coming (the sample is
                    # finished or the budget spent): then waiting would keep a
                    # contract met on cert labels nobody re-tested, for good.
                    coming = len(self.store.requests(
                        schema=scheme.name, status=["open", "assigned"],
                        purpose=["calibration", "certification"]))
                    if n_total + coming < due:
                        due = None
                    else:
                        n_edited = sum(1 for i, v in prev_cert.items()
                                       if cert_labels.get(i) not in (None, v))
                        note = (f"{n_edited} cert label(s) edited after look "
                                f"{prev.get('looks_spent')} and not re-tested yet; "
                                f"re-tested at {due} labels.")
                        marked = dict(prev, edit_n=edit_n, next_test_at=due, notes=[
                            n for n in prev.get("notes") or []
                            if "edited after look" not in n] + [note])
                        if marked != prev:
                            # Stored, so status, the admin page and the
                            # certificate show it, not only this call's result.
                            self.store.add_contract_version(ContractVersion(
                                contract_id=c.id, kind=c.kind, params=c.raw,
                                cascade_hash=h, status=prev["status"],
                                looks=prev.get("looks_spent") or used, result=marked))
                        out[c.id] = marked
                        continue
                if auto and due is not None and n_total < due:
                    out[c.id] = dict(prev, next_test_at=due, notes=[
                        n for n in prev.get("notes") or []
                        if not n.startswith("Cert labels were edited")]
                        + [edit_note + f" Re-tested at {due} labels."])
                    continue

            if same_cert and used:
                # Only dev labels arrived. If dev still picks the same rule,
                # this is the test already run: same look, fresh projection.
                res = contract.evaluate(view, look=used).to_dict()
                sig = self._signature(c.kind, view, c.raw, res)
                if sig is not None and sig == prev.get("signature"):
                    store(res, used, prev.get("n_at_look"))
                    continue
                if not auto and not retest and prev.get("pred_mark") == pred_mark:
                    note = (f"Dev labels now choose a different rule; certify with "
                            f"retest to test it (look {used + 1}).")
                    out[c.id] = dict(prev, retest_available=True,
                                     notes=[n for n in prev.get("notes") or []
                                            if not n.startswith("Dev labels now choose")]
                                     + [note])
                    continue

            if auto and same_base and used and not edited:
                if prev.get("status") == "met" and c.kind == "selective_risk":
                    # Met stays met for this cascade; audits watch for drift.
                    out[c.id] = prev
                    continue
                # Interval contracts (ppi, distributional, no_worse_than_human)
                # are "met" as soon as they can report; holding that froze the
                # estimate at the first sample big enough to give one. They
                # re-estimate at each milestone, and once more when the sample
                # is complete so the final figures use every label.
                due = self._next_test_at(prev)
                if due is not None and n_total < due:
                    sample_done = not self.store.requests(
                        schema=scheme.name, status=["open", "assigned"],
                        purpose=["calibration", "certification", "distribution"], limit=1)
                    if not (c.kind != "selective_risk" and sample_done
                            and n_total > (prev.get("n_at_look") or 0)):
                        out[c.id] = dict(prev, next_test_at=due)
                        continue

            res = contract.evaluate(view, look=used + 1).to_dict()
            if res.get("ran"):
                store(res, used + 1, n_total)
            else:
                # Nothing was tested, so nothing is spent. Without this, each
                # wave of labels drawn to reach a first test shrank alpha and
                # so called for another wave.
                if not res.get("ran"):
                    res = contract.evaluate(view, look=max(1, used)).to_dict()
                store(res, used, prev.get("n_at_look") if same_base else None)
        return out

    def contract_status(self, scheme: SchemeSpec) -> Dict[str, Dict[str, Any]]:
        """Latest result per contract, marked stale if the cascade changed."""
        h = self.cascade_hash(scheme)
        out = {}
        drift = (self.drift(scheme) if self.store.requests(
            schema=scheme.name, purpose=["audit"], status=["done"], limit=1) else {})
        for c in self.cfg.contracts:
            if c.schema != scheme.name:
                continue
            cv = self.store.latest_contract_version(c.id)
            if cv is None:
                out[c.id] = {"status": "insufficient", "kind": c.kind,
                             "notes": ["not evaluated yet"]}
                continue
            res = dict(cv.result)
            if cv.cascade_hash != h:
                res["status"] = "stale"
                res.setdefault("notes", []).append(
                    "A source, prompt or the scheme changed since this was certified.")
            res["contract_version_id"] = cv.id
            res["kind"] = c.kind
            d = drift.get(c.id) or {}
            if d.get("earlier_breach"):
                res["earlier_breach"] = d["earlier_breach"]
                res.setdefault("notes", []).append(d["earlier_breach"])
            if res["status"] == "met" and d.get("breach"):
                # A met test on the cert labels, then audits of the accepted
                # labels that show their error above target: say so wherever
                # the result is read, not only in the audit section.
                res["audits_breached"] = d.get("breach_at")
                if self.cfg.feature("drift"):
                    res["status"] = "violated"
                    res.setdefault("notes", []).append(
                        f"Audits of the accepted labels breached the target at audit "
                        f"{d.get('breach_at')}; machine labels are not accepted until "
                        "the contract is certified again.")
                else:
                    res.setdefault("notes", []).append(
                        f"Audits of the accepted labels breached the target at audit "
                        f"{d.get('breach_at')}; machine labels are still accepted because "
                        "labeling_engine.features.drift is false.")
            proj = res.get("projection") or {}
            more = proj.get("more_calibration_labels")
            if isinstance(more, (int, float)) and res["status"] not in ("met", "stale"):
                left = max(0, self.store.item_count()
                           - int(res.get("n_cert") or 0) - int(res.get("n_dev") or 0))
                if more > left:
                    # "About 234,719 more" on a 481-item corpus is a way of
                    # saying never; say it plainly.
                    res["projection"] = dict(proj, reachable=False, items_left=left)
                    res.setdefault("notes", []).append(
                        f"Not reachable with this corpus: about {int(more):,} more "
                        f"calibration labels would be needed and {left:,} items are "
                        "left to sample. Loosen the target or improve the sources.")
            if res["status"] not in ("met", "stale"):
                due = self._next_test_at(res)
                if due is not None:
                    res["next_test_at"] = due
            out[c.id] = res
        return out

    # === Resolution ========================================================

    def resolve(self, scheme: SchemeSpec, population_ids: Optional[Sequence[str]] = None,
                open_requests: bool = True, to_people: bool = False) -> Dict[str, int]:
        """Decide every item's label: certified machine, human, or pending.

        Machine labels are accepted only under a ``met`` selective-risk
        contract for the current cascade. Labels accepted under an older
        cascade become ``pending_recert``.
        """
        tiers = self.tiers(scheme)
        versions = self.tier_versions(scheme)
        h = self.cascade_hash(scheme)
        per_class = self._per_class(scheme)
        family = self.family(scheme)
        # A machine label is accepted only when every acceptance contract on
        # the scheme is met and accepts it: contracts declare what the
        # finished labels must satisfy, so an unmet one blocks rather than
        # being skipped (which accepted labels under the looser of two
        # targets while the stricter one said nothing was accepted). The
        # strictest target is listed first and recorded on the label.
        rules, all_met = [], True
        for c in sorted(self.cfg.contracts, key=lambda c: (c.error is None, c.error or 0)):
            if c.kind not in ("selective_risk", "threshold_legacy") or c.schema != scheme.name:
                continue
            cv = self.store.latest_contract_version(c.id)
            if cv and cv.cascade_hash == h and cv.status == "met":
                rules.append((cv.id, cv.result.get("acceptance") or {},
                              cv.result.get("metrics", {}).get("route") or {}))
            else:
                all_met = False
        # A contract the dev labels show cannot be met with these sources
        # blocks machine acceptance for good, so the items go to people (within
        # the budget), as they would with no machine at all. An unmet contract
        # that may still be met keeps waiting for calibration labels.
        blocked = [c.id for c in self.cfg.contracts
                   if c.kind == "selective_risk" and c.schema == scheme.name
                   and (lambda cv: cv is not None and cv.cascade_hash == h
                        and cv.status == "infeasible")(self.store.latest_contract_version(c.id))]
        if to_people and not blocked:
            # The planner found nothing left to draw while no rule is in force
            # (see Planner._people_fallback): the same as infeasible.
            blocked = ["no acceptance rule in force"]
        if not all_met:
            rules = []
        if rules and self.drift_breached(scheme):
            # Audits show the accepted labels' error is above target with the
            # contract's confidence: stop accepting until recalibrated.
            rules = []
        ids = list(population_ids) if population_ids is not None else self.store.all_item_ids()
        preds_by_tier = [self.store.current_predictions(scheme.name, v, ids) for v in versions]
        human = {}
        for r in self.store.requests(schema=scheme.name, status=["done"]):
            human.setdefault(r.item_id, []).append(r)
        open_by_item = {r.item_id for r in self.store.requests(
            schema=scheme.name, status=["open", "assigned"])}
        existing = {r.item_id: r for r in self.store.resolved(schema=scheme.name)}

        counts = Counter()
        labels, new_requests, stale_asks = [], [], []
        left = self.human_labels_remaining()
        for iid in ids:
            if iid in human:
                reqs = sorted(human[iid], key=lambda r: r.id)
                # One vote per person: their latest answer.
                latest = {}
                for r in sorted(reqs, key=lambda r: (r.completed_at or 0, r.id)):
                    latest[r.user_id or f"req{r.id}"] = r.label
                labels.append(ResolvedLabel(
                    iid, scheme.name, _majority(list(latest.values())), "human",
                    "accepted", request_ids=[r.id for r in reqs]))
                counts["human"] += 1
                continue
            accepted, first_answer, escalate_shown = None, None, None
            for t, tid in enumerate(tiers):
                p = preds_by_tier[t].get(iid)
                if p is None or p.status != "ok":
                    continue
                if first_answer is None:
                    first_answer = (t, p)
                key = family.class_of(p.value) if per_class else "*"
                conf = float(p.raw_conf or 0.0)
                ok = bool(rules)
                stopped = False
                for _cvid, acc, route in rules:
                    lam_route = _threshold(route, tid, key)
                    if lam_route is not None and conf >= lam_route:
                        stopped = True
                    lam = _threshold(acc, tid, key)
                    if lam is None or conf < lam:
                        ok = False
                if ok:
                    accepted = (t, p)
                    break
                if stopped:
                    escalate_shown = p
                    break
            if accepted is not None:
                t, p = accepted
                labels.append(ResolvedLabel(
                    iid, scheme.name, p.value, "auto", "accepted",
                    source_version_id=versions[t], contract_version_id=rules[0][0]))
                counts["auto"] += 1
                if iid in open_by_item:
                    # Verify or resolve requests opened while the item had no
                    # accepted label (a stale window) are not needed now.
                    stale_asks.append(iid)
                continue
            prev = existing.get(iid)
            if prev is not None and prev.origin == "auto" and prev.status == "accepted":
                prev.status = "pending_recert"
                labels.append(prev)
                counts["pending_recert"] += 1
            else:
                counts["pending"] += 1
            if not open_requests or not (rules or blocked) or iid in open_by_item:
                continue
            if left is not None and len(new_requests) >= left:
                counts["over_budget"] += 1
                continue
            shown = escalate_shown or (first_answer[1] if first_answer else None)
            if not rules:
                # Blocked: no machine label will be accepted, so the person's
                # answer is the label; nothing to verify.
                shown = None
            if shown is not None and self.cfg.humans.verify_visibility == "shown":
                new_requests.append(HumanRequest(
                    item_id=iid, schema=scheme.name, purpose="verify", inclusion_prob=None,
                    visibility="shown", shown_prediction_id=shown.id,
                    pool=self.cfg.humans.pools[0], priority=2.0))
            else:
                new_requests.append(HumanRequest(
                    item_id=iid, schema=scheme.name,
                    purpose="verify" if shown is not None else "resolve",
                    inclusion_prob=None, visibility="blind",
                    pool=self.cfg.humans.pools[0], priority=2.0 if shown else 3.0))
        if labels:
            self.store.set_resolved(labels)
        if stale_asks:
            gone = set(stale_asks)
            for r in self.store.requests(schema=scheme.name, status=["open"],
                                         purpose=["verify", "resolve"]):
                if r.item_id in gone:
                    self.store.update_request(r.id, status="cancelled")
                    counts["cancelled"] += 1
        if new_requests:
            # Items no machine label covers before verify requests.
            self.open_requests(new_requests, order_key=lambda r: (-r.priority, r.item_id))
        counts["requests_opened"] = len(new_requests)
        return dict(counts)

    # === Status ============================================================

    def status(self) -> Dict[str, Any]:
        schemes = {}
        for s in self.schemes():
            # Accepted under threshold_legacy is accepted without a guarantee;
            # count it as the export and the certificate name it.
            legacy = {cv.id for c in self.cfg.contracts
                      if c.kind == "threshold_legacy" and c.schema == s.name
                      for cv in self.store.contract_versions(c.id, self.cascade_hash(s))}
            resolved = Counter(
                (r.origin, "accepted_uncertified"
                 if r.status == "accepted" and r.contract_version_id in legacy else r.status)
                for r in self.store.resolved(schema=s.name))
            tiers = self.tiers(s)
            contracts = self.contract_status(s)
            for res in contracts.values():
                # Internal bookkeeping for look reuse: a hash per cert item
                # grows with the sample and means nothing to a reader.
                res.pop("cert_labels", None)
                res.pop("signature", None)
            schemes[s.name] = {
                "tiers": tiers,
                "sources": {sid: self.store.source_health(s.name, vid)
                            for sid, vid in zip(tiers, self.tier_versions(s))},
                "cascade_hash": self.cascade_hash(s),
                "contracts": contracts,
                "resolved": {f"{o}:{st}": n for (o, st), n in resolved.items()},
                "unlabeled": max(0, self.store.item_count() - sum(
                    n for (o, st), n in resolved.items() if st.startswith("accepted"))),
            }
        budgets = {k: (lambda b: {"limit": b.limit, "spent": b.spent} if b else None)(
            self.store.get_budget(k)) for k in ("model_usd", "human_usd", "human_labels")}
        if budgets.get("human_labels"):
            # The same count the cap is charged with, the budget table holds
            # and the certificate prints: requests opened, not organic labels
            # and not cancelled requests (summing every status put cancelled
            # verify requests on the admin page; potato-skill M3).
            budgets["human_labels"]["spent"] = float(self.store.count_opened_requests())
        unsupported = self.unsupported_schemes()
        for name, reasons in unsupported.items():
            schemes[name] = {"tiers": [], "status": "unsupported", "reasons": reasons,
                             "contracts": {c.id: {"kind": c.kind, "status": "unsupported",
                                                  "notes": reasons}
                                           for c in self.cfg.contracts if c.schema == name}}
        return {
            "enabled": self.cfg.enabled,
            "items": self.store.item_count(),
            "predictions": self.store.prediction_count(),
            "requests": self.store.request_counts(),
            "calls": self.store.call_totals(),
            "budgets": budgets,
            "schemes": schemes,
        }
