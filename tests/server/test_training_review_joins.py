"""The joins between training and its neighbours, through the real routes.

- the model-review report names the run behind each prelabel;
- "Train on these" pins items so later runs train on them;
- a run's split can be saved as a dataset version, with human labels.

The run ledger is written directly (no trainer runs here): these routes read
the ledger, and building one through a real run would test the trainer.
"""

import json
import os

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory

KEY = "joins-key"
IDS = ["t%d" % i for i in range(6)]


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("training_review_joins")
    data_path = os.path.join(test_dir, "items.json")
    with open(data_path, "w") as f:
        for iid in IDS:
            f.write(json.dumps({"id": iid, "text": "item %s" % iid}) + "\n")
    config = {
        "port": 8000, "server_name": "test",
        "annotation_task_name": "training review joins", "task_dir": test_dir,
        "output_annotation_dir": os.path.join(test_dir, "output"),
        "data_files": [data_path],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "user_config": {"allow_all_users": True, "users": []},
        "site_dir": "default", "admin_api_key": KEY,
        "annotation_schemes": [{"annotation_type": "radio", "name": "sentiment",
                                "description": "Sentiment?",
                                "labels": ["positive", "negative"]},
                               {"annotation_type": "radio", "name": "topic",
                                "description": "Topic?",
                                "labels": ["food", "film"]}],
        "model_training": {"enabled": True,
                           "writeback": {"schemas": ["sentiment"]}},
        "datasets": {"enabled": True},
    }
    path = os.path.join(test_dir, "config.yaml")
    with open(path, "w") as f:
        yaml.safe_dump(config, f)
    srv = FlaskTestServer(config_file=path)
    if not srv.start():
        cleanup_test_directory(test_dir)
        pytest.fail("Failed to start server")
    srv.test_config = config
    yield srv
    srv.stop()
    cleanup_test_directory(test_dir)


@pytest.fixture(scope="module")
def ledger(server):
    """One finished run: t0-t3 train, t4 val, t5 test, predictions on t4/t5."""
    from potato.training import store

    config = server.test_config
    run = store.TrainingRun(run_id="run-a", trainer="sklearn-text",
                            schema_names=["sentiment"], status="success",
                            created_at=1.0,
                            metrics={"heldout_score": 0.8125,
                                     "heldout_metric": "test macro_f1"})
    store.record_run(config, run)
    store.record_run_items(config, "run-a", {"train": IDS[:4], "val": ["t4"],
                                             "test": ["t5"]})
    store.record_predictions(config, "run-a", [
        ("t4", "sentiment", {"label": "positive", "confidence": 0.4}, 0.4),
        ("t5", "sentiment", {"label": "negative", "confidence": 0.9}, 0.9)])
    from potato.item_state_management import get_item_state_manager
    ism = get_item_state_manager()
    ism.set_prediction("t4", "sentiment", {"label": "positive", "confidence": 0.4})
    ism.set_prediction("t5", "sentiment", {"label": "negative", "confidence": 0.9})
    return config


def _admin(server):
    s = requests.Session()
    s.headers["X-API-Key"] = KEY
    return s


def _annotate(server, user, labels, scheme="sentiment"):
    s = requests.Session()
    s.post(server.base_url + "/register", data={"email": user, "pass": "p"})
    s.post(server.base_url + "/auth", data={"email": user, "pass": "p"})
    for iid, label in labels.items():
        r = s.post(server.base_url + "/updateinstance", json={
            "instance_id": iid,
            "annotations": {"%s:::%s" % (scheme, label): label},
            "span_annotations": []})
        assert r.status_code == 200, r.text


def test_the_review_report_names_the_run_behind_each_prelabel(server, ledger):
    r = _admin(server).get(server.base_url + "/admin/model-review")
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["queue"][:2] == ["t4", "t5"]
    assert report["provenance"]["t4"]["sentiment"] == {
        "run_id": "run-a", "trainer": "sklearn-text",
        "heldout_score": 0.8125, "heldout_metric": "test macro_f1"}
    assert set(report["provenance"]) == {"t4", "t5"}


def test_pinning_items_and_reading_them_back(server, ledger):
    s = _admin(server)
    r = s.post(server.base_url + "/admin/training/api/pinned",
               json={"instance_ids": ["t4", "t5", "nope"]})
    assert r.status_code == 200, r.text
    # run-a trained on t0-t3, so neither t4 nor t5 was in its train split.
    assert r.json() == {"pinned": 2, "already_pinned": 0, "unknown": 1,
                        "in_last_run_train": 0, "total": 2}
    r = s.post(server.base_url + "/admin/training/api/pinned",
               json={"instance_ids": ["t0"]})
    assert r.json()["in_last_run_train"] == 1
    s.delete(server.base_url + "/admin/training/api/pinned",
             json={"instance_ids": ["t0"]})
    again = s.post(server.base_url + "/admin/training/api/pinned",
                   json={"instance_ids": ["t4"]}).json()
    assert again["pinned"] == 0 and again["already_pinned"] == 1
    listed = s.get(server.base_url + "/admin/training/api/pinned").json()
    assert listed == {"pinned": {"hard_example": ["t4", "t5"]}}

    r = s.delete(server.base_url + "/admin/training/api/pinned",
                 json={"instance_ids": ["t5"]})
    assert r.json() == {"unpinned": 1}
    assert s.get(server.base_url + "/admin/training/api/pinned").json() == {
        "pinned": {"hard_example": ["t4"]}}


def test_pinning_needs_a_target(server, ledger):
    r = _admin(server).post(server.base_url + "/admin/training/api/pinned",
                            json={})
    assert r.status_code == 400


def test_pinning_needs_admin(server, ledger):
    r = requests.post(server.base_url + "/admin/training/api/pinned",
                      json={"instance_ids": ["t4"]})
    assert r.status_code in (401, 403)


def test_a_split_saved_as_a_dataset_carries_human_labels(server, ledger):
    _annotate(server, "ann1", {"t4": "positive"})
    s = _admin(server)
    r = s.post(server.base_url + "/admin/training/api/runs/run-a/pin-split",
               json={"dataset": "sentiment-heldout", "split": "val"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["imported"] == 1 and body["split"] == "val"
    assert body["version"]["example_count"] == 1

    from potato.eval_datasets.manager import get_datasets_manager
    examples = get_datasets_manager().store.list_examples("sentiment-heldout")
    assert [e.id for e in examples] == ["t4"]
    assert "positive" in json.dumps(examples[0].reference_outputs)


@pytest.mark.parametrize("body, status", [
    ({"split": "val"}, 400),                        # no dataset name
    ({"dataset": "x", "split": "unlabeled"}, 400),  # a split the run lacks
])
def test_pin_split_refusals(server, ledger, body, status):
    r = _admin(server).post(
        server.base_url + "/admin/training/api/runs/run-a/pin-split", json=body)
    assert r.status_code == status, r.text


def test_pin_split_of_an_unknown_run_is_404(server, ledger):
    r = _admin(server).post(
        server.base_url + "/admin/training/api/runs/nope/pin-split",
        json={"dataset": "x"})
    assert r.status_code == 404


def test_a_malformed_unpin_is_refused_rather_than_unpinning_all(server, ledger):
    s = _admin(server)
    s.post(server.base_url + "/admin/training/api/pinned",
           json={"instance_ids": ["t1", "t2"]})
    for body in ({"instance_ids": "t1"}, {"instance_ids": 3},
                 {"instance_ids": []}, ["t1"], [], "", 0, False):
        r = s.delete(server.base_url + "/admin/training/api/pinned", json=body)
        assert r.status_code == 400, (body, r.text)
    for raw in (b"{not json", b"null"):
        r = s.delete(server.base_url + "/admin/training/api/pinned", data=raw,
                     headers={"Content-Type": "application/json"})
        assert r.status_code == 400, (raw, r.text)
    assert set(s.get(server.base_url + "/admin/training/api/pinned")
               .json()["pinned"]["hard_example"]) >= {"t1", "t2"}
    s.delete(server.base_url + "/admin/training/api/pinned",
             json={"instance_ids": ["t1", "t2"]})


def test_each_saved_split_is_its_own_snapshot(server, ledger):
    # Audit 99: every example was "test", t4's prelabel was in its inputs,
    # and saving into an existing dataset added to the last version.
    _annotate(server, "ann2", {"t4": "positive", "t0": "negative"})
    _annotate(server, "ann2", {"t4": "food"}, scheme="topic")
    s = _admin(server)
    url = server.base_url + "/admin/training/api/runs/run-a/pin-split"
    first = s.post(url, json={"dataset": "snap", "split": "val"})
    second = s.post(url, json={"dataset": "snap", "split": "train"})
    assert first.status_code == second.status_code == 201, second.text
    assert second.json()["imported"] == 4

    from potato.eval_datasets.manager import get_datasets_manager
    store = get_datasets_manager().store
    val = store.list_examples("snap", as_of=first.json()["version"]["version_id"])
    train = store.list_examples("snap")
    assert [(e.id, e.split) for e in val] == [("t4", "val")]
    assert sorted((e.id, e.split) for e in train) == [
        ("t0", "train"), ("t1", "train"), ("t2", "train"), ("t3", "train")]
    assert "predictions" not in val[0].inputs
    assert val[0].inputs["text"] == "item t4"
    # The run trained sentiment only, so topic's label is not a reference.
    assert set(val[0].reference_outputs) == {"sentiment"}


@pytest.mark.parametrize("name", ["../escape", "a/b", ".hidden"])
def test_a_dataset_name_cannot_leave_the_datasets_directory(server, ledger, name):
    s = _admin(server)
    r = s.post(server.base_url + "/admin/training/api/runs/run-a/pin-split",
               json={"dataset": name, "split": "val"})
    assert r.status_code == 400, r.text
    r = s.post(server.base_url + "/datasets/api/datasets", json={"name": name})
    assert r.status_code == 400, r.text
    from potato.eval_datasets.manager import get_datasets_manager
    root = get_datasets_manager().store._root
    assert not os.path.exists(os.path.join(os.path.dirname(root), "escape"))
    assert not any(d.startswith(".") or d in ("a", "b")
                   for d in os.listdir(root))


def test_a_verdict_needs_the_item_assigned_and_same_origin(server, ledger):
    # A `correct` verdict sends an item to train; any logged-in account
    # could post one for any item, from any page (audit 99 D10).
    from potato.model_review import load_verdicts
    from potato.user_state_management import get_user_state_manager

    s = requests.Session()
    s.post(server.base_url + "/register", data={"email": "rev", "pass": "p"})
    s.post(server.base_url + "/auth", data={"email": "rev", "pass": "p"})
    s.get(server.base_url + "/annotate")
    mine = sorted(get_user_state_manager().get_user_state("rev")
                  .get_assigned_instance_ids())
    assert mine
    # Every item here is assigned to every annotator, so the item rev was
    # not given is one outside its queue.
    theirs = sorted(set(IDS) - set(mine)) or ["not-in-rev-queue"]
    url = server.base_url + "/api/model-review/verdict"

    def post(iid, **headers):
        return s.post(url, json={"instance_id": iid, "verdict": "correct",
                                 "schema_name": "sentiment"}, headers=headers)

    assert post(theirs[0]).status_code == 403
    assert post(mine[0], Origin="http://evil.example").status_code == 403
    assert post(mine[0], Origin=server.base_url).status_code == 200
    recorded = {(v.instance_id, v.reviewer)
                for v in load_verdicts(server.test_config)}
    assert (mine[0], "rev") in recorded
    assert not any(i == theirs[0] and r == "rev" for i, r in recorded)

    # An admin with the key may record a verdict on any item.
    r = _admin(server).post(url, json={"instance_id": "t0",
                                       "verdict": "accept"})
    assert r.status_code == 200, r.text
