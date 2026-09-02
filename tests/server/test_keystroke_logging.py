"""
Server tests for keystroke logging.

Exercises /api/track_typing against a live Flask instance: authentication, the
config gating, the fidelity contract, and persistence to BOTH destinations
(SQLite for the raw streams, user_state.json for the summary sketch).

The gating tests matter as much as the happy path. A project that has not opted
in must record nothing at all, and a project at `summary` fidelity must persist
no raw keystroke stream.
"""

import json
import os

import pytest
import requests


def typing_payload(instance_id="keystroke_test_item_01", schema="rationale",
                   label="rationale", paste_source=None, blur_ms=None,
                   n_typed=60, final_chars=None):
    """Build a /api/track_typing body.

    Without `paste_source` this is a plain typed session; with it, a paste
    lands at the start and the typed characters follow.
    """
    events = [{"t_ms": 0, "input_type": "focus", "key_class": "unknown",
               "pos": 0, "delta": 0}]
    t, pos = 100, 0

    if blur_ms:
        events.append({"t_ms": t, "input_type": "blur", "key_class": "unknown",
                       "pos": 0, "delta": 0, "meta": {"blur_ms": blur_ms}})
        t += blur_ms

    if paste_source:
        events.append({"t_ms": t, "input_type": "insertFromPaste",
                       "key_class": "unknown", "pos": 0, "delta": 287,
                       "meta": {"paste_source": paste_source}})
        pos = 287
        t += 500

    for i in range(n_typed):
        t += 130 + (i % 7) * 25
        events.append({"t_ms": t, "input_type": "insertText",
                       "key_class": "letter", "pos": pos, "delta": 1})
        pos += 1

    return {
        "instance_id": instance_id,
        "sessions": [{
            "schema_name": schema,
            "label_name": label,
            "instance_id": instance_id,
            "started_at": 1000.0,
            "ended_at": 1100.0,
            "final_chars": final_chars if final_chars is not None else pos,
            "virtual_keyboard": False,
            "events": events,
        }],
    }


def _build_server(test_dir_name, keystroke_config):
    from tests.helpers.flask_test_setup import FlaskTestServer
    from tests.helpers.test_utils import (
        create_test_config, create_test_data_file, create_test_directory)

    test_dir = create_test_directory(test_dir_name)
    data = [{"id": f"keystroke_test_item_{i:02d}",
             "text": f"Passage {i} for keystroke logging tests."}
            for i in range(1, 4)]
    data_file = create_test_data_file(test_dir, data, "keystroke_test_data.jsonl")

    config_file = create_test_config(
        test_dir,
        annotation_schemes=[{
            "name": "rationale",
            "annotation_type": "text",
            "labels": ["rationale"],
            "multiline": True,
            "description": "Explain your reasoning.",
        }],
        data_files=[data_file],
        annotation_task_name=test_dir_name,
        admin_api_key="test_admin_key",
        keystroke_logging=keystroke_config,
    )
    server = FlaskTestServer(config=config_file)
    if not server.start():
        pytest.fail(f"Failed to start Flask test server for {test_dir_name}")
    return server, test_dir


def _authed_session(server, username="ks_user"):
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
            "SELECT * FROM typing_sessions WHERE project = ?", (project,)
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []          # table never created -> nothing was recorded
    finally:
        conn.close()


def _user_state_summaries(test_dir, username="ks_user"):
    path = os.path.join(test_dir, "output", username, "user_state.json")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        state = json.load(f)
    out = {}
    for instance_id, bd in (state.get("instance_id_to_behavioral_data") or {}).items():
        if isinstance(bd, dict) and bd.get("typing_summaries"):
            out[instance_id] = bd["typing_summaries"]
    return out


class TestTrackTypingEnabled:
    """A project that opted in, at full fidelity."""

    PROJECT = "keystroke_enabled_test"

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
        r = requests.post(f"{flask_server.base_url}/api/track_typing",
                          json=typing_payload())
        assert r.status_code == 401

    def test_rejects_empty_body(self, flask_server):
        s = _authed_session(flask_server, "ks_empty")
        r = s.post(f"{flask_server.base_url}/api/track_typing", json={})
        assert r.status_code == 400

    def test_rejects_non_list_sessions(self, flask_server):
        s = _authed_session(flask_server, "ks_badtype")
        r = s.post(f"{flask_server.base_url}/api/track_typing",
                   json={"instance_id": "x", "sessions": "nope"})
        assert r.status_code == 400

    def test_records_a_typed_session(self, flask_server):
        s = _authed_session(flask_server, "ks_user")
        r = s.post(f"{flask_server.base_url}/api/track_typing",
                   json=typing_payload())
        assert r.status_code == 200
        assert r.json()["sessions_recorded"] == 1

    def test_session_landed_in_sqlite(self, flask_server):
        rows = _sqlite_rows(self.test_dir, self.PROJECT)
        assert rows, "no typing_sessions row was written"
        row = next(r for r in rows if r["user_id"] == "ks_user")
        assert row["schema_name"] == "rationale"
        assert row["keystrokes"] > 0
        assert row["events"] is not None, "raw stream missing at fidelity=events"

    def test_summary_mirrored_into_user_state(self, flask_server):
        """The sketch must travel with the annotation, not only sit in SQLite."""
        summaries = _user_state_summaries(self.test_dir, "ks_user")
        assert summaries, "typing_summaries never reached user_state.json"
        fields = next(iter(summaries.values()))
        assert "rationale:::rationale" in fields
        assert fields["rationale:::rationale"]["keystrokes"] > 0

    def test_handler_persists_without_an_annotation_save(self, flask_server):
        """A typing session can end with no /updateinstance ever firing. The
        other track_* handlers never persist; this one must."""
        path = os.path.join(self.test_dir, "output", "ks_user", "user_state.json")
        assert os.path.exists(path)

    def test_phase_stamped_server_side(self, flask_server):
        row = next(r for r in _sqlite_rows(self.test_dir, self.PROJECT)
                   if r["user_id"] == "ks_user")
        assert row["phase"], "phase was not stamped"

    def test_detector_verdict_stored(self, flask_server):
        s = _authed_session(flask_server, "ks_paster")
        s.post(f"{flask_server.base_url}/api/track_typing",
               json=typing_payload(paste_source="external", blur_ms=16000,
                                   n_typed=5, final_chars=292))
        row = next(r for r in _sqlite_rows(self.test_dir, self.PROJECT)
                   if r["user_id"] == "ks_paster")
        verdict = json.loads(row["flags"])
        assert verdict["level"] == "suspect"
        assert "paste_dominant" in verdict["flag_names"]
        assert "offscreen_composition" in verdict["flag_names"]

    def test_quoting_the_passage_is_not_flagged(self, flask_server):
        s = _authed_session(flask_server, "ks_quoter")
        s.post(f"{flask_server.base_url}/api/track_typing",
               json=typing_payload(paste_source="instance_text", blur_ms=16000,
                                   n_typed=5, final_chars=292))
        row = next(r for r in _sqlite_rows(self.test_dir, self.PROJECT)
                   if r["user_id"] == "ks_quoter")
        verdict = json.loads(row["flags"])
        assert verdict["flag_names"] == []
        assert verdict["level"] == "ok"

    def test_sessions_on_one_field_are_merged(self, flask_server):
        """Leaving a field and returning must read as one response."""
        s = _authed_session(flask_server, "ks_merger")
        for _ in range(3):
            s.post(f"{flask_server.base_url}/api/track_typing",
                   json=typing_payload(instance_id="keystroke_test_item_02"))
        summaries = _user_state_summaries(self.test_dir, "ks_merger")
        merged = summaries["keystroke_test_item_02"]["rationale:::rationale"]
        single = 60
        assert merged["keystrokes"] == pytest.approx(single * 3, abs=3)

    def test_read_endpoint_returns_summaries(self, flask_server):
        s = _authed_session(flask_server, "ks_reader")
        s.post(f"{flask_server.base_url}/api/track_typing", json=typing_payload())
        r = s.get(f"{flask_server.base_url}"
                  f"/api/typing_summary/keystroke_test_item_01")
        assert r.status_code == 200
        assert "rationale:::rationale" in r.json()["typing_summaries"]

    def test_read_endpoint_requires_auth(self, flask_server):
        r = requests.get(f"{flask_server.base_url}/api/typing_summary/x")
        assert r.status_code == 401

    @pytest.mark.parametrize("missing", [None, "", "null", "undefined"])
    def test_phase_pages_without_an_instance_id_are_kept(self, flask_server, missing):
        """Regression: free-text answers in the training phase and in
        prestudy/poststudy surveys arrive with no instance id, because the phase
        template leaves it empty. They were being silently dropped. They belong
        in the same "__phase_page__" bucket the rest of the behavioral system
        uses — `phase`/`page` are what actually identify them."""
        user = f"ks_phase_{missing or 'none'}"
        s = _authed_session(flask_server, user)
        payload = typing_payload()
        payload["instance_id"] = missing
        payload["sessions"][0]["instance_id"] = missing

        r = s.post(f"{flask_server.base_url}/api/track_typing", json=payload)
        assert r.status_code == 200
        assert r.json()["sessions_recorded"] == 1

        row = next(x for x in _sqlite_rows(self.test_dir, self.PROJECT)
                   if x["user_id"] == user)
        assert row["instance_id"] == "__phase_page__"
        assert row["keystrokes"] > 0

    def test_sessions_without_events_are_skipped(self, flask_server):
        s = _authed_session(flask_server, "ks_noevents")
        payload = typing_payload()
        payload["sessions"][0]["events"] = []
        r = s.post(f"{flask_server.base_url}/api/track_typing", json=payload)
        assert r.json()["sessions_recorded"] == 0

    def test_malformed_sessions_do_not_break_the_batch(self, flask_server):
        """One bad session must not lose the good ones alongside it."""
        s = _authed_session(flask_server, "ks_mixed")
        payload = typing_payload()
        payload["sessions"] = [
            "not a dict",
            {"label_name": "rationale", "events": []},   # no schema_name
            payload["sessions"][0],
        ]
        r = s.post(f"{flask_server.base_url}/api/track_typing", json=payload)
        assert r.status_code == 200
        assert r.json()["sessions_recorded"] == 1

    def test_admin_writing_process_endpoint(self, flask_server):
        r = requests.get(f"{flask_server.base_url}/admin/api/writing_process",
                         headers={"X-API-Key": "test_admin_key"})
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is True
        assert body["users"]
        assert "caveat" in body

    def test_admin_endpoint_requires_the_key(self, flask_server):
        r = requests.get(f"{flask_server.base_url}/admin/api/writing_process")
        assert r.status_code in (401, 403)


class TestTrackTypingDisabled:
    """A project that never opted in must record nothing."""

    PROJECT = "keystroke_disabled_test"

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        server, test_dir = _build_server(self.PROJECT, {"enabled": False})
        request.cls.test_dir = test_dir
        yield server
        server.stop()

    def test_endpoint_reports_disabled_without_erroring(self, flask_server):
        """A stale page may still be posting; that is not a client fault."""
        s = _authed_session(flask_server, "ks_user")
        r = s.post(f"{flask_server.base_url}/api/track_typing",
                   json=typing_payload())
        assert r.status_code == 200
        assert r.json()["status"] == "disabled"
        assert r.json()["sessions_recorded"] == 0

    def test_nothing_written_to_sqlite(self, flask_server):
        assert _sqlite_rows(self.test_dir, self.PROJECT) == []

    def test_nothing_written_to_user_state(self, flask_server):
        assert _user_state_summaries(self.test_dir, "ks_user") == {}

    def test_admin_panel_reports_disabled(self, flask_server):
        r = requests.get(f"{flask_server.base_url}/admin/api/writing_process",
                         headers={"X-API-Key": "test_admin_key"})
        assert r.json()["enabled"] is False


class TestSummaryFidelity:
    """`fidelity: summary` must compute features but persist no raw stream."""

    PROJECT = "keystroke_summary_test"

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        server, test_dir = _build_server(self.PROJECT, {
            "enabled": True,
            "fidelity": "summary",
            "store_events": True,       # deliberately contradictory; loses
        })
        request.cls.test_dir = test_dir
        yield server
        server.stop()

    def test_session_is_recorded(self, flask_server):
        s = _authed_session(flask_server, "ks_user")
        r = s.post(f"{flask_server.base_url}/api/track_typing",
                   json=typing_payload())
        assert r.json()["sessions_recorded"] == 1

    def test_features_computed(self, flask_server):
        row = _sqlite_rows(self.test_dir, self.PROJECT)[0]
        assert row["keystrokes"] > 0
        assert row["fidelity"] == "summary"

    def test_raw_stream_not_persisted(self, flask_server):
        """store_events: true must not override fidelity: summary."""
        row = _sqlite_rows(self.test_dir, self.PROJECT)[0]
        assert row["events"] is None
