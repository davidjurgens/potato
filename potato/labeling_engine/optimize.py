"""
Finding a cheaper cascade, or a better prompt, without touching the guarantee.

Both functions report; neither changes the study. Applying a recommendation
means editing the config, which makes a new cascade whose contracts are
certified afresh. Doing it automatically would let the engine shop for a
cascade that passes, which is exactly the selection the dev/cert split exists
to prevent.

``cascade_report`` scores every ordered subset of the configured tiers on the
**dev** labels only: half of them stand in for cert, so no look at the real
cert labels is spent. For each subset it gives the coverage each
selective-risk contract would certify and the expected model cost per item,
from the call log's measured cost per call.

``prompt_search`` asks an LLM tier for paraphrases of its prompt
(``solo_mode/prompt_sensitivity.generate_paraphrases``), labels the dev items
with each, and ranks them by accuracy against the people. Every call goes
through the call log and the model budget, and each paraphrase's predictions
are stored under its own source version (``<tier>-variantN``), which no
cascade reads. The current prompt is scored from the tier's stored
predictions.
"""

from __future__ import annotations

import itertools
import random
from dataclasses import replace
from typing import Any, Dict, List, Optional

from .contracts import CalibrationView, build_contract


def _cost_per_call(engine, version_id: str) -> float:
    row = engine.store.conn.execute(
        "SELECT AVG(COALESCE(cost_usd, 0)), COUNT(*) FROM model_call"
        " WHERE source_version_id = ? AND cache_hit = 0", (version_id,)).fetchone()
    return float(row[0] or 0.0)


def _dev_view(view: CalibrationView, idx: List[int], seed: int = 0) -> CalibrationView:
    dev = [c for c in view.cal if c.split == "dev"]
    rng = random.Random(seed)
    cal = []
    for c in dev:
        tiers = [c.tiers[i] if i < len(c.tiers) else None for i in idx]
        cal.append(replace(c, tiers=tiers, split="dev" if rng.random() < 0.5 else "cert"))
    return replace(view, cal=cal, tier_ids=[view.tier_ids[i] for i in idx],
                   population=[replace(p, tiers=[p.tiers[i] if i < len(p.tiers) else None
                                                 for i in idx]) for p in view.population])


def cascade_report(engine, scheme) -> Dict[str, Any]:
    view = engine.view(scheme)
    tiers = view.tier_ids
    versions = engine.tier_versions(scheme)
    costs = {tid: _cost_per_call(engine, vid) for tid, vid in zip(tiers, versions)}
    contracts = [c for c in engine.cfg.contracts
                 if c.kind == "selective_risk" and c.schema == scheme.name]
    out = []
    for r in range(1, len(tiers) + 1):
        for subset in itertools.combinations(range(len(tiers)), r):
            idx = list(subset)
            sub = _dev_view(view, idx)
            row: Dict[str, Any] = {"tiers": [tiers[i] for i in idx], "contracts": {}}
            reach_cost = 0.0
            for c in contracts:
                res = build_contract(c).evaluate(sub, look=1)
                row["contracts"][c.id] = {"status": res.status,
                                          "coverage": res.metrics.get("coverage", 0.0)}
                by_tier = res.metrics.get("accepted_by_tier") or {}
                n = max(1, res.metrics.get("population", 1))
                remaining = 1.0
                cost = 0.0
                for i in idx:
                    cost += remaining * costs[tiers[i]]
                    remaining -= by_tier.get(tiers[i], 0) / n
                reach_cost = max(reach_cost, cost)
            row["expected_cost_per_item_usd"] = round(reach_cost, 8)
            out.append(row)
    best = None
    note = "Scored on dev labels only; certify the chosen cascade afresh."
    if out and contracts:
        top = max(min(r["contracts"][c.id]["coverage"] for c in contracts) for r in out)
        if top <= 0:
            # Recommending the cheapest of several cascades that accept nothing
            # would name a tier the contract has just rejected.
            note = ("No candidate cascade keeps any coverage on the dev labels, so "
                    "none is recommended. " + note)
        else:
            ok = [r for r in out
                  if min(r["contracts"][c.id]["coverage"] for c in contracts) >= 0.95 * top]
            best = min(ok, key=lambda r: (r["expected_cost_per_item_usd"], len(r["tiers"])))
    return {"scheme": scheme.name, "n_dev": len([c for c in view.cal if c.split == "dev"]),
            "candidates": sorted(out, key=lambda r: r["expected_cost_per_item_usd"]),
            "recommended": best,
            "note": note}


def prompt_search(engine, scheme, items, source_id: Optional[str] = None,
                  n_variants: int = 4, generate=None) -> Dict[str, Any]:
    """``items`` are the study's ItemViews (the engine keeps hashes, not text).
    ``generate`` replaces the paraphrasing call (tests)."""
    from potato.solo_mode.prompt_sensitivity import generate_paraphrases
    from .runtime import RunContext, Runner
    from .sources import build_source
    sid = source_id or next((t for t in engine.tiers(scheme)
                             if engine.cfg.source(t).kind == "llm"), None)
    if sid is None:
        return {"error": "no llm tier to search prompts for"}
    base_cfg = engine.cfg.source(sid)
    base = engine.source(sid)
    base_prompt = base.prompt_template(scheme)
    view = engine.view(scheme, population_ids=[])
    dev = [c for c in view.cal if c.split == "dev"]
    if len(dev) < 20:
        return {"error": "needs at least 20 dev labels to compare prompts"}
    sv = base.version(scheme)
    ctx = RunContext(engine.store, engine.app_config, engine.cfg)

    def _generate(request: str) -> str:
        res = ctx.call(sv, base._endpoint(), request, schema_hash="paraphrase",
                       max_output_tokens=1500, base_url=base_cfg.base_url,
                       cacheable=True)
        if not res.ok:
            raise RuntimeError(res.error)
        return res.reply if isinstance(res.reply, str) else str(res.reply)

    paraphrases = generate_paraphrases(
        base_prompt, n_variants, generate or _generate, preserve_terms=list(scheme.labels))
    if not paraphrases:
        return {"error": f"the model returned no usable paraphrases of {sid}'s prompt "
                         "(each must keep the label names and placeholders)"}
    variants = [base_prompt] + paraphrases
    dev_ids = {c.item_id for c in dev}
    items = [it for it in items if it.item_id in dev_ids]
    results = []
    for k, prompt in enumerate(variants):
        if k == 0:
            # The current prompt is the tier itself: its predictions are
            # already stored, so the runner skips them and calls nothing.
            src = base
        else:
            cfg = replace(base_cfg, id=f"{sid}-variant{k}", prompt=prompt,
                          raw={**base_cfg.raw, "id": f"{sid}-variant{k}", "prompt": prompt})
            src = build_source(cfg, engine.app_config, engine.cfg)
        s = Runner(engine.store, engine.app_config, engine.cfg).predict(src, scheme, items)
        preds = engine.store.current_predictions(scheme.name, s.source_version_id)
        right = sum(1 for c in dev if c.item_id in preds and preds[c.item_id].status == "ok"
                    and view.correct(preds[c.item_id].value, c.human))
        results.append({"variant": k, "is_current": k == 0, "accuracy": right / len(dev),
                        "abstained": s.n_abstain, "errors": s.n_error,
                        "prompt": prompt})
    results.sort(key=lambda r: -r["accuracy"])
    return {"scheme": scheme.name, "source": sid, "n_dev": len(dev), "results": results,
            "note": "Accuracy on dev labels. Adopting a variant is a config change and "
                    "a new cascade; certify it afresh."}
