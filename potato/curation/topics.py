"""
Topics: persisted, auto-assigning trace groups (pattern-based grouping).

Where discovery (``discovery.py``) produces one-shot clusters, a **Topic** is
the durable artifact: a named group with a description, a member list, and a
stored centroid so that traces ingested *later* are auto-assigned to the
nearest topic (within a similarity threshold). This is the "recurring
pattern" workflow — e.g. "Tool call failed", "Confident but incorrect" —
kept fresh as production traces stream in.

Lifecycle:
    refresh_topics()   -> run discovery, persist each cluster as a Topic
                          (LLM axial code as name/description when available)
    assign_instance()  -> nearest-centroid assignment for one new trace
                          (called from the embed-on-ingest path)
    TopicStore         -> file-persisted (curation/topics.json), same pattern
                          as SliceStore
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from potato.curation.discovery import _dot, _normalize

#: Minimum cosine similarity for auto-assigning a new trace to a topic.
DEFAULT_ASSIGN_THRESHOLD = 0.55


@dataclass
class Topic:
    name: str
    description: str = ""
    centroid: List[float] = field(default_factory=list)
    member_ids: List[str] = field(default_factory=list)
    auto_assign: bool = True
    source: str = "discovered"     # discovered | manual
    refreshed_at: str = ""         # ISO timestamp of last refresh

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name, "description": self.description,
            "centroid": self.centroid, "member_ids": self.member_ids,
            "auto_assign": self.auto_assign, "source": self.source,
            "refreshed_at": self.refreshed_at,
        }

    def summary(self) -> Dict[str, Any]:
        """Centroid-free view for API responses."""
        return {
            "name": self.name, "description": self.description,
            "size": len(self.member_ids), "auto_assign": self.auto_assign,
            "source": self.source, "refreshed_at": self.refreshed_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Topic":
        return cls(
            name=d["name"], description=d.get("description", ""),
            centroid=d.get("centroid", []) or [],
            member_ids=d.get("member_ids", []) or [],
            auto_assign=bool(d.get("auto_assign", True)),
            source=d.get("source", "discovered"),
            refreshed_at=d.get("refreshed_at", ""),
        )


class TopicStore:
    """File-persisted store of topics (same pattern as SliceStore)."""

    def __init__(self, base_dir: Optional[str] = None):
        self._topics: Dict[str, Topic] = {}
        self._lock = threading.RLock()
        self._path = os.path.join(base_dir, "topics.json") if base_dir else None
        self._load()

    def _load(self):
        if self._path and os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    for d in json.load(f):
                        t = Topic.from_dict(d)
                        self._topics[t.name] = t
            except Exception:
                pass

    def _save(self):
        if not self._path:
            return
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump([t.to_dict() for t in self._topics.values()], f, indent=2)
        os.replace(tmp, self._path)

    def save(self, t: Topic) -> None:
        with self._lock:
            self._topics[t.name] = t
            self._save()

    def get(self, name: str) -> Optional[Topic]:
        return self._topics.get(name)

    def list(self) -> List[Topic]:
        return sorted(self._topics.values(), key=lambda t: len(t.member_ids), reverse=True)

    def delete(self, name: str) -> bool:
        with self._lock:
            existed = self._topics.pop(name, None) is not None
            if existed:
                self._save()
            return existed

    def replace_discovered(self, topics: List[Topic]) -> None:
        """Atomically replace all *discovered* topics, keeping manual ones."""
        with self._lock:
            kept = {n: t for n, t in self._topics.items() if t.source == "manual"}
            for t in topics:
                kept[t.name] = t
            self._topics = kept
            self._save()

    def topic_of(self, instance_id: str) -> Optional[str]:
        for t in self._topics.values():
            if instance_id in t.member_ids:
                return t.name
        return None


def centroid_of(member_ids: List[str], get_vec) -> List[float]:
    """Normalized mean vector of a member set ([] when no vectors exist)."""
    vecs = [_normalize(get_vec(mid)) for mid in member_ids if get_vec(mid)]
    if not vecs:
        return []
    dim = len(vecs[0])
    return _normalize([sum(v[d] for v in vecs) / len(vecs) for d in range(dim)])


def assign_instance(
    instance_id: str,
    vector: List[float],
    store: TopicStore,
    threshold: float = DEFAULT_ASSIGN_THRESHOLD,
) -> Optional[str]:
    """Assign one (new) embedded trace to the nearest auto-assign topic.

    Returns the topic name, or None when no topic clears the threshold.
    Idempotent: an instance already in a topic is not moved.
    """
    if not vector:
        return None
    existing = store.topic_of(instance_id)
    if existing:
        return existing
    vec = _normalize(vector)
    best_name, best_sim = None, threshold
    for topic in store.list():
        if not topic.auto_assign or not topic.centroid:
            continue
        sim = _dot(vec, topic.centroid)
        if sim >= best_sim:
            best_sim, best_name = sim, topic.name
    if best_name:
        topic = store.get(best_name)
        topic.member_ids.append(instance_id)
        store.save(topic)
    return best_name


def topics_from_clusters(clusters, get_vec, refreshed_at: str = "") -> List[Topic]:
    """Convert DiscoveredCluster results into persistable topics.

    Uses the LLM axial code as name/description when present, else a stable
    positional name.
    """
    topics = []
    for i, c in enumerate(clusters):
        name = (c.suggested_label or f"topic-{i + 1}").strip()
        topics.append(Topic(
            name=name,
            description=c.suggested_description or "",
            centroid=centroid_of(c.member_ids, get_vec),
            member_ids=list(c.member_ids),
            source="discovered",
            refreshed_at=refreshed_at,
        ))
    return topics
