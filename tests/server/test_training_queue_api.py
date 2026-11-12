"""POST /admin/training/api/runs while a run is in flight: 202 and a place
in the queue, not 409. The queue is in /api/status, and a waiting run is
cancelled through the same route as a running one."""

import json
import os

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory

KEY = "queue-key"


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("training_queue_api")
    data_path = os.path.join(test_dir, "items.json")
    with open(data_path, "w") as f:
        for i in range(8):
            f.write(json.dumps({"id": "q%d" % i, "text": "item %d" % i}) + "\n")
    config = {
        "port": 8000, "server_name": "test",
        "annotation_task_name": "training queue", "task_dir": test_dir,
        "output_annotation_dir": os.path.join(test_dir, "output"),
        "data_files": [data_path],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "user_config": {"allow_all_users": True, "users": []},
        "site_dir": "default", "admin_api_key": KEY,
        "annotation_schemes": [{"annotation_type": "radio", "name": "sentiment",
                                "description": "?", "labels": ["pos", "neg"]}],
        "model_training": {"enabled": True},
    }
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


def _admin():
    s = requests.Session()
    s.headers["X-API-Key"] = KEY
    return s


def test_a_second_run_is_queued_and_can_be_cancelled(server):
    from potato.training.manager import get_training_manager
    manager = get_training_manager()
    manager._set(state="running", run_id="in-flight")   # a run is in flight
    try:
        s = _admin()
        url = server.base_url + "/admin/training/api/runs"
        body = {"trainer": "sklearn-text", "schemas": ["sentiment"]}
        first = s.post(url, json=body)
        second = s.post(url, json=body)
        assert first.status_code == second.status_code == 202, first.text
        assert (first.json()["position"], second.json()["position"]) == (1, 2)

        refused = s.post(url, json=dict(body, queue=False))
        assert refused.status_code == 409

        status = s.get(server.base_url + "/admin/training/api/status").json()
        assert [q["run_id"] for q in status["queue"]] == [
            first.json()["run_id"], second.json()["run_id"]]

        cancel = s.post(server.base_url + "/admin/training/api/runs/%s/cancel"
                        % first.json()["run_id"])
        assert cancel.status_code == 200 and cancel.json()["cancelled"]
        status = s.get(server.base_url + "/admin/training/api/status").json()
        assert [(q["run_id"], q["position"]) for q in status["queue"]] == [
            (second.json()["run_id"], 1)]
        s.post(server.base_url + "/admin/training/api/runs/%s/cancel"
               % second.json()["run_id"])
    finally:
        manager._set(state="idle")
