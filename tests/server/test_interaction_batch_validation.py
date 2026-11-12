"""Exercise interaction validation through a running Potato server."""

import json
from pathlib import Path
import uuid

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager as ConfigManager


@pytest.fixture(scope="module")
def tracking_server():
    schemes = [{"annotation_type": "radio", "name": "choice",
                "description": "Choose one", "labels": ["yes", "no"]}]
    with ConfigManager("interaction_batch_validation", schemes) as cfg:
        server = FlaskTestServer(config_file=cfg.config_path)
        assert server.start()
        try:
            yield server, Path(cfg.test_dir) / "output"
        finally:
            server.stop()


@pytest.fixture
def participant(tracking_server):
    server, _ = tracking_server
    username = "tracking_" + uuid.uuid4().hex[:12]
    with requests.Session() as session:
        credentials = {"email": username, "pass": "test-password"}
        session.post(server.base_url + "/register", data=credentials, timeout=10)
        session.post(server.base_url + "/auth", data=credentials, timeout=10)
        assert session.get(server.base_url + "/annotate", timeout=10).status_code == 200
        yield session, username


@pytest.mark.parametrize("fields", [
    {"events": [{"event_type": "click", "timestamp": 101}, None]},
    {"focus_time": []},
    {"focus_time": {"audio": -1}},
    {"scroll_depth": None},
    {"events": [{"timestamp": "invalid"}]},
])
def test_rejected_batch_leaves_the_existing_record_unchanged(
        tracking_server, participant, fields):
    server, _ = tracking_server
    session, _ = participant
    endpoint = server.base_url + "/api/track_interactions"
    assert session.post(endpoint, json={
        "instance_id": "1", "events": [{"event_type": "click", "timestamp": 100}],
        "focus_time": {"audio": 25}, "scroll_depth": 30,
    }, timeout=10).status_code == 200
    record_url = server.base_url + "/api/behavioral_data/1"
    before = session.get(record_url, timeout=10).json()
    response = session.post(endpoint, json={
        "instance_id": "1", "events": [{"event_type": "click", "timestamp": 102}],
        **fields,
    }, timeout=10)
    assert response.status_code == 400, response.text
    assert response.headers["Content-Type"].startswith("application/json")
    assert session.get(record_url, timeout=10).json() == before


def test_non_object_body_is_a_json_error(tracking_server, participant):
    server, _ = tracking_server
    session, _ = participant
    response = session.post(server.base_url + "/api/track_interactions",
                            json=["invalid"], timeout=10)
    assert response.status_code == 400
    assert "error" in response.json()


@pytest.mark.timeout(60)
def test_rounded_scroll_depth_and_valid_events_are_persisted(
        tracking_server, participant):
    server, output = tracking_server
    session, username = participant
    response = session.post(server.base_url + "/api/track_interactions", json={
        "instance_id": "1", "events": [
            {"event_type": "click", "target": "audio", "timestamp": 100},
            {"event_type": "click", "target": "audio", "timestamp": 102},
        ], "focus_time": {"audio": 12.5}, "scroll_depth": 100.078125,
    }, timeout=10)
    assert response.status_code == 200
    assert response.json()["events_recorded"] == 2
    # The first save also imports the active-learning dependencies on a cold
    # server, so allow it more time than the lightweight tracking requests.
    response = session.post(server.base_url + "/updateinstance", json={
        "instance_id": "1", "annotations": {"choice:::yes": "yes"},
    }, timeout=30)
    assert response.status_code == 200, response.text
    saved = json.loads((output / username / "user_state.json").read_text())
    bd = saved["instance_id_to_behavioral_data"]["1"]
    assert bd["scroll_depth_max"] == 100
    assert bd["focus_time_by_element"] == {"audio": 12.5}
    clicks = [event for event in bd["interactions"] if event["event_type"] == "click"]
    assert len(clicks) == 2
