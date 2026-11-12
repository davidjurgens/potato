"""
Automation manager (singleton).

Owns the configured rules, the background worker, and the outcome store. The
ingestion path calls ``process_item(item_id, item_data)`` for every item (loaded
or runtime-ingested). For each rule that fires, fast actions run inline and heavy
actions are dispatched to the worker.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from potato.automation.actions import execute_action, is_heavy
from potato.automation.config import AutomationConfig
from potato.automation.rules import AutomationRule
from potato.automation.storage import OutcomeStore
from potato.automation.worker import AutomationWorker

logger = logging.getLogger("potato.automation")


class AutomationManager:
    def __init__(self, config: Dict[str, Any]):
        self.settings = AutomationConfig.from_config(config)
        self.rules: List[AutomationRule] = [
            AutomationRule.from_dict(r) for r in self.settings.rules
        ]
        self.store = OutcomeStore()
        self.worker = AutomationWorker(on_outcome=self.store.record_outcome)
        self.worker.start()
        logger.info("AutomationManager initialized with %d rule(s)", len(self.rules))

    def process_item(self, item_id: str, item_data: Dict[str, Any]) -> int:
        """Evaluate all rules against an item. Returns the number of rules fired.

        Never raises into the caller (ingestion must not break).
        """
        fired = 0
        try:
            for rule in self.rules:
                if not rule.fires_for(str(item_id), item_data or {}):
                    continue
                fired += 1
                ctx = {"item_id": str(item_id), "item_data": item_data, "rule": rule.name}
                for action in rule.actions:
                    if is_heavy(action):
                        self.worker.enqueue(action, ctx)  # outcome recorded by worker
                    else:
                        outcome = execute_action(action, ctx)
                        self.store.record_outcome(str(item_id), rule.name, outcome)
        except Exception as e:
            logger.error("Automation processing failed for %s: %s", item_id, e)
        self.store.record_item(fired)
        return fired

    def get_status(self) -> Dict[str, Any]:
        snap = self.store.snapshot()
        return {
            "enabled": self.settings.enabled,
            "rules": [
                {"name": r.name, "sample_rate": r.sample_rate,
                 "actions": [a.get("type") for a in r.actions], "enabled": r.enabled}
                for r in self.rules
            ],
            "counters": snap["counters"],
            "by_action": snap["by_action"],
        }

    def recent_outcomes(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self.store.recent(limit)

    def shutdown(self) -> None:
        self.worker.stop()


# ----- singleton -----

_manager: Optional[AutomationManager] = None


def init_automation_manager(config: Dict[str, Any]) -> AutomationManager:
    global _manager
    _manager = AutomationManager(config)
    return _manager


def get_automation_manager() -> Optional[AutomationManager]:
    return _manager


def clear_automation_manager() -> None:
    global _manager
    if _manager is not None:
        _manager.shutdown()
    _manager = None
