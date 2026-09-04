"""The v1 training event protocol.

One event vocabulary, two transports. The subprocess worker writes these as
JSON Lines on stdout; an external backend POSTs the same objects to
``/api/training/jobs/<id>/progress``. Because both carry identical payloads,
the manager, the status dict, the run ledger and the admin UI have a single
code path, and a built-in trainer is just an external backend that happens to
run on localhost.

``v`` is a protocol version. A backend pinned to v1 keeps working when v2
arrives, which matters because the backends are other people's code running on
other people's machines.

**Predictions do not travel on this stream.** They go to a file and the
producer emits one ``artifact`` event pointing at it. A detection run over a
large corpus would otherwise push hundreds of megabytes through a pipe the
supervisor reads a line at a time, and file delivery makes the write-back
transactional: the parent ingests the whole file after ``result``, or none of
it.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any, Callable, Dict, Iterator, Optional, TextIO

from potato.training.base import ProgressReporter

__all__ = [
    "PROTOCOL_VERSION",
    "EVENT_TYPES",
    "EXIT_OK",
    "EXIT_UNEXPECTED",
    "EXIT_BAD_SPEC",
    "EXIT_MISSING_DEPENDENCY",
    "EXIT_CANCELLED",
    "EXIT_OOM",
    "EXIT_MEANINGS",
    "event",
    "parse_line",
    "JsonlReporter",
    "CollectingReporter",
]

PROTOCOL_VERSION = 1

EVENT_TYPES = ("status", "progress", "metric", "log", "artifact", "result",
               "error")

#: Exit codes. A code alone is never trusted -- any exit without a ``result``
#: event is an error however cleanly the process left.
EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_BAD_SPEC = 2
EXIT_MISSING_DEPENDENCY = 3
EXIT_CANCELLED = 4
EXIT_OOM = 5

EXIT_MEANINGS = {
    EXIT_OK: "finished",
    EXIT_UNEXPECTED: "the trainer raised an unexpected error",
    EXIT_BAD_SPEC: "the spec or bundle could not be read",
    EXIT_MISSING_DEPENDENCY: "a required package is not installed",
    EXIT_CANCELLED: "cancelled",
    EXIT_OOM: "ran out of memory",
}


def event(kind: str, **fields: Any) -> Dict[str, Any]:
    """Build one protocol event."""
    if kind not in EVENT_TYPES:
        raise ValueError("Unknown event type %r; expected one of %s"
                         % (kind, ", ".join(EVENT_TYPES)))
    payload = {"v": PROTOCOL_VERSION, "event": kind, "t": time.time()}
    payload.update(fields)
    return payload


def parse_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse one stdout line, or ``None`` if it is not a protocol event.

    Returning None rather than raising is deliberate. A third-party library
    that prints a progress bar to stdout must not be able to kill a run that is
    otherwise going fine, so the supervisor treats unparseable output as a log
    line.
    """
    line = line.strip()
    if not line or not line.startswith("{"):
        return None
    try:
        payload = json.loads(line)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("event") not in EVENT_TYPES:
        return None
    return payload


class JsonlReporter(ProgressReporter):
    """Writes protocol events to a stream. Used by the subprocess worker.

    Progress and metric events are throttled: a fit that reports every batch
    can produce thousands of lines a second, and the supervisor parses each one
    on a thread that also has a pipe to drain.
    """

    def __init__(self, stream: Optional[TextIO] = None,
                 should_stop: Optional[Callable[[], bool]] = None,
                 min_interval_s: float = 0.25):
        self._stream = stream if stream is not None else sys.stdout
        self._should_stop = should_stop or (lambda: False)
        self._min_interval = min_interval_s
        self._last_progress = 0.0

    def _emit(self, payload: Dict[str, Any]) -> None:
        self._stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._stream.flush()

    def status(self, state: str, step: str = "") -> None:
        self._emit(event("status", state=state, step=step))

    def progress(self, phase: str, current: int, total: int,
                 eta_s: Optional[float] = None) -> None:
        now = time.time()
        final = total and current >= total
        if not final and now - self._last_progress < self._min_interval:
            return
        self._last_progress = now
        self._emit(event("progress", phase=phase, current=int(current),
                         total=int(total), eta_s=eta_s))

    def metric(self, split: str, name: str, value: float,
               step: int = 0) -> None:
        self._emit(event("metric", split=split, name=name,
                         value=float(value), step=int(step)))

    def log(self, level: str, msg: str) -> None:
        self._emit(event("log", level=level, msg=str(msg)))

    def artifact(self, path: str, bytes_: Optional[int] = None) -> None:
        self._emit(event("artifact", path=path, bytes=bytes_))

    def result(self, status: str, **fields: Any) -> None:
        self._emit(event("result", status=status, **fields))

    def error(self, code: str, message: str, install_hint: str = "") -> None:
        self._emit(event("error", code=code, message=message,
                         install_hint=install_hint))

    def should_stop(self) -> bool:
        return bool(self._should_stop())


class CollectingReporter(ProgressReporter):
    """Keeps events in a list. For tests and for in-process use."""

    def __init__(self, should_stop: Optional[Callable[[], bool]] = None):
        self.events: list = []
        self._should_stop = should_stop or (lambda: False)

    def status(self, state: str, step: str = "") -> None:
        self.events.append(event("status", state=state, step=step))

    def progress(self, phase: str, current: int, total: int,
                 eta_s: Optional[float] = None) -> None:
        self.events.append(event("progress", phase=phase, current=current,
                                 total=total, eta_s=eta_s))

    def metric(self, split: str, name: str, value: float,
               step: int = 0) -> None:
        self.events.append(event("metric", split=split, name=name,
                                 value=value, step=step))

    def log(self, level: str, msg: str) -> None:
        self.events.append(event("log", level=level, msg=msg))

    def should_stop(self) -> bool:
        return bool(self._should_stop())

    def of_type(self, kind: str) -> list:
        return [e for e in self.events if e["event"] == kind]
