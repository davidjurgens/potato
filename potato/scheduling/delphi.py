"""
Delphi rounds: per-item statistics, the stopping rule, and the feedback a
panelist sees in the next round.

Why rounds are built on the schedule rather than on rooms: a Delphi panel
rates on their own, anonymously, over days. Rooms are live sessions where
members see each other; the schedule already has windows, reminders, resume
links and per-session answers, which are what a round needs.

Statistics per item and round (ratings of panelists who submitted):

``n``, ``median``, ``q1``, ``q3``, ``iqr = q3 - q1``, ``mean``
    Quartiles by linear interpolation between order statistics (the
    "inclusive" method; R type 7, NumPy's default), so a panel of 1 has an
    IQR of 0.

``median_change``
    ``|median_r - median_{r-1}|`` (round 2 on).

``changed_share``
    Among panelists who rated the item in both rounds, the share whose
    rating changed (round 2 on).

Stopping rule: an item is *settled* when it meets at least one configured
criterion (``iqr_at_most`` -- consensus; ``median_change_at_most`` or
``changed_share_below`` -- stability, from round 2). The study stops after
the first round in which every item is settled, or after ``max_rounds``.
With no criteria it runs ``max_rounds`` rounds.
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Optional, Tuple


def quantile(sorted_values: List[float], q: float) -> Optional[float]:
    if not sorted_values:
        return None
    pos = (len(sorted_values) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return float(sorted_values[lo])
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def ratings_by_item(sessions: List[dict]) -> Dict[str, Dict[str, float]]:
    """``{item: {participant: rating}}`` from a round's submitted sessions."""
    out: Dict[str, Dict[str, float]] = {}
    for s in sessions:
        if not s.get("submitted_at") or not isinstance(s.get("answers"), dict):
            continue
        for item, ans in s["answers"].items():
            if isinstance(ans, dict) and isinstance(ans.get("rating"), (int, float)):
                out.setdefault(item, {})[s["participant"]] = float(ans["rating"])
    return out


def item_stats(items: List[dict], current: Dict[str, Dict[str, float]],
               previous: Optional[Dict[str, Dict[str, float]]],
               previous_stats: Optional[Dict[str, dict]], stop: Dict[str, float]
               ) -> List[Dict[str, Any]]:
    rows = []
    for it in items:
        iid = it["id"]
        ratings = current.get(iid, {})
        values = sorted(ratings.values())
        row: Dict[str, Any] = {"item": iid, "n": len(values)}
        if values:
            q1, med, q3 = quantile(values, 0.25), quantile(values, 0.5), quantile(values, 0.75)
            row.update(median=med, q1=q1, q3=q3, iqr=q3 - q1,
                       mean=sum(values) / len(values))
        settled = False
        if values:
            if "iqr_at_most" in stop and row["iqr"] <= stop["iqr_at_most"] + 1e-9:
                settled = True
            prev_stats = (previous_stats or {}).get(iid)
            if prev_stats and prev_stats.get("median") is not None:
                row["median_change"] = abs(row["median"] - prev_stats["median"])
                if "median_change_at_most" in stop and \
                        row["median_change"] <= stop["median_change_at_most"] + 1e-9:
                    settled = True
            if previous is not None:
                before = previous.get(iid, {})
                both = [p for p in ratings if p in before]
                if both:
                    row["changed_share"] = sum(1 for p in both if ratings[p] != before[p]) / len(both)
                    if "changed_share_below" in stop and \
                            row["changed_share"] < stop["changed_share_below"]:
                        settled = True
        row["settled"] = settled
        rows.append(row)
    return rows


def stop_decision(rows: List[dict], round_number: int, max_rounds: int,
                  stop: Dict[str, float]) -> Tuple[bool, str]:
    if stop and rows and all(r["settled"] for r in rows):
        return True, "every item met a stopping criterion"
    if round_number >= max_rounds:
        return True, f"maximum of {max_rounds} rounds reached"
    return False, ""


def feedback(items: List[dict], stats: Dict[str, dict], own: Dict[str, Any],
             comments: Dict[str, List[Tuple[str, str]]], participant: str, min_panel: int,
             seed: str) -> List[Dict[str, Any]]:
    """What the next round shows beside each item: the panel's median and
    IQR, the participant's own previous rating, and the other panelists'
    comments without names, in an order fixed per participant."""
    out = []
    for it in items:
        iid = it["id"]
        st = stats.get(iid) or {}
        mine = own.get(iid) if isinstance(own.get(iid), dict) else {}
        others = [text for who, text in comments.get(iid, []) if who != participant and text]
        random.Random(f"{seed}|{participant}|{iid}").shuffle(others)
        shown = st.get("n", 0) >= min_panel and st.get("median") is not None
        out.append({
            "item": iid,
            "n": st.get("n", 0),
            "shown": shown,
            "median": st.get("median") if shown else None,
            "q1": st.get("q1") if shown else None,
            "q3": st.get("q3") if shown else None,
            "iqr": st.get("iqr") if shown else None,
            "own": mine.get("rating"),
            "own_comment": mine.get("comment") or "",
            "comments": others if shown else [],
        })
    return out


def comments_by_item(sessions: List[dict]) -> Dict[str, List[Tuple[str, str]]]:
    out: Dict[str, List[Tuple[str, str]]] = {}
    for s in sessions:
        if not s.get("submitted_at") or not isinstance(s.get("answers"), dict):
            continue
        for item, ans in s["answers"].items():
            if isinstance(ans, dict) and ans.get("comment"):
                out.setdefault(item, []).append((s["participant"], str(ans["comment"])))
    return out


def format_number(value: Optional[float]) -> str:
    if value is None:
        return ""
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"
