"""
Write-back end to end: an item ingested from Langfuse, two annotators' saves
through /updateinstance, and the score arriving at a fake Langfuse.
"""

import os
import time

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    cleanup_test_directory, create_test_config, create_test_data_file,
    create_test_directory,
)
from tests.unit.test_trace_writeback import FakeService

ADMIN_KEY = "writeback-admin-key"
SCHEME = {"annotation_type": "radio", "name": "outcome", "description": "Did the agent succeed?",
          "labels": ["success", "failure"]}


@pytest.fixture
def setup(monkeypatch):
    from potato.trace_ingestion.writeback import clear_queue
    clear_queue()
    fake = FakeService()
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    test_dir = create_test_directory("trace_writeback_server")
    data_file = create_test_data_file(test_dir, [
        {"id": "langfuse_tr-1", "text": "Book a table",
         "metadata": {"source": "langfuse", "original_id": "tr-1"}},
        {"id": "plain_1", "text": "Not a trace"}])
    port = find_free_port(preferred_port=9898)
    config_file = create_test_config(test_dir, [SCHEME], data_files=[data_file], port=port,
                                     additional_config={
                                         "admin_api_key": ADMIN_KEY,
                                         "max_annotations_per_item": 2,
                                         "trace_ingestion": {
                                             "enabled": True, "api_key": "ingest-key",
                                             "writeback": {"langfuse": {"host": fake.url}}}})
    server = FlaskTestServer(port=port, debug=False, config_file=config_file)
    if not server.start():
        pytest.fail("Failed to start server")
    yield server, fake
    server.stop()
    clear_queue()
    fake.close()
    cleanup_test_directory(test_dir)


def _annotate(server, user, instance_id, label):
    s = requests.Session()
    s.post(f"{server.base_url}/register", data={"email": user, "pass": "pw"})
    s.post(f"{server.base_url}/auth", data={"email": user, "pass": "pw"})
    s.get(f"{server.base_url}/annotate")
    r = s.post(f"{server.base_url}/updateinstance", json={
        "instance_id": instance_id, "annotations": {f"outcome:{label}": "true"}})
    assert r.status_code == 200, r.text


def _wait_for(fake, n, seconds=10):
    deadline = time.time() + seconds
    while time.time() < deadline and len(fake.requests) < n:
        time.sleep(0.1)
    return fake.requests


def test_two_answers_reach_langfuse_as_one_score(setup):
    server, fake = setup
    _annotate(server, "ann1", "langfuse_tr-1", "success")
    time.sleep(0.5)
    assert fake.requests == []  # one annotator is not enough
    _annotate(server, "ann2", "langfuse_tr-1", "success")
    _annotate(server, "ann1", "plain_1", "failure")  # not a trace: never sent
    [request] = _wait_for(fake, 1)
    [score] = request["body"]
    assert score["traceId"] == "tr-1"
    assert (score["name"], score["value"]) == ("potato.outcome", "success")
    assert score["comment"] == "Potato: 2 of 2 annotator(s) chose success"
    status = requests.get(f"{server.base_url}/admin/api/trace_writeback",
                          headers={"X-API-Key": ADMIN_KEY}).json()
    assert status["enabled"] is True
    assert status["counts"] == {"pending": 0, "sent": 1, "failed": 0, "held": 0}
    time.sleep(0.5)
    assert len(fake.requests) == 1


@pytest.fixture
def review_setup(monkeypatch):
    """The potato-skill agent's repro: num_annotators_per_item, e-mail
    usernames, a text scheme beside the radio, and a split vote."""
    from potato.trace_ingestion.writeback import clear_queue
    clear_queue()
    fake = FakeService()
    monkeypatch.setenv("LF_PUB", "pk-test")
    monkeypatch.setenv("LF_SEC", "sk-test")
    test_dir = create_test_directory("trace_writeback_review")
    data_file = create_test_data_file(test_dir, [
        {"id": f"t{n}", "text": f"Trace {n}",
         "metadata": {"source": "langfuse", "original_id": f"tr-{n}"}} for n in (1, 2)])
    port = find_free_port(preferred_port=9899)
    config_file = create_test_config(
        test_dir,
        [{"annotation_type": "radio", "name": "verdict", "description": "Verdict",
          "labels": ["pass", "fail"]},
         {"annotation_type": "text", "name": "note", "description": "Note"}],
        data_files=[data_file], port=port,
        additional_config={
            "admin_api_key": ADMIN_KEY, "num_annotators_per_item": 2,
            "trace_ingestion": {"enabled": True, "api_key": "k", "writeback": {
                "trigger": "fully_annotated", "min_annotators": 2,
                "langfuse": {"host": fake.url, "public_key_env": "LF_PUB",
                             "secret_key_env": "LF_SEC"}}}})
    server = FlaskTestServer(port=port, debug=False, config_file=config_file)
    if not server.start():
        pytest.fail("Failed to start server")
    yield server, fake
    server.stop()
    clear_queue()
    fake.close()
    cleanup_test_directory(test_dir)


def _save(server, user, instance_id, verdict, note):
    s = requests.Session()
    s.post(f"{server.base_url}/register", data={"email": user, "pass": "pw"})
    s.post(f"{server.base_url}/auth", data={"email": user, "pass": "pw"})
    s.get(f"{server.base_url}/annotate")
    r = s.post(f"{server.base_url}/updateinstance", json={
        "instance_id": instance_id,
        "annotations": {f"verdict:{verdict}": verdict, "note:text_box": note}})
    assert r.status_code == 200, r.text


def test_a_split_vote_is_held_where_the_admin_can_see_it(review_setup):
    server, fake = review_setup
    _save(server, "alice.smith@lab.org", "t1", "pass", "looked fine to me")
    _save(server, "bob.jones@lab.org", "t1", "fail", "it looped twice")
    _save(server, "alice.smith@lab.org", "t2", "pass", "ok")
    _save(server, "bob.jones@lab.org", "t2", "pass", "ok too")
    [request] = _wait_for(fake, 1)
    [score] = request["body"]
    assert (score["traceId"], score["value"]) == ("tr-2", "pass")
    # Nothing that names a person, and no free text, leaves the server.
    text = str(score)
    for private in ("alice", "bob", "lab.org", "looked fine", "ok too"):
        assert private not in text
    status = requests.get(f"{server.base_url}/admin/api/trace_writeback",
                          headers={"X-API-Key": ADMIN_KEY}).json()
    assert status["counts"]["held"] == 1 and status["counts"]["sent"] == 1
    [held] = status["held"]
    assert (held["item_id"], held["scheme"]) == ("t1", "verdict")
    assert held["reason"] == "tie: fail 1, pass 1; adjudicate to send"
