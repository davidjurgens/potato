"""
Sampling designs: how items are chosen for human labels, with known odds.

Every estimate and guarantee the engine makes rests on knowing, for every
item in the population, the probability it was chosen for a random human
label. Designs here are Bernoulli draws (each item independently, with its own
rate), which covers simple random, stratified and uncertainty-weighted
sampling, and union cleanly across waves:

    after waves with rates r1, r2, ...:   pi = 1 - (1 - r1)(1 - r2)...

The cumulative pi is stored per item in ``engine_item.meta["pi"][scheme]``,
for sampled and unsampled items alike, so the population's strata are known
to the estimators (``contracts/ppi.py``).

Draws are a hash of (design seed, design id, item id), so a design can be
replayed and audited: given the design row, anyone can recompute which items
it selected.
"""

from __future__ import annotations

import hashlib
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from ..model.records import HumanRequest, SamplingDesign


def uniform(seed: Any, design_id: Any, item_id: str, salt: str = "") -> float:
    digest = hashlib.blake2b(f"{seed}:{design_id}:{salt}:{item_id}".encode(),
                             digest_size=8).digest()
    return int.from_bytes(digest, "big") / 2 ** 64


def combine(old: float, new: float) -> float:
    """Inclusion probability of the union of two independent Bernoulli waves."""
    return 1.0 - (1.0 - old) * (1.0 - new)


def wave_rate_for_target(current: float, target: float) -> float:
    """The rate a new wave needs to bring an item from ``current`` to ``target``."""
    if target <= current:
        return 0.0
    return 1.0 - (1.0 - target) / (1.0 - current)


def capped_inclusion(rate: float, n: int, m: int) -> float:
    """Inclusion probability under "Bernoulli(rate) over n items, then a
    uniform random m of them if more than m were drawn".

    An item is drawn with probability ``rate``; given that, the B others drawn
    are Binomial(n - 1, rate) and it survives the cut with probability
    min(1, m / (1 + B)). Exact, so a budget cap leaves the estimators valid.
    """
    if n <= 0 or rate <= 0 or m <= 0:
        return 0.0
    if m >= n:
        return rate
    import math
    k = n - 1
    mu = k * rate
    sd = math.sqrt(max(k * rate * (1 - rate), 1e-12))
    # Twelve standard deviations either side hold all but ~1e-30 of the mass.
    lo, hi = max(0, int(mu - 12 * sd) - 1), min(k, int(mu + 12 * sd) + 1)
    if rate >= 1.0:
        lo = hi = k
    lc = math.lgamma(k + 1)
    lr = math.log(rate) if rate < 1 else 0.0
    lq = math.log1p(-rate) if rate < 1 else float("-inf")
    keep = 0.0
    for b in range(lo, hi + 1):
        if rate >= 1.0:
            pmf = 1.0
        else:
            pmf = math.exp(lc - math.lgamma(b + 1) - math.lgamma(k - b + 1)
                           + b * lr + (k - b) * lq)
        keep += pmf * min(1.0, m / (1.0 + b))
    return rate * min(1.0, keep)


def _split_cap(m: int, expected: Dict[float, float]) -> Dict[float, int]:
    """``m`` requests split over groups in proportion to their expected
    draws, largest remainder first, with at least one per group. Depends on
    the expectations only, never on what was drawn."""
    total = sum(expected.values())
    if not expected:
        return {}
    if total <= 0 or m <= 0:
        return {g: 0 for g in expected}
    exact = {g: m * e / total for g, e in expected.items()}
    share = {g: max(1, int(x)) for g, x in exact.items()}
    by_remainder = sorted(expected, key=lambda g: (-(exact[g] - int(exact[g])), g))
    i = 0
    while sum(share.values()) < m and by_remainder:
        share[by_remainder[i % len(by_remainder)]] += 1
        i += 1
    while sum(share.values()) > m:
        g = max((g for g in share if share[g] > 1), key=lambda g: (share[g], g), default=None)
        if g is None:
            break
        share[g] -= 1
    return share


def draw(store, scheme: str, item_ids: Sequence[str], rates: Dict[str, float], *,
         seed: int = 0, kind: str = "bernoulli", params: Optional[Dict] = None,
         purpose: str = "calibration", dev_fraction: float = 0.5,
         pool: str = "team", visibility: str = "blind",
         priority: float = 0.0, contract_id: Optional[str] = None,
         shared_key: Optional[str] = None,
         max_requests: Optional[int] = None) -> Tuple[int, List[int]]:
    """One Bernoulli wave over ``item_ids``; opens a request per selected item.

    ``rates`` maps item id to this wave's selection rate. Items that already
    have a random request for this scheme are not drawn again (they are
    already in the sample), but their cumulative pi is still updated, because
    the union design would have included them at the new rate too.

    ``shared_key`` makes the draw depend on (seed, key, item) only, not on
    this design's id, so waves for different schemes with the same seed and
    rate pick the same items. A person served an item then answers every
    scheme's random request on it, instead of answering the others as
    organic labels that no estimate can use.

    ``max_requests`` is a hard cap (the human-label budget). The wave's rates
    are lowered so it expects at most that many. Items with the same rate
    form a group, and the cap is split across groups in proportion to their
    expected draws (at least one each). A group drawn larger than its share
    keeps a uniform random subset of that size. The recorded inclusion
    probabilities are those of the capped design (``capped_inclusion``, per
    group), so estimates stay valid. One cut across groups with unequal rates
    would drop each group's items with a probability no formula records.
    More groups than the cap (rates that all differ, as an active design's
    do) is refused: some group would get no share, and an item that cannot
    be drawn makes its π zero.

    Returns ``(design_id, request_ids)``.
    """
    already = {r.item_id for r in store.requests(
        schema=scheme, purpose=["calibration", "certification", "audit", "distribution"])}
    cap_m = None
    if max_requests is not None:
        cap_m = max(0, int(max_requests))
        eligible = [iid for iid in item_ids
                    if float(rates.get(iid, 0.0)) > 0 and iid not in already]
        expected = sum(float(rates[iid]) for iid in eligible)
        if expected > cap_m:
            scale = cap_m / expected if expected else 0.0
            rates = {iid: float(r) * scale for iid, r in rates.items()}
        groups: Dict[float, List[str]] = {}
        for iid in eligible:
            groups.setdefault(round(float(rates[iid]), 12), []).append(iid)
        if cap_m > 0 and len(groups) > cap_m:
            raise ValueError(
                f"max_requests={cap_m} cannot be split over {len(groups)} distinct "
                "rates; group the rates (strata) or draw without a cap")
        share = _split_cap(cap_m, {g: g * len(ids) for g, ids in groups.items()})
        eff = {g: capped_inclusion(float(rates[ids[0]]), len(ids), share[g])
               for g, ids in groups.items()}
        params = {**(params or {}), "max_requests": cap_m}
    design = SamplingDesign(kind=kind, params={"scheme": scheme, "purpose": purpose,
                                               **(params or {})}, seed=seed)
    design_id = store.add_design(design)
    pis = (store.get_items_meta(item_ids, "pi") or {})
    meta_updates, requests = [], []
    draw_key = shared_key if shared_key is not None else design_id
    for iid in item_ids:
        rate = float(rates.get(iid, 0.0))
        if cap_m is not None and rate > 0:
            pi_rate = eff.get(round(rate, 12), rate)
        else:
            pi_rate = rate
        old = float((pis.get(iid) or {}).get(scheme, 0.0))
        new_pi = combine(old, pi_rate)
        if rate > 0:
            meta_updates.append({"item_id": iid,
                                 "meta": {"pi": {**(pis.get(iid) or {}), scheme: new_pi}}})
        if rate <= 0 or iid in already:
            continue
        if uniform(seed, draw_key, iid) < rate:
            split = "dev" if uniform(seed, draw_key, iid, "split") < dev_fraction else "cert"
            if purpose == "audit":
                split = "audit"
            requests.append(HumanRequest(
                item_id=iid, schema=scheme, purpose=purpose, inclusion_prob=new_pi,
                design_id=design_id, split=split, visibility=visibility, pool=pool,
                priority=priority, contract_id=contract_id))
    if cap_m is not None:
        by_group: Dict[float, List[HumanRequest]] = {}
        for r in requests:
            by_group.setdefault(round(float(rates[r.item_id]), 12), []).append(r)
        requests = []
        for g, rs in by_group.items():
            rs.sort(key=lambda r: uniform(seed, draw_key, r.item_id, "cap"))
            requests.extend(rs[:share[g]])
    if meta_updates:
        store.upsert_items(meta_updates)
    ids = store.add_requests(requests) if requests else []
    return design_id, ids


def rates_uniform(item_ids: Iterable[str], rate: float) -> Dict[str, float]:
    return {iid: float(rate) for iid in item_ids}


def rates_by_stratum(item_ids: Iterable[str], stratum_of: Callable[[str], Any],
                     rate_for: Dict[Any, float], default: float = 0.0) -> Dict[str, float]:
    return {iid: float(rate_for.get(stratum_of(iid), default)) for iid in item_ids}


def rates_active(item_ids: Iterable[str], uncertainty: Callable[[str], float],
                 budget: float, floor: float = 0.02) -> Dict[str, float]:
    """Rates proportional to uncertainty, summing to about ``budget`` items.

    Every item keeps at least ``floor``: an item with zero chance of being
    checked would leave a part of the population no estimate can see.
    """
    ids = list(item_ids)
    if not ids:
        return {}
    u = [max(0.0, float(uncertainty(i))) for i in ids]
    total = sum(u) or 1.0
    scale = max(0.0, budget - floor * len(ids)) / total
    return {iid: min(1.0, floor + scale * ui) for iid, ui in zip(ids, u)}
