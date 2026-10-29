"""
The scheduling manager: enrolment, sessions, the notification loop, Delphi
rounds, and the summaries the admin page and the export read.

One manager per served app (``app.extensions["potato_scheduling"]``), built
from the config when routes are registered. Its background thread is started
there too, never at import, and only when ``schedule.scheduler`` is true (the
default). A second app on the same output directory (the in-process test
harness starts one per test class) stops the first manager's thread before
starting its own, and the claim step in the store keeps two processes from
sending the same message.

``tick(now)`` is the whole loop body and can be called directly; tests pass a
fixed ``now`` instead of waiting.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from potato.scheduling import delphi as delphi_math
from potato.scheduling import links, planner, timeutil
from potato.scheduling.config import ReminderRule, ScheduleSpec, missing_env
from potato.scheduling.notify import SendError, build_channel
from potato.scheduling.store import ContactStore, ScheduleStore

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
RETRY_SECONDS = 300
STALE_CLAIM_SECONDS = 600
STOP_LINK_GRACE = 30 * 86400

_REGISTRY: Dict[str, "SchedulingManager"] = {}
_REGISTRY_LOCK = threading.Lock()
_LATEST: Optional["SchedulingManager"] = None


def session_status(s: dict, now: float) -> str:
    """answered | upcoming | open | started | expired | missed.

    ``expired``: opened but not submitted before it closed. ``missed``: never
    opened while it was open."""
    if s.get("submitted_at"):
        return "answered"
    if now < s["opens_at"]:
        return "upcoming"
    if now < s["closes_at"]:
        return "started" if s.get("first_answer_at") else "open"
    return "expired" if (s.get("opened_at") or s.get("first_answer_at")) else "missed"


CLOSED_STATUSES = ("answered", "expired", "missed")


class SchedulingManager:
    def __init__(self, config: dict, spec: ScheduleSpec, clock=None):
        self.config = config
        self.spec = spec
        self.clock = clock or time.time
        output_dir = config.get("output_annotation_dir") or os.path.join(
            config.get("task_dir") or ".", "annotation_output")
        task_dir = config.get("task_dir") or "."
        self.store = ScheduleStore(os.path.join(output_dir, "scheduling", "schedule.sqlite"))
        self.private_dir = os.path.join(task_dir, ".potato", "scheduling")
        self.contacts = ContactStore(os.path.join(self.private_dir, "contacts.sqlite"))
        self.key = links.load_key(self.private_dir)
        self.channels = {}
        if spec.notify:
            for c in spec.notify.channels:
                self.channels[c.type] = build_channel(c)
                if not spec.notify.dry_run:
                    for name in missing_env(c):
                        logger.error("notifications: %s channel needs environment variable "
                                     "%s, which is not set; its messages will fail",
                                     c.type, name)
        self._delphi_lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        if spec.delphi:
            start = spec.delphi.start if spec.delphi.start is not None else self.now()
            self.store.set_meta("delphi_start", repr(float(start)), only_if_missing=True)

    # ------------------------------------------------------------------
    def now(self) -> float:
        return float(self.clock())

    # ------------------------------------------------------------ links
    def resume_link(self, participant: str, session_id: str, expires_at: float,
                    epoch: int) -> str:
        token = links.make_token(self.key, "resume", participant, session_id, expires_at, epoch)
        return f"{self.base_url()}/s/{token}"

    def stop_link(self, participant: str, epoch: int) -> str:
        last = max([s["closes_at"] for s in self.store.sessions(participant)] or [self.now()])
        exp = max(last, self.now()) + STOP_LINK_GRACE
        token = links.make_token(self.key, "stop", participant, "", exp, epoch)
        return f"{self.base_url()}/schedule/stop/{token}"

    def base_url(self) -> str:
        if self.spec.notify:
            return self.spec.notify.base_url
        return f"http://localhost:{self.config.get('port', 8000)}"

    def read_link(self, token: str) -> Tuple[Optional[dict], Optional[str]]:
        claims, problem = links.read_token(self.key, token, self.now())
        if claims is not None:
            p = self.store.participant(claims["participant"])
            if p is None or int(p.get("link_epoch") or 0) != claims["epoch"]:
                return None, "invalid"
        return claims, problem

    # ------------------------------------------------------- enrolment
    def participant(self, participant: str) -> Optional[dict]:
        return self.store.participant(participant)

    def consent_given(self, user_state) -> bool:
        notify = self.spec.notify
        if not notify or not notify.consent_question:
            return False
        from potato.server_utils.phase_flow import collect_flow_answers
        try:
            answers = collect_flow_answers(self.config, user_state)
        except Exception:
            return False
        got = answers.get(notify.consent_question)
        want = notify.consent_value
        wanted = [str(v) for v in (want if isinstance(want, list) else [want])]
        if isinstance(got, (list, tuple, set)):
            return any(str(g) in wanted for g in got)
        return got is not None and str(got) in wanted

    def channels_for(self, consent: bool, email: Optional[str], phone: Optional[str],
                     crowd: Dict[str, str]) -> List[str]:
        if not consent or not self.spec.notify:
            return []
        out = []
        for c in self.spec.notify.channels:
            if c.address is None:
                out.append(c.type)
            elif c.address == "email" and email:
                out.append(c.type)
            elif c.address == "phone" and phone:
                out.append(c.type)
            elif c.address == "prolific" and crowd.get("provider") == "prolific" \
                    and crowd.get("worker_id"):
                out.append(c.type)
        return out

    def enrol(self, participant: str, tz: str, tz_source: str, consent: bool,
              email: Optional[str] = None, phone: Optional[str] = None,
              crowd: Optional[Dict[str, str]] = None) -> bool:
        """Compute and store the participant's schedule. False if they were
        already enrolled (nothing is changed then)."""
        now = self.now()
        crowd = crowd or {}
        if not timeutil.valid_timezone(tz):
            tz, tz_source = self.spec.timezone, "default"
        if not consent:
            email = phone = None
        channels = self.channels_for(consent, email, phone, crowd)
        added = self.store.add_participant({
            "participant": participant, "enrolled_at": now, "timezone": tz,
            "timezone_source": tz_source, "contact_consent": 1 if consent else 0,
            "channels": json.dumps(channels), "crowd_provider": crowd.get("provider"),
            "crowd_worker_id": crowd.get("worker_id"), "crowd_study_id": crowd.get("study_id"),
        })
        if not added:
            return False
        if consent and (email or phone):
            self.contacts.set(participant, email, phone, now)
        sessions = planner.plan(self.spec, now, tz, participant)
        self.store.add_sessions(s.row(participant) for s in sessions)
        self._plan_notifications(participant, [s.row(participant) for s in sessions],
                                 skip_due_before=now)
        if self.spec.delphi:
            self.advance_delphi(now, enrolling=participant)
        logger.info("Enrolled %s in the schedule (%d sessions, tz %s, channels %s)",
                    participant, len(sessions), tz, channels or "none")
        return True

    def _rules_for(self, kind: str) -> List[ReminderRule]:
        if kind == "prompt":
            return self.spec.esm.reminders
        if kind == "round":
            return self.spec.delphi.reminders
        return []

    def _wave_rules(self, name: str) -> List[ReminderRule]:
        for w in self.spec.waves:
            if w.name == name:
                return w.reminders
        return []

    def _plan_notifications(self, participant: str, sessions: List[dict],
                            skip_due_before: Optional[float]) -> int:
        p = self.store.participant(participant)
        if not p or not p["contact_consent"] or p.get("withdrawn_at"):
            return 0
        channels = json.loads(p.get("channels") or "[]")
        if not channels:
            return 0
        rows = []
        for s in sessions:
            rules = self._wave_rules(s["name"]) if s["kind"] == "wave" else self._rules_for(s["kind"])
            for rule in rules:
                due = rule.due(s["opens_at"], s["closes_at"])
                if skip_due_before is not None and due < skip_due_before:
                    continue
                if due >= s["closes_at"]:
                    continue
                template = rule.template
                if rule.kind == "open" and s["kind"] == "prompt":
                    template = "prompt"
                elif rule.kind == "open" and s["kind"] == "round":
                    template = "delphi_round"
                for ch in channels:
                    rows.append({"key": f"{participant}|{s['id']}|{rule.key}|{ch}",
                                 "participant": participant, "session_id": s["id"],
                                 "rule": rule.key, "template": template, "channel": ch,
                                 "due_at": due})
        return self.store.add_notifications(rows)

    # -------------------------------------------------------- sessions
    def sessions(self, participant: str) -> List[dict]:
        now = self.now()
        out = self.store.sessions(participant)
        for s in out:
            s["status"] = session_status(s, now)
        return out

    def open_session(self, participant: str) -> Optional[dict]:
        live = [s for s in self.sessions(participant) if s["status"] in ("open", "started")]
        return min(live, key=lambda s: s["closes_at"]) if live else None

    def next_session(self, participant: str) -> Optional[dict]:
        up = [s for s in self.sessions(participant) if s["status"] == "upcoming"]
        return min(up, key=lambda s: s["opens_at"]) if up else None

    def session(self, participant: str, session_id: str) -> Optional[dict]:
        s = self.store.session(participant, session_id)
        if s:
            s["status"] = session_status(s, self.now())
        return s

    def questions_for(self, s: dict) -> List[dict]:
        if s["kind"] == "wave":
            for w in self.spec.waves:
                if w.name == s["name"]:
                    return w.questions
        if s["kind"] == "prompt" and self.spec.esm:
            return self.spec.esm.questions
        return []

    def wave_spec(self, name: str):
        for w in self.spec.waves:
            if w.name == name:
                return w
        return None

    def record_opened(self, participant: str, session_id: str) -> None:
        s = self.session(participant, session_id)
        if s and s["status"] in ("open", "started"):
            self.store.mark_opened(participant, session_id, self.now())

    def record_first_answer(self, participant: str, session_id: str) -> bool:
        return self.store.mark_first_answer(participant, session_id, self.now())

    def submit(self, participant: str, session_id: str, answers: Dict[str, Any]) -> bool:
        return self.store.submit(participant, session_id, answers, self.now())

    def prompt_times(self) -> Dict[Tuple[str, str], float]:
        """When each session's opening message went out, by (participant,
        session): the start of the latency clock when one was sent."""
        out: Dict[Tuple[str, str], float] = {}
        for n in self.store.notifications():
            if n["rule"] == "open" and n["status"] in ("sent", "dry_run") and n.get("sent_at"):
                key = (n["participant"], n["session_id"])
                out[key] = min(out.get(key, n["sent_at"]), n["sent_at"])
        return out

    # --------------------------------------------------------- contact
    def contact_flags(self, participant: str) -> Dict[str, bool]:
        c = self.contacts.get(participant)
        return {"email": bool(c and c.get("email")), "phone": bool(c and c.get("phone"))}

    def stop_messages(self, participant: str, reason: str) -> None:
        """Withdraw contact consent: delete the contact details, skip every
        pending message, and invalidate every link sent so far."""
        now = self.now()
        p = self.store.participant(participant)
        if p is None:
            return
        self.contacts.delete(participant)
        self.store.update_participant(participant, withdrawn_at=p.get("withdrawn_at") or now,
                                      contact_consent=0, contact_deleted_at=now,
                                      contact_deleted_reason=reason,
                                      link_epoch=int(p.get("link_epoch") or 0) + 1)
        self.store.skip_pending(participant, f"messages stopped ({reason})")

    def delete_contact(self, participant: str, reason: str) -> bool:
        """Delete stored addresses but keep the schedule (and the log channel
        or Prolific inbox messages, which need no address)."""
        had = self.contacts.delete(participant)
        if self.store.participant(participant) is not None:
            self.store.update_participant(participant, contact_deleted_at=self.now(),
                                          contact_deleted_reason=reason)
        return had

    def _delete_finished_contacts(self, now: float) -> int:
        if not (self.spec.notify and self.spec.notify.delete_after_study):
            return 0
        held = self.contacts.participants()
        if not held:
            return 0
        delphi_running = bool(self.spec.delphi) and not self.store.meta("delphi_finished")
        n = 0
        for participant in held:
            if delphi_running:
                break
            future = [s for s in self.store.sessions(participant)
                      if not s.get("submitted_at") and s["closes_at"] > now]
            if not future:
                self.delete_contact(participant, "study ended")
                n += 1
        return n

    # ------------------------------------------------------------ loop
    def tick(self, now: Optional[float] = None) -> Dict[str, int]:
        now = self.now() if now is None else float(now)
        summary = {"sent": 0, "dry_run": 0, "failed": 0, "skipped": 0, "retry": 0,
                   "interrupted": self.store.release_stale_claims(now - STALE_CLAIM_SECONDS)}
        if self.spec.delphi:
            self.advance_delphi(now)
        for row in self.store.due_notifications(now):
            if not self.store.claim(row["id"], now):
                continue
            outcome = self._deliver(row, now)
            summary[outcome] = summary.get(outcome, 0) + 1
        summary["contacts_deleted"] = self._delete_finished_contacts(now)
        return summary

    def _address(self, p: dict, channel: str) -> Optional[str]:
        if channel == "log":
            return p["participant"]
        if channel == "prolific":
            return p.get("crowd_worker_id") if p.get("crowd_provider") == "prolific" else None
        contact = self.contacts.get(p["participant"])
        if not contact:
            return None
        return contact.get("email") if channel == "smtp" else contact.get("phone")

    def render(self, template: str, s: dict, p: dict, now: float) -> Tuple[str, str]:
        tpl = self.spec.notify.templates[template]
        tz = p["timezone"]
        values = {
            "study": self.spec.study,
            "session": s.get("title") or s["name"],
            "opens": timeutil.format_local(s["opens_at"], tz),
            "closes": timeutil.format_local(s["closes_at"], tz),
            "time_left": timeutil.format_span(s["closes_at"] - max(now, s["opens_at"])),
            "link": self.resume_link(p["participant"], s["id"], s["closes_at"],
                                     int(p.get("link_epoch") or 0)),
            "stop_link": self.stop_link(p["participant"], int(p.get("link_epoch") or 0)),
        }
        return tpl.get("subject", "").format(**values), tpl.get("body", "").format(**values)

    def _deliver(self, row: dict, now: float) -> str:
        nid = row["id"]

        def skip(reason):
            self.store.finish(nid, "skipped", now, reason)
            return "skipped"

        p = self.store.participant(row["participant"])
        if p is None:
            return skip("participant is not enrolled")
        if not p["contact_consent"] or p.get("withdrawn_at"):
            return skip("no contact consent")
        s = self.store.session(row["participant"], row["session_id"])
        if s is None:
            return skip("session no longer exists")
        if s.get("submitted_at"):
            return skip("already answered")
        if now >= s["closes_at"]:
            return skip("the session closed before this message went out")
        if row["rule"].startswith("before_open") and now >= s["opens_at"]:
            return skip("the session had already opened")
        channel = self.channels.get(row["channel"])
        if channel is None:
            return skip(f"channel {row['channel']} is no longer configured")
        address = self._address(p, row["channel"])
        if not address:
            return skip("no address on file (contact details deleted)")
        subject, body = self.render(row["template"], s, p, now)
        if self.spec.notify.dry_run or row["channel"] == "log":
            status = "dry_run" if self.spec.notify.dry_run and row["channel"] != "log" else "sent"
            logger.info("[notification:%s%s] %s / %s: %s", row["channel"],
                        " dry run" if status == "dry_run" else "", row["participant"],
                        row["session_id"], subject)
            self.store.finish(nid, status, now, "dry run: not delivered"
                              if status == "dry_run" else "logged",
                              preview=f"{subject}\n\n{body}")
            return status
        try:
            if row["channel"] == "prolific":
                ref = channel.send(address, subject, body, study_id=p.get("crowd_study_id"))
            else:
                ref = channel.send(address, subject, body)
        except SendError as exc:
            attempts = int(row.get("attempts") or 0) + 1
            retry_at = now + RETRY_SECONDS * attempts
            if exc.retry and attempts < MAX_ATTEMPTS and retry_at < s["closes_at"]:
                self.store.finish(nid, "pending", now, f"attempt {attempts} failed: {exc}",
                                  retry_at=retry_at)
                return "retry"
            self.store.finish(nid, "failed", now, str(exc))
            logger.warning("Notification %s to %s via %s failed: %s", row["rule"],
                           row["participant"], row["channel"], exc)
            return "failed"
        except Exception as exc:  # a bug in a channel must not stop the loop
            self.store.finish(nid, "failed", now, f"unexpected error: {exc}")
            logger.exception("Notification %s failed unexpectedly", nid)
            return "failed"
        self.store.finish(nid, "sent", now, str(ref)[:200])
        return "sent"

    # ----------------------------------------------------------- Delphi
    def round_length(self) -> float:
        return self.spec.delphi.round_length

    def advance_delphi(self, now: float, enrolling: Optional[str] = None) -> None:
        """Open, close and create rounds as time passes; make sure every
        enrolled participant has a session for each round not yet closed."""
        spec = self.spec.delphi
        with self._delphi_lock:
            rounds = self.store.rounds()
            if not rounds:
                start = float(self.store.meta("delphi_start") or now)
                self.store.add_round(1, start, start + spec.round_length)
                rounds = self.store.rounds()
            for r in rounds:
                if r["status"] == "closed":
                    continue
                if now >= r["closes_at"]:
                    self._finalize_round(r, now)
                    continue
                if now >= r["opens_at"] and r["status"] == "scheduled":
                    self.store.update_round(r["round"], status="open")
                self._sync_round_sessions(r, now, enrolling)

    def _sync_round_sessions(self, r: dict, now: float, enrolling: Optional[str]) -> None:
        sid = f"round:{r['round']}"
        have = {s["participant"] for s in self.store.sessions(kind="round", session_id=sid)}
        title = f"{self.spec.delphi.title}: round {r['round']}"
        for p in self.store.participants():
            # Stopping messages is not leaving the panel: a withdrawn
            # participant still gets the round, only without reminders.
            if p["participant"] in have:
                continue
            row = {"participant": p["participant"], "id": sid, "kind": "round",
                   "name": str(r["round"]), "title": title, "seq": r["round"], "day": None,
                   "opens_at": r["opens_at"], "closes_at": r["closes_at"]}
            if self.store.add_sessions([row]):
                # A participant enrolling now is on the page already; anyone
                # else may hear late (the server was down when the round
                # opened) but still before it closes.
                self._plan_notifications(p["participant"], [row],
                                         skip_due_before=now if p["participant"] == enrolling
                                         else None)

    def _finalize_round(self, r: dict, now: float) -> None:
        spec = self.spec.delphi
        number = r["round"]
        current = self.store.sessions(kind="round", session_id=f"round:{number}")
        ratings = delphi_math.ratings_by_item(current)
        previous = previous_stats = None
        if number > 1:
            previous = delphi_math.ratings_by_item(
                self.store.sessions(kind="round", session_id=f"round:{number - 1}"))
            previous_stats = {s["item"]: s for s in self.store.stats(number - 1)}
        rows = delphi_math.item_stats(spec.items, ratings, previous, previous_stats, spec.stop)
        self.store.save_stats(number, rows)
        stop, reason = delphi_math.stop_decision(rows, number, spec.max_rounds, spec.stop)
        closed_at = min(now, r["closes_at"])
        self.store.update_round(number, status="closed", closed_at=closed_at,
                                stop_reason=reason or None)
        if stop:
            self.store.set_meta("delphi_finished", repr(closed_at))
            self.store.set_meta("delphi_stop_reason", reason)
            logger.info("Delphi stopped after round %d: %s", number, reason)
            return
        opens = closed_at + spec.gap
        if self.store.add_round(number + 1, opens, opens + spec.round_length):
            nxt = [x for x in self.store.rounds() if x["round"] == number + 1][0]
            if now >= nxt["opens_at"]:
                self.store.update_round(number + 1, status="open")
            self._sync_round_sessions(nxt, now, None)
        logger.info("Delphi round %d closed; round %d opens %s", number, number + 1,
                    timeutil.iso_utc(opens))

    def close_round_now(self) -> Optional[int]:
        """Close the open round early (admin). Returns its number."""
        now = self.now()
        with self._delphi_lock:
            open_rounds = [r for r in self.store.rounds()
                           if r["status"] != "closed" and r["opens_at"] <= now]
            if not open_rounds:
                return None
            r = open_rounds[0]
            self.store.update_round(r["round"], closes_at=now)
            self.store.close_round_sessions(r["round"], now)
            r["closes_at"] = now
            self._finalize_round(r, now)
            return r["round"]

    def delphi_round_view(self, participant: str, number: int) -> Dict[str, Any]:
        spec = self.spec.delphi
        fb = []
        if number > 1:
            prev_sessions = self.store.sessions(kind="round", session_id=f"round:{number - 1}")
            stats = {s["item"]: s for s in self.store.stats(number - 1)}
            own = next((s.get("answers") or {} for s in prev_sessions
                        if s["participant"] == participant and s.get("submitted_at")), {})
            comments = delphi_math.comments_by_item(prev_sessions) if spec.comments else {}
            fb = delphi_math.feedback(spec.items, stats, own, comments, participant,
                                      spec.min_panel, self.spec.seed)
        by_item = {f["item"]: f for f in fb}
        return {"items": [{"id": it["id"], "text": it["text"], "feedback": by_item.get(it["id"])}
                          for it in spec.items],
                "scale": list(range(spec.scale_min, spec.scale_max + 1))}

    def parse_delphi_answers(self, form) -> Tuple[Dict[str, Any], Dict[str, str]]:
        spec = self.spec.delphi
        answers, errors = {}, {}
        allowed = {str(v) for v in range(spec.scale_min, spec.scale_max + 1)}
        for it in spec.items:
            raw = (form.get(f"rating__{it['id']}") or "").strip()
            if raw not in allowed:
                errors[it["id"]] = "Choose a rating."
                continue
            entry: Dict[str, Any] = {"rating": int(raw)}
            if spec.comments:
                comment = (form.get(f"comment__{it['id']}") or "").strip()
                if len(comment) > 2000:
                    errors[it["id"]] = "Keep the comment under 2000 characters."
                    continue
                if comment:
                    entry["comment"] = comment
            answers[it["id"]] = entry
        return answers, errors

    # ----------------------------------------------------------- admin
    def admin_summary(self) -> Dict[str, Any]:
        now = self.now()
        sessions = self.store.sessions()
        by_p: Dict[str, List[dict]] = {}
        for s in sessions:
            s["status"] = session_status(s, now)
            by_p.setdefault(s["participant"], []).append(s)
        prompt_at = self.prompt_times()
        contact = self.contacts.participants()
        people = []
        for p in self.store.participants():
            mine = by_p.get(p["participant"], [])
            counts = {k: sum(1 for s in mine if s["status"] == k)
                      for k in ("answered", "expired", "missed", "open", "started", "upcoming")}
            closed = counts["answered"] + counts["expired"] + counts["missed"]
            lat = [s["first_answer_at"] - prompt_at.get((s["participant"], s["id"]), s["opens_at"])
                   for s in mine if s.get("first_answer_at")]
            lat.sort()
            nxt = min((s for s in mine if s["status"] == "upcoming"),
                      key=lambda s: s["opens_at"], default=None)
            people.append({
                "participant": p["participant"], "enrolled_at": p["enrolled_at"],
                "timezone": p["timezone"], "consent": bool(p["contact_consent"]),
                "withdrawn": bool(p.get("withdrawn_at")),
                "channels": json.loads(p.get("channels") or "[]"),
                "contact": contact.get(p["participant"], {"email": False, "phone": False}),
                "counts": counts, "closed": closed,
                "compliance": (counts["answered"] / closed) if closed else None,
                "median_latency": lat[len(lat) // 2] if lat else None,
                "next": nxt,
            })
        notes = self.store.notifications()
        return {
            "now": now, "participants": people, "sessions": sessions,
            "upcoming": [n for n in notes if n["status"] == "pending"][:200],
            "sent": sorted([n for n in notes if n["status"] in ("sent", "dry_run")],
                           key=lambda n: -(n.get("sent_at") or 0))[:200],
            "failed": [n for n in notes if n["status"] == "failed"],
            "skipped": sorted([n for n in notes if n["status"] == "skipped"],
                              key=lambda n: -n["due_at"])[:100],
            "counts": self.store.notification_counts(),
            "rounds": self.store.rounds() if self.spec.delphi else [],
            "stats": self.store.stats() if self.spec.delphi else [],
            "delphi_stop": self.store.meta("delphi_stop_reason") if self.spec.delphi else None,
        }

    # ---------------------------------------------------------- thread
    def start(self) -> None:
        if not self.spec.scheduler or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="potato-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        wait = min(2.0, self.spec.poll_seconds)
        while not self._stop.wait(wait):
            wait = self.spec.poll_seconds
            if not os.path.isdir(os.path.dirname(self.store.path)):
                logger.info("Schedule store %s is gone; scheduler stopping", self.store.path)
                return
            try:
                self.tick()
            except Exception:
                logger.exception("Scheduler tick failed")


def install(app, config: dict) -> Optional[SchedulingManager]:
    """Build the manager for ``app`` from ``config`` and start its thread.
    Returns None when the config has no ``schedule`` block."""
    global _LATEST
    from potato.scheduling.config import parse_schedule_config
    config_dir = (os.path.dirname(os.path.abspath(config["config_file"]))
                  if config.get("config_file") else (config.get("task_dir") or "."))
    spec = parse_schedule_config(config, config_dir)
    if spec is None:
        if app is not None:
            app.extensions.pop("potato_scheduling", None)
        return None
    manager = SchedulingManager(config, spec)
    with _REGISTRY_LOCK:
        old = _REGISTRY.get(manager.store.path)
        if old is not None:
            old.stop()
        _REGISTRY[manager.store.path] = manager
        _LATEST = manager
    if app is not None:
        app.extensions["potato_scheduling"] = manager
    manager.start()
    return manager


def get_manager() -> Optional[SchedulingManager]:
    """The manager of the app serving this request, else the latest built."""
    try:
        from flask import current_app
        m = current_app.extensions.get("potato_scheduling")
        if m is not None:
            return m
        return None
    except RuntimeError:
        return _LATEST


def stop_all() -> None:
    with _REGISTRY_LOCK:
        for m in _REGISTRY.values():
            m.stop()
        _REGISTRY.clear()
