"""
Server tests for annotation telemetry.

Exercises /api/track_annotation_telemetry against a live Flask instance:
authentication, the config gating, the fidelity contract, and persistence to
BOTH destinations (SQLite for the raw streams, user_state.json for the summary
sketch).

The gating tests matter as much as the happy path. A project that has not opted
in must record nothing at all, and a project at `summary` fidelity must persist
no raw event stream.

The pairing test is the one that carries the most weight: AI-accept latency is
derived here from suggest/accept ids rather than taken from the client, so a
modified client cannot inflate it. That property is only real if the server
genuinely recomputes it, which is what these assertions check.
"""

import json
import os

import pytest
import requests


def telemetry_payload(instance_id="telemetry_test_item_01", schema="objects",
                      shapes=3, accepts=0, accept_latency=200,
                      zoom=None):
    """Build a /api/track_annotation_telemetry body."""
    events = [{"t_ms": 0, "action": "tool", "shape": "unknown", "value": 0,
               "meta": {"tool": "bbox"}}]
    t = 500

    if zoom is not None:
        events.append({"t_ms": t, "action": "zoom", "shape": "unknown",
                       "value": int(zoom * 100)})
        t += 500

    for i in range(shapes):
        events.append({"t_ms": t, "action": "shape_add", "shape": "bbox",
                       "value": 4})
        t += 4000

    for i in range(accepts):
        events.append({"t_ms": t, "action": "ai_suggest", "shape": "bbox",
                       "value": 0, "meta": {"sid": f"s{i}"}})
        events.append({"t_ms": t + accept_latency, "action": "ai_accept",
                       "shape": "bbox", "value": 0, "meta": {"sid": f"s{i}"}})
        t += 600

    return {
        "instance_id": instance_id,
        "sessions": [{
            "schema_name": schema,
            "instance_id": instance_id,
            "started_at": 1000.0,
            "ended_at": 1100.0,
            "events": events,
        }],
    }


def _build_server(test_dir_name, telemetry_config):
    from tests.helpers.flask_test_setup import FlaskTestServer
    from tests.helpers.test_utils import (
        create_test_config, create_test_data_file, create_test_directory)

    test_dir = create_test_directory(test_dir_name)
    data = [{"id": f"telemetry_test_item_{i:02d}",
             "image_url": f"/static/img_{i}.png",
             "text": f"Image {i} for telemetry tests."}
            for i in range(1, 4)]
    data_file = create_test_data_file(test_dir, data, "telemetry_test_data.jsonl")

    config_file = create_test_config(
        test_dir,
        annotation_schemes=[{
            "name": "objects",
            "annotation_type": "image_annotation",
            "description": "Draw the objects.",
            "tools": ["bbox"],
            "labels": ["cat", "dog"],
        }],
        data_files=[data_file],
        annotation_task_name=test_dir_name,
        admin_api_key="test_admin_key",
        annotation_telemetry=telemetry_config,
    )
    server = FlaskTestServer(config=config_file)
    if not server.start():
        pytest.fail(f"Failed to start Flask test server for {test_dir_name}")
    return server, test_dir


def _authed_session(server, username="at_user"):
    s = requests.Session()
    s.post(f"{server.base_url}/register",
           data={"email": username, "pass": "pw", "action": "signup"})
    s.post(f"{server.base_url}/auth", data={"email": username, "pass": "pw"})
    s.get(f"{server.base_url}/annotate")
    return s


def _sqlite_rows(test_dir, project):
    import sqlite3
    db = os.path.join(test_dir, "project.sqlite")
    if not os.path.exists(db):
        return []
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM annotation_telemetry WHERE project = ?", (project,)
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []          # table never created -> nothing was recorded
    finally:
        conn.close()


def _user_state_summaries(test_dir, username="at_user"):
    path = os.path.join(test_dir, "output", username, "user_state.json")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        state = json.load(f)
    out = {}
    for instance_id, bd in (state.get("instance_id_to_behavioral_data") or {}).items():
        if isinstance(bd, dict) and bd.get("annotation_telemetry"):
            out[instance_id] = bd["annotation_telemetry"]
    return out


class TestTrackTelemetryEnabled:
    """A project that opted in, at full fidelity."""

    PROJECT = "telemetry_enabled_test"

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        server, test_dir = _build_server(self.PROJECT, {
            "enabled": True,
            "fidelity": "events",
            "detection": {"enabled": True},
        })
        request.cls.test_dir = test_dir
        yield server
        server.stop()

    def test_requires_authentication(self, flask_server):
        r = requests.post(
            f"{flask_server.base_url}/api/track_annotation_telemetry",
            json=telemetry_payload())
        assert r.status_code == 401

    def test_rejects_empty_body(self, flask_server):
        s = _authed_session(flask_server, "at_empty")
        r = s.post(f"{flask_server.base_url}/api/track_annotation_telemetry",
                   json={})
        assert r.status_code == 400

    def test_rejects_non_list_sessions(self, flask_server):
        s = _authed_session(flask_server, "at_badtype")
        r = s.post(f"{flask_server.base_url}/api/track_annotation_telemetry",
                   json={"instance_id": "x", "sessions": "nope"})
        assert r.status_code == 400

    def test_records_a_drawing_session(self, flask_server):
        s = _authed_session(flask_server, "at_user")
        r = s.post(f"{flask_server.base_url}/api/track_annotation_telemetry",
                   json=telemetry_payload())
        assert r.status_code == 200
        assert r.json()["sessions_recorded"] == 1

    def test_session_landed_in_sqlite(self, flask_server):
        rows = _sqlite_rows(self.test_dir, self.PROJECT)
        assert rows, "no telemetry session was written to project.sqlite"
        row = [r for r in rows if r["user_id"] == "at_user"][0]
        assert row["schema_name"] == "objects"
        assert row["shapes_added"] == 3

    def test_raw_stream_was_stored_at_events_fidelity(self, flask_server):
        rows = _sqlite_rows(self.test_dir, self.PROJECT)
        row = [r for r in rows if r["user_id"] == "at_user"][0]
        assert row["events_blob"] is not None

    def test_summary_mirrored_into_user_state(self, flask_server):
        summaries = _user_state_summaries(self.test_dir, "at_user")
        assert summaries, "nothing mirrored into user_state.json"
        entry = list(summaries.values())[0]["objects"]
        assert entry["shapes_added"] == 3

    def test_raw_events_never_reach_user_state(self, flask_server):
        """user_state.json is rewritten in full on every annotation save."""
        path = os.path.join(self.test_dir, "output", "at_user", "user_state.json")
        raw = open(path).read()
        assert "events_blob" not in raw
        assert '"t_ms"' not in raw

    def test_latency_is_recomputed_server_side(self, flask_server):
        """The client sends suggest/accept ids, never a latency. A modified
        client therefore cannot report a flattering number."""
        s = _authed_session(flask_server, "at_latency")
        s.post(f"{flask_server.base_url}/api/track_annotation_telemetry",
               json=telemetry_payload(instance_id="telemetry_test_item_02",
                                      shapes=0, accepts=6, accept_latency=150))
        rows = [r for r in _sqlite_rows(self.test_dir, self.PROJECT)
                if r["user_id"] == "at_latency"]
        assert rows
        assert rows[0]["ai_accepted"] == 6
        assert rows[0]["ai_accept_latency_median_ms"] == 150

    def test_screening_flags_are_stored_with_their_evidence(self, flask_server):
        rows = [r for r in _sqlite_rows(self.test_dir, self.PROJECT)
                if r["user_id"] == "at_latency"]
        verdict = json.loads(rows[0]["flags"])
        assert "rubber_stamping" in verdict["flags"]
        # The note is what stops a reviewer reading the flag as a finding.
        assert verdict["notes"]["rubber_stamping"]

    def test_the_read_endpoint_returns_the_summary(self, flask_server):
        s = _authed_session(flask_server, "at_user")
        r = s.get(f"{flask_server.base_url}"
                  f"/api/annotation_telemetry/telemetry_test_item_01")
        assert r.status_code == 200
        assert "objects" in r.json()["annotation_telemetry"]

    def test_a_session_with_no_events_records_nothing(self, flask_server):
        s = _authed_session(flask_server, "at_noevents")
        payload = telemetry_payload()
        payload["sessions"][0]["events"] = []
        r = s.post(f"{flask_server.base_url}/api/track_annotation_telemetry",
                   json=payload)
        assert r.json()["sessions_recorded"] == 0

    def test_a_work_free_page_view_is_not_stored(self, flask_server):
        """
        Found in live use. The manager arms a default tool at construction and
        clears it on teardown, so every page view emits a lone `tool` event —
        which produced a stored session per page view. Session count is the
        denominator of the admin risk score, so those rows diluted every flag
        rate toward zero.
        """
        s = _authed_session(flask_server, "at_pageview")
        payload = telemetry_payload(shapes=0)
        assert [e["action"] for e in payload["sessions"][0]["events"]] == ["tool"]

        r = s.post(f"{flask_server.base_url}/api/track_annotation_telemetry",
                   json=payload)
        assert r.json()["sessions_recorded"] == 0
        assert not [row for row in _sqlite_rows(self.test_dir, self.PROJECT)
                    if row["user_id"] == "at_pageview"]

    def test_inspecting_without_drawing_is_still_stored(self, flask_server):
        """Zoom is not bookkeeping: "examined this image and drew nothing" is a
        real observation about the work."""
        s = _authed_session(flask_server, "at_looker")
        r = s.post(f"{flask_server.base_url}/api/track_annotation_telemetry",
                   json=telemetry_payload(shapes=0, zoom=4.0))
        assert r.json()["sessions_recorded"] == 1

    def test_a_null_instance_id_is_bucketed_not_dropped(self, flask_server):
        """Training-phase items post instance_id null; the work is real and
        `phase` is what identifies it."""
        s = _authed_session(flask_server, "at_phase")
        payload = telemetry_payload()
        payload["instance_id"] = None
        payload["sessions"][0]["instance_id"] = None
        r = s.post(f"{flask_server.base_url}/api/track_annotation_telemetry",
                   json=payload)
        assert r.json()["sessions_recorded"] == 1

        rows = [r_ for r_ in _sqlite_rows(self.test_dir, self.PROJECT)
                if r_["user_id"] == "at_phase"]
        assert rows[0]["instance_id"] == "__phase_page__"
        assert rows[0]["phase"]


class TestTrackTelemetryDisabled:
    """A project that never opted in must record nothing at all."""

    PROJECT = "telemetry_disabled_test"

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        server, test_dir = _build_server(self.PROJECT, {"enabled": False})
        request.cls.test_dir = test_dir
        yield server
        server.stop()

    def test_posting_is_accepted_but_records_nothing(self, flask_server):
        """A stale page may still be posting after the feature was switched
        off, and that is not a client fault — so 200, not 4xx."""
        s = _authed_session(flask_server, "at_off")
        r = s.post(f"{flask_server.base_url}/api/track_annotation_telemetry",
                   json=telemetry_payload())
        assert r.status_code == 200
        assert r.json()["status"] == "disabled"
        assert r.json()["sessions_recorded"] == 0

    def test_nothing_reached_sqlite(self, flask_server):
        assert _sqlite_rows(self.test_dir, self.PROJECT) == []

    def test_the_tracker_script_is_not_served(self, flask_server):
        s = _authed_session(flask_server, "at_off_page")
        html = s.get(f"{flask_server.base_url}/annotate").text
        assert "annotation_telemetry.js" not in html

    def test_no_recording_notice_is_shown(self, flask_server):
        """A project that never opted in must not tell annotators it is
        measuring them."""
        s = _authed_session(flask_server, "at_off_notice")
        html = s.get(f"{flask_server.base_url}/annotate").text
        assert "annotation-telemetry-disclosure" not in html


class TestSummaryFidelity:
    """`summary` fidelity must persist no raw stream."""

    PROJECT = "telemetry_summary_test"

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        server, test_dir = _build_server(self.PROJECT, {
            "enabled": True,
            "fidelity": "summary",
            "store_events": True,   # deliberately contradictory; fidelity wins
        })
        request.cls.test_dir = test_dir
        yield server
        server.stop()

    def test_features_are_still_derived(self, flask_server):
        s = _authed_session(flask_server, "at_sum")
        r = s.post(f"{flask_server.base_url}/api/track_annotation_telemetry",
                   json=telemetry_payload())
        assert r.json()["sessions_recorded"] == 1
        rows = _sqlite_rows(self.test_dir, self.PROJECT)
        assert rows[0]["shapes_added"] == 3

    def test_no_raw_stream_was_stored(self, flask_server):
        rows = _sqlite_rows(self.test_dir, self.PROJECT)
        assert rows[0]["events_blob"] is None
        assert rows[0]["fidelity"] == "summary"


class TestSchemaScoping:
    """The client filters too, but a stale page carries the old config."""

    PROJECT = "telemetry_scoping_test"

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        server, test_dir = _build_server(self.PROJECT, {
            "enabled": True,
            "exclude_schemas": ["objects"],
        })
        request.cls.test_dir = test_dir
        yield server
        server.stop()

    def test_an_excluded_schema_is_refused_server_side(self, flask_server):
        s = _authed_session(flask_server, "at_scope")
        r = s.post(f"{flask_server.base_url}/api/track_annotation_telemetry",
                   json=telemetry_payload(schema="objects"))
        assert r.json()["sessions_recorded"] == 0
        assert _sqlite_rows(self.test_dir, self.PROJECT) == []

    def test_a_schema_outside_the_exclusion_is_recorded(self, flask_server):
        s = _authed_session(flask_server, "at_scope2")
        r = s.post(f"{flask_server.base_url}/api/track_annotation_telemetry",
                   json=telemetry_payload(schema="other_schema"))
        assert r.json()["sessions_recorded"] == 1


class TestAdminRollup:
    PROJECT = "telemetry_admin_test"

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        server, test_dir = _build_server(self.PROJECT, {
            "enabled": True,
            "fidelity": "events",
            "detection": {"enabled": True},
        })
        request.cls.test_dir = test_dir

        s = _authed_session(server, "at_stamper")
        s.post(f"{server.base_url}/api/track_annotation_telemetry",
               json=telemetry_payload(shapes=0, accepts=8, accept_latency=120))
        careful = _authed_session(server, "at_careful")
        careful.post(f"{server.base_url}/api/track_annotation_telemetry",
                     json=telemetry_payload(shapes=4, accepts=0, zoom=4.0))
        yield server
        server.stop()

    def test_requires_the_admin_key(self, flask_server):
        r = requests.get(f"{flask_server.base_url}/admin/api/annotation_process")
        assert r.status_code in (401, 403)

    def test_rollup_ranks_the_flagged_annotator_first(self, flask_server):
        r = requests.get(f"{flask_server.base_url}/admin/api/annotation_process",
                         headers={"X-API-Key": "test_admin_key"})
        assert r.status_code == 200
        data = r.json()
        assert data["enabled"] is True
        assert data["users"], data
        assert data["users"][0]["user_id"] == "at_stamper"
        assert "rubber_stamping" in data["users"][0]["flag_counts"]

    def test_the_careful_annotator_is_not_flagged(self, flask_server):
        r = requests.get(f"{flask_server.base_url}/admin/api/annotation_process",
                         headers={"X-API-Key": "test_admin_key"})
        careful = [u for u in r.json()["users"] if u["user_id"] == "at_careful"]
        assert careful and careful[0]["flag_counts"] == {}

    def test_the_caveat_travels_with_the_ranking(self, flask_server):
        """A risk score surfaced without it will be read as an accusation."""
        r = requests.get(f"{flask_server.base_url}/admin/api/annotation_process",
                         headers={"X-API-Key": "test_admin_key"})
        assert "not proof" in r.json()["caveat"]
