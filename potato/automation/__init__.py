"""
Automation rules engine.

Closes the production -> eval loop: a programmable ``filter -> sampling rate ->
actions`` engine over every item entering Potato (loaded or runtime-ingested).
Actions route items to the annotation queue, curate them into datasets, run
evaluators, fire outbound webhooks, or notify annotators. Built on the shared
condition matcher (``server_utils/conditions``), the datasets/evaluators
subsystems, and the trace-ingestion notifier.
"""

from potato.automation.config import AutomationConfig
from potato.automation.rules import AutomationRule, deterministic_sample
from potato.automation.manager import (
    AutomationManager,
    init_automation_manager,
    get_automation_manager,
    clear_automation_manager,
)

__all__ = [
    "AutomationConfig",
    "AutomationRule",
    "deterministic_sample",
    "AutomationManager",
    "init_automation_manager",
    "get_automation_manager",
    "clear_automation_manager",
]
