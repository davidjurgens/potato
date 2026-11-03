"""POST /admin/training/api/runs/<id>/push-to-hub through the real route,
with the Hub replaced by tests/unit/test_training_hub.FakeHub."""

import json
import os

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory
from tests.unit.test_training_hub import FakeHub

KEY = "hub-route-key"


@pytest.fixture(scope="module")
def server():
    pytest.importorskip("huggingface_hub")
    test_dir = create_test_directory("training_hub_route")
    data_path = os.path.join(test_dir, "items.json")
    with open(data_path, "w") as f:
        f.write(json.dumps({"id": "h0", "text": "item"}) + "\n")
    config = {
        "port": 8000, "server_name": "test",
        "annotation_task_name": "training hub route", "task_dir": test_dir,
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

    from potato.training import store
    from potato.training.manager import get_training_manager
    for run_id, trainer in (("run-ok", "sklearn-text"),
                            ("run-yolo", "ultralytics-detect")):
        store.record_run(config, store.TrainingRun(
            run_id=run_id, trainer=trainer, schema_names=["sentiment"],
            status="success", n_train=6, n_val=1, n_test=1))
        artifacts = os.path.join(get_training_manager().run_dir(run_id), "artifacts")
        os.makedirs(artifacts, exist_ok=True)
        with open(os.path.join(artifacts, "model.pkl"), "wb") as fh:
            fh.write(b"model")
    srv.test_config = config
    yield srv
    srv.stop()
    cleanup_test_directory(test_dir)


@pytest.fixture
def fake(monkeypatch):
    from potato.training import hub
    fake = FakeHub()
    monkeypatch.setattr(hub, "_default_api", lambda token: fake)
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    return fake


def _post(server, run_id, body, **headers):
    return requests.post(
        server.base_url + "/admin/training/api/runs/%s/push-to-hub" % run_id,
        json=body, headers=dict({"X-API-Key": KEY}, **headers))


def test_the_repository_must_be_named_twice(server, fake):
    r = _post(server, "run-ok", {"repo_id": "lab/a", "confirm_repo_id": "lab/b"})
    assert r.status_code == 400 and "twice" in r.json()["error"]
    assert fake.commits == []


def test_another_sites_page_cannot_push(server, fake):
    r = _post(server, "run-ok", {"repo_id": "lab/a", "confirm_repo_id": "lab/a"},
              Origin="http://evil.example")
    assert r.status_code == 403 and fake.commits == []


def test_a_push_is_made_and_recorded(server, fake):
    r = _post(server, "run-ok", {"repo_id": "lab/a", "confirm_repo_id": "lab/a"})
    assert r.status_code == 201, r.text
    assert r.json()["files"] == ["model.pkl", "README.md"]
    from potato.training import store
    assert store.hub_pushes(server.test_config, "run-ok")[0]["repo_id"] == "lab/a"
    page = requests.get(server.base_url + "/admin/training/runs/run-ok",
                        headers={"X-API-Key": KEY})
    assert 'href="https://huggingface.co/lab/a/commit/abc"' in page.text


def test_a_licensed_trainers_weights_need_the_licence_confirmed(server, fake):
    body = {"repo_id": "lab/y", "confirm_repo_id": "lab/y"}
    r = _post(server, "run-yolo", body)
    assert r.status_code == 400 and r.json()["needs_licence_ack"]
    assert _post(server, "run-yolo", dict(body, accept_licence=True)).status_code == 201


def test_an_unknown_run_is_404(server, fake):
    r = _post(server, "nope", {"repo_id": "lab/a", "confirm_repo_id": "lab/a"})
    assert r.status_code == 404
