"""
Dawid-Skene consensus: worker-quality-weighted truth inference.

Majority vote treats every annotator as equally reliable and every item as
equally easy. Dawid-Skene (1979) instead jointly estimates, via EM, each
annotator's **confusion matrix** (how they label each true class) and each item's
**posterior** true label — so a careful annotator's vote counts for more than a
careless one, and you get a per-item confidence plus a per-annotator reliability
score. This is the standard upgrade over majority vote for noisy crowd labels and
pairs naturally with honeypot/gold scoring.

Pure Python (no numpy), deterministic. Categorical labels only.

    result = dawid_skene([(worker, item, label), ...])
    result.labels      # {item: consensus_label}
    result.confidence  # {item: posterior prob of the consensus label}
    result.reliability # {worker: estimated accuracy on the diagonal}
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

Observation = Tuple[str, str, str]  # (worker, item, label)


@dataclass
class ConsensusResult:
    labels: Dict[str, str] = field(default_factory=dict)
    confidence: Dict[str, float] = field(default_factory=dict)
    reliability: Dict[str, float] = field(default_factory=dict)
    classes: List[str] = field(default_factory=list)
    n_iter: int = 0

    def to_dict(self) -> Dict:
        return {
            "labels": self.labels,
            "confidence": {k: round(v, 4) for k, v in self.confidence.items()},
            "reliability": {k: round(v, 4) for k, v in self.reliability.items()},
            "classes": self.classes,
            "n_iter": self.n_iter,
        }


def majority_vote(observations: List[Observation]) -> Dict[str, str]:
    """Plain majority vote per item (ties → first-seen label)."""
    by_item: Dict[str, List[str]] = defaultdict(list)
    for w, i, l in observations:
        by_item[i].append(l)
    out = {}
    for item, labels in by_item.items():
        counts: Dict[str, int] = defaultdict(int)
        order: List[str] = []
        for l in labels:
            if l not in counts:
                order.append(l)
            counts[l] += 1
        out[item] = max(order, key=lambda l: (counts[l], -order.index(l)))
    return out


def dawid_skene(observations: List[Observation], max_iter: int = 100,
                tol: float = 1e-6) -> ConsensusResult:
    """Estimate consensus labels + annotator reliability via Dawid-Skene EM.

    ``observations`` is a flat list of ``(worker, item, label)``. Returns a
    ``ConsensusResult``. Robust to a single annotator (falls back to that
    annotator's labels) and to items/workers with sparse coverage.
    """
    if not observations:
        return ConsensusResult()

    workers = sorted({w for w, _, _ in observations})
    items = sorted({i for _, i, _ in observations})
    classes = sorted({l for _, _, l in observations})
    K = len(classes)
    cls_idx = {c: k for k, c in enumerate(classes)}

    # obs_by_item[item] -> list of (worker, class_index)
    obs_by_item: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
    for w, i, l in observations:
        obs_by_item[i].append((w, cls_idx[l]))

    if K == 1:
        only = classes[0]
        return ConsensusResult(
            labels={i: only for i in items},
            confidence={i: 1.0 for i in items},
            reliability={w: 1.0 for w in workers},
            classes=classes, n_iter=0)

    # --- init T (item posteriors) from frequency / majority vote ---
    T: Dict[str, List[float]] = {}
    for item in items:
        counts = [0.0] * K
        for _, k in obs_by_item[item]:
            counts[k] += 1.0
        s = sum(counts)
        T[item] = [c / s for c in counts] if s else [1.0 / K] * K

    prev_ll = None
    n_iter = 0
    pi: Dict[str, List[List[float]]] = {}
    prior = [1.0 / K] * K

    for n_iter in range(1, max_iter + 1):
        # --- M-step: class prior + per-worker confusion matrices ---
        prior = [0.0] * K
        for item in items:
            for k in range(K):
                prior[k] += T[item][k]
        tot = sum(prior) or 1.0
        prior = [p / tot for p in prior]

        # confusion[w][j][l] = P(worker w says l | true j)
        num = {w: [[0.0] * K for _ in range(K)] for w in workers}
        den = {w: [0.0] * K for w in workers}
        for item in items:
            for w, l in obs_by_item[item]:
                for j in range(K):
                    num[w][j][l] += T[item][j]
                    den[w][j] += T[item][j]
        pi = {}
        for w in workers:
            mat = [[0.0] * K for _ in range(K)]
            for j in range(K):
                if den[w][j] > 0:
                    for l in range(K):
                        mat[j][l] = num[w][j][l] / den[w][j]
                else:
                    # unseen true-class for this worker: assume uninformative
                    mat[j] = [1.0 / K] * K
            pi[w] = mat

        # --- E-step: update item posteriors ---
        ll = 0.0
        for item in items:
            scores = [prior[j] for j in range(K)]
            for w, l in obs_by_item[item]:
                for j in range(K):
                    scores[j] *= pi[w][j][l]
            s = sum(scores)
            if s > 0:
                T[item] = [x / s for x in scores]
                ll += _log(s)
            else:
                T[item] = [1.0 / K] * K

        if prev_ll is not None and abs(ll - prev_ll) < tol:
            break
        prev_ll = ll

    # --- outputs ---
    labels, confidence = {}, {}
    for item in items:
        best = max(range(K), key=lambda k: T[item][k])
        labels[item] = classes[best]
        confidence[item] = T[item][best]

    # reliability = prior-weighted mean of the worker's confusion diagonal
    reliability = {}
    for w in workers:
        acc = sum(prior[j] * pi[w][j][j] for j in range(K))
        reliability[w] = acc

    return ConsensusResult(labels=labels, confidence=confidence,
                           reliability=reliability, classes=classes, n_iter=n_iter)


def _log(x: float) -> float:
    import math
    return math.log(x) if x > 0 else 0.0
