"""
Server tests for the `phases` key of the paradata trackers.

With `phases: [annotation]`, the consent page must not load the trackers,
and a post from the consent phase (a cached page, an old tab) must be
answered 2xx and stored nowhere. A phase name from `phases.order` selects one
page. The final flush of the last item, which arrives after the annotator
moved on, still counts as annotation. Without the key, the trackers load on
every page as before.
"""

import json
import os
import re

import pytest
import requests


ADMIN_KEY = "test_admin_key"
CONSENT = [{"name": "agree", "annotation_type": "radio",
            "description": "Do you agree?", "labels": ["Yes", "No"]}]
EXIT = [{"name": "fun", "annotation_type": "radio",
         "description": "Was it fun?", "labels": ["Yes", "No"]}]
CONSENT_FIRST = {
    "order": ["consent", "annotation"],
    "consent": {"type": "consent", "file": "consent.json"},
}


def _build_server(test_dir_name, phases=CONSENT_FIRST, n_items=3, **trackers):
    from tests.helpers.flask_test_setup import FlaskTestServer
    from tests.helpers.test_utils import (
        create_test_config, create_test_data_file, create_test_directory)

    test_dir = create_test_directory(test_dir_name)
    data = [{"id": f"tp_item_{i:02d}", "text": f"Statement number {i}."}
            for i in range(1, n_items + 1)]
    data_file = create_test_data_file(test_dir, data, "tp_data.jsonl")
    for name, content in (("consent.json", CONSENT), ("exit.json", EXIT)):
        with open(os.path.join(test_dir, name), "w") as f:
            json.dump(content, f)
    config_file = create_test_config(
        test_dir,
        annotation_schemes=[{
            "name": "rationale", "annotation_type": "text",
            "labels": ["rationale"], "description": "Explain your answer.",
        }],
        data_files=[data_file],
        annotation_task_name=test_dir_name,
        admin_api_key=ADMIN_KEY,
        additional_config={"phases": phases, **trackers},
    )
    server = FlaskTestServer(config=config_file)
    if not server.start():
        pytest.fail(f"Failed to start Flask test server for {test_dir_name}")
    return server, test_dir


def _consent_page(server, username, route="consent"):
    """A logged-in session that stands on the consent page, and its HTML."""
    s = requests.Session()
    s.post(f"{server.base_url}/register",
           data={"email": username, "pass": "pw", "action": "signup"})
    s.post(f"{server.base_url}/auth", data={"email": username, "pass": "pw"})
    r = s.get(f"{server.base_url}/{route}")
    assert r.status_code == 200
    assert "Do you agree?" in r.text
    return s, r.text


def _give_consent(server, s, route="consent"):
    s.post(f"{server.base_url}/updateinstance",
           json={"instance_id": "__phase_page__",
                 "annotations": {"agree:Yes": "Yes"}, "span_annotations": []})
    s.post(f"{server.base_url}/{route}", data={})
    html = s.get(f"{server.base_url}/annotate").text
    assert "Explain your answer." in html, "did not reach the annotation page"
    return html


def _interaction_config(html):
    """The JSON the page hands to interaction_tracker.js."""
    m = re.search(r"window\.interactionTrackingConfig = (\{.*?\});", html)
    assert m, "interaction tracker config missing"
    return json.loads(m.group(1))


def _user_state(test_dir, username):
    path = os.path.join(test_dir, "output", username, "user_state.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _behavioral(test_dir, username, key):
    state = _user_state(test_dir, username)
    return {iid: bd[key]
            for iid, bd in (state.get("instance_id_to_behavioral_data") or {}).items()
            if isinstance(bd, dict) and bd.get(key)}


def _typing_rows(test_dir, username):
    import sqlite3
    db = os.path.join(test_dir, "project.sqlite")
    if not os.path.exists(db):
        return []
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT * FROM typing_sessions WHERE user_id = ?",
                            (username,)).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def _typing_payload():
    events = [{"t_ms": 0, "input_type": "focus", "key_class": "unknown",
               "pos": 0, "delta": 0}]
    events += [{"t_ms": 100 + 150 * i, "input_type": "insertText",
                "key_class": "letter", "pos": i, "delta": 1} for i in range(30)]
    return {"instance_id": "tp_item_01", "sessions": [{
        "schema_name": "rationale", "label_name": "rationale",
        "instance_id": "tp_item_01", "started_at": 1000.0, "ended_at": 1100.0,
        "final_chars": 30, "virtual_keyboard": False, "events": events}]}


def _authenticity(s, server, instance_id, view_id):
    return s.post(f"{server.base_url}/api/track_authenticity", json={
        "instance_id": instance_id, "view_id": view_id, "final": True,
        "snapshot": {"hidden_events": 2}, "tracker_version": 1})


class TestTrackersLimitedToAnnotation:
    PROJECT = "tracker_phases_limited_test"

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        on_annotation = {"enabled": True, "phases": ["annotation"]}
        server, test_dir = _build_server(
            self.PROJECT,
            authenticity=on_annotation,
            keystroke_logging=on_annotation,
            annotation_telemetry=on_annotation,
            interaction_tracking=on_annotation,
        )
        request.cls.test_dir = test_dir
        yield server
        server.stop()

    def test_consent_page_loads_no_tracker_but_keeps_the_notices(self, flask_server):
        _, html = _consent_page(flask_server, "tp_page")
        for marker in ("authenticity_tracker.js", "window.authenticityConfig",
                       "keystroke_tracker.js", "window.keystrokeConfig",
                       "annotation_telemetry.js", "window.annotationTelemetryConfig"):
            assert marker not in html, marker
        # The participant reads what will be recorded before consenting.
        assert 'id="authenticity-disclosure"' in html
        assert 'id="keystroke-disclosure"' in html
        # The interaction tracker stays, switched to its timing-only mode, and
        # sends nothing at all: its flush when "next" is clicked reaches the
        # server after the phase changed, where annotation's phases would
        # keep it.
        cfg = _interaction_config(html)
        assert cfg["enabled"] is False
        assert cfg["record"] is False

    def test_annotation_page_loads_the_trackers(self, flask_server):
        s, _ = _consent_page(flask_server, "tp_annot")
        html = _give_consent(flask_server, s)
        assert "authenticity_tracker.js" in html
        assert "keystroke_tracker.js" in html
        cfg = _interaction_config(html)
        assert cfg["enabled"] is True
        assert cfg.get("record", True) is True

    def test_authenticity_post_during_consent_is_dropped(self, flask_server):
        s, _ = _consent_page(flask_server, "tp_au")
        r = s.post(f"{flask_server.base_url}/api/track_authenticity", json={
            "instance_id": None, "view_id": "v1", "final": True,
            "snapshot": {"hidden_events": 2, "webdriver": True},
            "tracker_version": 1})
        assert 200 <= r.status_code < 300
        assert r.json()["status"] == "phase_not_tracked"
        assert _behavioral(self.test_dir, "tp_au", "authenticity") == {}
        users = requests.get(f"{flask_server.base_url}/admin/api/authenticity",
                             headers={"X-API-Key": ADMIN_KEY}).json()["users"]
        assert "tp_au" not in {u["user_id"] for u in users}

        # Control: the same post is stored once the participant has consented.
        _give_consent(flask_server, s)
        r = _authenticity(s, flask_server, "tp_item_01", "v2")
        assert r.json()["status"] == "ok"
        assert "tp_item_01" in _behavioral(self.test_dir, "tp_au", "authenticity")

    def test_typing_post_during_consent_is_dropped(self, flask_server):
        s, _ = _consent_page(flask_server, "tp_ks")
        r = s.post(f"{flask_server.base_url}/api/track_typing",
                   json=_typing_payload())
        assert 200 <= r.status_code < 300
        assert r.json()["status"] == "phase_not_tracked"
        assert r.json()["sessions_recorded"] == 0
        assert _behavioral(self.test_dir, "tp_ks", "typing_summaries") == {}
        assert _typing_rows(self.test_dir, "tp_ks") == []

        _give_consent(flask_server, s)
        r = s.post(f"{flask_server.base_url}/api/track_typing",
                   json=_typing_payload())
        assert r.json()["sessions_recorded"] == 1

    def test_telemetry_post_during_consent_is_dropped(self, flask_server):
        s, _ = _consent_page(flask_server, "tp_at")
        r = s.post(f"{flask_server.base_url}/api/track_annotation_telemetry",
                   json={"instance_id": None, "sessions": [{
                       "schema_name": "rationale", "instance_id": None,
                       "started_at": 1000.0, "ended_at": 1001.0, "events": []}]})
        assert 200 <= r.status_code < 300
        assert r.json()["status"] == "phase_not_tracked"
        assert r.json()["sessions_recorded"] == 0

    def test_interaction_post_during_consent_keeps_nothing(self, flask_server):
        # Not even the timing marks: time per item is measured on items only.
        s, _ = _consent_page(flask_server, "tp_it")
        r = s.post(f"{flask_server.base_url}/api/track_interactions", json={
            "instance_id": None, "events": [
                {"event_type": "click", "timestamp": 1, "target": "agree"},
                {"event_type": "navigation", "timestamp": 2,
                 "target": "instance_load"}]})
        assert 200 <= r.status_code < 300
        assert r.json()["events_recorded"] == 0
        assert _behavioral(self.test_dir, "tp_it", "interactions") == {}


class TestPhaseNamesAndTheLastItem:
    """A phase name selects one page; the last item's final flush, which
    arrives after "next" moved the annotator to the survey, is kept."""

    PROJECT = "tracker_phases_names_test"

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        server, test_dir = _build_server(
            self.PROJECT,
            phases={
                "order": ["intake", "annotation", "exit"],
                "intake": {"type": "consent", "file": "consent.json"},
                "exit": {"type": "poststudy", "file": "exit.json"},
            },
            n_items=1,
            authenticity={"enabled": True, "phases": ["annotation"]},
            keystroke_logging={"enabled": True, "phases": ["intake"]},
        )
        request.cls.test_dir = test_dir
        yield server
        server.stop()

    def test_phase_name_selects_the_page(self, flask_server):
        _, html = _consent_page(flask_server, "tp_name")
        assert "keystroke_tracker.js" in html
        assert "authenticity_tracker.js" not in html

    def test_final_flush_of_the_last_item_is_kept(self, flask_server):
        s, _ = _consent_page(flask_server, "tp_last")
        _give_consent(flask_server, s)
        s.post(f"{flask_server.base_url}/updateinstance",
               json={"instance_id": "tp_item_01",
                     "annotations": {"rationale:::rationale": "Because."}})
        s.post(f"{flask_server.base_url}/annotate",
               data={"action": "next_instance"})
        html = s.get(f"{flask_server.base_url}/poststudy").text
        assert "Was it fun?" in html, "did not reach the exit survey"
        assert "authenticity_tracker.js" not in html

        r = _authenticity(s, flask_server, "tp_item_01", "last")
        assert r.json()["status"] == "ok"
        assert "tp_item_01" in _behavioral(self.test_dir, "tp_last", "authenticity")

        r = _authenticity(s, flask_server, None, "survey")
        assert r.json()["status"] == "phase_not_tracked"
        assert "__phase_page__" not in _behavioral(
            self.test_dir, "tp_last", "authenticity")


class TestAdminWhenAnnotationIsNotTracked:
    """Phases that leave out annotation must not make the admin read the
    absent annotation data as suspicious (the PR 176 follow-up: a switch that
    stops recording must not turn ordinary work into flags)."""

    PROJECT = "tracker_phases_admin_test"

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        server, test_dir = _build_server(
            self.PROJECT,
            authenticity={"enabled": True, "phases": ["consent"]},
            interaction_tracking={"enabled": True, "phases": ["consent"]},
        )
        request.cls.test_dir = test_dir
        yield server
        server.stop()

    def test_annotated_items_are_not_paradata_missing(self, flask_server):
        s, _ = _consent_page(flask_server, "tp_adm")
        _give_consent(flask_server, s)
        t0 = 1_700_000_100_000
        s.post(f"{flask_server.base_url}/api/track_interactions",
               json={"instance_id": "tp_item_01", "events": [
                   {"event_type": "navigation", "target": "instance_load",
                    "timestamp": t0 / 1000, "client_timestamp": t0},
                   {"event_type": "save", "target": "instance:tp_item_01",
                    "timestamp": (t0 + 12000) / 1000,
                    "client_timestamp": t0 + 12000}]})
        r = s.post(f"{flask_server.base_url}/updateinstance",
                   json={"instance_id": "tp_item_01",
                         "annotations": {"rationale:::rationale": "Because."}})
        assert r.status_code == 200, r.text

        body = requests.get(f"{flask_server.base_url}/admin/api/authenticity",
                            headers={"X-API-Key": ADMIN_KEY}).json()
        users = {u["user_id"]: u for u in body["users"]}
        assert "paradata_missing" not in users["tp_adm"]["flag_counts"]

        body = requests.get(
            f"{flask_server.base_url}/admin/api/behavioral_analytics",
            headers={"X-API-Key": ADMIN_KEY}).json()
        assert body["aggregate_stats"]["interaction_tracking_enabled"] is False
        row = {u["user_id"]: u for u in body["users"]}["tp_adm"]
        assert row["low_interaction_rate"] is None
        assert row["no_scroll_rate"] is None


class TestTrackersWithoutPhases:
    """No `phases` key: the trackers load on the consent page, as before."""

    PROJECT = "tracker_phases_default_test"

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        server, test_dir = _build_server(
            self.PROJECT,
            authenticity={"enabled": True},
            keystroke_logging={"enabled": True},
        )
        request.cls.test_dir = test_dir
        yield server
        server.stop()

    def test_consent_page_loads_the_trackers(self, flask_server):
        _, html = _consent_page(flask_server, "tp_default")
        assert "authenticity_tracker.js" in html
        assert "keystroke_tracker.js" in html
        cfg = _interaction_config(html)
        assert cfg["enabled"] is True
        assert cfg.get("record", True) is True

    def test_consent_phase_posts_are_stored(self, flask_server):
        s, _ = _consent_page(flask_server, "tp_default_post")
        r = _authenticity(s, flask_server, None, "v1")
        assert r.json()["status"] == "ok"
        assert "__phase_page__" in _behavioral(
            self.test_dir, "tp_default_post", "authenticity")
        r = s.post(f"{flask_server.base_url}/api/track_interactions", json={
            "instance_id": None, "events": [
                {"event_type": "click", "timestamp": 1, "target": "agree"}]})
        assert r.json()["events_recorded"] == 1
