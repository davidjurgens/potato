"""Configuration for Multiplayer Annotation Rooms.

YAML block:

```yaml
rooms:
  enabled: true
  who_can_create: "any"      # "any" member, or "admin" only
  persist_votes: true         # final votes write into members' annotations
  poll_interval_ms: 1500      # client event-poll cadence
  max_members: 12
  schema: "sarcasm"          # defaults to the first radio/likert scheme
```
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_VOTE_SCHEMA_TYPES = ("radio", "likert")


@dataclass
class RoomsConfig:
    enabled: bool = False
    who_can_create: str = "any"          # "any" | "admin"
    persist_votes: bool = True
    poll_interval_ms: int = 1500
    max_members: int = 12
    schema: Optional[str] = None


def _autopick_schema(config: Dict[str, Any]) -> Optional[str]:
    """First radio/likert scheme — the natural single-choice vote target."""
    for scheme in config.get("annotation_schemes", []) or []:
        if scheme.get("annotation_type") in _VOTE_SCHEMA_TYPES:
            return scheme.get("name")
    return None


def parse_rooms_config(config: Dict[str, Any]) -> RoomsConfig:
    block = config.get("rooms", {}) or {}
    parsed = RoomsConfig(enabled=bool(block.get("enabled", False)))
    if not parsed.enabled:
        return parsed

    who = str(block.get("who_can_create", "any")).lower()
    if who not in ("any", "admin"):
        logger.warning("rooms.who_can_create '%s' not recognized; using 'any'", who)
        who = "any"
    parsed.who_can_create = who

    parsed.persist_votes = bool(block.get("persist_votes", True))

    try:
        parsed.poll_interval_ms = max(500, min(int(block.get("poll_interval_ms", 1500)), 30000))
    except (TypeError, ValueError):
        parsed.poll_interval_ms = 1500

    try:
        parsed.max_members = max(2, min(int(block.get("max_members", 12)), 100))
    except (TypeError, ValueError):
        parsed.max_members = 12

    parsed.schema = block.get("schema") or _autopick_schema(config)
    if not parsed.schema:
        logger.warning(
            "rooms: no radio/likert annotation scheme found and no rooms.schema "
            "set — rooms will be disabled")
        parsed.enabled = False
    return parsed
