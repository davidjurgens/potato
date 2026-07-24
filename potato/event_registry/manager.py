"""
Event Registry Manager

Holds cross-document Event objects for multi-document event annotation. Unlike
`event_annotation` (which models trigger+argument events *inside a single
instance*), an Event here is a FIRST-CLASS object that lives ABOVE documents:
it has template slot values, a set of member document ids, and per-slot evidence
citations that each point at a (doc_id, span) in some document.

This mirrors how cross-document event corpora (ECB+, GVC, ERE) are actually
built: the event is a shared node, and each document contributes evidence to it.

Storage is a single JSON file `{output_dir}/event_registry.json`, written
atomically (`.tmp` + `os.replace`). This is intentionally SEPARATE from the
per-instance span store (`span.py`) so that adding event/evidence data can never
break span serialization (the span on-disk format is a strict single source of
truth).

Concurrency: all mutations take `self._lock`. MVP is last-write-wins with an
`updated_at` stamp on each event; optimistic-locking (reject on stale write) is
a later hardening step.

This module is import-light on purpose: it must NOT pull in the ML stack
(sentence-transformers / sklearn / umap) at import time, so it is safe to import
at server boot.
"""

import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Singleton
_EVENT_REGISTRY_MANAGER: Optional["EventRegistryManager"] = None
_EVENT_REGISTRY_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class StaleWriteError(Exception):
    """Raised when a conditional write loses to a concurrent update.

    Carries the current event so the caller can return it to the client for a
    merge/refresh instead of silently clobbering another annotator's edit.
    """

    def __init__(self, current: "Event"):
        super().__init__("Event was modified by another writer")
        self.current = current


@dataclass
class EvidenceCitation:
    """A single piece of evidence: a span in one document supporting one slot."""

    slot_name: str
    doc_id: str
    span_start: int
    span_end: int
    quoted_text: str = ""
    span_id: str = ""
    created_by: str = ""
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EvidenceCitation":
        return cls(
            slot_name=d.get("slot_name", ""),
            doc_id=str(d.get("doc_id", "")),
            span_start=int(d.get("span_start", 0)),
            span_end=int(d.get("span_end", 0)),
            quoted_text=d.get("quoted_text", ""),
            span_id=d.get("span_id", ""),
            created_by=d.get("created_by", ""),
            created_at=d.get("created_at", _now_iso()),
        )


@dataclass
class Event:
    """A cross-document event: template slots + member docs + evidence."""

    id: str
    template_name: str = ""
    title: str = ""
    slot_values: Dict[str, str] = field(default_factory=dict)
    member_doc_ids: List[str] = field(default_factory=list)
    evidence: List[EvidenceCitation] = field(default_factory=list)
    created_by: str = ""
    provenance: str = "annotator"  # "annotator" | "seeded"
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "template_name": self.template_name,
            "title": self.title,
            "slot_values": dict(self.slot_values),
            "member_doc_ids": list(self.member_doc_ids),
            "evidence": [e.to_dict() for e in self.evidence],
            "created_by": self.created_by,
            "provenance": self.provenance,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Event":
        return cls(
            id=str(d["id"]),
            template_name=d.get("template_name", ""),
            title=d.get("title", ""),
            slot_values=dict(d.get("slot_values", {})),
            member_doc_ids=[str(x) for x in d.get("member_doc_ids", [])],
            evidence=[EvidenceCitation.from_dict(e) for e in d.get("evidence", [])],
            created_by=d.get("created_by", ""),
            provenance=d.get("provenance", "annotator"),
            created_at=d.get("created_at", _now_iso()),
            updated_at=d.get("updated_at", _now_iso()),
        )


class EventRegistryManager:
    """Singleton owning the cross-document event registry and its persistence."""

    SCHEMA_VERSION = 1

    def __init__(self, config: Dict[str, Any]):
        self.config = config or {}
        self._lock = threading.RLock()
        self._events: Dict[str, Event] = {}

        template_cfg = self.config.get("event_template", {}) or {}
        self.enabled = bool(template_cfg.get("enabled", False))
        self.allow_annotator_create = bool(
            template_cfg.get("allow_annotator_create", True)
        )
        self.slots: List[Dict[str, Any]] = list(template_cfg.get("slots", []) or [])
        self.template_name = template_cfg.get("name", "event_template")

        self._path = self._registry_path()
        self._load()
        self._load_seed_events(template_cfg)

    # ---- paths -------------------------------------------------------------
    def _registry_path(self) -> str:
        output_dir = self.config.get("output_annotation_dir", "annotation_output")
        os.makedirs(output_dir, exist_ok=True)
        return os.path.join(output_dir, "event_registry.json")

    # ---- persistence -------------------------------------------------------
    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            events = data.get("events", {})
            with self._lock:
                self._events = {
                    eid: Event.from_dict(ed) for eid, ed in events.items()
                }
            logger.info(
                "Loaded %d cross-document events from %s",
                len(self._events),
                self._path,
            )
        except Exception as e:  # pragma: no cover - defensive
            logger.error("Failed to load event registry from %s: %s", self._path, e)

    def _save(self) -> None:
        """Atomically write the registry to disk. Caller holds self._lock."""
        payload = {
            "version": self.SCHEMA_VERSION,
            "events": {eid: ev.to_dict() for eid, ev in self._events.items()},
        }
        tmp = self._path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self._path)
        except Exception as e:  # pragma: no cover - defensive
            logger.error("Failed to save event registry to %s: %s", self._path, e)
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    def _load_seed_events(self, template_cfg: Dict[str, Any]) -> None:
        """Load admin-seeded events, id-idempotent (never clobber existing)."""
        seed = template_cfg.get("seed_events")
        if not seed:
            return

        seed_events: List[Dict[str, Any]] = []
        if isinstance(seed, str):
            # Path relative to the task/output dir.
            candidates = [
                seed,
                os.path.join(self.config.get("task_dir", "."), seed),
            ]
            path = next((p for p in candidates if os.path.exists(p)), None)
            if not path:
                logger.warning("seed_events file not found: %s", seed)
                return
            try:
                with open(path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                seed_events = loaded.get("events", loaded) if isinstance(loaded, dict) else loaded
            except Exception as e:
                logger.error("Failed to read seed_events %s: %s", path, e)
                return
        elif isinstance(seed, list):
            seed_events = seed

        added = 0
        with self._lock:
            for i, ed in enumerate(seed_events):
                eid = str(ed.get("id") or f"evt_seed_{i}")
                if eid in self._events:
                    continue  # do not clobber annotator edits on restart
                ev = Event.from_dict({**ed, "id": eid})
                ev.provenance = "seeded"
                self._events[eid] = ev
                added += 1
            if added:
                self._save()
        if added:
            logger.info("Seeded %d events into registry", added)

    # ---- mutations ---------------------------------------------------------
    def create_event(
        self, user: str, title: str = "", template_name: Optional[str] = None
    ) -> Event:
        with self._lock:
            eid = "evt_" + uuid.uuid4().hex[:12]
            ev = Event(
                id=eid,
                template_name=template_name or self.template_name,
                title=title,
                created_by=user,
                provenance="annotator",
            )
            self._events[eid] = ev
            self._save()
            return ev

    def update_slot(
        self,
        event_id: str,
        slot: str,
        value: str,
        user: str,
        expected_updated_at: Optional[str] = None,
    ) -> Optional[Event]:
        with self._lock:
            ev = self._events.get(event_id)
            if ev is None:
                return None
            # Optimistic concurrency: if the caller declared the version it read
            # and another writer has since changed the event, refuse the write.
            if expected_updated_at and expected_updated_at != ev.updated_at:
                raise StaleWriteError(ev)
            ev.slot_values[slot] = value
            ev.updated_at = _now_iso()
            self._save()
            return ev

    def set_title(self, event_id: str, title: str) -> Optional[Event]:
        with self._lock:
            ev = self._events.get(event_id)
            if ev is None:
                return None
            ev.title = title
            ev.updated_at = _now_iso()
            self._save()
            return ev

    def add_member(self, event_id: str, doc_id: str) -> Optional[Event]:
        with self._lock:
            ev = self._events.get(event_id)
            if ev is None:
                return None
            doc_id = str(doc_id)
            if doc_id not in ev.member_doc_ids:
                ev.member_doc_ids.append(doc_id)
                ev.updated_at = _now_iso()
                self._save()
            return ev

    def remove_member(self, event_id: str, doc_id: str) -> Optional[Event]:
        with self._lock:
            ev = self._events.get(event_id)
            if ev is None:
                return None
            doc_id = str(doc_id)
            if doc_id in ev.member_doc_ids:
                ev.member_doc_ids.remove(doc_id)
                ev.updated_at = _now_iso()
                self._save()
            return ev

    def add_evidence(self, event_id: str, citation: EvidenceCitation) -> Optional[Event]:
        with self._lock:
            ev = self._events.get(event_id)
            if ev is None:
                return None
            ev.evidence.append(citation)
            # Citing evidence from a doc implies membership.
            if citation.doc_id and citation.doc_id not in ev.member_doc_ids:
                ev.member_doc_ids.append(citation.doc_id)
            ev.updated_at = _now_iso()
            self._save()
            return ev

    def remove_evidence(self, event_id: str, index: int) -> Optional[Event]:
        with self._lock:
            ev = self._events.get(event_id)
            if ev is None:
                return None
            if 0 <= index < len(ev.evidence):
                ev.evidence.pop(index)
                ev.updated_at = _now_iso()
                self._save()
            return ev

    def delete_event(self, event_id: str) -> bool:
        with self._lock:
            if event_id in self._events:
                del self._events[event_id]
                self._save()
                return True
            return False

    # ---- reads -------------------------------------------------------------
    def get_event(self, event_id: str) -> Optional[Event]:
        with self._lock:
            ev = self._events.get(event_id)
            return ev

    def list_events(self, doc_id: Optional[str] = None) -> List[Event]:
        with self._lock:
            events = list(self._events.values())
        if doc_id is not None:
            doc_id = str(doc_id)
            events = [e for e in events if doc_id in e.member_doc_ids]
        return sorted(events, key=lambda e: e.created_at)

    def to_json(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "version": self.SCHEMA_VERSION,
                "events": {eid: ev.to_dict() for eid, ev in self._events.items()},
            }


# ---- singleton helpers -----------------------------------------------------
def init_event_registry_manager(config: Dict[str, Any]) -> "EventRegistryManager":
    global _EVENT_REGISTRY_MANAGER
    with _EVENT_REGISTRY_LOCK:
        if _EVENT_REGISTRY_MANAGER is None:
            _EVENT_REGISTRY_MANAGER = EventRegistryManager(config)
    return _EVENT_REGISTRY_MANAGER


def get_event_registry_manager() -> Optional["EventRegistryManager"]:
    return _EVENT_REGISTRY_MANAGER


def clear_event_registry_manager() -> None:
    global _EVENT_REGISTRY_MANAGER
    with _EVENT_REGISTRY_LOCK:
        _EVENT_REGISTRY_MANAGER = None
