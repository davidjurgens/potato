"""Data model and state machine for Multiplayer Annotation Rooms.

A Room is an event-sourced group annotation session. Every mutation (join,
vote, reveal, vote change, message, advance, close) is appended to the room's
event list — persisted as JSONL by the manager — and room state is a pure
function of the event sequence, so rooms survive restarts by replay.

The blind→reveal invariant lives here: before an item is revealed, vote
events broadcast to pollers carry NO label (only who has voted). Labels
become public in the ``revealed`` event's vote table and in post-reveal
``vote_changed`` events. The persisted (full) event always keeps the label so
replay works.
"""

import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class RoomError(Exception):
    """Invalid room operation (wrong phase, wrong role, unknown member...)."""


# Room types
NORMING = "norming"
HUDDLE = "huddle"
SHADOW = "shadow"
ROOM_TYPES = (NORMING, HUDDLE, SHADOW)

# Per-item phases
VOTING = "voting"
REVEALED = "revealed"

# Room statuses
OPEN = "open"
CLOSED = "closed"

# Roles
HOST = "host"
MEMBER = "member"
OBSERVER = "observer"

# Room codes avoid ambiguous glyphs (0/O, 1/I/L) so they can be read aloud.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def new_room_id() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))


@dataclass
class RoomMember:
    username: str
    role: str = MEMBER
    joined_at: float = 0.0
    active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {"username": self.username, "role": self.role,
                "joined_at": self.joined_at, "active": self.active}


@dataclass
class RoomItemState:
    """Votes and reveal state for one instance within a room."""

    instance_id: str
    revealed: bool = False
    skipped: bool = False
    # Blind votes: immutable once the item is revealed.
    initial_votes: Dict[str, str] = field(default_factory=dict)
    # Current votes: equals initial until a post-reveal change.
    current_votes: Dict[str, str] = field(default_factory=dict)
    # Post-reveal changes: {user, from, to, majority_at_time, ts}
    changes: List[Dict[str, Any]] = field(default_factory=list)

    def majority_label(self) -> Optional[str]:
        """Most common current vote; None on empty or tie."""
        if not self.current_votes:
            return None
        counts: Dict[str, int] = {}
        for label in self.current_votes.values():
            counts[label] = counts.get(label, 0) + 1
        best = max(counts.values())
        winners = [label for label, c in counts.items() if c == best]
        return winners[0] if len(winners) == 1 else None

    def to_dict(self, include_votes: bool) -> Dict[str, Any]:
        """Snapshot for clients. Pre-reveal, votes are voter-count only."""
        base: Dict[str, Any] = {
            "instance_id": self.instance_id,
            "revealed": self.revealed,
            "skipped": self.skipped,
            "n_voted": len(self.initial_votes),
            "voted_users": sorted(self.initial_votes),
        }
        if include_votes:
            base["initial_votes"] = dict(self.initial_votes)
            base["current_votes"] = dict(self.current_votes)
            base["changes"] = list(self.changes)
            base["majority_label"] = self.majority_label()
        return base


class Room:
    """A live group annotation session, mutated only via record()/apply."""

    def __init__(self, room_id: str, room_type: str, host: str, schema: str,
                 labels: List[str], item_ids: List[str],
                 settings: Optional[Dict[str, Any]] = None,
                 created_at: Optional[float] = None):
        if room_type not in ROOM_TYPES:
            raise RoomError(f"Unknown room type '{room_type}'")
        if not item_ids:
            raise RoomError("A room needs at least one item")
        self.room_id = room_id
        self.room_type = room_type
        self.host = host
        self.schema = schema
        self.labels = list(labels)
        self.item_ids = list(item_ids)
        self.settings = dict(settings or {})
        self.created_at = created_at if created_at is not None else time.time()

        self.status = OPEN
        self.current_index = 0
        self.members: Dict[str, RoomMember] = {}
        self.item_states: Dict[str, RoomItemState] = {
            iid: RoomItemState(iid) for iid in self.item_ids
        }
        # Full (unredacted) events; seq is the poll cursor.
        self.events: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Event plumbing

    def _append(self, event_type: str, user: Optional[str],
                data: Optional[Dict[str, Any]] = None,
                ts: Optional[float] = None) -> Dict[str, Any]:
        event = {
            "seq": len(self.events) + 1,
            "ts": ts if ts is not None else time.time(),
            "type": event_type,
            "user": user,
            "data": data or {},
        }
        self.events.append(event)
        return event

    @staticmethod
    def public_view(event: Dict[str, Any]) -> Dict[str, Any]:
        """The broadcast form of an event: blind votes lose their label."""
        if event["type"] == "vote_cast" and not event["data"].get("post_reveal"):
            redacted = dict(event, data=dict(event["data"]))
            redacted["data"].pop("label", None)
            return redacted
        return event

    # ------------------------------------------------------------------
    # Convenience accessors

    @property
    def current_item_id(self) -> Optional[str]:
        if self.status == CLOSED or self.current_index >= len(self.item_ids):
            return None
        return self.item_ids[self.current_index]

    @property
    def current_item(self) -> Optional[RoomItemState]:
        iid = self.current_item_id
        return self.item_states[iid] if iid else None

    @property
    def phase(self) -> str:
        item = self.current_item
        if item is None:
            return CLOSED
        return REVEALED if item.revealed else VOTING

    def _require_open(self):
        if self.status != OPEN:
            raise RoomError("Room is closed")

    def _require_host(self, username: str):
        member = self.members.get(username)
        if member is None or member.role != HOST:
            raise RoomError("Only the host can do that")

    def _require_voter(self, username: str):
        member = self.members.get(username)
        if member is None or not member.active:
            raise RoomError("Not a member of this room")
        if member.role == OBSERVER:
            raise RoomError("Observers cannot vote")

    def voters(self) -> List[str]:
        """Active members who are allowed to vote (host included)."""
        return sorted(u for u, m in self.members.items()
                      if m.active and m.role != OBSERVER)

    def all_voted(self) -> bool:
        item = self.current_item
        if item is None:
            return False
        voters = self.voters()
        return bool(voters) and all(u in item.initial_votes for u in voters)

    # ------------------------------------------------------------------
    # Mutations (each appends exactly one event)

    def record_created(self, ts: Optional[float] = None) -> Dict[str, Any]:
        return self._append("room_created", self.host, {
            "room_type": self.room_type, "schema": self.schema,
            "labels": self.labels, "item_ids": self.item_ids,
            "settings": self.settings,
        }, ts)

    def join(self, username: str, role: str = MEMBER,
             ts: Optional[float] = None) -> Dict[str, Any]:
        self._require_open()
        if role not in (HOST, MEMBER, OBSERVER):
            raise RoomError(f"Unknown role '{role}'")
        existing = self.members.get(username)
        if existing is not None:
            # Rejoin keeps the original role (host stays host).
            existing.active = True
            return self._append("member_joined", username,
                                {"role": existing.role, "rejoin": True}, ts)
        member = RoomMember(username=username, role=role,
                            joined_at=ts if ts is not None else time.time())
        self.members[username] = member
        return self._append("member_joined", username, {"role": role}, ts)

    def leave(self, username: str, ts: Optional[float] = None) -> Dict[str, Any]:
        member = self.members.get(username)
        if member is None:
            raise RoomError("Not a member of this room")
        member.active = False
        return self._append("member_left", username, {}, ts)

    def vote(self, username: str, label: str,
             ts: Optional[float] = None) -> Dict[str, Any]:
        """Blind vote (pre-reveal) or vote change (post-reveal)."""
        self._require_open()
        self._require_voter(username)
        if label not in self.labels:
            raise RoomError(f"Unknown label '{label}'")
        item = self.current_item
        if item is None:
            raise RoomError("No current item")

        if not item.revealed:
            # Blind phase: overwriting your own blind vote is allowed and
            # stays a single "initial" vote — only the last one counts.
            item.initial_votes[username] = label
            item.current_votes[username] = label
            return self._append("vote_cast", username, {
                "instance_id": item.instance_id, "label": label,
                "post_reveal": False,
            }, ts)

        # Post-reveal: a change is public and logged as conformity data.
        previous = item.current_votes.get(username)
        if previous is None:
            # Late voter after reveal: counts as an initial vote cast in the
            # open, flagged so metrics can exclude it from the blind pool.
            item.initial_votes[username] = label
            item.current_votes[username] = label
            return self._append("vote_cast", username, {
                "instance_id": item.instance_id, "label": label,
                "post_reveal": True,
            }, ts)
        if previous == label:
            raise RoomError("That is already your vote")
        majority = item.majority_label()
        change = {
            "user": username, "from": previous, "to": label,
            "majority_at_time": majority,
            "ts": ts if ts is not None else time.time(),
        }
        item.changes.append(change)
        item.current_votes[username] = label
        return self._append("vote_changed", username, {
            "instance_id": item.instance_id, "from": previous, "to": label,
            "majority_at_time": majority,
        }, ts)

    def reveal(self, username: str, ts: Optional[float] = None) -> Dict[str, Any]:
        self._require_open()
        self._require_host(username)
        item = self.current_item
        if item is None:
            raise RoomError("No current item")
        if item.revealed:
            raise RoomError("Item is already revealed")
        if not item.initial_votes:
            raise RoomError("Nobody has voted yet")
        item.revealed = True
        return self._append("revealed", username, {
            "instance_id": item.instance_id,
            "votes": dict(item.initial_votes),
        }, ts)

    def message(self, username: str, text: str,
                ts: Optional[float] = None) -> Dict[str, Any]:
        self._require_open()
        if username not in self.members:
            raise RoomError("Not a member of this room")
        text = (text or "").strip()
        if not text:
            raise RoomError("Empty message")
        return self._append("message", username, {"text": text[:2000]}, ts)

    def advance(self, username: str, ts: Optional[float] = None) -> Dict[str, Any]:
        """Move to the next item (host). Closes the room after the last one."""
        self._require_open()
        self._require_host(username)
        item = self.current_item
        if item is None:
            raise RoomError("No current item")
        if not item.revealed:
            item.skipped = True
        finished_id = item.instance_id
        self.current_index += 1
        if self.current_index >= len(self.item_ids):
            self.status = CLOSED
            return self._append("room_closed", username,
                                {"after_instance_id": finished_id,
                                 "reason": "completed"}, ts)
        return self._append("advanced", username, {
            "from_instance_id": finished_id,
            "to_instance_id": self.item_ids[self.current_index],
            "index": self.current_index,
        }, ts)

    def close(self, username: str, ts: Optional[float] = None) -> Dict[str, Any]:
        self._require_open()
        self._require_host(username)
        self.status = CLOSED
        return self._append("room_closed", username, {"reason": "closed_by_host"}, ts)

    # ------------------------------------------------------------------
    # Replay

    APPLY_ORDER = ("room_created", "member_joined", "member_left", "vote_cast",
                   "vote_changed", "revealed", "message", "advanced",
                   "room_closed")

    def apply(self, event: Dict[str, Any]) -> None:
        """Re-apply a persisted event during replay (no new event emitted)."""
        etype, user, data = event["type"], event["user"], event["data"]
        ts = event.get("ts")
        # Suppress the append the mutation would do; splice the original back.
        before = len(self.events)
        if etype == "room_created":
            pass  # constructor state already covers it
        elif etype == "member_joined":
            if user in self.members:
                self.members[user].active = True
            else:
                self.members[user] = RoomMember(
                    username=user, role=data.get("role", MEMBER),
                    joined_at=ts or 0.0)
        elif etype == "member_left":
            if user in self.members:
                self.members[user].active = False
        elif etype == "vote_cast":
            item = self.item_states[data["instance_id"]]
            item.initial_votes[user] = data["label"]
            item.current_votes[user] = data["label"]
        elif etype == "vote_changed":
            item = self.item_states[data["instance_id"]]
            item.changes.append({
                "user": user, "from": data["from"], "to": data["to"],
                "majority_at_time": data.get("majority_at_time"), "ts": ts,
            })
            item.current_votes[user] = data["to"]
        elif etype == "revealed":
            self.item_states[data["instance_id"]].revealed = True
        elif etype == "message":
            pass  # chat is rendered straight from events
        elif etype == "advanced":
            item = self.item_states[data["from_instance_id"]]
            if not item.revealed:
                item.skipped = True
            self.current_index = data["index"]
        elif etype == "room_closed":
            after = data.get("after_instance_id")
            if after and not self.item_states[after].revealed:
                self.item_states[after].skipped = True
            self.status = CLOSED
            self.current_index = len(self.item_ids)
        del self.events[before:]
        self.events.append(event)

    # ------------------------------------------------------------------
    # Snapshots

    def to_summary(self) -> Dict[str, Any]:
        """Lobby row."""
        return {
            "room_id": self.room_id, "room_type": self.room_type,
            "host": self.host, "status": self.status,
            "n_members": sum(1 for m in self.members.values() if m.active),
            "n_items": len(self.item_ids),
            "current_index": min(self.current_index, len(self.item_ids)),
            "created_at": self.created_at,
        }

    def to_state(self, viewer: str) -> Dict[str, Any]:
        """Full snapshot for the room page. Blind votes stay blind — except
        the viewer always sees their own current vote."""
        item = self.current_item
        item_snapshot = None
        seed_votes = None
        if item is not None:
            item_snapshot = item.to_dict(include_votes=item.revealed)
            item_snapshot["my_vote"] = item.current_votes.get(viewer)
            # Huddle context: the original (pre-room) annotations for this item.
            seeds = self.settings.get("seed_annotations") or {}
            seed_votes = seeds.get(item.instance_id)
        member = self.members.get(viewer)
        return {
            "room_id": self.room_id, "room_type": self.room_type,
            "host": self.host, "schema": self.schema, "labels": self.labels,
            "status": self.status, "phase": self.phase,
            "current_index": min(self.current_index, len(self.item_ids)),
            "n_items": len(self.item_ids),
            "item_ids": self.item_ids,
            "current_instance_id": self.current_item_id,
            "members": [m.to_dict() for m in self.members.values()],
            "current_item": item_snapshot,
            "seed_votes": seed_votes,
            "my_role": member.role if member else None,
            "all_voted": self.all_voted(),
            "cursor": len(self.events),
        }
