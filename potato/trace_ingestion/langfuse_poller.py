"""
Langfuse Trace Poller

Background thread that polls a Langfuse project for new traces and injects
them as annotation items.

Two APIs, tried in this order:

* **Langfuse v4**: ``GET /api/public/v2/observations``, filtered by start time
  and paginated by cursor. Each row is one observation; a trace is the rows
  sharing a ``traceId``, and the row with no ``parentObservationId`` is its
  root. Self-hosted v4 in ``events_only`` mode refuses the legacy endpoints,
  and Langfuse Cloud removes them on 2026-11-16.
* **Legacy** (servers without the v2 endpoint): ``GET /api/public/traces``
  lists traces, whose ``observations`` are ids only, so each new trace is then
  read in full from ``GET /api/public/traces/{id}``.

When a trace is finished: an OpenTelemetry SDK (Langfuse's Python and JS
SDKs are both built on it) exports a span only when it ends, so a run in
progress shows its finished steps and nothing else. The root ends last, so a
trace is taken once its root observation has arrived with an end time and
``settle_seconds`` have passed. A trace whose root never arrives is taken,
marked incomplete, after ``max_trace_seconds``. On the legacy API a trace is
over when every observation has ended.

Each poll fetches everything that started in the last ``max_trace_seconds``
(plus the settle window), because a long call becomes visible only when it
ends, with its old start time. Traces already handled, or already in the item
store after a restart, are skipped.
"""

import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

V2_OBSERVATIONS = "/api/public/v2/observations"
LEGACY_TRACES = "/api/public/traces"
V2_FIELDS = "core,basic,io,trace_context,metadata"


def _parse_time(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class LangfusePoller:
    """
    Polls Langfuse for new traces and converts them to annotation items.

    Runs in a background daemon thread and calls ``on_trace`` with each new
    trace, normalized to Potato's trace format.
    """

    def __init__(
        self,
        api_url: str,
        public_key: str,
        secret_key: str,
        poll_interval: float = 30.0,
        on_trace: Optional[Callable[[Dict[str, Any]], Any]] = None,
        lookback_hours: float = 24.0,
        settle_seconds: float = 30.0,
        max_trace_seconds: float = 3600.0,
        is_known: Optional[Callable[[str], bool]] = None,
        session=None,
    ):
        self.api_url = api_url.rstrip("/")
        self.public_key = public_key
        self.secret_key = secret_key
        self.poll_interval = poll_interval
        self.on_trace = on_trace
        self.settle_seconds = settle_seconds
        self.max_trace_seconds = max_trace_seconds
        self.is_known = is_known or (lambda item_id: False)
        self._session = session
        self._since = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        #: trace id -> its start, for traces already handled. Pruned to the
        #: fetch window; older traces are not fetched again.
        self._seen: Dict[str, datetime] = {}
        self._api: Optional[str] = None  # "v2" or "legacy", decided on first poll
        self._stop_event = threading.Event()
        self._thread = None

    # -- lifecycle ------------------------------------------------------------

    def start(self):
        """Start the polling thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("Langfuse poller already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="langfuse-poller"
        )
        self._thread.start()
        logger.info(
            f"Langfuse poller started (interval={self.poll_interval}s, url={self.api_url})"
        )

    def stop(self):
        """Stop the polling thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=self.poll_interval + 5)
        logger.info("Langfuse poller stopped")

    def _poll_loop(self):
        while not self._stop_event.is_set():
            try:
                self.poll_once()
            except Exception as e:  # noqa: BLE001 - keep polling
                logger.error(f"Langfuse poll error: {e}")
            self._stop_event.wait(self.poll_interval)

    # -- one poll -------------------------------------------------------------

    @property
    def session(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
        return self._session

    def _get(self, path: str, params: Dict[str, Any]):
        return self.session.get(f"{self.api_url}{path}", params=params,
                                auth=(self.public_key, self.secret_key), timeout=30)

    def poll_once(self, now: Optional[datetime] = None) -> int:
        """Fetch, settle and hand over new traces. Returns how many were handed over."""
        now = now or datetime.now(timezone.utc)
        traces = self._fetch_v2(now) if self._api != "legacy" else None
        if traces is None:
            self._api = "legacy"
            traces = self._fetch_legacy(now)
        else:
            self._api = "v2"

        delivered = 0
        quiet_since = now - timedelta(seconds=self.settle_seconds)
        give_up_before = now - timedelta(seconds=self.max_trace_seconds)
        for trace_id, trace in traces.items():
            last = trace.pop("_last_activity", None)
            first = trace.pop("_first_start", None) or last
            complete = trace.pop("_complete", False)
            if trace_id in self._seen:
                continue
            if complete:
                if last is not None and last > quiet_since:
                    continue  # finished moments ago; late rows may still be arriving
            elif first is None or first > give_up_before:
                # Not finished. An OTel SDK exports a span only when it ends,
                # so a run in progress shows its finished steps and no root:
                # taking it now would freeze it at those steps.
                continue
            self._seen[trace_id] = first or now
            normalized = self._normalize_trace(trace)
            if normalized is None or self.is_known(normalized["id"]):
                continue
            if not complete:
                normalized["metadata"]["complete"] = False
                logger.warning("Langfuse trace %s never finished within %ss; taking the %d "
                               "observation(s) it has", trace_id, int(self.max_trace_seconds),
                               len(normalized["steps"]))
            if self.on_trace:
                self.on_trace(normalized)
                delivered += 1
                logger.info(f"Ingested Langfuse trace: {trace_id}")

        # The window always reaches back as far as a trace may run. A long
        # call is invisible until it ends, and then arrives with its old start
        # time; a window that had moved past that start would never fetch it.
        self._since = max(self._since, give_up_before - timedelta(seconds=self.settle_seconds))
        horizon = self._since - timedelta(seconds=self.settle_seconds)
        self._seen = {t: started for t, started in self._seen.items() if started >= horizon}
        return delivered

    def _fetch_v2(self, now: datetime) -> Optional[Dict[str, Dict[str, Any]]]:
        """Traces from Observations API v2, or None when the server lacks it."""
        rows: List[Dict[str, Any]] = []
        params = {"fromStartTime": _iso(self._since), "toStartTime": _iso(now),
                  "fields": V2_FIELDS, "limit": 1000}
        while True:
            response = self._get(V2_OBSERVATIONS, params)
            if response.status_code in (404, 405):
                return None
            response.raise_for_status()
            body = response.json()
            rows.extend(body.get("data") or [])
            cursor = (body.get("meta") or {}).get("cursor")
            if not cursor:
                break
            params = {**params, "cursor": cursor}
        return self._group_rows(rows)

    @staticmethod
    def _group_rows(rows: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        traces: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            trace_id = row.get("traceId")
            if not trace_id:
                continue
            trace = traces.setdefault(trace_id, {"id": trace_id, "observations": [],
                                                 "_last_activity": None, "_first_start": None})
            trace["observations"].append(row)
            when = _parse_time(row.get("endTime")) or _parse_time(row.get("startTime"))
            if when and (trace["_last_activity"] is None or when > trace["_last_activity"]):
                trace["_last_activity"] = when
            started = _parse_time(row.get("startTime"))
            if started and (trace["_first_start"] is None or started < trace["_first_start"]):
                trace["_first_start"] = started
            if not row.get("parentObservationId"):
                # The root ends last, and an OTel SDK exports a span when it
                # ends, so a root with an end time means the run is over.
                trace["_complete"] = bool(row.get("endTime"))
                trace.update(name=row.get("traceName") or row.get("name"),
                             input=row.get("input"), output=row.get("output"),
                             sessionId=row.get("sessionId") or None,
                             userId=row.get("userId") or None, tags=row.get("tags") or [],
                             metadata=row.get("metadata") or {})
        return traces

    def _fetch_legacy(self, now: datetime) -> Dict[str, Dict[str, Any]]:
        """Traces from the legacy API, each read in full for its observations."""
        traces: Dict[str, Dict[str, Any]] = {}
        page = 1
        while True:
            response = self._get(LEGACY_TRACES, {"limit": 50, "page": page,
                                                 "fromTimestamp": _iso(self._since),
                                                 "orderBy": "timestamp.asc"})
            response.raise_for_status()
            body = response.json()
            for summary in body.get("data") or []:
                trace_id = summary.get("id")
                if not trace_id or trace_id in self._seen:
                    continue
                detail = self._get(f"{LEGACY_TRACES}/{trace_id}", {})
                detail.raise_for_status()
                trace = detail.json()
                observations = [o for o in trace.get("observations") or [] if isinstance(o, dict)]
                times = [_parse_time(o.get("endTime")) or _parse_time(o.get("startTime"))
                         for o in observations]
                times = [t for t in times if t] or [_parse_time(trace.get("timestamp"))]
                trace["observations"] = observations
                trace["_last_activity"] = max((t for t in times if t), default=None)
                starts = [_parse_time(trace.get("timestamp"))] + [
                    _parse_time(o.get("startTime")) for o in observations]
                trace["_first_start"] = min((t for t in starts if t), default=None)
                # The legacy SDKs create the trace first and stream observations
                # in; it is over when every span and generation has ended.
                trace["_complete"] = bool(observations) and all(
                    o.get("endTime") or o.get("type") == "EVENT" for o in observations)
                traces[trace_id] = trace
            total_pages = (body.get("meta") or {}).get("totalPages") or 1
            if page >= total_pages:
                break
            page += 1
        return traces

    # -- normalize ------------------------------------------------------------

    def _normalize_trace(self, trace: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert a Langfuse trace to Potato's trace format.

        The steps are the trace's observations in start order, without the
        root span, which stands for the whole run; a trace with only a root
        becomes one step.
        """
        trace_id = trace.get("id", "")
        if not trace_id:
            return None
        observations = [o for o in trace.get("observations") or [] if isinstance(o, dict)]
        observations.sort(key=lambda o: (o.get("startTime") or "", o.get("id") or ""))
        children = [o for o in observations if o.get("parentObservationId")]
        steps_source = children or observations

        steps = []
        for i, obs in enumerate(steps_source):
            obs_type = obs.get("type", "SPAN")
            steps.append({
                "step_index": i,
                "action_type": self._obs_type_to_action(obs_type),
                "thought": self._text(obs.get("input")),
                "observation": self._text(obs.get("output")),
                "screenshot_url": "",
                "timestamp": i,
                "metadata": {
                    "observation_id": obs.get("id"),
                    "observation_type": obs_type,
                    "name": obs.get("name"),
                    "model": obs.get("model") or obs.get("providedModelName"),
                    "parent_observation_id": obs.get("parentObservationId"),
                    "start_time": obs.get("startTime"),
                },
            })

        meta = trace.get("metadata") if isinstance(trace.get("metadata"), dict) else {}
        return {
            "id": f"langfuse_{trace_id}",
            "task_description": trace.get("name") or meta.get("task", "")
                                or self._text(trace.get("input")),
            "site": "",
            "steps": steps,
            "metadata": {
                "source": "langfuse",
                "format": "langfuse",
                "received_at": time.time(),
                "original_id": trace_id,
                "session_id": trace.get("sessionId"),
                "user_id": trace.get("userId"),
                "tags": trace.get("tags", []),
                "input": self._text(trace.get("input")),
                "output": self._text(trace.get("output")),
            },
        }

    @staticmethod
    def _text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _obs_type_to_action(obs_type: str) -> str:
        """Map Langfuse observation types to action types."""
        mapping = {
            "GENERATION": "type",
            "SPAN": "navigate",
            "EVENT": "click",
        }
        return mapping.get(obs_type, "wait")
