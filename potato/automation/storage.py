"""
In-memory outcome log for automation actions.

Keeps the most recent N outcomes (for the admin inspection view) plus running
counters by action type and status. Bounded so a long-running server doesn't
grow unbounded; the admin page surfaces recent activity, not a full audit trail.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Any, Deque, Dict, List


class OutcomeStore:
    def __init__(self, capacity: int = 500):
        self._recent: Deque[Dict[str, Any]] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self.counters: Dict[str, int] = {
            "items_processed": 0,
            "rules_fired": 0,
            "actions_ok": 0,
            "actions_error": 0,
            "actions_skipped": 0,
        }
        self.by_action: Dict[str, int] = {}

    def record_outcome(self, item_id: str, rule: str, outcome: Dict[str, Any]) -> None:
        with self._lock:
            entry = {"item_id": item_id, "rule": rule, **outcome}
            self._recent.appendleft(entry)
            status = outcome.get("status", "ok")
            self.counters[f"actions_{status}"] = self.counters.get(f"actions_{status}", 0) + 1
            atype = outcome.get("action", "?")
            self.by_action[atype] = self.by_action.get(atype, 0) + 1

    def record_item(self, fired: int) -> None:
        with self._lock:
            self.counters["items_processed"] += 1
            self.counters["rules_fired"] += fired

    def recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._recent)[:limit]

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {"counters": dict(self.counters), "by_action": dict(self.by_action)}
