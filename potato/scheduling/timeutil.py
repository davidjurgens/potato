"""
Durations, clock times and time zones for schedules.

Everything is stored as UTC epoch seconds. A participant's time zone is used
for two things only: placing times written as a local clock time (a wave that
opens "at 09:00", a sampling window "09:00-21:00") and showing times back to
them. Local clock times are converted through ``zoneinfo`` on the day they
fall on, so a 09:00 prompt is 09:00 on both sides of a daylight-saving change.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Optional, Tuple

try:  # Python 3.9+
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones
except ImportError:  # pragma: no cover - Potato requires 3.9+
    ZoneInfo = None  # type: ignore

UTC = timezone.utc

_DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(s|m|h|d|w)\s*$")
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 7 * 86400}
_CLOCK = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def parse_duration(value, where: str = "duration") -> float:
    """Seconds in ``value``: a number of seconds, or text such as ``90m``,
    ``48h``, ``7d``, ``2w``. Raises ValueError naming ``where``."""
    if isinstance(value, bool):
        raise ValueError(f"{where} must be a duration such as 30m, 48h or 7d")
    if isinstance(value, (int, float)):
        if value < 0:
            raise ValueError(f"{where} must not be negative")
        return float(value)
    if isinstance(value, str):
        m = _DURATION.match(value)
        if m:
            return float(m.group(1)) * _UNITS[m.group(2)]
    raise ValueError(f"{where} must be a duration such as 30m, 48h or 7d (got {value!r})")


def parse_clock(value, where: str = "time") -> Tuple[int, int]:
    """``(hour, minute)`` from ``"HH:MM"`` (24-hour).

    YAML 1.1 reads an unquoted ``10:30`` as the base-60 integer 630, so an
    integer under 1440 is taken as minutes after midnight."""
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 1440:
        return value // 60, value % 60
    if isinstance(value, str):
        m = _CLOCK.match(value.strip())
        if m:
            return int(m.group(1)), int(m.group(2))
    raise ValueError(f"{where} must be a 24-hour clock time such as 09:00 (got {value!r})")


def parse_window(value, where: str = "daily_window") -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """``((h, m), (h, m))`` from ``"09:00-21:00"``; the end must be later."""
    if not isinstance(value, str) or "-" not in value:
        raise ValueError(f"{where} must look like 09:00-21:00 (got {value!r})")
    start_s, end_s = value.split("-", 1)
    start = parse_clock(start_s.strip(), where)
    end = parse_clock(end_s.strip(), where)
    if end[0] * 60 + end[1] <= start[0] * 60 + start[1]:
        raise ValueError(f"{where} must end later in the day than it starts (got {value!r})")
    return start, end


def valid_timezone(name) -> bool:
    if not isinstance(name, str) or not name or len(name) > 64:
        return False
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return False


def timezone_names():
    """Every IANA zone name this machine knows, sorted."""
    try:
        return sorted(available_timezones())
    except Exception:  # pragma: no cover - platform without tz data
        return ["UTC"]


def zone(name: str):
    return ZoneInfo(name) if valid_timezone(name) else ZoneInfo("UTC")


def local_date(epoch: float, tz: str) -> date:
    return datetime.fromtimestamp(epoch, tz=zone(tz)).date()


def local_to_epoch(day: date, hour: int, minute: int, tz: str, extra_seconds: float = 0) -> float:
    """UTC epoch of the wall-clock time ``hour:minute`` (+ ``extra_seconds``
    of wall-clock time) on ``day`` in ``tz``.

    Wall-clock arithmetic happens before the zone is attached, so the result
    keeps the local clock time across a daylight-saving change. A time that
    does not exist (inside a spring-forward gap) resolves as ``zoneinfo``
    does with ``fold=0``: the offset in force before the change.
    """
    naive = datetime.combine(day, dtime(hour, minute)) + timedelta(seconds=extra_seconds)
    return naive.replace(tzinfo=zone(tz)).timestamp()


def iso_utc(epoch: Optional[float]) -> str:
    if epoch is None:
        return ""
    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_local(epoch: Optional[float], tz: str) -> str:
    if epoch is None:
        return ""
    return datetime.fromtimestamp(epoch, tz=zone(tz)).isoformat(timespec="seconds")


def format_local(epoch: Optional[float], tz: str, with_zone: bool = True) -> str:
    """``Tue 3 Nov 2026, 09:00 EST`` in the participant's zone."""
    if epoch is None:
        return ""
    dt = datetime.fromtimestamp(epoch, tz=zone(tz))
    text = f"{dt.strftime('%a')} {dt.day} {dt.strftime('%b %Y')}, {dt.strftime('%H:%M')}"
    if with_zone:
        text += f" {dt.strftime('%Z')}"
    return text


def format_span(seconds: float) -> str:
    """``2 days 3 hours`` / ``45 minutes``: coarse, for messages."""
    seconds = max(0, int(round(seconds)))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    parts = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes and not days:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    return " ".join(parts) or "less than a minute"


def parse_instant(value, where: str) -> float:
    """UTC epoch from an ISO 8601 date-time that carries its offset
    (``2026-11-02T09:00:00-05:00`` or ``...Z``)."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            raise ValueError(f"{where} must be an ISO 8601 date-time such as "
                             f"2026-11-02T09:00:00-05:00 (got {value!r})")
    else:
        raise ValueError(f"{where} must be an ISO 8601 date-time with a UTC offset")
    if dt.tzinfo is None:
        raise ValueError(f"{where} must include a UTC offset (for example -05:00 or Z)")
    return dt.timestamp()
