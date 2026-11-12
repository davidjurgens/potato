"""Live collaborative sessions: the event-sourced session model.

A session is a team working through a set of items together. Their shared
answer for each item is stored under one team user (``team-<slug>``); the
session itself records who is in it, who leads, where each member is looking,
and every change anyone made to the shared answers.

Every change to a session is an event, and ``Session.apply`` is the only
thing that changes one -- live, and when the log is replayed at boot. An event
is ``{"seq", "ts", "type", "user", "data"}``:

| type             | data                                                     |
|------------------|----------------------------------------------------------|
| session_created  | name, team_user, team_id, item_ids, mode, leader, source,|
|                  | blind_first, require_signoff                             |
| member_joined    | role                                                     |
| member_left      | {}                                                       |
| leader_changed   | leader                                                   |
| mode_changed     | mode                                                     |
| viewing          | instance_id, following                                   |
| edit             | instance_id, rev, ops, conflicts, save_id, reverts?      |
| message          | text, mentions                                           |
| discussion       | instance_id, memo_id, excerpt, mentions                  |
| summon           | instance_id                                              |
| signoff          | instance_id, ready, rev                                  |
| blind_done       | instance_id                                              |
| revealed         | instance_id, answers, units, agreement, seeded           |
| poll_opened      | poll_id, instance_id, question, options, schema          |
| poll_vote        | poll_id, option                                          |
| poll_closed      | poll_id, counts, winner, applied                         |
| session_closed   | {}                                                       |

Sign-off is bound to a revision: a member is ready on an item while the
revision they signed is still the item's revision, so any later edit clears
everyone's sign-off without an event of its own.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

LEADER = "leader"
MEMBER = "member"
OBSERVER = "observer"
ROLES = (LEADER, MEMBER, OBSERVER)

FOLLOW = "follow"
FREE = "free"
MODES = (FOLLOW, FREE)

OPEN = "open"
CLOSED = "closed"

MAX_MESSAGE_CHARS = 2000
MAX_POLL_OPTIONS = 10


class CollabError(Exception):
    """A refused session action (maps to a 4xx)."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass
class Member:
    username: str
    role: str = MEMBER
    joined_at: float = 0.0
    active: bool = True
    viewing: Optional[str] = None
    following: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {"username": self.username, "role": self.role,
                "joined_at": self.joined_at, "active": self.active,
                "viewing": self.viewing, "following": self.following}


@dataclass
class Session:
    session_id: str
    name: str
    team_user: str
    team_id: str
    item_ids: List[str]
    created_by: Optional[str]
    created_at: float
    source: str = "lobby"            # "lobby" | "config"
    mode: str = FOLLOW
    leader: Optional[str] = None
    status: str = OPEN
    members: Dict[str, Member] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)
    #: instance_id -> number of edits applied to it (its revision)
    item_rev: Dict[str, int] = field(default_factory=dict)
    #: instance_id -> indices into ``events`` of its edits, oldest first
    item_edits: Dict[str, List[int]] = field(default_factory=dict)
    #: members answer each item on their own before the team's answer opens
    blind_first: bool = False
    #: an item is done when every active editing member has signed it off
    require_signoff: bool = False
    #: instance_id -> username -> the revision they signed off
    signoffs: Dict[str, Dict[str, int]] = field(default_factory=dict)
    #: instance_id -> members who finished their blind answer
    blind_done: Dict[str, List[str]] = field(default_factory=dict)
    #: instance_id -> the reveal event's seq
    revealed: Dict[str, int] = field(default_factory=dict)
    #: poll_id -> {poll_id, instance_id, question, options, schema, opened_by,
    #:             votes: {user: option}, open, counts?, winner?}
    polls: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Events

    def new_event(self, type_: str, user: Optional[str], data: Dict[str, Any],
                  ts: Optional[float] = None) -> Dict[str, Any]:
        return {"seq": len(self.events) + 1, "ts": ts if ts is not None else time.time(),
                "type": type_, "user": user, "data": data}

    def apply(self, event: Dict[str, Any]) -> None:
        """Apply one event to the session and append it to the log."""
        kind, user, data = event["type"], event.get("user"), event.get("data") or {}
        if kind == "member_joined":
            member = self.members.get(user)
            if member is None:
                self.members[user] = Member(user, data.get("role", MEMBER),
                                            event["ts"], True)
            else:
                member.active = True
                if data.get("role"):
                    member.role = data["role"]
        elif kind == "member_left":
            if user in self.members:
                self.members[user].active = False
        elif kind == "leader_changed":
            new_leader = data.get("leader")
            for member in self.members.values():
                if member.role == LEADER and member.username != new_leader:
                    member.role = MEMBER
            if new_leader in self.members:
                self.members[new_leader].role = LEADER
            self.leader = new_leader
        elif kind == "mode_changed":
            self.mode = data.get("mode", self.mode)
        elif kind == "viewing":
            member = self.members.get(user)
            if member is not None:
                member.viewing = data.get("instance_id")
                if "following" in data:
                    member.following = bool(data["following"])
        elif kind == "edit":
            iid = data["instance_id"]
            self.item_rev[iid] = int(data.get("rev", self.item_rev.get(iid, 0) + 1))
            self.item_edits.setdefault(iid, []).append(len(self.events))
        elif kind == "signoff":
            per_item = self.signoffs.setdefault(data["instance_id"], {})
            if data.get("ready"):
                per_item[user] = int(data.get("rev", 0))
            else:
                per_item.pop(user, None)
        elif kind == "blind_done":
            done = self.blind_done.setdefault(data["instance_id"], [])
            if user not in done:
                done.append(user)
        elif kind == "revealed":
            self.revealed[data["instance_id"]] = len(self.events) + 1
        elif kind == "poll_opened":
            self.polls[data["poll_id"]] = {
                "poll_id": data["poll_id"], "instance_id": data.get("instance_id"),
                "question": data.get("question"), "options": list(data.get("options") or []),
                "schema": data.get("schema"), "opened_by": user, "opened_at": event["ts"],
                "votes": {}, "open": True}
        elif kind == "poll_vote":
            poll = self.polls.get(data.get("poll_id"))
            if poll is not None and poll["open"]:
                poll["votes"][user] = data.get("option")
        elif kind == "poll_closed":
            poll = self.polls.get(data.get("poll_id"))
            if poll is not None:
                poll.update(open=False, counts=data.get("counts") or {},
                            winner=data.get("winner"), applied=data.get("applied", False),
                            closed_by=user)
        elif kind == "session_closed":
            self.status = CLOSED
        self.events.append(event)

    # ------------------------------------------------------------------
    # Reads

    def rev_of(self, instance_id: str) -> int:
        return self.item_rev.get(instance_id, 0)

    def edits_of(self, instance_id: str) -> List[Dict[str, Any]]:
        return [self.events[i] for i in self.item_edits.get(instance_id, [])]

    def is_member(self, username: str) -> bool:
        member = self.members.get(username)
        return member is not None and member.active

    def can_edit(self, username: str) -> bool:
        member = self.members.get(username)
        return (member is not None and member.active and member.role != OBSERVER
                and self.status == OPEN)

    def editors(self) -> List[str]:
        """Active members who can change the answer (not observers)."""
        return [m.username for m in self.members.values()
                if m.active and m.role != OBSERVER]

    def is_blind(self, instance_id: str) -> bool:
        """Still in the answer-on-your-own stage for this item."""
        return self.blind_first and instance_id not in self.revealed

    def ready_members(self, instance_id: str) -> List[str]:
        """Members whose sign-off is on the item's current revision."""
        rev = self.rev_of(instance_id)
        return sorted(u for u, r in self.signoffs.get(instance_id, {}).items()
                      if r == rev and self.is_member(u))

    def is_signed_off(self, instance_id: str) -> bool:
        editors = self.editors()
        ready = set(self.ready_members(instance_id))
        return bool(editors) and all(u in ready for u in editors)

    def open_poll_for(self, instance_id: str) -> Optional[Dict[str, Any]]:
        for poll in self.polls.values():
            if poll["open"] and poll.get("instance_id") == instance_id:
                return poll
        return None

    def item_status(self, instance_id: str) -> Dict[str, Any]:
        return {
            "rev": self.rev_of(instance_id),
            "ready": self.ready_members(instance_id),
            "signed_off": self.is_signed_off(instance_id),
            "blind": self.is_blind(instance_id),
            "blind_done": list(self.blind_done.get(instance_id, [])),
        }

    def leader_view(self) -> Optional[str]:
        leader = self.members.get(self.leader) if self.leader else None
        return leader.viewing if leader is not None else None

    def to_summary(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id, "name": self.name,
            "team_id": self.team_id, "team_user": self.team_user,
            "source": self.source, "mode": self.mode,
            "leader": self.leader, "status": self.status,
            "n_items": len(self.item_ids),
            "n_members": sum(1 for m in self.members.values() if m.active),
            "created_by": self.created_by, "created_at": self.created_at,
            "blind_first": self.blind_first, "require_signoff": self.require_signoff,
        }

    def to_state(self, viewer: str) -> Dict[str, Any]:
        state = self.to_summary()
        state.update({
            "item_ids": list(self.item_ids),
            "members": [m.to_dict() for m in self.members.values()],
            "me": self.members[viewer].to_dict() if viewer in self.members else None,
            "cursor": len(self.events),
            "leader_view": self.leader_view(),
            "items": {iid: self.item_status(iid) for iid in self.item_ids},
            "polls": [self.poll_view(p, viewer) for p in self.polls.values()
                      if p["open"] or time.time() - p.get("opened_at", 0) < 3600],
        })
        return state

    def poll_view(self, poll: Dict[str, Any], viewer: str) -> Dict[str, Any]:
        """A poll as one member may see it: others' votes stay hidden until it closes."""
        view = {k: v for k, v in poll.items() if k != "votes"}
        view["voted"] = sorted(poll["votes"])
        view["my_vote"] = poll["votes"].get(viewer)
        if not poll["open"]:
            view["votes"] = dict(poll["votes"])
        return view
