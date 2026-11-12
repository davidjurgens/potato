"""
Automation rule model: ``filter -> sampling rate -> actions``.

A rule fires for an item when its ``when`` condition(s) match AND the item is
selected by the rule's ``sample_rate``. Sampling is **deterministic** (a hash of
the item id + rule name), so re-processing the same item yields the same
decision — important for replayable, idempotent ingestion.

Config shape:

    automation:
      enabled: true
      rules:
        - name: "Route errors to review"
          when: {field: status, in: [error, failed]}
          sample_rate: 1.0           # 0.0–1.0 (default 1.0 = always)
          actions:
            - {type: add_to_queue, priority: 100}
            - {type: add_to_dataset, dataset: errors-to-fix}
            - {type: run_evaluator, evaluator: trajectory_match}
            - {type: fire_webhook, url: "https://example.com/hook"}
            - {type: notify, message: "New error trace"}
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Union

from potato.server_utils.conditions import matches_all


def deterministic_sample(item_id: str, salt: str) -> float:
    """A stable pseudo-random value in [0, 1) from (item_id, salt)."""
    h = hashlib.sha256(f"{item_id}|{salt}".encode("utf-8")).hexdigest()
    return int(h[:8], 16) / float(0x100000000)


@dataclass
class AutomationRule:
    name: str
    when: Union[Dict[str, Any], List[Dict[str, Any]]] = field(default_factory=list)
    sample_rate: float = 1.0
    actions: List[Dict[str, Any]] = field(default_factory=list)
    enabled: bool = True

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AutomationRule":
        return cls(
            name=d.get("name", "unnamed"),
            when=d.get("when", []),
            sample_rate=float(d.get("sample_rate", 1.0)),
            actions=list(d.get("actions", []) or []),
            enabled=bool(d.get("enabled", True)),
        )

    def matches(self, item_data: Dict[str, Any]) -> bool:
        return matches_all(self.when, item_data)

    def sampled(self, item_id: str) -> bool:
        if self.sample_rate >= 1.0:
            return True
        if self.sample_rate <= 0.0:
            return False
        return deterministic_sample(str(item_id), self.name) < self.sample_rate

    def fires_for(self, item_id: str, item_data: Dict[str, Any]) -> bool:
        return self.enabled and self.matches(item_data) and self.sampled(item_id)
