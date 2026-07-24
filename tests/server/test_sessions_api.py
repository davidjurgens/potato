"""
Server tests for D1 session-level scoring.

Boots a real Flask server with `sessions.enabled` + a session_level
scheme over items carrying session_id, then exercises the whole flow:
auto-detection at startup, /sessions page, queue/detail APIs, the
annotate save (incl. validation + cross-annotator aggregates), the
session_annotations.jsonl export, and exclusion of session-level
schemes from the per-instance form.
"""

import json
import os

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory, create_test_config, create_test_data_file,
)

PORT = 9723


def _sessions_config(test_dir):
    data_file = create_test_data_file(test_dir, [
        {"id": "tr-1", "text": "first trace of session A",
         "session_id": "sess-A"},
        {"id": "tr-2", "text": "second trace of session A",
         "session_id": "sess-A"},
        {"id": "tr-3", "text": "only trace of session B",
         "metadata": {"session_id": "sess-B"}},
        {"id": "tr-4", "text": "no session at all"},
    ])
    return create_test_config(
        test_dir,
        [
            {
                "annotation_type": "likert",
                "name": "session_quality",
                "description": "Overall session quality",
                "size": 5,
                "min_label": "poor",
                "max_label": "great",
                "session_level": True,
            },
            {
                "annotation_type": "multiselect",
                "name": "session_issues",
                "description": "Session issues",
                "labels": ["dropped_context", "wrong_goal"],
                "session_level": True,
            },
            {
                "annotation_type": "radio",
                "name": "trace_ok",
                "description": "Trace ok?",
                "labels": ["yes", "no"],
            },
        ],
        data_files=[data_file],
        additional_config={
            "item_properties": {"id_key": "id", "text_key": "text"},
            "sessions": {"enabled": True},
        },
    )


class TestSessionsAPI:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("sessions_api")
        cfg = _sessions_config(test_dir)
        server = FlaskTestServer(port=PORT, config_file=cfg)
        if not server.start():
            pytest.fail("Failed to start server")
        server.test_dir = test_dir
        yield server
        server.stop()

    def _session(self, server, name):
        s = requests.Session()
        s.post(f"{server.base_url}/register",
               data={"email": name, "pass": "x", "action": "signup"})
        s.post(f"{server.base_url}/auth",
               data={"email": name, "pass": "x", "action": "login"})
        return s

    def _queue(self, s, server):
        r = s.get(f"{server.base_url}/api/sessions")
        assert r.status_code == 200, r.text
        return {x["name"]: x for x in r.json()["sessions"]}

    # -- detection & listing ------------------------------------------------

    def test_sessions_detected_at_startup(self, flask_server):
        s = self._session(flask_server, "sess_u1")
        queue = self._queue(s, flask_server)
        assert set(queue) == {"sess-A", "sess-B"}
        assert queue["sess-A"]["n_traces"] == 2
        assert queue["sess-B"]["n_traces"] == 1  # detected via metadata

    def test_requires_login(self, flask_server):
        r = requests.get(f"{flask_server.base_url}/api/sessions")
        assert r.status_code == 401

    def test_page_renders_for_logged_in_user(self, flask_server):
        s = self._session(flask_server, "sess_u2")
        r = s.get(f"{flask_server.base_url}/sessions")
        assert r.status_code == 200
        assert "session_quality" in r.text
        assert "Overall session quality" in r.text

    # -- detail & save ------------------------------------------------------

    def test_detail_members_and_previews(self, flask_server):
        s = self._session(flask_server, "sess_u3")
        case_id = self._queue(s, flask_server)["sess-A"]["case_id"]
        r = s.get(f"{flask_server.base_url}/api/sessions/{case_id}")
        assert r.status_code == 200
        detail = r.json()
        ids = {m["instance_id"] for m in detail["members"]}
        assert ids == {"tr-1", "tr-2"}
        previews = {m["instance_id"]: m["preview"] for m in detail["members"]}
        assert "first trace" in previews["tr-1"]

    def test_annotate_round_trip_and_aggregates(self, flask_server):
        alice = self._session(flask_server, "sess_alice")
        bob = self._session(flask_server, "sess_bob")
        case_id = self._queue(alice, flask_server)["sess-A"]["case_id"]

        r = alice.post(
            f"{flask_server.base_url}/api/sessions/{case_id}/annotate",
            json={"schema": "session_quality", "value": {"value": 4}})
        assert r.status_code == 200, r.text
        r = bob.post(
            f"{flask_server.base_url}/api/sessions/{case_id}/annotate",
            json={"schema": "session_quality", "value": {"value": 2}})
        assert r.status_code == 200, r.text
        r = alice.post(
            f"{flask_server.base_url}/api/sessions/{case_id}/annotate",
            json={"schema": "session_issues",
                  "value": {"values": ["dropped_context"]}})
        assert r.status_code == 200, r.text

        detail = alice.get(
            f"{flask_server.base_url}/api/sessions/{case_id}").json()
        assert detail["my_annotations"]["session_quality"] == {"value": 4}
        agg = detail["aggregates"]["session_quality"]
        assert agg["n_annotators"] == 2
        assert agg["mean"] == 3.0
        assert detail["aggregates"]["session_issues"]["value_counts"] == {
            "dropped_context": 1}

        # Queue reflects per-annotator progress
        assert self._queue(alice, flask_server)["sess-A"][
            "my_schemas_done"] == ["session_issues", "session_quality"]
        assert self._queue(bob, flask_server)["sess-A"][
            "my_schemas_done"] == ["session_quality"]

    def test_clear_annotation(self, flask_server):
        s = self._session(flask_server, "sess_clear")
        case_id = self._queue(s, flask_server)["sess-B"]["case_id"]
        s.post(f"{flask_server.base_url}/api/sessions/{case_id}/annotate",
               json={"schema": "session_quality", "value": {"value": 5}})
        s.post(f"{flask_server.base_url}/api/sessions/{case_id}/annotate",
               json={"schema": "session_quality", "value": None})
        detail = s.get(
            f"{flask_server.base_url}/api/sessions/{case_id}").json()
        assert "session_quality" not in detail["my_annotations"]

    def test_rejects_unknown_schema_and_bad_value(self, flask_server):
        s = self._session(flask_server, "sess_bad")
        case_id = self._queue(s, flask_server)["sess-A"]["case_id"]
        r = s.post(f"{flask_server.base_url}/api/sessions/{case_id}/annotate",
                   json={"schema": "trace_ok", "value": {"value": "yes"}})
        assert r.status_code == 400  # per-instance scheme, not session_level
        r = s.post(f"{flask_server.base_url}/api/sessions/{case_id}/annotate",
                   json={"schema": "session_quality", "value": [1, 2]})
        assert r.status_code == 400
        r = s.post(f"{flask_server.base_url}/api/sessions/{case_id}/annotate",
                   json={"schema": "session_quality", "value": {"bogus": 1}})
        assert r.status_code == 400
        r = s.post(f"{flask_server.base_url}/api/sessions/bogus-id/annotate",
                   json={"schema": "session_quality", "value": {"value": 1}})
        assert r.status_code == 404

    def test_cross_origin_save_rejected(self, flask_server):
        s = self._session(flask_server, "sess_csrf")
        case_id = self._queue(s, flask_server)["sess-A"]["case_id"]
        r = s.post(f"{flask_server.base_url}/api/sessions/{case_id}/annotate",
                   json={"schema": "session_quality", "value": {"value": 1}},
                   headers={"Origin": "https://evil.example"})
        assert r.status_code == 403

    # -- export & form exclusion -------------------------------------------

    def test_export_file_written(self, flask_server):
        s = self._session(flask_server, "sess_export")
        case_id = self._queue(s, flask_server)["sess-A"]["case_id"]
        r = s.post(f"{flask_server.base_url}/api/sessions/{case_id}/annotate",
                   json={"schema": "session_quality", "value": {"value": 3}})
        assert r.status_code == 200
        path = r.json().get("export")
        assert path and os.path.exists(path), path
        with open(path) as f:
            rows = [json.loads(line) for line in f if line.strip()]
        mine = [x for x in rows if x["annotator"] == "sess_export"]
        assert mine and mine[0]["session"] == "sess-A"
        assert set(mine[0]["instance_ids"]) == {"tr-1", "tr-2"}

    def test_session_schemes_not_on_annotation_form(self, flask_server):
        s = self._session(flask_server, "sess_form")
        html = s.get(f"{flask_server.base_url}/annotate").text
        # Per-instance scheme renders a real form...
        assert 'schema="trace_ok"' in html or 'name="trace_ok"' in html
        # ...session-level schemes render only the pointer note (which carries
        # data-schema-name); no *real* form input (bare name= attr) is emitted.
        assert "session-level-note" in html
        assert ' name="session_quality"' not in html
