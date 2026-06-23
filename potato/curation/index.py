"""
In-memory embedding index with brute-force cosine similarity search.

Pure-Python (no numpy dependency) so it imports light and runs anywhere; fine
for the moderate trace volumes Potato handles. Vectors are stored per instance
id; search returns ``(id, score)`` ranked by cosine similarity, optionally
filtered by a similarity threshold.
"""

from __future__ import annotations

import math
import threading
from typing import Dict, List, Optional, Tuple


def cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class EmbeddingIndex:
    def __init__(self):
        self._vectors: Dict[str, List[float]] = {}
        self._lock = threading.RLock()

    def __len__(self) -> int:
        return len(self._vectors)

    def __contains__(self, instance_id: str) -> bool:
        return str(instance_id) in self._vectors

    def add(self, instance_id: str, vector: List[float]) -> None:
        with self._lock:
            self._vectors[str(instance_id)] = list(vector)

    def remove(self, instance_id: str) -> None:
        with self._lock:
            self._vectors.pop(str(instance_id), None)

    def ids(self) -> List[str]:
        with self._lock:
            return list(self._vectors.keys())

    def get(self, instance_id: str) -> Optional[List[float]]:
        return self._vectors.get(str(instance_id))

    def search(self, query_vector: List[float], top_k: int = 10,
               threshold: float = 0.0, exclude: Optional[set] = None
               ) -> List[Tuple[str, float]]:
        exclude = exclude or set()
        with self._lock:
            scored = [
                (iid, cosine(query_vector, vec))
                for iid, vec in self._vectors.items()
                if iid not in exclude
            ]
        scored = [(i, s) for i, s in scored if s >= threshold]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k] if top_k else scored
