"""
The quality certificate: what was delivered, how it was produced, what holds.

One certificate covers the study at a moment. For each scheme it records:

- every contract's status, statement and key numbers, as last evaluated;
- the cascade: each source version with model, endpoint and prompt hash, so
  the run can be reproduced or audited;
- where the delivered labels came from: accepted machine labels (per tier),
  human, adjudicated, and those still pending;
- the human labels the engine asked for, by purpose and pool, and the
  sampling designs behind them;
- drift monitoring, when audits exist.

Study-wide it records model calls and cost, human spend, and two hashes: the
delivered labels (``dataset_hash``) and the call log (``call_log_digest``).
The certificate's own ``content_sha256`` covers everything else in it, so a
copy that has been edited can be told from the one the engine wrote.
"""

from __future__ import annotations

import hashlib
import time
from collections import Counter
from typing import Any, Dict, List

from ..model.records import Certificate, canonical_json, content_hash


def _call_log_digest(store) -> str:
    h = hashlib.sha256()
    for row in store.conn.execute(
            "SELECT id, source_version_id, prompt_hash, input_hash, response_hash, "
            "input_tokens, output_tokens, cost_usd, cache_hit, error FROM model_call "
            "ORDER BY id"):
        h.update(canonical_json(list(row)).encode())
    return h.hexdigest()


def _dataset_hash(store, schemes: List[str]) -> str:
    h = hashlib.sha256()
    for name in sorted(schemes):
        for r in sorted(store.resolved(schema=name), key=lambda r: r.item_id):
            h.update(canonical_json([r.item_id, r.schema, r.value, r.origin,
                                     r.status]).encode())
    return h.hexdigest()


def _designs(store, scheme: str) -> List[Dict[str, Any]]:
    out = []
    counts = Counter(r.design_id for r in store.requests(schema=scheme) if r.design_id)
    for did, n in sorted(counts.items()):
        d = store.get_design(did)
        if d is not None:
            out.append({"id": did, "kind": d.kind, "params": d.params, "seed": d.seed,
                        "requests": n})
    return out


def build_certificate(engine, save: bool = True) -> Dict[str, Any]:
    store = engine.store
    schemes = engine.schemes()
    engine._sync_human_spend()
    sections: Dict[str, Any] = {}
    for s in schemes:
        tiers = []
        for sid, vid in zip(engine.tiers(s), engine.tier_versions(s)):
            sv = store.get_source_version(vid)
            tiers.append({"source": sid, "version": vid,
                          "kind": sv.kind if sv else None,
                          "model": sv.model if sv else None,
                          "endpoint_type": sv.endpoint_type if sv else None,
                          "revision": sv.revision if sv else None,
                          "prompt_hash": sv.prompt_template_hash if sv else None})
        resolved = store.resolved(schema=s.name)
        origins = Counter((r.origin, r.status) for r in resolved)
        auto_by_tier = Counter(r.source_version_id for r in resolved
                               if r.origin == "auto" and r.status == "accepted")
        reqs = store.requests(schema=s.name)
        by_purpose: Dict[str, Dict[str, int]] = {}
        raters: Dict[str, set] = {}
        for r in reqs:
            d = by_purpose.setdefault(r.purpose, {})
            d[r.status] = d.get(r.status, 0) + 1
            if (r.status == "done" and r.purpose in ("calibration", "certification")
                    and r.user_id is not None):
                raters.setdefault(r.item_id, set()).add(r.user_id)
        contracts = {}
        for cid, res in engine.contract_status(s).items():
            contracts[cid] = {
                "kind": res.get("kind"), "status": res.get("status"),
                "statement": res.get("statement"), "look": res.get("look"),
                "alpha": res.get("alpha"), "n_cert": res.get("n_cert"),
                "n_dev": res.get("n_dev"),
                "coverage": (res.get("metrics") or {}).get("coverage"),
                "acceptance": res.get("acceptance"),
                "estimates": (res.get("metrics") or {}).get("estimates"),
                "alt_test": (res.get("metrics") or {}).get("alt_test"),
                "projection": res.get("projection"), "notes": res.get("notes"),
                "audits_breached": res.get("audits_breached"),
                "contract_version_id": res.get("contract_version_id"),
            }
        sections[s.name] = {
            "annotation_type": s.annotation_type, "family": engine.family(s).kind,
            "labels": s.labels, "cascade": tiers, "cascade_hash": engine.cascade_hash(s),
            "contracts": contracts,
            "delivered": {f"{o}:{st}": n for (o, st), n in sorted(origins.items())},
            "accepted_by_source_version": dict(auto_by_tier),
            "human_requests": by_purpose,
            "sampling_designs": _designs(store, s.name),
            "truth": engine.cfg.humans.truth,
            "multi_rater_items": sum(1 for u in raters.values() if len(u) > 1),
            "drift": engine.drift(s) if store.requests(schema=s.name, purpose=["audit"])
            else None,
        }
    calls = store.call_totals()
    budgets = {k: (lambda b: {"limit": b.limit, "spent": b.spent} if b else None)(
        store.get_budget(k)) for k in ("model_usd", "human_usd", "human_labels")}
    body = {
        "study": engine.app_config.get("annotation_task_name"),
        "created_at": time.time(),
        "schemes": sections,
        "model_calls": {"n": calls["n_calls"], "cost_usd": calls["cost_usd"],
                        "by_source": calls["by_source"]},
        "budgets": budgets,
        "call_log_digest": _call_log_digest(store),
        "dataset_hash": _dataset_hash(store, [s.name for s in schemes]),
        "config_hash": engine.cfg.config_hash(),
    }
    body["content_sha256"] = content_hash({k: v for k, v in body.items()
                                           if k != "created_at"})
    if save:
        cid = store.add_certificate(Certificate(
            cascade_hash=content_hash([sections[s]["cascade_hash"] for s in sections]),
            dataset_hash=body["dataset_hash"],
            contract_version_ids=[c["contract_version_id"] for sec in sections.values()
                                  for c in sec["contracts"].values()
                                  if c.get("contract_version_id")],
            sections=body, budget=budgets, content_sha256=body["content_sha256"]))
        body["certificate_id"] = cid
    return body
