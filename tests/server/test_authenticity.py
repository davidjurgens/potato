"""
Server tests for authenticity paradata.

Exercises /api/track_authenticity and /admin/api/authenticity against a live
Flask instance: authentication, config gating, the replace-not-add contract for
retried posts, the server-side verdict, that no text survives into
user_state.json, the tracker reaching the page with its disclosure, and the
interaction_tracking off switch.
"""

import json
import os

import pytest
import requests


ADMIN_KEY = "test_admin_key"


def _build_server(test_dir_name, **extra_config):
    from tests.helpers.flask_test_setup import FlaskTestServer
    from tests.helpers.test_utils import (
        create_test_config, create_test_data_file, create_test_directory)

    test_dir = create_test_directory(test_dir_name)
    data = [{"id": f"auth_item_{i:02d}", "text": f"Statement number {i} to rate."}
            for i in range(1, 4)]
    data_file = create_test_data_file(test_dir, data, "auth_test_data.jsonl")
    config_file = create_test_config(
        test_dir,
        annotation_schemes=[{
            "name": "agree",
            "annotation_type": "radio",
            "description": "Do you agree?",
            "labels": ["yes", "no"],
        }],
        data_files=[data_file],
        annotation_task_name=test_dir_name,
        admin_api_key=ADMIN_KEY,
        additional_config=extra_config,
    )
    server = FlaskTestServer(config=config_file)
    if not server.start():
        pytest.fail(f"Failed to start Flask test server for {test_dir_name}")
    return server, test_dir


def _authed_session(server, username):
    s = requests.Session()
    s.post(f"{server.base_url}/register",
           data={"email": username, "pass": "pw", "action": "signup"})
    s.post(f"{server.base_url}/auth", data={"email": username, "pass": "pw"})
    s.get(f"{server.base_url}/annotate")
    return s


def _authenticity_records(test_dir, username):
    path = os.path.join(test_dir, "output", username, "user_state.json")
    if not os.path.exists(path):
        return {}, ""
    raw = open(path, encoding="utf-8").read()
    state = json.loads(raw)
    out = {}
    for instance_id, bd in (state.get("instance_id_to_behavioral_data") or {}).items():
        if isinstance(bd, dict) and bd.get("authenticity"):
            out[instance_id] = bd["authenticity"]
    return out, raw


def _post(session, server, **body):
    payload = {"instance_id": "auth_item_01", "view_id": "view1",
               "snapshot": {"elapsed_ms": 30000}, "tracker_version": 1}
    payload.update(body)
    return session.post(f"{server.base_url}/api/track_authenticity", json=payload)


class TestAuthenticityEnabled:
    PROJECT = "authenticity_enabled_test"

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        server, test_dir = _build_server(self.PROJECT, authenticity={
            "enabled": True, "disclosure_text": "Custom notice for this study."})
        request.cls.test_dir = test_dir
        yield server
        server.stop()

    def test_requires_authentication(self, flask_server):
        r = requests.post(f"{flask_server.base_url}/api/track_authenticity",
                          json={"view_id": "v", "snapshot": {"hidden_events": 1}})
        assert r.status_code == 401

    def test_rejects_bad_view_id(self, flask_server):
        s = _authed_session(flask_server, "au_badview")
        assert _post(s, flask_server, view_id="../x").status_code == 400

    def test_rejects_empty_snapshot(self, flask_server):
        s = _authed_session(flask_server, "au_empty")
        assert _post(s, flask_server, snapshot={"junk": 1}).status_code == 400

    def test_page_loads_tracker_with_disclosure(self, flask_server):
        s = _authed_session(flask_server, "au_page")
        html = s.get(f"{flask_server.base_url}/annotate").text
        assert "authenticity_tracker.js" in html
        assert 'id="authenticity-disclosure"' in html
        assert "Custom notice for this study." in html
        # Thresholds are never shipped to the page.
        assert "copy_then_away" not in html

    def test_copy_then_paste_is_recorded_and_flagged(self, flask_server):
        s = _authed_session(flask_server, "au_user")
        snap = {"elapsed_ms": 45000, "item_copy_events": 1, "item_copy_chars": 120,
                "external_paste_events": 1, "max_external_paste_words": 35,
                "max_paste_words_after_item_copy": 35,
                "pasted_text": "SHOULD NEVER BE STORED"}
        r = _post(s, flask_server, snapshot=snap)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

        records, raw = _authenticity_records(self.test_dir, "au_user")
        rec = records["auth_item_01"]
        assert rec["verdict"]["level"] == "suspect"
        assert "copy_then_paste" in rec["verdict"]["flag_names"]
        assert "SHOULD NEVER BE STORED" not in raw
        assert "pasted_text" not in raw

    def test_retried_post_does_not_double_count(self, flask_server):
        s = _authed_session(flask_server, "au_retry")
        for _ in range(3):
            assert _post(s, flask_server, view_id="same",
                         snapshot={"hidden_events": 2, "hidden_ms": 4000,
                                   "elapsed_ms": 20000}).status_code == 200
        records, _ = _authenticity_records(self.test_dir, "au_retry")
        summary = records["auth_item_01"]["summary"]
        assert summary["hidden_events"] == 2
        assert summary["views"] == 1

    def test_phase_page_bucket(self, flask_server):
        s = _authed_session(flask_server, "au_phase")
        assert _post(s, flask_server, instance_id=None,
                     snapshot={"hidden_events": 1}).status_code == 200
        records, _ = _authenticity_records(self.test_dir, "au_phase")
        assert "__phase_page__" in records

    def test_admin_rollup(self, flask_server):
        r = requests.get(f"{flask_server.base_url}/admin/api/authenticity",
                         headers={"X-API-Key": ADMIN_KEY})
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is True
        users = {u["user_id"]: u for u in body["users"]}
        assert users["au_user"]["flag_counts"].get("copy_then_paste") == 1
        assert users["au_user"]["authenticity_risk"] > 0
        assert body["caveat"]

    def test_admin_rollup_requires_key(self, flask_server):
        r = requests.get(f"{flask_server.base_url}/admin/api/authenticity")
        assert r.status_code in (401, 403)


class TestAuthenticityDisabled:
    PROJECT = "authenticity_disabled_test"

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        server, test_dir = _build_server(
            self.PROJECT, interaction_tracking={"enabled": False})
        request.cls.test_dir = test_dir
        yield server
        server.stop()

    def test_endpoint_records_nothing(self, flask_server):
        s = _authed_session(flask_server, "au_off")
        r = _post(s, flask_server, snapshot={"webdriver": True})
        assert r.status_code == 200
        assert r.json()["status"] == "disabled"
        records, _ = _authenticity_records(self.test_dir, "au_off")
        assert records == {}

    def test_page_does_not_load_tracker(self, flask_server):
        s = _authed_session(flask_server, "au_off_page")
        html = s.get(f"{flask_server.base_url}/annotate").text
        assert "authenticity_tracker.js" not in html
        assert "authenticity-disclosure" not in html

    def test_interaction_tracking_switch_reaches_page_and_server(self, flask_server):
        s = _authed_session(flask_server, "au_it_off")
        html = s.get(f"{flask_server.base_url}/annotate").text
        assert "window.interactionTrackingConfig" in html
        assert '"enabled": false' in html
        r = s.post(f"{flask_server.base_url}/api/track_interactions",
                   json={"instance_id": "auth_item_01", "events": [
                       {"event_type": "click", "timestamp": 1, "target": "nav:next"}]})
        assert r.json()["status"] == "disabled"

    def test_admin_rollup_disabled(self, flask_server):
        r = requests.get(f"{flask_server.base_url}/admin/api/authenticity",
                         headers={"X-API-Key": ADMIN_KEY})
        assert r.json()["enabled"] is False
