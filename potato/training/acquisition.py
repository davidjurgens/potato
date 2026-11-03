"""Acquisition scores: which unlabelled item is most worth asking about.

``llm_confidence`` assignment serves items least-confident first. Confidence
alone is a weak signal for a neural model, which is often confidently wrong,
and it says nothing about redundancy: ten near-copies of one hard item all
look equally worth asking. A classifier trainer's ``acquisition`` parameter
picks a better score, written on each prediction as ``acquisition``
(higher means ask sooner); the assignment order prefers it to confidence.

=================  ========================================================
least_confident    1 - the top probability (the ordering confidence gives)
margin             1 - (top probability - runner-up): close calls first
entropy            entropy of the predicted distribution, scaled to [0, 1]
bald               mutual information between the label and the weights,
                   from Monte Carlo dropout (Gal et al., 2017): items the
                   model is unsure about because it lacks data, not because
                   the item is ambiguous
coreset            greedy k-centre over the model's embeddings (Sener and
                   Savarese, 2018): each item's distance to the nearest
                   labelled or already-chosen item, so the queue spreads
                   over the data instead of piling into one region
=================  ========================================================

The trainers pass plain lists. Core-set selection uses numpy when it is
installed (the trainers that call it have it): in pure Python it is
O(n^2 d), 4.4 s for 400 candidates and about 11 minutes for 5,000.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence

__all__ = ["METHODS", "uncertainty", "bald", "coreset_scores", "scores_for",
           "mc_dropout", "has_dropout"]

METHODS = ("least_confident", "margin", "entropy", "bald", "coreset")


def _entropy(probs: Sequence[float]) -> float:
    return -sum(p * math.log(p) for p in probs if p > 0)


def uncertainty(probs: Sequence[float], method: str) -> float:
    """A score in [0, 1] from one predicted distribution; higher is more
    worth asking."""
    probs = list(probs)
    if not probs:
        return 0.0
    ranked = sorted(probs, reverse=True)
    if method == "margin":
        return 1.0 - (ranked[0] - (ranked[1] if len(ranked) > 1 else 0.0))
    if method == "entropy":
        return _entropy(probs) / math.log(len(probs)) if len(probs) > 1 else 0.0
    return 1.0 - ranked[0]


def bald(samples: Sequence[Sequence[float]]) -> float:
    """BALD from Monte Carlo dropout samples of one item's distribution:
    entropy of the mean prediction minus the mean entropy of the samples,
    scaled by the most it can be (log of the number of labels)."""
    samples = [list(s) for s in samples if s]
    if not samples:
        return 0.0
    n_labels = len(samples[0])
    mean = [sum(s[k] for s in samples) / len(samples) for k in range(n_labels)]
    value = _entropy(mean) - sum(_entropy(s) for s in samples) / len(samples)
    return max(0.0, value / math.log(n_labels)) if n_labels > 1 else 0.0


def has_dropout(model) -> bool:
    """Whether any dropout layer in *model* drops anything. ViT checkpoints
    ship with dropout 0, and Monte Carlo passes through them all agree, so
    BALD would score every item 0."""
    import torch
    return any(isinstance(m, torch.nn.modules.dropout._DropoutNd) and m.p > 0
               for m in model.modules())


def mc_dropout(model, forward, batches, samples: int) -> List[List[List[float]]]:
    """Each item's predicted distribution from *samples* passes with dropout
    on: ``forward(batch)`` returns probabilities for one batch. The model is
    back in eval mode afterwards."""
    import torch
    out: List[List[List[float]]] = []
    model.train()            # dropout on; no gradients are taken
    try:
        with torch.inference_mode():
            for _ in range(samples):
                row = 0
                for batch in batches():
                    for p in forward(batch):
                        if row == len(out):
                            out.append([])
                        out[row].append(p)
                        row += 1
    finally:
        model.eval()
    return out


def scores_for(method: str, probabilities=None, samples=None, embeddings=None,
               labelled=None) -> List[float]:
    """One score per item, from what *method* needs: each item's predicted
    distribution (margin, entropy), its Monte Carlo samples (bald), or its
    embedding and the labelled items' (coreset)."""
    if method in ("margin", "entropy", "least_confident"):
        return [uncertainty(p, method) for p in probabilities or []]
    if method == "bald":
        return [bald(s) for s in samples or []]
    if method == "coreset":
        return coreset_scores(embeddings or [], labelled or [])
    raise ValueError("Unknown acquisition method %r" % method)


def _distance(a: Sequence[float], b: Sequence[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def coreset_scores(candidates: Sequence[Sequence[float]],
                   labelled: Sequence[Sequence[float]]) -> List[float]:
    """Greedy k-centre. Picks, again and again, the candidate farthest from
    every labelled and already-picked point; each candidate's score is its
    distance at the moment it was picked, scaled to [0, 1], so the scores
    fall in picking order. Without labelled points the first pick is the
    candidate farthest from the candidates' mean."""
    n = len(candidates)
    if not n:
        return []
    try:
        import numpy  # noqa: F401
    except ImportError:
        return _coreset_python(candidates, labelled)
    return _coreset_numpy(candidates, labelled)


def _coreset_numpy(candidates, labelled) -> List[float]:
    """coreset_scores() in numpy: one matrix-vector product per pick, from
    squared distances as |x|^2 + |p|^2 - 2 x.p."""
    import numpy as np
    points = np.asarray(candidates, dtype=np.float64)
    norms = (points * points).sum(1)
    n = len(points)
    # Accelerate's matmul on macOS raises spurious divide and overflow flags.
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        if len(labelled):
            known = np.asarray(labelled, dtype=np.float64)
            nearest = np.full(n, np.inf)
            for start in range(0, len(known), 1024):
                block = known[start:start + 1024]
                squared = norms[:, None] + (block * block).sum(1)[None, :] \
                    - 2 * points @ block.T
                nearest = np.minimum(nearest, squared.min(1))
            nearest = np.sqrt(np.maximum(nearest, 0))
        else:
            nearest = np.sqrt(((points - points.mean(0)) ** 2).sum(1))
        scores = np.zeros(n)
        picked = np.zeros(n, dtype=bool)
        for _ in range(n):
            pick = int(np.where(picked, -np.inf, nearest).argmax())
            scores[pick] = nearest[pick]
            picked[pick] = True
            to_pick = norms + norms[pick] - 2 * (points @ points[pick])
            nearest = np.minimum(nearest, np.sqrt(np.maximum(to_pick, 0)))
    top = float(scores.max()) or 1.0
    return [round(float(s) / top, 6) for s in scores]


def _coreset_python(candidates, labelled) -> List[float]:
    n = len(candidates)
    if labelled:
        nearest = [min(_distance(c, l) for l in labelled) for c in candidates]
    else:
        dims = len(candidates[0])
        centre = [sum(c[d] for c in candidates) / n for d in range(dims)]
        nearest = [_distance(c, centre) for c in candidates]
    scores: List[Optional[float]] = [None] * n
    for _ in range(n):
        pick = max((i for i in range(n) if scores[i] is None), key=nearest.__getitem__)
        scores[pick] = nearest[pick]
        for i in range(n):
            if scores[i] is None:
                nearest[i] = min(nearest[i], _distance(candidates[i], candidates[pick]))
    top = max(scores) or 1.0
    return [round(s / top, 6) for s in scores]
