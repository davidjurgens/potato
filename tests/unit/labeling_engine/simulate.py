"""
Synthetic studies for the validity tests.

A population of items with a known true label, one or more machine tiers
whose answers and confidences are drawn from known distributions, and a
random human sample with recorded inclusion probabilities. Because the truth
is known for every item, the true error among accepted labels and the true
prevalence can be computed exactly, and a contract's promise can be checked.
"""

import numpy as np

from potato.labeling_engine.contracts import CalItem, CalibrationView, PopItem, TierPred

LABELS = ["a", "b", "c"]


def tier_answers(rng, truth, err_by_conf):
    """Confidences uniform on [0,1]; P(wrong | conf) = err_by_conf(conf)."""
    n = len(truth)
    conf = rng.random(n)
    wrong = rng.random(n) < err_by_conf(conf)
    shift = rng.integers(1, len(LABELS), n)
    idx = np.array([LABELS.index(t) for t in truth])
    pred_idx = np.where(wrong, (idx + shift) % len(LABELS), idx)
    return [LABELS[i] for i in pred_idx], conf


def study(rng, n_pop=2000, rate=0.15, dev_fraction=0.5, prevalence=(0.5, 0.3, 0.2),
          tiers=(lambda c: 0.4 * (1 - c) ** 2,), pi_by_pred=None):
    """Return (view, truth dict, tier predictions per item)."""
    truth = rng.choice(LABELS, size=n_pop, p=prevalence)
    tier_preds = [tier_answers(rng, truth, f) for f in tiers]
    pop = []
    for i in range(n_pop):
        pop.append(PopItem(item_id=f"i{i}", tiers=[
            TierPred(tp[0][i], float(tp[1][i])) for tp in tier_preds]))
    # Bernoulli sample, optionally with probability depending on tier-0's
    # predicted class (a stratified design).
    pis = np.full(n_pop, rate)
    if pi_by_pred is not None:
        pis = np.array([pi_by_pred[tier_preds[0][0][i]] for i in range(n_pop)])
    take = rng.random(n_pop) < pis
    cal = []
    for i in np.flatnonzero(take):
        split = "dev" if rng.random() < dev_fraction else "cert"
        cal.append(CalItem(item_id=f"i{i}", human=truth[i], split=split,
                           pi=float(pis[i]), tiers=pop[i].tiers))
    view = CalibrationView(scheme="s", labels=list(LABELS),
                           tier_ids=[f"t{k}" for k in range(len(tiers))],
                           cal=cal, population=pop)
    return view, truth


def true_accepted_error(view, truth, acceptance, route, per_class):
    """Exact error rate among population items the rule accepts."""
    accepted = wrong = 0
    for idx, it in enumerate(view.population):
        for t, tid in enumerate(view.tier_ids):
            p = it.tiers[t]
            key = p.value if per_class else "*"
            lam_route = route.get(tid, {}).get(key)
            if lam_route is None or p.conf < lam_route:
                continue
            lam = acceptance.get(tid, {}).get(key)
            if lam is not None and p.conf >= lam:
                accepted += 1
                wrong += p.value != truth[idx]
            break
    return (wrong / accepted) if accepted else 0.0, accepted
