"""Configuration for live collaborative sessions.

YAML block:

```yaml
collab:
  enabled: true
  who_can_create: any          # "any" member, or "admin" only
  max_members: 8
  default_mode: follow         # follow: members follow the leader; free: no leader view
  conflict_policy: lww         # lww: the later save wins and the other is told;
                               # reject: the earlier value stays (rest of the save goes in)
  require_signoff: false       # an item is done when every member marked it ready
  blind_first: false           # members answer on their own before the team answer opens
  sync_view: true              # followers' scroll and media follow the leader's
  exclude_members_from_solo: true
  transport: poll              # poll, or sse (server push, capped)
  poll_interval_ms: 1000
  hidden_poll_interval_ms: 5000
  sse:
    max_streams: 3
    max_stream_seconds: 25
  teams:                       # optional: teams set up by the study
    - id: red
      members: [alice, bob]
      leader: alice
      items: [item_1, item_2]  # or {count: 20}, or {group: <batch group>}
      blind_first: true        # optional per-team overrides of the two above
      require_signoff: true
```
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TEAM_USER_PREFIX = "team-"
CONFLICT_POLICIES = ("lww", "reject")
_SLUG = re.compile(r"[^a-z0-9_-]+")


def team_user_for(team_id: str) -> str:
    """The username the team's shared answers are stored under.

    No ``:`` (a directory per user is created from it, and Windows refuses
    the character), and a fixed prefix so it reads as a team in exports.
    """
    slug = _SLUG.sub("-", str(team_id).strip().lower()).strip("-") or "team"
    return f"{TEAM_USER_PREFIX}{slug}"


@dataclass
class TeamSpec:
    id: str
    members: List[str]
    leader: Optional[str] = None
    items: Optional[List[str]] = None
    item_count: Optional[int] = None
    group: Optional[str] = None
    name: Optional[str] = None
    blind_first: Optional[bool] = None
    require_signoff: Optional[bool] = None


@dataclass
class CollabConfig:
    enabled: bool = False
    who_can_create: str = "any"
    max_members: int = 8
    default_mode: str = "follow"
    conflict_policy: str = "lww"
    require_signoff: bool = False
    blind_first: bool = False
    sync_view: bool = True
    exclude_members_from_solo: bool = True
    transport: str = "poll"
    poll_interval_ms: int = 1000
    hidden_poll_interval_ms: int = 5000
    sse_max_streams: int = 3
    sse_max_stream_seconds: int = 25
    max_items: int = 500
    teams: List[TeamSpec] = field(default_factory=list)


def _clamp_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(int(value), high))
    except (TypeError, ValueError):
        return default


def _choice(value: Any, allowed, default: str, key: str) -> str:
    text = str(value if value is not None else default).lower()
    if text not in allowed:
        logger.warning("collab.%s '%s' not recognized; using '%s'", key, value, default)
        return default
    return text


def parse_team(raw: Dict[str, Any]) -> TeamSpec:
    """One ``collab.teams`` entry. Raises ValueError on a malformed one."""
    if not isinstance(raw, dict):
        raise ValueError("each collab.teams entry must be a mapping")
    team_id = str(raw.get("id") or "").strip()
    if not team_id:
        raise ValueError("each collab.teams entry needs an id")
    members = raw.get("members") or []
    if not isinstance(members, list) or not all(isinstance(m, str) and m for m in members):
        raise ValueError(f"collab team '{team_id}': members must be a list of usernames")
    leader = raw.get("leader")
    if leader is not None and leader not in members:
        raise ValueError(f"collab team '{team_id}': leader '{leader}' is not one of its members")
    spec = TeamSpec(id=team_id, members=list(members), leader=leader,
                    name=raw.get("name"))
    for key in ("blind_first", "require_signoff"):
        if key in raw:
            if not isinstance(raw[key], bool):
                raise ValueError(f"collab team '{team_id}': {key} must be true or false")
            setattr(spec, key, raw[key])
    items = raw.get("items")
    if isinstance(items, list):
        spec.items = [str(i) for i in items]
    elif isinstance(items, dict):
        if "count" in items:
            spec.item_count = _clamp_int(items.get("count"), 0, 1, 100000)
        if "group" in items:
            spec.group = str(items.get("group"))
        if spec.item_count is None and spec.group is None:
            raise ValueError(f"collab team '{team_id}': items needs count or group")
    elif items is not None:
        raise ValueError(f"collab team '{team_id}': items must be a list, "
                         "{count: N} or {group: name}")
    return spec


def parse_collab_config(config: Dict[str, Any]) -> CollabConfig:
    block = config.get("collab") or {}
    parsed = CollabConfig(enabled=bool(block.get("enabled", False)))
    if not parsed.enabled:
        return parsed
    parsed.who_can_create = _choice(block.get("who_can_create"), ("any", "admin"),
                                    "any", "who_can_create")
    parsed.max_members = _clamp_int(block.get("max_members", 8), 8, 2, 50)
    parsed.default_mode = _choice(block.get("default_mode"), ("follow", "free"),
                                  "follow", "default_mode")
    parsed.conflict_policy = _choice(block.get("conflict_policy"), CONFLICT_POLICIES,
                                     "lww", "conflict_policy")
    parsed.require_signoff = bool(block.get("require_signoff", False))
    parsed.blind_first = bool(block.get("blind_first", False))
    parsed.sync_view = bool(block.get("sync_view", True))
    parsed.exclude_members_from_solo = bool(block.get("exclude_members_from_solo", True))
    parsed.transport = _choice(block.get("transport"), ("poll", "sse"), "poll", "transport")
    parsed.poll_interval_ms = _clamp_int(block.get("poll_interval_ms", 1000), 1000, 250, 30000)
    parsed.hidden_poll_interval_ms = _clamp_int(
        block.get("hidden_poll_interval_ms", 5000), 5000, 1000, 120000)
    sse = block.get("sse") or {}
    parsed.sse_max_streams = _clamp_int(sse.get("max_streams", 3), 3, 0, 64)
    parsed.sse_max_stream_seconds = _clamp_int(sse.get("max_stream_seconds", 25), 25, 5, 300)
    parsed.max_items = _clamp_int(block.get("max_items", 500), 500, 1, 100000)
    for raw in block.get("teams") or []:
        try:
            parsed.teams.append(parse_team(raw))
        except ValueError as exc:
            logger.warning("collab: skipping team: %s", exc)
    return parsed


ALLOWED_KEYS = {
    "enabled", "who_can_create", "max_members", "default_mode", "conflict_policy",
    "require_signoff", "blind_first", "sync_view",
    "exclude_members_from_solo", "transport", "poll_interval_ms",
    "hidden_poll_interval_ms", "sse", "max_items", "teams",
}
TEAM_KEYS = {"id", "name", "members", "leader", "items", "blind_first", "require_signoff"}


def validate_collab_block(config: Dict[str, Any]) -> None:
    """Config-load validation; raises ValueError naming the problem."""
    block = config.get("collab")
    if block is None:
        return
    if not isinstance(block, dict):
        raise ValueError("collab must be a mapping")
    if not block.get("enabled"):
        return
    for key in ("default_mode", "conflict_policy", "transport", "who_can_create"):
        allowed = {"default_mode": ("follow", "free"), "conflict_policy": CONFLICT_POLICIES,
                   "transport": ("poll", "sse"), "who_can_create": ("any", "admin")}[key]
        if key in block and str(block[key]).lower() not in allowed:
            raise ValueError(f"collab.{key} must be one of {', '.join(allowed)} "
                             f"(got {block[key]!r})")
    for key in ("require_signoff", "blind_first", "sync_view", "exclude_members_from_solo"):
        if key in block and not isinstance(block[key], bool):
            raise ValueError(f"collab.{key} must be true or false (got {block[key]!r})")
    teams = block.get("teams") or []
    if not isinstance(teams, list):
        raise ValueError("collab.teams must be a list")
    seen_ids, seen_users = set(), set()
    for raw in teams:
        spec = parse_team(raw)
        unknown = set(raw) - TEAM_KEYS
        if unknown:
            raise ValueError(f"collab team '{spec.id}': unknown key(s) {sorted(unknown)}")
        user = team_user_for(spec.id)
        if user in seen_ids:
            raise ValueError(f"collab teams: two teams map to the user '{user}'")
        seen_ids.add(user)
        overlap = seen_users & set(spec.members)
        if overlap:
            raise ValueError(f"collab teams: {sorted(overlap)} listed in more than one team")
        seen_users |= set(spec.members)
    tai = config.get("text_as_image")
    if (tai.get("enabled") if isinstance(tai, dict) else bool(tai)):
        raise ValueError("collab and text_as_image cannot be used together: "
                         "teammates' changes are shown on the page as text")
