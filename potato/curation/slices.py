"""
Dynamic slices: saved semantic + metadata filters that auto-include new matching
instances.

A slice is resolved *on demand* against the current index, so traces ingested
after the slice was saved are automatically included if they match. Resolution =
(optional semantic neighborhood of a text query or anchor instance) ∩ (optional
metadata filter, using the shared condition grammar).
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from potato.server_utils.conditions import matches_all


@dataclass
class Slice:
    name: str
    query: str = ""                 # free-text semantic query
    anchor_id: str = ""             # or: an instance id to find neighbours of
    threshold: float = 0.0          # min cosine similarity
    top_k: int = 50
    metadata_filter: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name, "query": self.query, "anchor_id": self.anchor_id,
            "threshold": self.threshold, "top_k": self.top_k,
            "metadata_filter": self.metadata_filter,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Slice":
        return cls(
            name=d["name"], query=d.get("query", ""), anchor_id=d.get("anchor_id", ""),
            threshold=float(d.get("threshold", 0.0)), top_k=int(d.get("top_k", 50)),
            metadata_filter=d.get("metadata_filter", []) or [],
        )


class SliceStore:
    """File-persisted store of saved slices."""

    def __init__(self, base_dir: Optional[str] = None):
        self._slices: Dict[str, Slice] = {}
        self._lock = threading.RLock()
        self._path = os.path.join(base_dir, "slices.json") if base_dir else None
        self._load()

    def _load(self):
        if self._path and os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    for d in json.load(f):
                        s = Slice.from_dict(d)
                        self._slices[s.name] = s
            except Exception:
                pass

    def _save(self):
        if not self._path:
            return
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump([s.to_dict() for s in self._slices.values()], f, indent=2)
        os.replace(tmp, self._path)

    def save(self, s: Slice) -> None:
        with self._lock:
            self._slices[s.name] = s
            self._save()

    def get(self, name: str) -> Optional[Slice]:
        return self._slices.get(name)

    def list(self) -> List[Slice]:
        return list(self._slices.values())

    def delete(self, name: str) -> bool:
        with self._lock:
            existed = self._slices.pop(name, None) is not None
            if existed:
                self._save()
            return existed


def resolve_slice(slc: Slice, index, embedder, metadata_for: Any) -> List[str]:
    """Resolve a slice to the current set of matching instance ids.

    ``metadata_for(instance_id) -> dict`` supplies the metadata used by the
    metadata filter. Semantic candidates come from the index (by query text or
    anchor vector); if neither is set, all indexed ids are candidates.
    """
    # 1. semantic candidate set
    if slc.anchor_id:
        anchor_vec = index.get(slc.anchor_id)
        candidates = ([(i, s) for i, s in index.search(
            anchor_vec, top_k=slc.top_k, threshold=slc.threshold,
            exclude={slc.anchor_id})] if anchor_vec is not None else [])
        ids = [i for i, _ in candidates]
    elif slc.query:
        vec = embedder.embed(slc.query)
        ids = [i for i, _ in index.search(vec, top_k=slc.top_k, threshold=slc.threshold)]
    else:
        ids = index.ids()

    # 2. metadata filter
    if slc.metadata_filter:
        ids = [i for i in ids if matches_all(slc.metadata_filter, metadata_for(i) or {})]
    return ids
