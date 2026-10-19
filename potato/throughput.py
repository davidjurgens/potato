"""
How fast each annotator works, and how often their work comes back.

The numbers behind the admin dashboard's Throughput tab, from data Potato
already keeps:

* **active time** per item from the interaction events
  (``BehavioralData.active_time_ms``: the gaps between events, each capped so
  an idle tab does not count as work);
* **items per active hour** and the **median active time per item**, per
  annotator and per day;
* **first-pass approval** and **rework**, when the review workflow is on: of
  the items an annotator worked on that reached review, the share that went to
  ``done`` without ever being sent back to an earlier review state, and the
  share that was sent back at least once.

Everything here is a pure function over plain data, so it is tested without a
server; ``admin.py`` gathers the inputs.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

#: Review states in board order (review_workflow.STATES). A move to an earlier
#: state is a send-back.
REVIEW_ORDER = ("pending", "in_review", "needs_second", "adjudication", "done")
#: The by-day bucket for saved items that have no interaction events.
NO_EVENTS = "no events"


def _active_ms(behavior: Any) -> int:
    """Active milliseconds from a BehavioralData or its dict form."""
    if behavior is None:
        return 0
    if isinstance(behavior, dict):
        from potato.interaction_tracking import BehavioralData
        try:
            behavior = BehavioralData.from_dict(behavior)
        except Exception:  # noqa: BLE001 - a malformed record counts as nothing
            return int(behavior.get("total_time_ms") or 0)
    try:
        return int(behavior.active_time_ms())
    except Exception:  # noqa: BLE001
        return int(getattr(behavior, "total_time_ms", 0) or 0)


def _finished_at(behavior: Any) -> Optional[float]:
    """When the annotator last touched the item (unix seconds), if known."""
    if behavior is None:
        return None
    if isinstance(behavior, dict):
        times = [e.get("timestamp") for e in behavior.get("interactions") or []
                 if isinstance(e, dict) and e.get("timestamp")]
        end = behavior.get("session_end")
    else:
        times = [getattr(e, "timestamp", None) for e in getattr(behavior, "interactions", []) or []]
        times = [t for t in times if t]
        end = getattr(behavior, "session_end", None)
    if times:
        return max(times)
    return float(end) if end else None


def _day(ts: Optional[float]) -> Optional[str]:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _rate(items: int, active_ms: int) -> Optional[float]:
    hours = active_ms / 3_600_000
    return round(items / hours, 2) if hours > 0 else None


def _days(days: Dict[str, Dict[str, float]]) -> List[Dict[str, Any]]:
    """Day rows, oldest first, with the no-events bucket last."""
    order = sorted(days, key=lambda d: (d == NO_EVENTS, d))
    return [{"day": day, "items": int(days[day]["items"]),
             "active_seconds": round(days[day]["active_ms"] / 1000, 1),
             "active_hours": round(days[day]["active_ms"] / 3_600_000, 3),
             "items_per_active_hour": _rate(int(days[day]["items"]), int(days[day]["active_ms"]))}
            for day in order]


def review_outcomes(transitions: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, bool]]:
    """Per item: did it reach ``done``, and was it ever sent back?"""
    rank = {state: i for i, state in enumerate(REVIEW_ORDER)}
    out: Dict[str, Dict[str, bool]] = {}
    for t in sorted(transitions, key=lambda t: t.get("at") or 0):
        item = str(t.get("instance_id"))
        record = out.setdefault(item, {"done": False, "sent_back": False})
        before, after = rank.get(t.get("from_state")), rank.get(t.get("to_state"))
        if before is not None and after is not None and after < before:
            record["sent_back"] = True
        if t.get("to_state") == "done":
            record["done"] = True
    return out


def compute_throughput(
    behavior: Dict[str, Dict[str, Any]],
    saved: Dict[str, Iterable[str]],
    transitions: Optional[Iterable[Dict[str, Any]]] = None,
    qc_items: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Throughput per annotator, per annotator per day, and for the project.

    Args:
        behavior: ``{annotator: {instance_id: BehavioralData or dict}}``.
        saved: ``{annotator: instance ids with a saved answer}``. Only these
            count as items done; time on an item opened and abandoned counts
            towards nothing.
        transitions: review_workflow transition rows, or None when review is
            off.
        qc_items: attention-check and gold item ids. They are not work on
            the data, so they are counted apart (``qc_items``) and left out of
            every rate; a heavily checked study would otherwise look faster.
    """
    qc = {str(i) for i in qc_items or []}
    outcomes = review_outcomes(transitions or []) if transitions is not None else None
    annotators = []
    project_days: Dict[str, Dict[str, float]] = defaultdict(lambda: {"items": 0, "active_ms": 0})
    total_items = total_ms = 0
    all_item_seconds: List[float] = []

    for user in sorted(saved):
        everything = {str(i) for i in saved[user] or []}
        items = sorted(everything - qc)
        per_item = behavior.get(user) or {}
        times = {iid: _active_ms(per_item.get(iid)) for iid in items}
        timed = [ms for ms in times.values() if ms > 0]
        active_ms = sum(times.values())
        days: Dict[str, Dict[str, float]] = defaultdict(lambda: {"items": 0, "active_ms": 0})
        for iid in items:
            # An item with no events has no time either; it is grouped apart
            # rather than guessed onto a day.
            day = _day(_finished_at(per_item.get(iid))) or NO_EVENTS
            days[day]["items"] += 1
            days[day]["active_ms"] += times[iid]
            project_days[day]["items"] += 1
            project_days[day]["active_ms"] += times[iid]
        row: Dict[str, Any] = {
            "annotator": user,
            "items": len(items),
            "qc_items": len(everything & qc),
            "items_timed": len(timed),
            "active_seconds": round(active_ms / 1000, 1),
            "active_hours": round(active_ms / 3_600_000, 3),
            "items_per_active_hour": _rate(len(timed), sum(timed)),
            "median_active_seconds": (round(statistics.median(timed) / 1000, 1) if timed else None),
            "by_day": _days(days),
        }
        if outcomes is not None:
            reviewed = [outcomes[i] for i in items if i in outcomes]
            finished = [o for o in reviewed if o["done"]]
            row["reviewed_items"] = len(reviewed)
            row["first_pass_approval"] = (
                round(sum(1 for o in finished if not o["sent_back"]) / len(finished), 3)
                if finished else None)
            row["rework_rate"] = (round(sum(1 for o in reviewed if o["sent_back"]) / len(reviewed), 3)
                                  if reviewed else None)
        annotators.append(row)
        total_items += len(timed)
        total_ms += sum(timed)
        all_item_seconds.extend(ms / 1000 for ms in timed)

    report: Dict[str, Any] = {
        "annotators": annotators,
        "project": {
            "annotators": len(annotators),
            "items": sum(a["items"] for a in annotators),
            "qc_items": sum(a["qc_items"] for a in annotators),
            "items_timed": total_items,
            "active_seconds": round(total_ms / 1000, 1),
            "active_hours": round(total_ms / 3_600_000, 3),
            "items_per_active_hour": _rate(total_items, total_ms),
            "median_active_seconds": (round(statistics.median(all_item_seconds), 1)
                                      if all_item_seconds else None),
            "by_day": _days(project_days),
        },
        "review_enabled": outcomes is not None,
    }
    untimed = report["project"]["items"] - total_items
    if untimed:
        report["note"] = (f"{untimed} saved item(s) have no interaction events to time "
                          f"(imported answers, or saves from the API), so rates count "
                          f"only the timed ones.")
    return report
