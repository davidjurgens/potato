"""
The Langfuse poller against Langfuse v4's Observations API and the legacy
traces API.

tests/data/langfuse/v2_observations_one_trace.json is a real response from a
self-hosted Langfuse 4.63 (docker), for a trace made with the Langfuse Python
SDK 5.0.2: a root span with a generation and a tool span under it. The legacy
shapes follow Langfuse's documented API: the trace list carries observation
ids only, and the trace detail carries the observations themselves.
"""

import copy
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from potato.trace_ingestion.langfuse_poller import LangfusePoller

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "data", "langfuse",
                       "v2_observations_one_trace.json")
TRACE = "764461b655dc337137d4b2e152faa2a3"
RECORDED_AT = datetime(2026, 10, 19, 14, 15, 12, 543000, tzinfo=timezone.utc)  # last endTime


class Response:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeLangfuse:
    """Answers GETs from a route table; records every request."""

    def __init__(self, routes):
        self.routes, self.requests = routes, []

    def get(self, url, params=None, auth=None, timeout=None):
        path = url.split("http://lf", 1)[1]
        self.requests.append((path, dict(params or {})))
        handler = self.routes.get(path)
        if handler is None:
            return Response(404, {"message": "not found"})
        return handler(dict(params or {}))


def v2_rows():
    with open(FIXTURE) as handle:
        return json.load(handle)["data"]


def shifted(rows, trace_id, by):
    """The same trace again under another id, ``by`` later."""
    out = []
    for row in copy.deepcopy(rows):
        row["traceId"] = trace_id
        for key in ("startTime", "endTime"):
            moment = datetime.fromisoformat(row[key].replace("Z", "+00:00")) + by
            row[key] = moment.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        out.append(row)
    return out


def poller(routes, **kwargs):
    delivered = []
    fake = FakeLangfuse(routes)
    lf = LangfusePoller("http://lf", "pk", "sk", on_trace=delivered.append,
                        session=fake, settle_seconds=30, **kwargs)
    lf._since = RECORDED_AT - timedelta(hours=1)
    return lf, fake, delivered


class TestV4:
    def test_a_recorded_trace_becomes_one_item_with_its_steps_in_order(self):
        rows = v2_rows()
        lf, fake, delivered = poller({"/api/public/v2/observations": lambda p: Response(200, {"data": rows, "meta": {}})})
        assert lf.poll_once(now=RECORDED_AT + timedelta(minutes=5)) == 1
        [item] = delivered
        assert item["id"] == f"langfuse_{TRACE}"
        assert item["metadata"]["original_id"] == TRACE
        assert item["task_description"] == "check-1"
        # The root span is the run itself; its children are the steps.
        assert [s["metadata"]["name"] for s in item["steps"]] == ["plan", "search_tool"]
        plan, tool = item["steps"]
        assert (plan["thought"], plan["observation"]) == ("plan it", "search, then book")
        assert tool["thought"] == '{"q": "tables"}' and plan["action_type"] == "type"
        assert item["metadata"]["input"] == '{"task": "book a table"}'
        assert item["metadata"]["output"] == "booked"
        path, params = fake.requests[0]
        assert path == "/api/public/v2/observations"
        assert params["fields"] == "core,basic,io,trace_context,metadata"
        assert params["fromStartTime"].endswith("Z") and "toStartTime" in params

    def test_a_trace_still_being_written_waits_and_holds_the_cursor(self):
        rows = v2_rows()
        lf, _fake, delivered = poller({"/api/public/v2/observations": lambda p: Response(200, {"data": rows})})
        assert lf.poll_once(now=RECORDED_AT + timedelta(seconds=10)) == 0
        assert delivered == []
        assert lf._since < RECORDED_AT  # its start stays inside the next window
        assert lf.poll_once(now=RECORDED_AT + timedelta(seconds=40)) == 1
        assert lf.poll_once(now=RECORDED_AT + timedelta(minutes=5)) == 0  # never twice

    def test_the_cursor_does_not_pass_a_running_trace(self):
        rows = v2_rows() + shifted(v2_rows(), "late", timedelta(minutes=10))
        lf, _fake, delivered = poller({"/api/public/v2/observations": lambda p: Response(200, {"data": rows})})
        lf.poll_once(now=RECORDED_AT + timedelta(minutes=10, seconds=5))
        assert [d["metadata"]["original_id"] for d in delivered] == [TRACE]
        assert lf._since < RECORDED_AT + timedelta(minutes=10)

    def test_pages_are_followed_by_cursor(self):
        rows = v2_rows()
        pages = {None: {"data": rows[:2], "meta": {"cursor": "c2"}},
                 "c2": {"data": rows[2:], "meta": {}}}
        lf, fake, delivered = poller({"/api/public/v2/observations": lambda p: Response(200, pages[p.get("cursor")])})
        lf.poll_once(now=RECORDED_AT + timedelta(minutes=5))
        assert [p.get("cursor") for _path, p in fake.requests] == [None, "c2"]
        assert len(delivered[0]["steps"]) == 2

    def test_a_trace_already_stored_is_skipped(self):
        rows = v2_rows()
        lf, _fake, delivered = poller({"/api/public/v2/observations": lambda p: Response(200, {"data": rows})},
                                      is_known=lambda item_id: item_id == f"langfuse_{TRACE}")
        assert lf.poll_once(now=RECORDED_AT + timedelta(minutes=5)) == 0


T0 = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def obs(trace, oid, start, end=None, parent="root", kind="SPAN", name=None):
    """One Observations-v2 row, ``start``/``end`` in seconds after T0."""
    def at(sec):
        return None if sec is None else (T0 + timedelta(seconds=sec)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return {"id": oid, "traceId": trace, "startTime": at(start), "endTime": at(end),
            "parentObservationId": parent, "type": kind, "name": name or oid,
            "input": "", "output": ""}


class Visible:
    """What the server shows, changed between polls; filters by start time."""

    def __init__(self):
        self.rows, self.params = [], []

    def __call__(self, params):
        self.params.append(params)
        since = datetime.fromisoformat(params["fromStartTime"].replace("Z", "+00:00"))
        rows = [r for r in self.rows
                if datetime.fromisoformat(r["startTime"].replace("Z", "+00:00")) >= since]
        return Response(200, {"data": rows})


def at(sec):
    return T0 + timedelta(seconds=sec)


class TestRunsInProgress:
    """An OTel SDK exports a span when it ends: a run in progress shows only
    its finished steps. These are the reviewer's three cases."""

    def make(self, **kwargs):
        server = Visible()
        lf, _fake, delivered = poller({"/api/public/v2/observations": server}, **kwargs)
        lf._since = T0 - timedelta(minutes=5)
        return lf, server, delivered

    def test_finished_steps_of_an_open_run_are_not_taken_alone(self):
        lf, server, delivered = self.make()
        server.rows = [obs("A", "plan", 1, 10)]                     # root and llm still open
        assert lf.poll_once(now=at(50)) == 0
        server.rows += [obs("A", "llm", 15, 75, kind="GENERATION"), obs("A", "root", 0, 80, parent=None)]
        assert lf.poll_once(now=at(90)) == 0                         # root ended 10s ago
        assert lf.poll_once(now=at(120)) == 1
        assert [s["metadata"]["name"] for s in delivered[0]["steps"]] == ["plan", "llm"]
        assert "complete" not in delivered[0]["metadata"]

    def test_a_long_call_that_appears_late_is_still_fetched(self):
        lf, server, delivered = self.make()
        server.rows = [obs("B1", "b1root", 250, 260, parent=None)]
        assert lf.poll_once(now=at(300)) == 1
        server.rows += [obs("B2", "b2root", 100, 600, parent=None)]  # one 500s call
        lf.poll_once(now=at(650))
        assert [d["metadata"]["original_id"] for d in delivered] == ["B1", "B2"]
        assert server.params[-1]["fromStartTime"] <= "2026-10-19T12:01:40"

    def test_a_run_whose_root_never_arrives_is_taken_after_the_bound(self):
        lf, server, delivered = self.make(max_trace_seconds=600)
        server.rows = [obs("C", "step", 0, 10)]
        assert lf.poll_once(now=at(300)) == 0
        assert lf.poll_once(now=at(601)) == 1
        assert delivered[0]["metadata"]["complete"] is False

    def test_handled_traces_are_forgotten_once_out_of_the_window(self):
        lf, server, delivered = self.make(max_trace_seconds=600)
        server.rows = [obs("D", "droot", 0, 10, parent=None)]
        lf.poll_once(now=at(60))
        assert "D" in lf._seen
        lf.poll_once(now=at(2000))
        assert "D" not in lf._seen and len(delivered) == 1


class TestLegacy:
    def routes(self):
        detail = {"id": "t1", "name": "legacy-run", "timestamp": "2026-10-19T14:00:00.000Z",
                  "input": "q", "output": "a", "sessionId": "s9", "userId": "u9", "tags": ["x"],
                  "observations": [
                      {"id": "o2", "type": "SPAN", "name": "tool", "parentObservationId": "o0",
                       "startTime": "2026-10-19T14:00:02.000Z", "endTime": "2026-10-19T14:00:03.000Z",
                       "input": {"q": 1}, "output": "r"},
                      {"id": "o0", "type": "SPAN", "name": "legacy-run", "parentObservationId": None,
                       "startTime": "2026-10-19T14:00:00.000Z", "endTime": "2026-10-19T14:00:04.000Z",
                       "input": "q", "output": "a"},
                      {"id": "o1", "type": "GENERATION", "name": "llm", "parentObservationId": "o0",
                       "startTime": "2026-10-19T14:00:01.000Z", "endTime": "2026-10-19T14:00:02.000Z",
                       "input": "p", "output": "c"}]}
        return {
            "/api/public/traces": lambda p: Response(200, {
                # The list carries observation ids, not objects.
                "data": [{"id": "t1", "name": "legacy-run", "observations": ["o0", "o1", "o2"]}],
                "meta": {"page": 1, "totalPages": 1}}),
            "/api/public/traces/t1": lambda p: Response(200, detail),
        }

    def test_an_unfinished_legacy_trace_waits_and_stays_in_the_window(self):
        detail = {"id": "t2", "name": "run", "timestamp": "2026-10-19T14:00:00.000Z",
                  "observations": [{"id": "o1", "type": "GENERATION", "name": "llm",
                                    "parentObservationId": None,
                                    "startTime": "2026-10-19T14:00:00.000Z", "endTime": None}]}
        lists = []

        def listing(params):
            lists.append(params)
            return Response(200, {"data": [{"id": "t2", "observations": ["o1"]}], "meta": {"totalPages": 1}})
        lf, _fake, delivered = poller({"/api/public/traces": listing,
                                       "/api/public/traces/t2": lambda p: Response(200, detail)})
        assert lf.poll_once(now=datetime(2026, 10, 19, 14, 10, tzinfo=timezone.utc)) == 0
        detail["observations"][0]["endTime"] = "2026-10-19T14:20:00.000Z"
        assert lf.poll_once(now=datetime(2026, 10, 19, 14, 21, tzinfo=timezone.utc)) == 1
        assert lists[-1]["fromTimestamp"] <= "2026-10-19T14:00:00"

    def test_a_server_without_the_v2_api_is_read_through_trace_details(self):
        lf, fake, delivered = poller(self.routes())
        assert lf.poll_once(now=datetime(2026, 10, 19, 14, 5, tzinfo=timezone.utc)) == 1
        [item] = delivered
        assert "complete" not in item["metadata"]
        assert [s["metadata"]["name"] for s in item["steps"]] == ["llm", "tool"]
        assert item["metadata"]["session_id"] == "s9" and item["metadata"]["tags"] == ["x"]
        assert [path for path, _ in fake.requests] == [
            "/api/public/v2/observations", "/api/public/traces", "/api/public/traces/t1"]
        # The decision sticks: the next poll goes straight to the legacy API.
        lf.poll_once(now=datetime(2026, 10, 19, 15, 1, tzinfo=timezone.utc))
        assert fake.requests[3][0] == "/api/public/traces"


class TestWiring:
    def test_a_polled_trace_becomes_an_item_on_the_server(self, monkeypatch):
        """The poller configure_app starts injects what it fetches.

        It used to be started with no callback, so every trace was dropped.
        """
        from flask import Flask

        import potato.item_state_management as ism_mod
        from potato.flask_server import _langfuse_poller_for
        from potato.server_utils import config_module
        from tests.helpers.test_utils import cleanup_test_directory, create_test_directory

        folder = create_test_directory("langfuse_poller_wiring")
        try:
            for key, value in {"task_dir": folder, "output_annotation_dir": folder,
                               "annotation_schemes": [], "item_properties": {"id_key": "id", "text_key": "text"}}.items():
                monkeypatch.setitem(config_module.config, key, value)
            monkeypatch.setattr(ism_mod, "ITEM_STATE_MANAGER", None)
            ism = ism_mod.init_item_state_manager(config_module.config)
            app = Flask("wiring")
            app.config["trace_ingestion"] = {"notify_annotators": False}

            rows = v2_rows()
            lf = _langfuse_poller_for(app, {"type": "langfuse", "api_url": "http://lf"})
            lf._session = FakeLangfuse({"/api/public/v2/observations":
                                        lambda p: Response(200, {"data": rows})})
            lf._since = RECORDED_AT - timedelta(hours=1)
            assert lf.poll_once(now=RECORDED_AT + timedelta(minutes=5)) == 1
            item = ism.get_item(f"langfuse_{TRACE}")
            assert [s["metadata"]["name"] for s in item.get_data()["steps"]] == ["plan", "search_tool"]
            # Already stored: a restart's lookback does not add it again.
            lf._seen.clear()
            assert lf.poll_once(now=RECORDED_AT + timedelta(minutes=6)) == 0
        finally:
            ism_mod.ITEM_STATE_MANAGER = None
            cleanup_test_directory(folder)
