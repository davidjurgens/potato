"""
Codebook event bus — the seam for future live (websocket) collaboration.

Today the codebook syncs across users by revision-polling
(`GET /api/codebook/version`). This module adds a discrete event stream so
a future websocket/SSE broadcaster can subscribe and push "scope X changed
to revision N" to connected clients with **no change** to the mutation
path: `content_service` already calls `emit()` after every successful
save. v1 ships a logging subscriber only.

Mirrors `service._CHANGE_LISTENERS` (process-global registry); kept
separate so the broadcaster is a leaf with no import edge into the
service.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List

logger = logging.getLogger(__name__)


@dataclass
class CodebookEvent:
    kind: str                     # e.g. 'content_saved', 'content_restored'
    project: str
    scope_kind: str               # 'code' | 'section'
    scope_id: str
    revision: int                 # structural revision after the change
    sem_revision: int             # semantic revision after the change
    actor: str
    payload: Dict[str, Any] = field(default_factory=dict)


_SUBSCRIBERS: List[Callable[[CodebookEvent], None]] = []


def subscribe(fn: Callable[[CodebookEvent], None]) -> None:
    if fn not in _SUBSCRIBERS:
        _SUBSCRIBERS.append(fn)


def clear_subscribers() -> None:
    """Tests only — the registry is process-global."""
    _SUBSCRIBERS.clear()


def emit(event: CodebookEvent) -> None:
    for fn in list(_SUBSCRIBERS):
        try:
            fn(event)
        except Exception:  # a subscriber must never break a mutation
            logger.exception("codebook event subscriber failed")


def _log_subscriber(event: CodebookEvent) -> None:
    logger.debug(
        "codebook event %s project=%s scope=%s/%s rev=%s sem=%s by=%s",
        event.kind, event.project, event.scope_kind, event.scope_id,
        event.revision, event.sem_revision, event.actor)


# default v1 subscriber: just logs.
subscribe(_log_subscriber)
