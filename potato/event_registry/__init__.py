"""Cross-document event registry package.

Import-light: importing this package must NOT pull in the ML stack. Heavy
managers (corpus_map) live in their own package.
"""

from .manager import (
    Event,
    EvidenceCitation,
    EventRegistryManager,
    init_event_registry_manager,
    get_event_registry_manager,
    clear_event_registry_manager,
)

__all__ = [
    "Event",
    "EvidenceCitation",
    "EventRegistryManager",
    "init_event_registry_manager",
    "get_event_registry_manager",
    "clear_event_registry_manager",
]
