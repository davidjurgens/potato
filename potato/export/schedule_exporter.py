"""
Schedule Exporter (format ``schedule``)

Scheduled sessions (waves, experience-sampling prompts, Delphi rounds) are a
sidecar to the main export rather than a column added to it: their answers
are not item annotations, a prompt study writes hundreds of sessions per
participant, and ``user_state.json`` (which every other exporter reads) is
rewritten in full on each save, so it does not carry them. Every table here
has ``participant``, the same id the main export's ``user_id`` holds, to join
on. Written from ``<output_annotation_dir>/scheduling/schedule.sqlite``:

    schedule_sessions.csv       one row per participant and session, plus an
                                ``enrolment`` row per participant (the regular
                                flow, whose answers are in the main export):
                                kind, wave / day / prompt / round, window in UTC
                                and the participant's local time, status
                                (answered | expired | missed | open | started |
                                upcoming), prompt_at (when the opening message
                                went out, else the window start), opened,
                                first answer, submitted, latency_seconds
                                (prompt_at to first answer), response_seconds
                                (first answer to submit), one ``answer.<name>``
                                column per question
    schedule_compliance.csv     per participant and kind: sessions closed,
                                answered, expired, missed, compliance
                                (answered / closed), median latency
    schedule_notifications.csv  every planned message: session, rule,
                                channel, due, status, attempts, sent time and
                                detail. Never the address or the message text
    delphi_ratings.csv          (Delphi) participant, round, item, rating,
                                comment
    delphi_rounds.csv           (Delphi) per round and item: n, median, Q1,
                                Q3, IQR, mean, median change, changed share,
                                settled, the round's window and stop reason

Email addresses and phone numbers are in a different database
(``<task_dir>/.potato/scheduling/contacts.sqlite``) that this exporter never
opens.
"""

from __future__ import annotations

import csv
import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

SESSION_COLUMNS = [
    "participant", "kind", "session_id", "wave", "day", "prompt", "round", "title",
    "timezone", "opens_at_utc", "closes_at_utc", "opens_at_local", "closes_at_local",
    "status", "prompt_at_utc", "opened_at_utc", "first_answer_at_utc", "submitted_at_utc",
    "latency_seconds", "response_seconds", "reminder_channels",
]
NOTIFICATION_COLUMNS = ["participant", "session_id", "rule", "template", "channel",
                        "due_at_utc", "status", "attempts", "sent_at_utc", "detail"]
COMPLIANCE_COLUMNS = ["participant", "kind", "sessions", "closed", "answered", "expired",
                      "missed", "compliance", "median_latency_seconds"]


def _store_path(context: ExportContext) -> str:
    return os.path.join(context.output_dir, "scheduling", "schedule.sqlite")


def _cell(value: Any) -> Any:
    if isinstance(value, list):
        return ";".join(str(v) for v in value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return "" if value is None else value


def _secs(value: Optional[float]) -> str:
    return "" if value is None else f"{value:.1f}"


class ScheduleExporter(BaseExporter):
    format_name = "schedule"
    description = ("Scheduled sessions: waves, experience-sampling prompts and Delphi rounds "
                   "with windows, compliance and latency; the notification log without addresses")
    file_extensions = [".csv"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not isinstance((context.config or {}).get("schedule"), dict):
            return False, "this config has no schedule: block"
        if not os.path.isfile(_store_path(context)):
            return False, "nobody has enrolled in the schedule yet"
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        from potato.scheduling import timeutil
        from potato.scheduling.manager import CLOSED_STATUSES, session_status
        from potato.scheduling.store import ScheduleStore

        store = ScheduleStore(_store_path(context))
        now = time.time()
        people = {p["participant"]: p for p in store.participants()}
        sessions = store.sessions()
        notes = store.notifications()
        prompt_at: Dict[Tuple[str, str], float] = {}
        for n in notes:
            if n["rule"] == "open" and n["status"] in ("sent", "dry_run") and n.get("sent_at"):
                key = (n["participant"], n["session_id"])
                prompt_at[key] = min(prompt_at.get(key, n["sent_at"]), n["sent_at"])

        answer_cols: List[str] = []
        for s in sessions:
            if s["kind"] == "round":
                continue
            for name in (s.get("answers") or {}):
                col = f"answer.{name}"
                if col not in answer_cols:
                    answer_cols.append(col)

        rows = []
        for pid, p in people.items():
            rows.append({"participant": pid, "kind": "enrolment", "session_id": "enrolment",
                         "title": "regular study flow", "timezone": p["timezone"],
                         "opens_at_utc": timeutil.iso_utc(p["enrolled_at"]),
                         "closes_at_utc": timeutil.iso_utc(p["enrolled_at"]),
                         "opens_at_local": timeutil.iso_local(p["enrolled_at"], p["timezone"]),
                         "closes_at_local": timeutil.iso_local(p["enrolled_at"], p["timezone"]),
                         "status": "enrolled", "submitted_at_utc": timeutil.iso_utc(p["enrolled_at"]),
                         "reminder_channels": ";".join(json.loads(p.get("channels") or "[]"))})
        by_kind: Dict[Tuple[str, str], List[dict]] = {}
        for s in sessions:
            p = people.get(s["participant"]) or {"timezone": "UTC"}
            tz = p["timezone"]
            status = session_status(s, now)
            start = prompt_at.get((s["participant"], s["id"]), s["opens_at"])
            latency = (s["first_answer_at"] - start) if s.get("first_answer_at") else None
            response = (s["submitted_at"] - s["first_answer_at"]) \
                if s.get("submitted_at") and s.get("first_answer_at") else None
            parts = s["id"].split(":")
            row = {
                "participant": s["participant"], "kind": s["kind"], "session_id": s["id"],
                "wave": s["name"] if s["kind"] == "wave" else "",
                "day": s.get("day") if s.get("day") is not None else "",
                "prompt": parts[2] if s["kind"] == "prompt" and len(parts) == 3 else "",
                "round": s["name"] if s["kind"] == "round" else "",
                "title": s.get("title") or "", "timezone": tz,
                "opens_at_utc": timeutil.iso_utc(s["opens_at"]),
                "closes_at_utc": timeutil.iso_utc(s["closes_at"]),
                "opens_at_local": timeutil.iso_local(s["opens_at"], tz),
                "closes_at_local": timeutil.iso_local(s["closes_at"], tz),
                "status": status, "prompt_at_utc": timeutil.iso_utc(start),
                "opened_at_utc": timeutil.iso_utc(s.get("opened_at")),
                "first_answer_at_utc": timeutil.iso_utc(s.get("first_answer_at")),
                "submitted_at_utc": timeutil.iso_utc(s.get("submitted_at")),
                "latency_seconds": _secs(latency), "response_seconds": _secs(response),
            }
            if s["kind"] != "round":
                for name, value in (s.get("answers") or {}).items():
                    row[f"answer.{name}"] = _cell(value)
            rows.append(row)
            by_kind.setdefault((s["participant"], s["kind"]), []).append(
                {"status": status, "latency": latency})

        os.makedirs(output_path, exist_ok=True)
        files = []

        def write(name, columns, data):
            path = os.path.join(output_path, name)
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
                w.writeheader()
                for r in data:
                    w.writerow(r)
            files.append(path)

        write("schedule_sessions.csv", SESSION_COLUMNS + answer_cols, rows)

        comp = []
        for (pid, kind), items in sorted(by_kind.items()):
            closed = [i for i in items if i["status"] in CLOSED_STATUSES]
            answered = sum(1 for i in closed if i["status"] == "answered")
            lat = sorted(i["latency"] for i in items if i["latency"] is not None)
            comp.append({"participant": pid, "kind": kind, "sessions": len(items),
                         "closed": len(closed), "answered": answered,
                         "expired": sum(1 for i in closed if i["status"] == "expired"),
                         "missed": sum(1 for i in closed if i["status"] == "missed"),
                         "compliance": f"{answered / len(closed):.3f}" if closed else "",
                         "median_latency_seconds": _secs(lat[len(lat) // 2]) if lat else ""})
        write("schedule_compliance.csv", COMPLIANCE_COLUMNS, comp)

        write("schedule_notifications.csv", NOTIFICATION_COLUMNS, [{
            "participant": n["participant"], "session_id": n["session_id"], "rule": n["rule"],
            "template": n["template"], "channel": n["channel"],
            "due_at_utc": timeutil.iso_utc(n["due_at"]), "status": n["status"],
            "attempts": n["attempts"], "sent_at_utc": timeutil.iso_utc(n.get("sent_at")),
            "detail": n.get("detail") or ""} for n in notes])

        rounds = store.rounds()
        if rounds:
            ratings = []
            for s in sessions:
                if s["kind"] != "round" or not s.get("submitted_at"):
                    continue
                for item, ans in (s.get("answers") or {}).items():
                    if isinstance(ans, dict):
                        ratings.append({"participant": s["participant"], "round": s["name"],
                                        "item": item, "rating": ans.get("rating"),
                                        "comment": ans.get("comment") or ""})
            write("delphi_ratings.csv", ["participant", "round", "item", "rating", "comment"],
                  ratings)
            by_round = {r["round"]: r for r in rounds}
            stat_rows = []
            for st in store.stats():
                r = by_round.get(st["round"], {})
                stat_rows.append({**st, "settled": int(bool(st["settled"])),
                                  "opens_at_utc": timeutil.iso_utc(r.get("opens_at")),
                                  "closed_at_utc": timeutil.iso_utc(r.get("closed_at")),
                                  "round_status": r.get("status", ""),
                                  "stop_reason": r.get("stop_reason") or ""})
            write("delphi_rounds.csv",
                  ["round", "item", "n", "median", "q1", "q3", "iqr", "mean", "median_change",
                   "changed_share", "settled", "opens_at_utc", "closed_at_utc", "round_status",
                   "stop_reason"], stat_rows)

        return ExportResult(success=True, format_name=self.format_name, files_written=files,
                            stats={"participants": len(people), "sessions": len(sessions),
                                   "notifications": len(notes), "delphi_rounds": len(rounds)})
