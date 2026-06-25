"""
Failure-mode *discovery* via open / axial coding over traces.

Where the MAST taxonomy ([[failure_taxonomy]]) tags failures against a *fixed*
known set, this *discovers* a **project-specific** taxonomy bottom-up — the
qualitative-coding workflow (Hamel/Shankar error analysis, 2025): embed the
(failed) traces, cluster them, and let an LLM propose a candidate "axial code"
(a name + description) for each cluster from representative examples. A human then
confirms or edits the codes — Potato's home turf (this is QDA over agent traces).

Clustering is pure-Python spherical k-means (cosine), deterministic given a seed,
reusing the curation ``EmbeddingIndex`` vectors. LLM labeling is optional — without
an endpoint you still get clusters + representatives for manual coding.
"""

from __future__ import annotations

import json
import logging
import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _normalize(v: List[float]) -> List[float]:
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else list(v)


def _dot(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def kmeans_cosine(items: List[Tuple[str, List[float]]], k: int,
                  seed: int = 12345, max_iter: int = 50) -> Dict[str, int]:
    """Spherical k-means (cosine) over ``(id, vector)`` pairs → ``{id: cluster}``.

    Deterministic given ``seed``. k is clamped to ``[1, n]``. Empty/degenerate
    input returns an empty mapping.
    """
    pts = [(i, _normalize(v)) for i, v in items if v]
    n = len(pts)
    if n == 0:
        return {}
    k = max(1, min(k, n))
    rng = random.Random(seed)
    # k-means++-ish seeded init: first centroid random, rest farthest-from-chosen.
    idx0 = rng.randrange(n)
    centroids = [list(pts[idx0][1])]
    while len(centroids) < k:
        # pick the point least similar to its nearest centroid
        best_i, best_sim = None, 2.0
        for i, (_id, v) in enumerate(pts):
            nearest = max(_dot(v, c) for c in centroids)
            if nearest < best_sim:
                best_sim, best_i = nearest, i
        centroids.append(list(pts[best_i][1]))

    labels = [0] * n
    for _ in range(max_iter):
        changed = False
        for i, (_id, v) in enumerate(pts):
            sims = [_dot(v, c) for c in centroids]
            lbl = max(range(k), key=lambda c: sims[c])
            if lbl != labels[i]:
                changed = True
            labels[i] = lbl
        # recompute centroids as the (re-normalized) mean of members
        for c in range(k):
            members = [pts[i][1] for i in range(n) if labels[i] == c]
            if members:
                dim = len(members[0])
                mean = [sum(m[d] for m in members) / len(members) for d in range(dim)]
                centroids[c] = _normalize(mean)
        if not changed:
            break
    return {pts[i][0]: labels[i] for i in range(n)}


@dataclass
class DiscoveredCluster:
    cluster_id: int
    member_ids: List[str] = field(default_factory=list)
    size: int = 0
    examples: List[str] = field(default_factory=list)        # representative texts
    suggested_label: str = ""                                 # LLM axial code (HITL-editable)
    suggested_description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"cluster_id": self.cluster_id, "size": self.size,
                "member_ids": self.member_ids, "examples": self.examples,
                "suggested_label": self.suggested_label,
                "suggested_description": self.suggested_description}


def _representatives(member_ids, get_vec, get_text, max_examples) -> Tuple[List[str], List[str]]:
    """Order members by closeness to the cluster centroid; return top texts + ids."""
    vecs = [(mid, _normalize(get_vec(mid))) for mid in member_ids if get_vec(mid)]
    if not vecs:
        ordered = member_ids
    else:
        dim = len(vecs[0][1])
        centroid = _normalize([sum(v[d] for _i, v in vecs) / len(vecs) for d in range(dim)])
        ordered = [mid for mid, _ in sorted(vecs, key=lambda iv: _dot(iv[1], centroid), reverse=True)]
        ordered += [m for m in member_ids if m not in {o for o in ordered}]
    top = ordered[:max_examples]
    return [str(get_text(mid) or "")[:500] for mid in top], top


def _axial_label(llm, examples: List[str]) -> Tuple[str, str]:
    """Ask the judge to name the common failure mode across representative examples."""
    joined = "\n\n".join(f"Example {i+1}:\n{e}" for i, e in enumerate(examples) if e)
    prompt = (
        "These agent traces were grouped together because they fail in a SIMILAR way. "
        "Name the common failure mode with a short label and a one-sentence description.\n\n"
        f"{joined}\n\n"
        'Respond as JSON: {"label": "<3-6 word failure mode>", "description": "<one sentence>"}.'
    )
    try:
        from pydantic import BaseModel

        class Code(BaseModel):
            label: str = ""
            description: str = ""

        resp = llm.query(prompt, Code)
        if isinstance(resp, str):
            data = (llm.parseStringToJson(resp) if hasattr(llm, "parseStringToJson")
                    else json.loads(resp))
        elif hasattr(resp, "model_dump"):
            data = resp.model_dump()
        else:
            data = resp or {}
        if not isinstance(data, dict):
            data = {}
        return str(data.get("label", "")).strip(), str(data.get("description", "")).strip()
    except Exception as e:
        logger.error(f"discovery: axial label failed: {e}")
        return "", ""


def discover_failure_modes(index, get_text: Callable[[str], str], k: int = 6,
                           llm: Any = None, max_examples: int = 4,
                           seed: int = 12345,
                           instance_ids: Optional[List[str]] = None) -> List[DiscoveredCluster]:
    """Cluster embedded traces and (optionally) propose an axial code per cluster.

    ``index`` is a curation ``EmbeddingIndex``; ``get_text(id)`` returns a trace's
    text. ``instance_ids`` restricts to a subset (e.g. only failed traces). Returns
    clusters sorted by size (largest = most prevalent failure mode first).
    """
    ids = [i for i in (instance_ids or index.ids()) if index.get(i)]
    items = [(i, index.get(i)) for i in ids]
    if not items:
        return []
    labels = kmeans_cosine(items, k, seed=seed)
    by_cluster: Dict[int, List[str]] = {}
    for iid, c in labels.items():
        by_cluster.setdefault(c, []).append(iid)

    clusters: List[DiscoveredCluster] = []
    for cid, members in by_cluster.items():
        examples, _ = _representatives(members, index.get, get_text, max_examples)
        label, desc = ("", "")
        if llm is not None and examples:
            label, desc = _axial_label(llm, examples)
        clusters.append(DiscoveredCluster(
            cluster_id=cid, member_ids=members, size=len(members),
            examples=examples, suggested_label=label, suggested_description=desc))
    clusters.sort(key=lambda c: c.size, reverse=True)
    return clusters
