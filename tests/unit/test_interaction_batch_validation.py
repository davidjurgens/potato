"""Reject a malformed batch before any of its events reach user state."""

import copy

from flask import Flask
import pytest

from potato import routes
from potato.interaction_tracking import BehavioralData, InteractionEvent
from potato.phase import UserPhase
from potato.user_state_management import InMemoryUserState


@pytest.fixture
def tracking(monkeypatch):
    state = InMemoryUserState("tracking_test", max_assignments=2)
    state.current_phase_and_page = (UserPhase.ANNOTATION, "annotation")
    # Rejection must also leave an existing bucket intact.
    state.instance_id_to_behavioral_data["item1"] = BehavioralData(
        instance_id="item1",
        interactions=[InteractionEvent("click", 100.0, "audio", "item1")],
        focus_time_by_element={"audio": 25},
        scroll_depth_max=30.0,
    )
    monkeypatch.setattr(routes, "get_user_state", lambda username: state)
    monkeypatch.setattr(routes, "config", {})
    app = Flask(__name__)
    app.config.update(SECRET_KEY="test-secret", TESTING=True,
                      PROPAGATE_EXCEPTIONS=False)
    app.add_url_rule("/api/track_interactions", view_func=routes.track_interactions,
                     methods=["POST"])
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "tracking_test"
    return client, state


@pytest.mark.parametrize("payload", [
    None, [], ["event"], "event", 1, True,
])
def test_body_must_be_an_object(tracking, payload):
    client, state = tracking
    before = copy.deepcopy(state.instance_id_to_behavioral_data)
    response = client.post("/api/track_interactions", json=payload)
    assert response.status_code == 400
    assert state.instance_id_to_behavioral_data == before


@pytest.mark.parametrize("fields", [
    {"events": None},
    {"events": {}},
    {"events": "click"},
    {"events": [None]},
    {"events": [1]},
    {"events": [{"event_type": "click", "timestamp": 101}, None]},
    {"events": [{"event_type": []}]},
    {"events": [{"target": {}}]},
    {"events": [{"metadata": []}]},
    {"events": [{"metadata": None}]},
    {"events": [{"timestamp": "101"}]},
    {"events": [{"timestamp": True}]},
    {"events": [{"timestamp": -1}]},
    {"events": [{"timestamp": float("nan")}]},
    {"events": [{"client_timestamp": float("inf")}]},
    {"events": [{"client_timestamp": 10**400}]},
    {"focus_time": None},
    {"focus_time": []},
    {"focus_time": {"audio": "25"}},
    {"focus_time": {"audio": True}},
    {"focus_time": {"audio": -1}},
    {"focus_time": {"audio": float("nan")}},
    {"focus_time": {"audio": float("inf")}},
    {"focus_time": {"audio": 10**400}},
    {"scroll_depth": None},
    {"scroll_depth": "50"},
    {"scroll_depth": True},
    {"scroll_depth": float("nan")},
    {"scroll_depth": float("inf")},
    {"scroll_depth": 10**400},
])
@pytest.mark.parametrize("instance_id", ["item1", "item2"])
def test_invalid_batch_is_rejected_without_partial_mutation(
        tracking, fields, instance_id):
    client, state = tracking
    before = copy.deepcopy(state.instance_id_to_behavioral_data)
    payload = {"instance_id": instance_id,
               "events": [{"event_type": "click", "timestamp": 101}], **fields}
    response = client.post("/api/track_interactions", json=payload)
    assert response.status_code == 400
    assert response.is_json
    assert state.instance_id_to_behavioral_data == before


@pytest.mark.parametrize("depth, expected", [
    (100.078125, 100.0), (-0.5, 0.0), (62.5, 62.5),
])
def test_scroll_rounding_keeps_the_rest_of_the_batch(tracking, depth, expected):
    client, state = tracking
    response = client.post("/api/track_interactions", json={
        "instance_id": "item2",
        "events": [{"event_type": "click", "timestamp": 101}],
        "focus_time": {"audio": 12.5}, "scroll_depth": depth,
    })
    assert response.status_code == 200
    assert response.json["events_recorded"] == 1
    bd = state.instance_id_to_behavioral_data["item2"]
    assert len(bd.interactions) == 1
    assert bd.focus_time_by_element == {"audio": 12.5}
    assert bd.scroll_depth_max == expected


def test_missing_optional_event_fields_keep_their_defaults(tracking):
    client, state = tracking
    response = client.post("/api/track_interactions", json={
        "instance_id": None,
        "events": [{}, {"timestamp": None, "client_timestamp": None}],
    })
    assert response.status_code == 200
    assert response.json["events_recorded"] == 2
    bd = state.instance_id_to_behavioral_data["__phase_page__"]
    assert all(event.timestamp > 0 for event in bd.interactions)
    assert all(event.metadata == {} for event in bd.interactions)


def test_tracking_disabled_still_keeps_only_content_free_timing(tracking, monkeypatch):
    monkeypatch.setattr(routes, "config", {"interaction_tracking": {"enabled": False}})
    client, state = tracking
    response = client.post("/api/track_interactions", json={
        "instance_id": "item2",
        "events": [
            {"event_type": "navigation", "target": "instance_load", "timestamp": 100},
            {"event_type": "activity", "target": "field", "timestamp": 105,
             "metadata": {"key": "q"}},
            {"event_type": "click", "timestamp": 108},
            {"event_type": "save", "timestamp": 110},
        ],
        "focus_time": {"audio": 25}, "scroll_depth": 100.078125,
    })
    assert response.status_code == 200
    assert response.json["events_recorded"] == 3
    bd = state.instance_id_to_behavioral_data["item2"]
    assert [event.event_type for event in bd.interactions] == [
        "navigation", "activity", "save"]
    assert bd.interactions[1].target == ""
    assert bd.interactions[1].metadata == {}
    assert bd.total_time_ms == 10000
    assert bd.focus_time_by_element == {}
    assert bd.scroll_depth_max == 0


def test_authentication_is_checked_before_the_payload(tracking):
    client, state = tracking
    before = copy.deepcopy(state.instance_id_to_behavioral_data)
    with client.session_transaction() as session:
        session.clear()
    response = client.post("/api/track_interactions", json=["invalid"])
    assert response.status_code == 401
    assert state.instance_id_to_behavioral_data == before


@pytest.mark.parametrize("instance_id", [["item1"], {"id": "item1"}, True, 1.5])
def test_instance_id_must_be_a_scalar_id(tracking, instance_id):
    """A list or object id was str()'d into a new bucket keyed by its repr."""
    client, state = tracking
    before = copy.deepcopy(state.instance_id_to_behavioral_data)
    response = client.post("/api/track_interactions", json={
        "instance_id": instance_id,
        "events": [{"event_type": "click", "timestamp": 101}]})
    assert response.status_code == 400
    assert state.instance_id_to_behavioral_data == before


@pytest.mark.parametrize("instance_id", ["item1", 7, None])
def test_string_int_and_missing_ids_are_accepted(tracking, instance_id):
    client, _state = tracking
    response = client.post("/api/track_interactions", json={
        "instance_id": instance_id,
        "events": [{"event_type": "click", "timestamp": 101}]})
    assert response.status_code == 200, response.get_json()
