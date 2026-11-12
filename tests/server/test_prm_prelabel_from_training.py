"""The process_reward AI pre-label button offers a trained step model's
ratings, when a prm-reward run wrote some, before asking an LLM judge.

No judge is configured here, so without the trained ratings the route
answers 503: the test can tell which source answered.
"""

import json
import os

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory

STEPS = [{"action": "open the file"}, {"action": "delete everything"}]


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("prm_prelabel_from_training")
    data_path = os.path.join(test_dir, "items.json")
    with open(data_path, "w") as f:
        for iid in ("rated", "unrated", "bad", "allbad"):
            f.write(json.dumps({"id": iid, "text": "t", "task": "tidy up",
                                "steps": STEPS}) + "\n")
    config = {
        "port": 8000, "server_name": "test",
        "annotation_task_name": "prm prelabel", "task_dir": test_dir,
        "output_annotation_dir": os.path.join(test_dir, "output"),
        "data_files": [data_path],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "user_config": {"allow_all_users": True, "users": []},
        "site_dir": "default",
        "annotation_schemes": [{"annotation_type": "process_reward",
                                "name": "prm", "description": "Rate each step",
                                "steps_key": "steps", "mode": "per_step",
                                "ai_prelabel": True}],
        "model_training": {"enabled": True, "writeback": {"schemas": ["prm"]}},
    }
    path = os.path.join(test_dir, "config.yaml")
    with open(path, "w") as f:
        yaml.safe_dump(config, f)
    srv = FlaskTestServer(config_file=path)
    if not srv.start():
        cleanup_test_directory(test_dir)
        pytest.fail("Failed to start server")
    from potato.item_state_management import get_item_state_manager
    get_item_state_manager().set_prediction("rated", "prm", {"steps": [
        {"index": 0, "reward": 1, "confidence": 0.97, "source": "model"},
        {"index": 1, "reward": -1, "confidence": 0.81, "source": "model"}]})
    # Out of range, a reward the scheme cannot store, a duplicate, and a
    # confidence that is not a probability (audit 99 saw these served).
    get_item_state_manager().set_prediction("bad", "prm", {"steps": [
        {"index": 0, "reward": 1, "confidence": 7},
        {"index": 0, "reward": -1, "confidence": 0.5},
        {"index": 1, "reward": 5, "confidence": 0.9},
        {"index": 7, "reward": 1, "confidence": 0.9},
        {"index": True, "reward": 1}, "junk"]})
    get_item_state_manager().set_prediction("allbad", "prm", {"steps": [
        {"index": 9, "reward": 1}]})
    yield srv
    srv.stop()
    cleanup_test_directory(test_dir)


@pytest.fixture
def session(server):
    s = requests.Session()
    s.post(server.base_url + "/register", data={"email": "u", "pass": "p"})
    s.post(server.base_url + "/auth", data={"email": "u", "pass": "p"})
    return s


def test_trained_ratings_are_offered(server, session):
    r = session.get(server.base_url + "/api/prm/prelabel",
                    params={"instance_id": "rated", "schema": "prm"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "model"
    assert [(s["index"], s["reward"], s["confidence"]) for s in body["steps"]] == [
        (0, 1, 0.97), (1, -1, 0.81)]


def test_without_trained_ratings_the_judge_is_asked(server, session):
    r = session.get(server.base_url + "/api/prm/prelabel",
                    params={"instance_id": "unrated", "schema": "prm"})
    assert r.status_code == 503


def test_bad_stored_ratings_are_dropped_not_served(server, session):
    r = session.get(server.base_url + "/api/prm/prelabel",
                    params={"instance_id": "bad", "schema": "prm"})
    assert r.status_code == 200, r.text
    assert [(s["index"], s["reward"], s["confidence"])
            for s in r.json()["steps"]] == [(0, 1, None)]


def test_a_rating_with_no_usable_step_falls_back_to_the_judge(server, session):
    r = session.get(server.base_url + "/api/prm/prelabel",
                    params={"instance_id": "allbad", "schema": "prm"})
    assert r.status_code == 503
