"""
A trained model's relations, chains and events reach the link widgets.

hf-relation predicts spans and the links between them in one canonical
answer under the link scheme's name. The widgets read spans from
``/api/spans`` and links or events from ``/api/links`` and ``/api/events``,
which returned only the annotator's own records. Now the prediction's spans
are span prelabels for the ``span_schema``, with ids the predicted links and
events refer to, while the annotator has no spans of their own on the item.
"""

import json
import os

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory

TEXT = "alice works at acme ."
SPANS = [{"start": 0, "end": 5, "label": "PER"}, {"start": 15, "end": 19, "label": "ORG"},
         {"start": 6, "end": 11, "label": "TRIG"}]
ITEM = {"id": "d1", "text": TEXT, "predictions": {
    "rels": {"spans": SPANS[:2], "links": [{"type": "WORKS_AT", "spans": [0, 1],
                                            "directed": True}]},
    "coref": {"spans": SPANS[:2], "clusters": [{"type": "ENTITY", "spans": [0, 1]}]},
    "events": {"spans": SPANS, "events": [{"type": "JOB", "trigger": 2, "arguments": [
        {"role": "worker", "span": 0}]}]}}}


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("link_prelabel")
    data_path = os.path.join(test_dir, "items.json")
    with open(data_path, "w") as f:
        f.write(json.dumps(ITEM) + "\n")
        f.write(json.dumps({"id": "d2", "text": "nothing predicted ."}) + "\n")
    config = {
        "port": 8000, "server_name": "test", "annotation_task_name": "link prelabel",
        "task_dir": test_dir, "output_annotation_dir": os.path.join(test_dir, "output"),
        "data_files": [data_path],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "user_config": {"allow_all_users": True, "users": []}, "site_dir": "default",
        "pre_annotation": {"enabled": True, "field": "predictions",
                           "allow_modification": True},
        "annotation_schemes": [
            {"annotation_type": "span", "name": "ents", "description": "Entities",
             "labels": ["PER", "ORG", "TRIG"]},
            {"annotation_type": "span_link", "name": "rels", "description": "Relations",
             "span_schema": "ents",
             "link_types": [{"name": "WORKS_AT", "directed": True, "color": "#dc2626"}]},
            {"annotation_type": "coreference", "name": "coref", "description": "Chains",
             "span_schema": "ents"},
            {"annotation_type": "event_annotation", "name": "events", "description": "Events",
             "span_schema": "ents",
             "event_types": [{"type": "JOB", "trigger_labels": ["TRIG"],
                              "arguments": [{"role": "worker", "entity_types": ["PER"]}]}]},
        ],
    }
    config_path = os.path.join(test_dir, "config.yaml")
    with open(config_path, "w") as f:
        yaml.safe_dump(config, f)
    srv = FlaskTestServer(config_file=config_path)
    if not srv.start():
        cleanup_test_directory(test_dir)
        pytest.fail("Failed to start server")
    yield srv
    srv.stop()
    cleanup_test_directory(test_dir)


def _session(server, username):
    session = requests.Session()
    session.post(f"{server.base_url}/register",
                 data={"email": username, "pass": "pw", "action": "signup"})
    session.post(f"{server.base_url}/auth",
                 data={"email": username, "pass": "pw", "action": "login"})
    session.get(f"{server.base_url}/annotate")
    return session


def test_predicted_links_refer_to_predicted_span_ids(server):
    session = _session(server, "link_reader")
    spans = session.get(f"{server.base_url}/api/spans/d1").json()["spans"]
    by_offsets = {(s["start"], s["end"]): s for s in spans}
    assert {(0, 5), (15, 19), (6, 11)} <= set(by_offsets)
    assert all(s.get("prelabel") for s in spans)
    links = {l["schema"]: l for l in
             session.get(f"{server.base_url}/api/links/d1").json()["links"]}
    rel = links["rels"]
    assert rel["prelabel"] is True and rel["direction"] == "directed"
    assert rel["span_ids"] == [by_offsets[(0, 5)]["id"], by_offsets[(15, 19)]["id"]]
    assert rel["properties"]["color"] == "#dc2626"
    assert links["coref"]["link_type"] == "ENTITY"
    (event,) = session.get(f"{server.base_url}/api/events/d1").json()["events"]
    assert event["trigger_span_id"] == by_offsets[(6, 11)]["id"]
    assert event["arguments"] == [{"role": "worker", "span_id": by_offsets[(0, 5)]["id"],
                                   "text": "alice"}]
    # What the event list shows; without it the trigger read "?".
    assert event["properties"]["trigger_text"] == "works"
    assert rel["properties"]["span_texts"] == ["alice", "acme"]


def test_an_item_without_predictions_has_no_prelabel_links(server):
    session = _session(server, "plain_reader")
    assert session.get(f"{server.base_url}/api/links/d2").json()["links"] == []


def test_the_annotators_own_spans_replace_the_prediction(server):
    session = _session(server, "own_spans")
    response = session.post(f"{server.base_url}/updateinstance", json={
        "type": "span", "schema": "ents", "instance_id": "d1",
        "state": [{"name": "PER", "start": 0, "end": 5, "title": "PER", "value": 1}]})
    assert response.ok, response.text
    assert session.get(f"{server.base_url}/api/links/d1").json()["links"] == []
    assert session.get(f"{server.base_url}/api/events/d1").json()["events"] == []


def test_moving_on_from_the_prediction_takes_it_over(server):
    """An annotator who deleted every predicted span and moved on has
    answered "nothing here": the prediction is not offered again."""
    session = _session(server, "emptied_it")
    assert session.get(f"{server.base_url}/api/spans/d1").json()["spans"]
    response = session.post(f"{server.base_url}/updateinstance", json={
        "instance_id": "d1", "annotations": {}, "span_annotations": [],
        "prelabels_reviewed": True})
    assert response.ok, response.text
    assert session.get(f"{server.base_url}/api/spans/d1").json()["spans"] == []
    assert session.get(f"{server.base_url}/api/links/d1").json()["links"] == []
    assert session.get(f"{server.base_url}/api/events/d1").json()["events"] == []
    page = session.get(f"{server.base_url}/annotate").text
    assert 'data-annotation-id="pred_ents_' not in page and "pred_ents_0_5_PER" not in page
    # Another annotator still gets the prediction.
    assert _session(server, "fresh_eyes").get(
        f"{server.base_url}/api/links/d1").json()["links"]


def test_storing_a_link_takes_the_prediction_over(server):
    session = _session(server, "linked_one")
    response = session.post(f"{server.base_url}/updateinstance", json={
        "instance_id": "d1", "annotations": {},
        "link_annotations": [{"schema": "coref", "link_type": "ENTITY", "id": "c1",
                              "span_ids": ["pred_ents_0_5_PER", "pred_ents_15_19_ORG"]}]})
    assert response.ok, response.text
    assert [l["id"] for l in session.get(
        f"{server.base_url}/api/links/d1").json()["links"]] == ["c1"]
    assert session.get(f"{server.base_url}/api/events/d1").json()["events"] == []
