"""
A span prelabel must reach the span manager, not only the page's markup.

The page marked up a pre-annotated span, but ``/api/spans`` returned only the
annotator's saved spans. The span manager never held the prelabel, so it
could not be edited or deleted, and Next saved none of it -- while every other
type saves its untouched prelabel as the annotator's answer (audit 98, D7).
"""

import json
import os

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory

TEXT = "Ada Lovelace met Charles Babbage in London."


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("span_prelabel_api")
    data_path = os.path.join(test_dir, "items.json")
    with open(data_path, "w") as f:
        f.write(json.dumps({"id": "s1", "text": TEXT, "predictions": {
            "people": [{"name": "PERSON", "start": 0, "end": 12},
                       {"name": "PERSON", "start": 17, "end": 32}]}}) + "\n")
        f.write(json.dumps({"id": "s2", "text": "No names here."}) + "\n")
    config = {
        "port": 8000, "server_name": "test",
        "annotation_task_name": "span prelabel api", "task_dir": test_dir,
        "output_annotation_dir": os.path.join(test_dir, "output"),
        "data_files": [data_path],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "user_config": {"allow_all_users": True, "users": []},
        "site_dir": "default",
        "pre_annotation": {"enabled": True, "field": "predictions",
                           "allow_modification": True},
        "annotation_schemes": [{"annotation_type": "span", "name": "people",
                                "description": "Mark every person.",
                                "labels": ["PERSON"]}],
    }
    import yaml
    path = os.path.join(test_dir, "config.yaml")
    with open(path, "w") as f:
        yaml.safe_dump(config, f)
    srv = FlaskTestServer(config_file=path)
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
    assert session.get(f"{server.base_url}/annotate").status_code == 200
    return session


def test_the_span_manager_gets_the_prelabel_spans(server):
    session = _session(server, "span_reader")
    data = session.get(f"{server.base_url}/api/spans/s1").json()
    assert [(s["start"], s["end"], s["label"]) for s in data["spans"]] == [
        (0, 12, "PERSON"), (17, 32, "PERSON")]
    assert TEXT[0:12] == "Ada Lovelace"


def test_the_annotators_own_spans_replace_the_prelabel(server):
    session = _session(server, "span_writer")
    saved = session.post(f"{server.base_url}/updateinstance", json={
        "instance_id": "s1", "annotations": {},
        "span_annotations": [{"schema": "people", "name": "PERSON",
                              "title": "PERSON", "start": 36, "end": 42,
                              "value": "London"}]})
    assert saved.status_code == 200, saved.text[:300]
    data = session.get(f"{server.base_url}/api/spans/s1").json()
    assert [(s["start"], s["end"]) for s in data["spans"]] == [(36, 42)]
