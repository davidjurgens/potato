"""RoomsManager — lifecycle, persistence, and metrics for annotation rooms.

Rooms are event-sourced: every mutation appends one event to the room's
in-memory list AND to ``<output_annotation_dir>/rooms/room-<id>.jsonl``.
On boot the manager replays any existing logs, so live sessions survive a
server restart. Ephemeral presence (shadow-mode cursors) is kept in a small
in-memory ring buffer and never persisted.

Metrics: the live agreement meter computes nominal Krippendorff's alpha over
revealed items twice — on blind (initial) votes and on current votes — via
simpledorff (a core dependency that tolerates missing annotator/item cells).
The gap between the two is the room's "norming lift". Post-reveal vote
changes are the conformity log.
"""

import json
import logging
import os
import threading
from collections import deque
from typing import Any, Dict, Hashable, List, Optional

from potato.rooms.config import RoomsConfig, parse_rooms_config
from potato.rooms.models import (
    CLOSED,
    HOST,
    MEMBER,
    OBSERVER,
    Room,
    RoomError,
    new_room_id,
)

logger = logging.getLogger(__name__)

_PRESENCE_BUFFER = 50

# Annotation values that mean "not actually selected" (see psychometrics).
_FALSY_VALUES = {None, "", 0, False, "false", "False", "unchecked", "0"}


class RoomsManager:
    def __init__(self, config: Dict[str, Any]):
        self.app_config = config
        self.rooms_config: RoomsConfig = parse_rooms_config(config)
        self.rooms: Dict[str, Room] = {}
        # room_id -> deque of ephemeral presence events (not persisted)
        self.presence: Dict[str, deque] = {}
        self.lock = threading.RLock()

        output_dir = config.get("output_annotation_dir", "")
        self.rooms_dir = os.path.join(output_dir, "rooms") if output_dir else None
        if self.rooms_dir:
            os.makedirs(self.rooms_dir, exist_ok=True)
            self._load_existing_rooms()

    # ------------------------------------------------------------------
    # Persistence

    def _log_path(self, room_id: str) -> Optional[str]:
        if not self.rooms_dir:
            return None
        return os.path.join(self.rooms_dir, f"room-{room_id}.jsonl")

    def _persist_event(self, room_id: str, event: Dict[str, Any]) -> None:
        path = self._log_path(room_id)
        if not path:
            return
        try:
            with open(path, "a") as f:
                f.write(json.dumps(event) + "\n")
        except OSError as e:  # persistence failure must not kill a live room
            logger.error("rooms: could not append to %s: %s", path, e)

    def _load_existing_rooms(self) -> None:
        try:
            filenames = sorted(os.listdir(self.rooms_dir))
        except OSError:
            return
        for filename in filenames:
            if not (filename.startswith("room-") and filename.endswith(".jsonl")):
                continue
            room_id = filename[len("room-"):-len(".jsonl")]
            path = os.path.join(self.rooms_dir, filename)
            try:
                room = self._replay(room_id, path)
            except Exception as e:
                logger.error("rooms: could not replay %s: %s", path, e)
                continue
            if room is not None:
                self.rooms[room_id] = room
        if self.rooms:
            logger.info("rooms: restored %d room(s) from event logs", len(self.rooms))

    @staticmethod
    def _replay(room_id: str, path: str) -> Optional[Room]:
        events: List[Dict[str, Any]] = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        if not events or events[0]["type"] != "room_created":
            return None
        created = events[0]
        data = created["data"]
        room = Room(
            room_id=room_id,
            room_type=data["room_type"],
            host=created["user"],
            schema=data["schema"],
            labels=data["labels"],
            item_ids=data["item_ids"],
            settings=data.get("settings"),
            created_at=created.get("ts"),
        )
        for event in events:
            room.apply(event)
        return room

    # ------------------------------------------------------------------
    # Room lifecycle

    def create_room(self, host: str, room_type: str, item_ids: List[str],
                    labels: List[str], schema: Optional[str] = None,
                    settings: Optional[Dict[str, Any]] = None) -> Room:
        with self.lock:
            room_id = new_room_id()
            while room_id in self.rooms:
                room_id = new_room_id()
            room = Room(
                room_id=room_id,
                room_type=room_type,
                host=host,
                schema=schema or self.rooms_config.schema,
                labels=labels,
                item_ids=item_ids,
                settings=settings,
            )
            self._persist_event(room_id, room.record_created())
            self._persist_event(room_id, room.join(host, role=HOST))
            self.rooms[room_id] = room
            return room

    def get_room(self, room_id: str) -> Optional[Room]:
        return self.rooms.get((room_id or "").upper())

    def list_rooms(self) -> List[Dict[str, Any]]:
        with self.lock:
            rooms = sorted(self.rooms.values(),
                           key=lambda r: r.created_at, reverse=True)
            return [r.to_summary() for r in rooms]

    # ------------------------------------------------------------------
    # Mutations (thread-safe, persisted)

    def _mutate(self, room: Room, method: str, *args) -> Dict[str, Any]:
        with self.lock:
            event = getattr(room, method)(*args)
            self._persist_event(room.room_id, event)
            return event

    def join(self, room: Room, username: str, role: str = MEMBER) -> Dict[str, Any]:
        with self.lock:
            active = sum(1 for m in room.members.values() if m.active)
            if (username not in room.members
                    and active >= self.rooms_config.max_members):
                raise RoomError("Room is full")
            return self._mutate(room, "join", username, role)

    def leave(self, room: Room, username: str) -> Dict[str, Any]:
        return self._mutate(room, "leave", username)

    def vote(self, room: Room, username: str, label: str) -> Dict[str, Any]:
        return self._mutate(room, "vote", username, label)

    def reveal(self, room: Room, username: str) -> Dict[str, Any]:
        return self._mutate(room, "reveal", username)

    def message(self, room: Room, username: str, text: str) -> Dict[str, Any]:
        return self._mutate(room, "message", username, text)

    def advance(self, room: Room, username: str) -> Dict[str, Any]:
        with self.lock:
            finished = room.current_item
            event = self._mutate(room, "advance", username)
            if (finished is not None and finished.revealed
                    and self.rooms_config.persist_votes):
                self._persist_final_votes(room, finished)
            return event

    def close(self, room: Room, username: str) -> Dict[str, Any]:
        with self.lock:
            finished = room.current_item
            event = self._mutate(room, "close", username)
            if (finished is not None and finished.revealed
                    and self.rooms_config.persist_votes):
                self._persist_final_votes(room, finished)
            return event

    # ------------------------------------------------------------------
    # Presence (ephemeral, shadow mode)

    def record_presence(self, room: Room, username: str,
                        data: Dict[str, Any]) -> None:
        buffer = self.presence.setdefault(room.room_id, deque(maxlen=_PRESENCE_BUFFER))
        buffer.append({"user": username, "data": data,
                       "seq": len(room.events)})

    def presence_since(self, room: Room, since: int) -> List[Dict[str, Any]]:
        buffer = self.presence.get(room.room_id)
        if not buffer:
            return []
        return [p for p in buffer if p["seq"] >= since]

    # ------------------------------------------------------------------
    # Events for pollers

    def events_since(self, room: Room, since: int) -> List[Dict[str, Any]]:
        """Public (blind-safe) views of events with seq > since."""
        with self.lock:
            return [Room.public_view(e) for e in room.events[since:]]

    # ------------------------------------------------------------------
    # Metrics

    @staticmethod
    def _alpha(votes_by_item: Dict[str, Dict[str, str]]) -> Optional[float]:
        """Nominal Krippendorff's alpha over an incomplete item×user table."""
        rows = [(iid, user, label)
                for iid, votes in votes_by_item.items()
                for user, label in votes.items()]
        if len(rows) < 2:
            return None
        try:
            import pandas as pd
            import simpledorff
            df = pd.DataFrame(rows, columns=["instance_id", "user", "label"])
            alpha = simpledorff.calculate_krippendorffs_alpha_for_df(
                df, experiment_col="instance_id",
                annotator_col="user", class_col="label")
        except Exception:  # degenerate tables (1 item, unanimity...) → no meter
            return None
        if alpha != alpha:  # NaN
            return None
        return float(alpha)

    def metrics(self, room: Room) -> Dict[str, Any]:
        """Live meter payload: blind vs final alpha + conformity accounting."""
        with self.lock:
            revealed = [s for s in room.item_states.values() if s.revealed]
            blind = {s.instance_id: dict(s.initial_votes) for s in revealed}
            final = {s.instance_id: dict(s.current_votes) for s in revealed}
            blind_alpha = self._alpha(blind)
            final_alpha = self._alpha(final)

            per_member: Dict[str, Dict[str, int]] = {}
            total_changes = 0
            toward_majority = 0
            for state in revealed:
                for user in state.initial_votes:
                    entry = per_member.setdefault(
                        user, {"votes": 0, "changes": 0, "toward_majority": 0})
                    entry["votes"] += 1
                for change in state.changes:
                    entry = per_member.setdefault(
                        change["user"],
                        {"votes": 0, "changes": 0, "toward_majority": 0})
                    entry["changes"] += 1
                    total_changes += 1
                    if (change.get("majority_at_time")
                            and change["to"] == change["majority_at_time"]):
                        entry["toward_majority"] += 1
                        toward_majority += 1

            return {
                "n_revealed": len(revealed),
                "blind_alpha": blind_alpha,
                "final_alpha": final_alpha,
                "alpha_lift": (final_alpha - blind_alpha
                               if blind_alpha is not None and final_alpha is not None
                               else None),
                "total_changes": total_changes,
                "toward_majority": toward_majority,
                "per_member": per_member,
            }

    # ------------------------------------------------------------------
    # Huddle seeds: items the team currently disagrees on

    def find_disagreements(self) -> List[Dict[str, Any]]:
        """Items with ≥2 annotators and non-unanimous labels on the room
        schema — the natural seed list for an adjudication huddle."""
        schema = self.rooms_config.schema
        if not schema:
            return []
        votes: Dict[str, Dict[str, str]] = {}
        try:
            from potato.user_state_management import get_user_state_manager
            users = get_user_state_manager().get_all_users()
        except Exception:
            return []
        for user_state in users:
            user_id = getattr(user_state, "user_id", None)
            if not user_id:
                continue
            for instance_id, annotations in user_state.get_all_annotations().items():
                names = [
                    label_obj.get_name()
                    for label_obj, value in (annotations.get("labels") or {}).items()
                    if label_obj.get_schema() == schema
                    and not (isinstance(value, Hashable) and value in _FALSY_VALUES)
                ]
                if len(names) == 1:
                    votes.setdefault(str(instance_id), {})[user_id] = names[0]
        disagreements = []
        for instance_id, item_votes in votes.items():
            distinct = len(set(item_votes.values()))
            if len(item_votes) >= 2 and distinct > 1:
                disagreements.append({
                    "instance_id": instance_id,
                    "annotations": item_votes,
                    "n_annotators": len(item_votes),
                    "n_labels": distinct,
                })
        disagreements.sort(key=lambda r: (-r["n_labels"], -r["n_annotators"],
                                          r["instance_id"]))
        return disagreements

    # ------------------------------------------------------------------
    # Writing final votes into real annotation state

    def _persist_final_votes(self, room: Room, item_state) -> None:
        """Write each member's final vote into their annotation state so room
        work counts as annotations. Never allowed to break the room."""
        try:
            from potato.item_state_management import (
                Label,
                get_item_state_manager,
            )
            from potato.user_state_management import get_user_state_manager

            usm = get_user_state_manager()
            ism = get_item_state_manager()
            instance_id = item_state.instance_id
            if not ism.has_item(instance_id):
                return
            for username, label in item_state.current_votes.items():
                member = room.members.get(username)
                if member is None or member.role == OBSERVER:
                    continue
                user_state = usm.get_user_state(username)
                if user_state is None:
                    continue
                annotations = user_state.instance_id_to_label_to_value[instance_id]
                for existing in [l for l in list(annotations)
                                 if isinstance(l, Label)
                                 and l.get_schema() == room.schema]:
                    del annotations[existing]
                annotations[Label(room.schema, label)] = "true"
                if username not in ism.instance_annotators[instance_id]:
                    ism.register_annotator(instance_id, username)
                usm.save_user_state(user_state)
        except Exception as e:
            logger.error("rooms: could not persist votes for room %s: %s",
                         room.room_id, e)

    # ------------------------------------------------------------------
    # Export

    def export_room(self, room: Room) -> Dict[str, Any]:
        with self.lock:
            return {
                "room": room.to_summary(),
                "schema": room.schema,
                "items": [s.to_dict(include_votes=True)
                          for s in room.item_states.values()],
                "metrics": self.metrics(room),
                "events": list(room.events),
            }


# ----------------------------------------------------------------------
# Singleton

_ROOMS_MANAGER: Optional[RoomsManager] = None


def init_rooms_manager(config: Dict[str, Any]) -> Optional[RoomsManager]:
    global _ROOMS_MANAGER
    manager = RoomsManager(config)
    if not manager.rooms_config.enabled:
        _ROOMS_MANAGER = None
        return None
    _ROOMS_MANAGER = manager
    logger.info("Multiplayer rooms enabled (schema=%s)", manager.rooms_config.schema)
    return _ROOMS_MANAGER


def get_rooms_manager() -> Optional[RoomsManager]:
    return _ROOMS_MANAGER


def clear_rooms_manager() -> None:
    global _ROOMS_MANAGER
    _ROOMS_MANAGER = None
