"""The live collaborative session manager (a process-wide singleton).

Owns the sessions, their logs (``<output_annotation_dir>/collab/
session-<CODE>.jsonl``, replayed at boot), the team users the shared answers
are stored under, and the write path that merges a member's save into the
team's answer and records what changed.

Single process: like every other in-memory store in Potato, sessions live in
this process, so a deployment runs one worker (see docker-entrypoint.sh).
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional, Set

from potato.collab.config import CollabConfig, parse_collab_config, team_user_for
from potato.collab.models import (
    CLOSED,
    FOLLOW,
    LEADER,
    MAX_MESSAGE_CHARS,
    MAX_POLL_OPTIONS,
    MEMBER,
    MODES,
    OBSERVER,
    OPEN,
    CollabError,
    Session,
)
from potato.collab import state as collab_state

logger = logging.getLogger(__name__)

_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_PRESENCE_TTL_SECONDS = 45.0
_MENTION = re.compile(r"(?<![\w@])@([\w.\-]+)")
#: a gap longer than this between two moves is not counted as time on an item
_IDLE_CAP_SECONDS = 600.0


def new_session_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))


class CollabManager:
    def __init__(self, config: Dict[str, Any]):
        self.app_config = config
        self.cfg: CollabConfig = parse_collab_config(config)
        self.sessions: Dict[str, Session] = {}
        self.lock = threading.RLock()
        # Woken on every appended event, for the SSE streams.
        self.changed = threading.Condition(self.lock)
        self._session_locks: Dict[str, threading.RLock] = {}
        # session_id -> username -> {instance_id, focus, ts, seq}; not persisted
        self.presence: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._presence_seq = 0
        self.active_streams = 0

        output_dir = config.get("output_annotation_dir", "")
        self.dir = os.path.join(output_dir, "collab") if output_dir else None
        if self.dir:
            os.makedirs(self.dir, exist_ok=True)
            self._load_existing()

    # ------------------------------------------------------------------
    # Persistence

    def _path(self, session_id: str) -> Optional[str]:
        return os.path.join(self.dir, f"session-{session_id}.jsonl") if self.dir else None

    def _persist(self, session: Session, event: Dict[str, Any]) -> None:
        path = self._path(session.session_id)
        if not path:
            return
        try:
            with open(path, "a+b") as f:
                # A log cut off mid-line (a crash during a write) must not
                # swallow the next event too: start it on a fresh line.
                f.seek(0, os.SEEK_END)
                if f.tell():
                    f.seek(-1, os.SEEK_END)
                    if f.read(1) != b"\n":
                        f.write(b"\n")
                f.write((json.dumps(event, default=str) + "\n").encode("utf-8"))
        except OSError as exc:
            # Raised, unlike the rooms log: an edit missing from the log
            # breaks every later merge against an older base.
            logger.error("Could not write collab session log %s: %s", path, exc)
            raise

    def _load_existing(self) -> None:
        for name in sorted(os.listdir(self.dir)):
            if not (name.startswith("session-") and name.endswith(".jsonl")):
                continue
            session_id = name[len("session-"):-len(".jsonl")]
            path = os.path.join(self.dir, name)
            try:
                session = self._replay(path)
            except Exception as exc:  # noqa: BLE001 - one bad log must not stop boot
                # Set aside, not left in place: a configured team would
                # otherwise start a fresh session in the same file, and every
                # later boot would skip that one too.
                aside = f"{path}.unreadable-{int(time.time())}"
                logger.error("Collab session log %s cannot be read (%s); moved to %s",
                             name, exc, os.path.basename(aside))
                try:
                    os.replace(path, aside)
                except OSError:
                    pass
                continue
            if session is not None:
                self.sessions[session_id] = session
        if self.sessions:
            logger.info("Restored %d collaborative session(s)", len(self.sessions))

    def _replay(self, path: str) -> Optional[Session]:
        session = None
        with open(path, encoding="utf-8") as f:
            lines = [line.strip() for line in f]
        for line in lines:
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                # A write cut off by a crash. The event it would have held
                # was never applied (the process died writing it), and the
                # next append starts on a fresh line, so this can sit mid-file.
                logger.warning("Ignoring a cut-off line in %s: %.60s", path, line)
                continue
            if session is None:
                if event.get("type") != "session_created":
                    raise ValueError("log does not start with session_created")
                session = self._session_from_created(event)
            session.apply(event)
        return session

    @staticmethod
    def _session_from_created(event: Dict[str, Any]) -> Session:
        data = event["data"]
        return Session(
            session_id=data["session_id"], name=data.get("name") or data["session_id"],
            team_user=data["team_user"], team_id=data.get("team_id") or data["team_user"],
            item_ids=list(data.get("item_ids") or []), created_by=event.get("user"),
            created_at=event["ts"], source=data.get("source", "lobby"),
            mode=data.get("mode", FOLLOW), leader=data.get("leader"),
            blind_first=bool(data.get("blind_first", False)),
            require_signoff=bool(data.get("require_signoff", False)),
        )

    def _emit(self, session: Session, type_: str, user: Optional[str],
              data: Dict[str, Any]) -> Dict[str, Any]:
        with self.lock:
            event = session.new_event(type_, user, data)
            self._persist(session, event)
            session.apply(event)
            self.changed.notify_all()
            return event

    # ------------------------------------------------------------------
    # Locks

    def raw_session_lock(self, session: Session) -> threading.RLock:
        """The lock every write to one session's shared answers holds."""
        with self.lock:
            return self._session_locks.setdefault(session.session_id, threading.RLock())

    @contextmanager
    def session_lock(self, session: Session):
        with self.raw_session_lock(session):
            yield

    # ------------------------------------------------------------------
    # Lookup

    def get_session(self, session_id: str) -> Optional[Session]:
        return self.sessions.get(str(session_id or "").upper())

    def sessions_for(self, username: str, open_only: bool = True) -> List[Session]:
        return [s for s in self.sessions.values()
                if s.is_member(username) and (s.status == OPEN or not open_only)]

    def list_sessions(self, username: str) -> List[Dict[str, Any]]:
        rows = []
        for s in self.sessions.values():
            if s.status != OPEN:
                continue
            # A config team is listed to its own members only.
            if s.source == "config" and username not in s.members:
                continue
            row = s.to_summary()
            row["is_member"] = s.is_member(username)
            rows.append(row)
        return sorted(rows, key=lambda r: -r["created_at"])

    def excluded_items(self, username: str) -> Set[str]:
        """Items a member's team holds, kept out of their solo queue."""
        if not self.cfg.exclude_members_from_solo:
            return set()
        excluded: Set[str] = set()
        for s in self.sessions.values():
            # is_member: a member who left gets their own queue back.
            if s.status == OPEN and s.is_member(username):
                excluded.update(s.item_ids)
        return excluded

    def teams_of(self, username: str) -> Set[str]:
        """Team ids the user belongs to, for team-scoped memos."""
        return {s.team_user for s in self.sessions.values() if s.is_member(username)}

    def session_holding(self, username: str, instance_id: str) -> Optional[Session]:
        for s in self.sessions.values():
            if s.status == OPEN and s.is_member(username) and instance_id in s.item_ids:
                return s
        return None

    # ------------------------------------------------------------------
    # Team users

    def ensure_team_user(self, team_user: str, item_ids: Iterable[str]):
        """Create (or top up) the user the team's answers are stored under."""
        from potato.item_state_management import get_item_state_manager
        from potato.phase import UserPhase
        from potato.user_state_management import get_user_state_manager

        usm, ism = get_user_state_manager(), get_item_state_manager()
        if usm.has_user(team_user):
            user_state = usm.get_user_state(team_user)
        else:
            user_state = usm.add_user(team_user)
        user_state.set_max_assignments(-1)
        if user_state.get_phase() != UserPhase.ANNOTATION:
            user_state.advance_to_phase(UserPhase.ANNOTATION, None)
        held = set(user_state.get_assigned_instance_ids())
        for iid in item_ids:
            if iid in held or not ism.has_item(iid):
                continue
            user_state.assign_instance(ism.get_item(iid))
            ism.instance_assignees[iid].add(team_user)
        usm.save_user_state(user_state)
        return user_state

    def _resolve_items(self, item_ids: Optional[List[str]] = None,
                       count: Optional[int] = None, group: Optional[str] = None) -> List[str]:
        from potato.item_state_management import get_item_state_manager
        ism = get_item_state_manager()
        if item_ids:
            missing = [i for i in item_ids if not ism.has_item(i)]
            if missing:
                raise CollabError(f"Unknown item(s): {', '.join(missing[:5])}")
            ids = list(dict.fromkeys(item_ids))
        elif group:
            resolver = getattr(ism, "_batch_candidate_ids_for_group", None)
            ids = list(resolver(group)) if resolver else []
            if not ids:
                raise CollabError(f"Batch group '{group}' has no items")
        else:
            ids = list(ism.get_instance_ids())
            if count:
                ids = ids[:count]
        qc_items = [i for i in ids if _is_quality_check(i)]
        if qc_items and item_ids:
            raise CollabError("Attention-check and gold items cannot be in a session: "
                              f"{', '.join(qc_items[:5])}")
        # They grade a person; a team save is not graded, so a session over
        # every item must not take them out of the members' own queues.
        ids = [i for i in ids if i not in set(qc_items)]
        if not ids:
            raise CollabError("A session needs at least one item")
        if len(ids) > self.cfg.max_items:
            raise CollabError(f"A session holds at most {self.cfg.max_items} items")
        return ids

    # ------------------------------------------------------------------
    # Session lifecycle

    def create_session(self, creator: Optional[str], *, name: Optional[str] = None,
                       item_ids: Optional[List[str]] = None, count: Optional[int] = None,
                       mode: Optional[str] = None, team_id: Optional[str] = None,
                       members: Iterable[str] = (), leader: Optional[str] = None,
                       source: str = "lobby", group: Optional[str] = None,
                       session_id: Optional[str] = None,
                       blind_first: Optional[bool] = None,
                       require_signoff: Optional[bool] = None) -> Session:
        mode = mode or self.cfg.default_mode
        blind_first = self.cfg.blind_first if blind_first is None else bool(blind_first)
        require_signoff = (self.cfg.require_signoff if require_signoff is None
                           else bool(require_signoff))
        if mode not in MODES:
            raise CollabError(f"mode must be one of {', '.join(MODES)}")
        ids = self._resolve_items(item_ids, count, group)
        with self.lock:
            if session_id is None:
                session_id = new_session_code()
                while session_id in self.sessions:
                    session_id = new_session_code()
            if session_id in self.sessions:
                raise CollabError(f"Session {session_id} already exists", 409)
            team_id = team_id or f"session-{session_id.lower()}"
            team_user = team_user_for(team_id)
            if any(s.team_user == team_user for s in self.sessions.values()):
                raise CollabError(f"Team '{team_id}' already has a session", 409)
            leader = leader or (creator if mode == FOLLOW else None)
            created = {
                "seq": 1, "ts": time.time(), "type": "session_created", "user": creator,
                "data": {"session_id": session_id, "name": name or session_id,
                         "team_user": team_user, "team_id": team_id, "item_ids": ids,
                         "mode": mode, "leader": leader, "source": source,
                         "blind_first": blind_first, "require_signoff": require_signoff},
            }
            session = self._session_from_created(created)
            self._persist(session, created)
            session.apply(created)
            self.sessions[session_id] = session
        self.ensure_team_user(team_user, ids)
        for username in dict.fromkeys(([creator] if creator else []) + list(members)):
            role = LEADER if username == leader else MEMBER
            self._emit(session, "member_joined", username, {"role": role})
        if leader:
            self._emit(session, "leader_changed", creator, {"leader": leader})
        return session

    def ensure_config_teams(self) -> None:
        """One session per ``collab.teams`` entry; idempotent."""
        for spec in self.cfg.teams:
            team_user = team_user_for(spec.id)
            existing = next((s for s in self.sessions.values()
                             if s.team_user == team_user), None)
            if existing is None:
                code = team_user[len("team-"):].upper()[:24]
                if code in self.sessions:
                    code = None
                try:
                    self.create_session(
                        None, name=spec.name or spec.id, item_ids=spec.items,
                        count=spec.item_count, group=spec.group, team_id=spec.id,
                        members=spec.members, leader=spec.leader, source="config",
                        session_id=code, blind_first=spec.blind_first,
                        require_signoff=spec.require_signoff)
                except CollabError as exc:
                    logger.error("collab team '%s' was not set up: %s", spec.id, exc)
                continue
            self.ensure_team_user(existing.team_user, existing.item_ids)
            for username in spec.members:
                if username not in existing.members:
                    self._emit(existing, "member_joined", username, {"role": MEMBER})

    def join(self, session: Session, username: str, role: str = MEMBER,
             admin: bool = False) -> None:
        """``admin``: the caller may watch any session, configured teams too."""
        if session.status != OPEN:
            raise CollabError("This session has ended", 409)
        if role not in (MEMBER, OBSERVER):
            raise CollabError("role must be member or observer")
        if session.source == "config" and username not in session.members and not (
                admin and role == OBSERVER):
            raise CollabError("This team's members are set by the study", 403)
        member = session.members.get(username)
        if member is not None and member.active:
            return
        active = sum(1 for m in session.members.values() if m.active and m.role != OBSERVER)
        if member is None and role != OBSERVER and active >= self.cfg.max_members:
            raise CollabError("This session is full", 409)
        self._emit(session, "member_joined", username,
                   {"role": member.role if member else role})

    def leave(self, session: Session, username: str) -> None:
        self._require_member(session, username)
        self._emit(session, "member_left", username, {})
        if session.leader == username:
            successor = next((m.username for m in session.members.values()
                              if m.active and m.role != OBSERVER), None)
            self._emit(session, "leader_changed", username, {"leader": successor})

    def set_leader(self, session: Session, username: str, new_leader: str) -> None:
        self._require_member(session, username)
        if session.leader and username != session.leader:
            raise CollabError("Only the leader can hand over the lead", 403)
        target = session.members.get(new_leader)
        if target is None or not target.active or target.role == OBSERVER:
            raise CollabError(f"'{new_leader}' is not an active member")
        self._emit(session, "leader_changed", username, {"leader": new_leader})

    def set_mode(self, session: Session, username: str, mode: str) -> None:
        self._require_member(session, username)
        if session.leader and username != session.leader:
            raise CollabError("Only the leader can change the mode", 403)
        if mode not in MODES:
            raise CollabError(f"mode must be one of {', '.join(MODES)}")
        self._emit(session, "mode_changed", username, {"mode": mode})
        if mode == FOLLOW and not session.leader:
            self._emit(session, "leader_changed", username, {"leader": username})

    def close(self, session: Session, username: str) -> None:
        self._require_member(session, username)
        if session.leader and username != session.leader:
            raise CollabError("Only the leader can end the session", 403)
        self._emit(session, "session_closed", username, {})

    def _require_member(self, session: Session, username: str) -> None:
        if not session.is_member(username):
            raise CollabError("Join the session first", 403)

    # ------------------------------------------------------------------
    # Viewing, following, summoning

    def target_for(self, session: Session, username: str, action: str,
                   go_to: Any = None, current: Optional[str] = None) -> str:
        """The item a navigation action leads to within the session."""
        self._require_member(session, username)
        ids = session.item_ids
        here = current if current in ids else (session.members[username].viewing
                                               if session.members[username].viewing in ids
                                               else ids[0])
        index = ids.index(here)
        if action in ("next_instance", "next"):
            return ids[min(index + 1, len(ids) - 1)]
        if action in ("prev_instance", "prev"):
            return ids[max(index - 1, 0)]
        if action == "follow":
            return session.leader_view() or here
        if action == "go_to":
            if go_to in ids:
                return go_to
            try:
                position = int(go_to)
            except (TypeError, ValueError):
                raise CollabError(f"'{go_to}' is not an item in this session", 404)
            if 1 <= position <= len(ids):
                return ids[position - 1]
            raise CollabError(f"There is no item {position} in this session", 404)
        if action in ("jump_to_unannotated", "jump_to_unannotated_prev"):
            return self._next_unanswered(session, ids, index,
                                         backwards=action.endswith("_prev")) or here
        raise CollabError(f"Unknown navigation action '{action}'")

    def _next_unanswered(self, session, ids, index, backwards=False) -> Optional[str]:
        from potato.user_state_management import get_user_state_manager
        team = get_user_state_manager().get_user_state(session.team_user)
        order = (list(reversed(ids[:index])) + list(reversed(ids[index:]))
                 if backwards else ids[index + 1:] + ids[:index + 1])
        for iid in order:
            if session.require_signoff:
                if not session.is_signed_off(iid):
                    return iid
            elif not team.has_annotated(iid):
                return iid
        return None

    def view(self, session: Session, username: str, instance_id: str,
             following: Optional[bool] = None) -> None:
        """Record where a member is. A non-leader moving by hand stops following."""
        self._require_member(session, username)
        if instance_id not in session.item_ids:
            raise CollabError("That item is not in this session", 404)
        member = session.members[username]
        if following is None:
            following = member.following
        if member.viewing == instance_id and member.following == following:
            return
        self._emit(session, "viewing", username,
                   {"instance_id": instance_id, "following": bool(following)})

    def summon(self, session: Session, username: str, instance_id: str) -> None:
        self._require_member(session, username)
        if instance_id not in session.item_ids:
            raise CollabError("That item is not in this session", 404)
        self._emit(session, "summon", username, {"instance_id": instance_id})

    def message(self, session: Session, username: str, text: str) -> Dict[str, Any]:
        self._require_member(session, username)
        text = (text or "").strip()[:MAX_MESSAGE_CHARS]
        if not text:
            raise CollabError("A message needs some text")
        return self._emit(session, "message", username,
                          {"text": text, "mentions": self.mentions_in(session, text, username)})

    @staticmethod
    def mentions_in(session: Session, text: str, author: Optional[str] = None) -> List[str]:
        """Members named as ``@name`` in ``text`` (any case), in order, once each."""
        by_lower = {name.lower(): name for name in session.members}
        found: List[str] = []
        for raw in _MENTION.findall(text or ""):
            # "@ana." at the end of a sentence still names ana.
            for candidate in (raw, raw.rstrip(".-")):
                name = by_lower.get(candidate.lower())
                if name and name != author and name not in found:
                    found.append(name)
                    break
        return found

    def discuss(self, session: Session, username: str, instance_id: str, body: str,
                task_dir: str, project: str) -> Dict[str, Any]:
        """Post to the item's team thread (a memo) and tell the session."""
        from potato.memos.service import MemoError, create_memo
        self._require_member(session, username)
        if instance_id not in session.item_ids:
            raise CollabError("That item is not in this session", 404)
        try:
            memo = create_memo(task_dir, project=project, instance_id=instance_id,
                               body=body, created_by=username, visibility="shared",
                               team_id=session.team_user)
        except MemoError as exc:
            raise CollabError(str(exc))
        text = memo.get("body") or ""
        self._emit(session, "discussion", username, {
            "instance_id": instance_id, "memo_id": memo.get("id"),
            "excerpt": text[:140], "mentions": self.mentions_in(session, text, username)})
        return memo

    # ------------------------------------------------------------------
    # Presence (ephemeral)

    def record_presence(self, session: Session, username: str,
                        data: Dict[str, Any]) -> None:
        self._require_member(session, username)
        with self.lock:
            self._presence_seq += 1
            entry = {
                "user": username, "instance_id": data.get("instance_id"),
                "focus": data.get("focus"), "ts": time.time(), "seq": self._presence_seq,
            }
            view = data.get("view")
            # Only the leader's view is followed; nobody else's is worth sending.
            if isinstance(view, dict) and username == session.leader and self.cfg.sync_view:
                entry["view"] = _clean_view(view)
            self.presence.setdefault(session.session_id, {})[username] = entry

    def presence_of(self, session: Session) -> List[Dict[str, Any]]:
        now = time.time()
        with self.lock:
            entries = self.presence.get(session.session_id, {})
            return [dict(p) for p in entries.values()
                    if now - p["ts"] <= _PRESENCE_TTL_SECONDS]

    # ------------------------------------------------------------------
    # Events

    def events_since(self, session: Session, since: int) -> List[Dict[str, Any]]:
        with self.lock:
            return list(session.events[max(0, since):])

    def wait_for_events(self, session: Session, since: int, timeout: float) -> bool:
        """Block until the session has events past ``since`` (or timeout)."""
        with self.changed:
            if len(session.events) > since:
                return True
            self.changed.wait(timeout)
            return len(session.events) > since

    # ------------------------------------------------------------------
    # The shared answer

    def state_at(self, session: Session, instance_id: str, rev: int,
                 current: Dict[str, Any]) -> Dict[str, Any]:
        """The item's snapshot as of revision ``rev`` (undo later edits)."""
        later = [e["data"]["ops"] for e in session.edits_of(instance_id)
                 if int(e["data"].get("rev", 0)) > rev]
        snap = dict(current)
        for ops in reversed(later):
            snap = collab_state.unapply(snap, ops)
        return snap

    def _last_author(self, session: Session, instance_id: str, key: str,
                     after_rev: int) -> Optional[str]:
        for event in reversed(session.edits_of(instance_id)):
            if int(event["data"].get("rev", 0)) <= after_rev:
                break
            if any(op["key"] == key or op["key"].startswith(key + ":::")
                   for op in event["data"]["ops"]):
                return event["user"]
        return None

    def record_edit(self, session: Session, actor: str, instance_id: str,
                    before: Dict[str, Any], after: Dict[str, Any], *,
                    conflicts: Optional[List[Dict[str, Any]]] = None,
                    save_id: Optional[str] = None, via: str = "save",
                    base_rev: Optional[int] = None,
                    reverts: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Log what a write changed; None when it changed nothing."""
        ops = collab_state.diff(before, after)
        if not ops:
            return None
        from potato.collab.describe import describe_ops
        overwrote = []
        for c in conflicts or []:
            who = self._last_author(session, instance_id, c["key"],
                                    base_rev if base_rev is not None else 0)
            if who and who != actor:
                overwrote.append({"key": c["key"], "user": who,
                                  "theirs": c.get("theirs")})
        data = {"instance_id": instance_id, "rev": session.rev_of(instance_id) + 1,
                "ops": ops,
                "summary": describe_ops(ops, self.app_config, self._plain_text(instance_id)),
                "via": via, "save_id": save_id, "overwrote": overwrote}
        if base_rev is not None:
            data["base_rev"] = base_rev
        if reverts is not None:
            data["reverts"] = reverts
        event = self._emit(session, "edit", actor, data)
        try:
            from potato.user_state_management import get_user_state_manager
            team = get_user_state_manager().get_user_state(session.team_user)
            if actor and hasattr(team, "record_collab_contribution"):
                team.record_collab_contribution(instance_id, session.session_id,
                                                session.team_id, actor, event["ts"])
                # The write itself was saved before its ops were known.
                get_user_state_manager().save_user_state(team)
        except Exception as exc:  # noqa: BLE001 - provenance must not lose the edit
            logger.warning("Could not record who changed %s: %s", instance_id, exc)
        return event

    @staticmethod
    def _plain_text(instance_id: str) -> Optional[str]:
        """The item's text as span offsets count it, for quoting a span."""
        try:
            from potato.item_state_management import get_item_state_manager
            from potato.server_utils.span_text import instance_dom_text
            ism = get_item_state_manager()
            if not ism.has_item(instance_id):
                return None
            text = ism.get_item(instance_id).get_text()
            return instance_dom_text(text) if isinstance(text, str) else None
        except Exception:  # noqa: BLE001 - a missing quote is not worth an error
            return None

    def revert(self, session: Session, actor: str, seq: int) -> Optional[Dict[str, Any]]:
        """Put back what one logged edit changed."""
        from potato.annotation_commit import finish_annotation_write
        if not (1 <= seq <= len(session.events)):
            raise CollabError("No such change", 404)
        event = session.events[seq - 1]
        if event["type"] != "edit":
            raise CollabError("Only an edit can be undone")
        iid = event["data"]["instance_id"]
        if not session.can_edit(actor):
            raise CollabError("You cannot edit in this session", 403)
        from potato.user_state_management import get_user_state_manager
        with self.session_lock(session):
            team = get_user_state_manager().get_user_state(session.team_user)
            before = collab_state.item_snapshot(team, iid)
            values = {}
            for op in event["data"]["ops"]:
                # A drawing takes back only this edit's shapes; a teammate's
                # later shapes on the same image stay.
                is_blob, merged = collab_state.revert_blob(op["before"], op["after"],
                                                           before.get(op["key"]))
                values[op["key"]] = merged if is_blob else op["before"]
            collab_state.write_values(team, iid, values)
            finish_annotation_write(team, iid, session.team_user)
            after = collab_state.item_snapshot(team, iid)
            return self.record_edit(session, actor, iid, before, after,
                                    via="revert", reverts=seq)


    def write_answer(self, session: Session, actor: Optional[str], instance_id: str,
                     values: Dict[str, Any], via: str, **extra) -> Optional[Dict[str, Any]]:
        """Set snapshot keys on the team answer (None removes) and log the edit."""
        from potato.annotation_commit import finish_annotation_write
        from potato.user_state_management import get_user_state_manager
        with self.session_lock(session):
            team = get_user_state_manager().get_user_state(session.team_user)
            before = collab_state.item_snapshot(team, instance_id)
            collab_state.write_values(team, instance_id, values)
            finish_annotation_write(team, instance_id, session.team_user)
            after = collab_state.item_snapshot(team, instance_id)
            return self.record_edit(session, actor, instance_id, before, after,
                                    via=via, **extra)

    # ------------------------------------------------------------------
    # Sign-off

    def signoff(self, session: Session, username: str, instance_id: str,
                ready: bool = True) -> Dict[str, Any]:
        """Mark (or unmark) the item's current answer as ready."""
        if not session.can_edit(username):
            raise CollabError("Only an editing member can sign off", 403)
        if instance_id not in session.item_ids:
            raise CollabError("That item is not in this session", 404)
        if session.is_blind(instance_id):
            raise CollabError("The team's answer is not open yet: answers are still blind", 409)
        event = self._emit(session, "signoff", username, {
            "instance_id": instance_id, "ready": bool(ready),
            "rev": session.rev_of(instance_id)})
        self._record_signoffs(session, instance_id)
        return event

    def _record_signoffs(self, session: Session, instance_id: str) -> None:
        try:
            from potato.user_state_management import get_user_state_manager
            usm = get_user_state_manager()
            team = usm.get_user_state(session.team_user)
            store = getattr(team, "instance_id_to_collab_provenance", None)
            if store is None:
                return
            record = store.setdefault(instance_id, {
                "session_id": session.session_id, "team_id": session.team_id,
                "contributors": {}})
            record["signed_off_by"] = session.ready_members(instance_id)
            record["signed_rev"] = session.rev_of(instance_id)
            record["consensus"] = session.is_signed_off(instance_id)
            usm.save_user_state(team)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record sign-off on %s: %s", instance_id, exc)

    # ------------------------------------------------------------------
    # Blind first

    def blind_answer(self, session: Session, username: str,
                     instance_id: str) -> Dict[str, Any]:
        """A member's own answer to an item (their blind answer)."""
        from potato.user_state_management import get_user_state_manager
        usm = get_user_state_manager()
        if not usm.has_user(username):
            return {}
        return collab_state.item_snapshot(usm.get_user_state(username), instance_id)

    def note_blind_answer(self, session: Session, username: str, instance_id: str) -> None:
        """Mark a member's own answer as part of this session (for the export)."""
        from potato.user_state_management import get_user_state_manager
        try:
            usm = get_user_state_manager()
            own = usm.get_user_state(username)
            store = getattr(own, "instance_id_to_collab_provenance", None)
            if store is None:
                return
            store[instance_id] = {"session_id": session.session_id,
                                  "team_id": session.team_id, "stage": "blind"}
            usm.save_user_state(own)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not mark %s's blind answer on %s: %s",
                           username, instance_id, exc)

    def blind_done(self, session: Session, username: str, instance_id: str) -> None:
        """A member has finished their own answer; reveal once everyone has."""
        if not session.can_edit(username):
            raise CollabError("Only an editing member answers", 403)
        if not session.is_blind(instance_id):
            return
        if username not in session.blind_done.get(instance_id, []):
            self._emit(session, "blind_done", username, {"instance_id": instance_id})
        if all(u in session.blind_done.get(instance_id, []) for u in session.editors()):
            self.reveal(session, None, instance_id)

    def reveal(self, session: Session, username: Optional[str],
               instance_id: str) -> Optional[Dict[str, Any]]:
        """Show everyone's own answers and open the team's.

        ``username`` None is the automatic reveal once every member is done.
        Schemes everyone agreed on start the team's answer.
        """
        if instance_id not in session.item_ids:
            raise CollabError("That item is not in this session", 404)
        if not session.is_blind(instance_id):
            return None
        if username is not None:
            self._require_member(session, username)
            if session.leader and username != session.leader:
                raise CollabError("Only the leader can reveal before everyone is done", 403)
        from potato.collab.describe import describe_unit, unit_title
        with self.session_lock(session):
            if not session.is_blind(instance_id):
                return None
            people = list(dict.fromkeys(session.editors()
                                        + session.blind_done.get(instance_id, [])))
            answers = {u: self.blind_answer(session, u, instance_id) for u in people}
            comparison = collab_state.compare_answers(answers)
            text = self._plain_text(instance_id)
            units = {}
            for unit, info in comparison["units"].items():
                shown = {u: describe_unit(unit, answers[u], self.app_config, text)
                         for u in comparison["answered"]}
                units[unit] = {"title": unit_title(unit), "agree": info["agree"],
                               "answers": shown}
                if not info["agree"] and len(shown) > 1 and len(set(shown.values())) == 1:
                    # "1 car" and "1 car": same labels, drawn in different places.
                    units[unit]["detail"] = "placement"
            seed = collab_state.agreed_values(answers, comparison)
            event = self._emit(session, "revealed", username, {
                "instance_id": instance_id,
                "answers": {u: answers[u] for u in comparison["answered"]},
                "answered": comparison["answered"], "units": units,
                "agreement": comparison["agreement"],
                "seeded": sorted({collab_state.unit_of(k, v) for k, v in seed.items()})})
            if seed:
                self.write_answer(session, None, instance_id, seed, via="reveal")
            self._record_reveal(session, instance_id, comparison)
            return event

    def _record_reveal(self, session: Session, instance_id: str,
                       comparison: Dict[str, Any]) -> None:
        try:
            from potato.user_state_management import get_user_state_manager
            usm = get_user_state_manager()
            team = usm.get_user_state(session.team_user)
            store = getattr(team, "instance_id_to_collab_provenance", None)
            if store is None:
                return
            record = store.setdefault(instance_id, {
                "session_id": session.session_id, "team_id": session.team_id,
                "contributors": {}})
            record["blind"] = {"answered": comparison["answered"],
                               "agreement": comparison["agreement"]}
            usm.save_user_state(team)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record the reveal of %s: %s", instance_id, exc)

    def reveal_of(self, session: Session, instance_id: str) -> Optional[Dict[str, Any]]:
        seq = session.revealed.get(instance_id)
        return session.events[seq - 1] if seq else None

    # ------------------------------------------------------------------
    # Quick polls

    def _scheme(self, name: Optional[str]) -> Optional[Dict[str, Any]]:
        for scheme in self.app_config.get("annotation_schemes") or []:
            if isinstance(scheme, dict) and scheme.get("name") == name:
                return scheme
        return None

    @staticmethod
    def _label_names(scheme: Dict[str, Any]) -> List[str]:
        names = []
        for label in scheme.get("labels") or []:
            name = label.get("name") if isinstance(label, dict) else label
            if name is not None:
                names.append(str(name))
        if not names and scheme.get("annotation_type") == "likert":
            size = int(scheme.get("size") or 0)
            names = [str(i) for i in range(1, size + 1)]
        return names

    def _is_single_choice(self, schema: str, session: Session) -> bool:
        from potato.server_utils.schema_exclusivity import (
            is_single_select, single_select_schema_names)
        if schema in single_select_schema_names(self.app_config.get("annotation_schemes")):
            return True
        try:
            return is_single_select(schema, session.team_user)
        except Exception:  # noqa: BLE001 - no server config loaded
            return False

    def open_poll(self, session: Session, username: str, instance_id: str, *,
                  question: Optional[str] = None, options: Optional[List[str]] = None,
                  schema: Optional[str] = None) -> Dict[str, Any]:
        if not session.can_edit(username):
            raise CollabError("Only an editing member can start a poll", 403)
        if instance_id not in session.item_ids:
            raise CollabError("That item is not in this session", 404)
        if session.open_poll_for(instance_id):
            raise CollabError("This item already has an open poll", 409)
        if schema:
            scheme = self._scheme(schema)
            if scheme is None:
                raise CollabError(f"No scheme named '{schema}'")
            if not options:
                options = self._label_names(scheme)
            question = question or scheme.get("description") or schema
        options = [str(o).strip()[:80] for o in (options or []) if str(o).strip()]
        options = list(dict.fromkeys(options))
        if not (2 <= len(options) <= MAX_POLL_OPTIONS):
            raise CollabError(f"A poll needs 2 to {MAX_POLL_OPTIONS} options")
        question = str(question or "").strip()[:200]
        if not question:
            raise CollabError("A poll needs a question")
        return self._emit(session, "poll_opened", username, {
            "poll_id": f"p{len(session.events) + 1}", "instance_id": instance_id,
            "question": question, "options": options, "schema": schema or None})

    def vote(self, session: Session, username: str, poll_id: str, option: str) -> None:
        poll = session.polls.get(poll_id)
        if poll is None:
            raise CollabError("No such poll", 404)
        if not poll["open"]:
            raise CollabError("This poll has closed", 409)
        if not session.can_edit(username):
            raise CollabError("Only an editing member can vote", 403)
        if option not in poll["options"]:
            raise CollabError("That is not one of the poll's options")
        self._emit(session, "poll_vote", username, {"poll_id": poll_id, "option": option})
        if all(u in poll["votes"] for u in session.editors()):
            self.close_poll(session, None, poll_id)

    def close_poll(self, session: Session, username: Optional[str], poll_id: str,
                   apply: bool = False) -> Dict[str, Any]:
        """Close a poll; ``apply`` writes a single-select scheme's winner."""
        poll = session.polls.get(poll_id)
        if poll is None:
            raise CollabError("No such poll", 404)
        if username is not None:
            self._require_member(session, username)
            if username not in (poll["opened_by"], session.leader):
                raise CollabError("Only whoever opened the poll, or the leader, closes it", 403)
        if poll["open"]:
            counts = {o: 0 for o in poll["options"]}
            for choice in poll["votes"].values():
                counts[choice] = counts.get(choice, 0) + 1
            top = max(counts.values()) if counts else 0
            leaders = [o for o, n in counts.items() if n == top and n > 0]
            self._emit(session, "poll_closed", username, {
                "poll_id": poll_id, "counts": counts,
                "winner": leaders[0] if len(leaders) == 1 else None, "applied": False})
        if apply:
            self.apply_poll(session, username, poll_id)
        return session.polls[poll_id]

    def apply_poll(self, session: Session, username: Optional[str], poll_id: str) -> None:
        poll = session.polls[poll_id]
        schema, winner, iid = poll.get("schema"), poll.get("winner"), poll.get("instance_id")
        if not (schema and winner):
            raise CollabError("Only a scheme poll with a single winner can be applied")
        if username is not None and not session.can_edit(username):
            raise CollabError("You cannot edit in this session", 403)
        if not self._is_single_choice(schema, session):
            raise CollabError("Only a single-choice scheme takes a poll's winner")
        from potato.user_state_management import get_user_state_manager
        team = get_user_state_manager().get_user_state(session.team_user)
        current = collab_state.item_snapshot(team, iid)
        values = {k: None for k in current
                  if k.startswith(collab_state.LABEL)
                  and collab_state.split_label_key(k)[0] == schema}
        values[collab_state.label_key(schema, winner)] = winner
        self.write_answer(session, username, iid, values, via="poll")
        poll["applied"] = True

    # ------------------------------------------------------------------
    # Metrics and replay

    def metrics(self, session: Session) -> Dict[str, Any]:
        """Per-member contribution counts and session progress."""
        from potato.user_state_management import get_user_state_manager
        members = {m: {"edits": 0, "changes": 0, "overwrote": 0, "overwritten": 0,
                       "undid": 0, "messages": 0, "discussion": 0, "votes": 0,
                       "signoffs": 0, "seconds_on_items": 0.0, "blind_kept": None}
                   for m in session.members}
        last_view: Dict[str, tuple] = {}
        edit_author = {}
        for e in session.events:
            user, kind, data = e.get("user"), e["type"], e.get("data") or {}
            row = members.get(user)
            if kind == "edit":
                edit_author[e["seq"]] = user
                if row is not None:
                    row["edits"] += 1
                    row["changes"] += len(data.get("ops") or [])
                    row["overwrote"] += len(data.get("overwrote") or [])
                    if data.get("reverts"):
                        row["undid"] += 1
                for o in data.get("overwrote") or []:
                    if o.get("user") in members:
                        members[o["user"]]["overwritten"] += 1
            elif row is None:
                continue
            elif kind == "message":
                row["messages"] += 1
            elif kind == "discussion":
                row["discussion"] += 1
            elif kind == "poll_vote":
                row["votes"] += 1
            elif kind == "signoff" and data.get("ready"):
                row["signoffs"] += 1
            if kind == "viewing" and row is not None:
                if user in last_view:
                    row["seconds_on_items"] += min(e["ts"] - last_view[user][0],
                                                   _IDLE_CAP_SECONDS)
                last_view[user] = (e["ts"], data.get("instance_id"))
        now = time.time()
        for user, (ts, _) in last_view.items():
            if session.status == OPEN and session.is_member(user):
                members[user]["seconds_on_items"] += min(now - ts, _IDLE_CAP_SECONDS)

        team = get_user_state_manager().get_user_state(session.team_user)
        kept: Dict[str, List[int]] = {}
        agreements = []
        for iid, seq in session.revealed.items():
            data = session.events[seq - 1]["data"]
            if data.get("agreement") is not None:
                agreements.append(data["agreement"])
            final = collab_state.answer_units(collab_state.item_snapshot(team, iid)) if team else {}
            for user, snap in (data.get("answers") or {}).items():
                mine = collab_state.answer_units(snap)
                units = set(mine) | set(final)
                if not units:
                    continue
                same = sum(1 for u in units if mine.get(u) == final.get(u))
                acc = kept.setdefault(user, [0, 0])
                acc[0] += same
                acc[1] += len(units)
        for user, (same, total) in kept.items():
            if user in members and total:
                members[user]["blind_kept"] = same / total
        for row in members.values():
            row["seconds_on_items"] = round(row["seconds_on_items"], 1)

        answered = [iid for iid in session.item_ids
                    if team is not None and team.has_annotated(iid)]
        return {
            "session_id": session.session_id, "items": len(session.item_ids),
            "answered": len(answered),
            "signed_off": sum(1 for iid in session.item_ids if session.is_signed_off(iid)),
            "revealed": len(session.revealed),
            "edits": sum(1 for e in session.events if e["type"] == "edit"),
            "conflicts": sum(len(e["data"].get("overwrote") or [])
                             for e in session.events if e["type"] == "edit"),
            "blind_agreement": (sum(agreements) / len(agreements)) if agreements else None,
            "members": members,
        }

    _REPLAY_TYPES = {"edit", "message", "discussion", "signoff", "blind_done", "revealed",
                     "poll_opened", "poll_closed", "summon", "viewing", "member_joined",
                     "member_left", "leader_changed", "mode_changed", "session_closed"}

    def replay(self, session: Session, instance_id: str) -> Dict[str, Any]:
        """The item's history as frames, each with the team's answer after it."""
        from potato.collab.describe import describe_snapshot
        from potato.user_state_management import get_user_state_manager
        if instance_id not in session.item_ids:
            raise CollabError("That item is not in this session", 404)
        team = get_user_state_manager().get_user_state(session.team_user)
        current = collab_state.item_snapshot(team, instance_id)
        snap = self.state_at(session, instance_id, 0, current)
        text = self._plain_text(instance_id)
        initial = describe_snapshot(snap, self.app_config, text)
        frames = []
        for e in session.events:
            kind, data = e["type"], e.get("data") or {}
            if kind not in self._REPLAY_TYPES:
                continue
            about = data.get("instance_id")
            if kind == "viewing" and about != instance_id:
                continue
            if about is not None and about != instance_id and kind != "message":
                continue
            frame = {"seq": e["seq"], "ts": e["ts"], "user": e.get("user"), "type": kind}
            if kind == "edit":
                for op in data.get("ops") or []:
                    if op.get("after") is None:
                        snap.pop(op["key"], None)
                    else:
                        snap[op["key"]] = op["after"]
                frame["lines"] = data.get("summary") or []
                frame["via"] = data.get("via")
                frame["answer"] = describe_snapshot(snap, self.app_config, text)
            elif kind == "message":
                frame["lines"] = [data.get("text", "")]
            elif kind == "discussion":
                frame["lines"] = [data.get("excerpt", "")]
            elif kind == "revealed":
                frame["lines"] = [f"{u['title']}: " + ", ".join(
                    f"{who} {ans}" for who, ans in u["answers"].items())
                    + (" (agreed)" if u["agree"] else "")
                    for u in (data.get("units") or {}).values()]
                frame["agreement"] = data.get("agreement")
            elif kind == "signoff":
                frame["lines"] = ["ready" if data.get("ready") else "not ready"]
            elif kind == "poll_opened":
                frame["lines"] = [f"{data.get('question')} ({', '.join(data.get('options') or [])})"]
            elif kind == "poll_closed":
                counts = data.get("counts") or {}
                frame["lines"] = [", ".join(f"{o} {n}" for o, n in counts.items())
                                  + (f" → {data['winner']}" if data.get("winner") else "")]
            else:
                frame["lines"] = []
            frames.append(frame)
        return {"instance_id": instance_id, "initial": initial, "frames": frames,
                "final": describe_snapshot(current, self.app_config, text)}


def _is_quality_check(instance_id: str) -> bool:
    """An attention check or gold item: graded per person, never a team's."""
    try:
        from potato.quality_control import get_quality_control_manager
        qc = get_quality_control_manager()
        return bool(qc) and (qc.is_attention_check(instance_id)
                             or qc.is_gold_standard(instance_id))
    except Exception:  # noqa: BLE001 - QC absent or not configured
        return False


def _clean_view(view: Dict[str, Any]) -> Dict[str, Any]:
    """A leader's scroll position and media playheads, bounded."""
    out: Dict[str, Any] = {}
    try:
        out["scroll"] = max(0.0, min(1.0, float(view.get("scroll", 0))))
    except (TypeError, ValueError):
        pass
    media = []
    for m in (view.get("media") or [])[:8]:
        if not isinstance(m, dict):
            continue
        try:
            media.append({"index": int(m.get("index", 0)),
                          "time": max(0.0, float(m.get("time", 0))),
                          "paused": bool(m.get("paused", True)),
                          "rate": max(0.25, min(4.0, float(m.get("rate", 1) or 1)))})
        except (TypeError, ValueError):
            continue
    out["media"] = media
    out["at"] = time.time()
    return out


# ----------------------------------------------------------------------
# Singleton

_COLLAB_MANAGER: Optional[CollabManager] = None


def init_collab_manager(config: Dict[str, Any]) -> Optional[CollabManager]:
    global _COLLAB_MANAGER
    clear_collab_manager()
    manager = CollabManager(config)
    if not manager.cfg.enabled:
        return None
    _COLLAB_MANAGER = manager
    _install_hooks(manager)
    try:
        manager.ensure_config_teams()
    except Exception as exc:  # noqa: BLE001 - a team problem must not stop boot
        logger.error("collab: could not set up configured teams: %s", exc)
    logger.info("Live collaborative sessions enabled (%d session(s))", len(manager.sessions))
    return manager


def get_collab_manager() -> Optional[CollabManager]:
    return _COLLAB_MANAGER


def clear_collab_manager() -> None:
    global _COLLAB_MANAGER
    _COLLAB_MANAGER = None
    _uninstall_hooks()


def _excluded(username: str):
    manager = _COLLAB_MANAGER
    return manager.excluded_items(username) if manager is not None else ()


def _teams(username: str):
    manager = _COLLAB_MANAGER
    return manager.teams_of(username) if manager is not None else ()


def _install_hooks(manager: CollabManager) -> None:
    from potato.item_state_management import register_assignment_exclusion
    from potato.memos import service as memo_service
    register_assignment_exclusion(_excluded)
    memo_service.team_membership_resolver = _teams
    try:
        from potato.collab.writes import intercept_update
        from potato.routes import set_update_instance_interceptor
        set_update_instance_interceptor(intercept_update)
    except ImportError:  # pragma: no cover - routes absent in a bare unit test
        pass


def _uninstall_hooks() -> None:
    from potato.item_state_management import unregister_assignment_exclusion
    unregister_assignment_exclusion(_excluded)
    try:
        from potato.memos import service as memo_service
        if memo_service.team_membership_resolver is _teams:
            memo_service.team_membership_resolver = None
    except ImportError:  # pragma: no cover
        pass
    try:
        import sys
        routes = sys.modules.get("potato.routes")
        if routes is not None:
            routes.set_update_instance_interceptor(None)
    except Exception:  # noqa: BLE001
        pass
