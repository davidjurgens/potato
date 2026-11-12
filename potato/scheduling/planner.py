"""
A participant's sessions, computed once at enrolment.

Pure functions of the parsed schedule, the enrolment time, the participant's
time zone and id. Random prompt times are drawn from a generator seeded with
``schedule.seed``, the participant id and the study day, so the plan can be
recomputed and checked later and two participants do not share prompt times.

Waves
    ``offset`` after enrolment, open for ``window``. With ``at: "09:00"`` the
    wave opens at that local clock time on the day ``offset`` days after the
    enrolment day, which keeps it at 09:00 across a daylight-saving change;
    without ``at`` it opens exactly ``offset`` of elapsed time later.

Experience sampling
    One day at a time from ``start_day`` for ``days`` days. The daily window
    is placed on each local date separately (so it is 09:00-21:00 local on a
    DST day too).

    * signal-contingent: ``per_day`` prompts at random inside the window, at
      least ``min_gap`` apart, each expiring after ``expires_after`` and
      never after the window ends. Drawn by sampling ``per_day`` points in the
      window shortened by ``(per_day - 1) * min_gap`` and the expiry, sorting
      them and spacing them out by ``min_gap``: every arrangement that keeps
      the gaps is equally likely.
    * interval-contingent: ``every`` (from the window start) or fixed
      ``times``.

    Prompts that would already have opened at enrolment are left out.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import timedelta
from typing import List, Optional

from potato.scheduling import timeutil
from potato.scheduling.config import EsmSpec, ScheduleSpec, WaveSpec


@dataclass
class PlannedSession:
    id: str
    kind: str            # wave | prompt | round
    name: str
    title: str
    seq: int
    day: Optional[int]
    opens_at: float
    closes_at: float

    def row(self, participant: str) -> dict:
        return {"participant": participant, "id": self.id, "kind": self.kind,
                "name": self.name, "title": self.title, "seq": self.seq, "day": self.day,
                "opens_at": self.opens_at, "closes_at": self.closes_at}


def plan_wave(wave: WaveSpec, enrolled_at: float, tz: str, seq: int) -> PlannedSession:
    if wave.at is not None:
        day = timeutil.local_date(enrolled_at, tz) + timedelta(days=int(wave.offset // 86400))
        opens = timeutil.local_to_epoch(day, wave.at[0], wave.at[1], tz)
    else:
        opens = enrolled_at + wave.offset
    return PlannedSession(id=f"wave:{wave.name}", kind="wave", name=wave.name,
                          title=wave.title, seq=seq, day=None, opens_at=opens,
                          closes_at=opens + wave.window)


def _window_seconds(esm: EsmSpec) -> float:
    (h0, m0), (h1, m1) = esm.window
    return float(((h1 * 60 + m1) - (h0 * 60 + m0)) * 60)


def prompt_offsets(esm: EsmSpec, rng: random.Random) -> List[float]:
    """Seconds after the window start (wall clock) for one day's prompts."""
    length = _window_seconds(esm)
    if esm.mode == "signal":
        slack = length - esm.expires_after - (esm.per_day - 1) * esm.min_gap
        points = sorted(rng.uniform(0, max(0.0, slack)) for _ in range(esm.per_day))
        return [round(p + i * esm.min_gap) for i, p in enumerate(points)]
    if esm.every:
        out, t = [], 0.0
        while t + esm.expires_after <= length:
            out.append(t)
            t += esm.every
        return out
    (h0, m0), _end = esm.window
    start = h0 * 3600 + m0 * 60
    return [h * 3600 + m * 60 - start for h, m in esm.times]


def plan_prompts(esm: EsmSpec, enrolled_at: float, tz: str, participant: str,
                 seed: str) -> List[PlannedSession]:
    first_day = timeutil.local_date(enrolled_at, tz)
    (h0, m0), (h1, m1) = esm.window
    out: List[PlannedSession] = []
    seq = 0
    for d in range(esm.start_day, esm.start_day + esm.days):
        day = first_day + timedelta(days=d)
        rng = random.Random(f"{seed}|{participant}|esm|{day.isoformat()}")
        study_day = d - esm.start_day + 1
        window_end = timeutil.local_to_epoch(day, h1, m1, tz)
        n = 0
        for offset in prompt_offsets(esm, rng):
            opens = timeutil.local_to_epoch(day, h0, m0, tz, extra_seconds=offset)
            if opens < enrolled_at:
                continue
            closes = opens + esm.expires_after
            if esm.mode == "signal" or esm.every:
                closes = min(closes, window_end)
            n += 1
            seq += 1
            out.append(PlannedSession(
                id=f"prompt:{study_day}:{n}", kind="prompt",
                name=f"day {study_day} prompt {n}", title=esm.title, seq=seq, day=study_day,
                opens_at=opens, closes_at=closes))
    return out


def plan(spec: ScheduleSpec, enrolled_at: float, tz: str, participant: str) -> List[PlannedSession]:
    """Every wave and prompt for one participant (Delphi rounds are panel-wide
    and come from the round table instead)."""
    sessions = [plan_wave(w, enrolled_at, tz, i + 1) for i, w in enumerate(spec.waves)]
    if spec.esm is not None:
        sessions += plan_prompts(spec.esm, enrolled_at, tz, participant, spec.seed)
    return sessions
