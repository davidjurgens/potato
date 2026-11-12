"""Publishing a run's model to the Hugging Face Hub.

The Hub is a stand-in (FakeHub) with the four calls the push makes; nothing
leaves this machine. What is checked: what goes up and what does not, the
model card, every refusal, and that the push is recorded.
"""

import json
import os
import types

import pytest

pytest.importorskip("huggingface_hub")

from potato.training import hub, store  # noqa: E402


class RepositoryNotFoundError(Exception):
    """Named like huggingface_hub's, which the push recognises by name."""


class FakeHub:
    def __init__(self, existing=None, info_error=None, commit_error=None):
        self.existing = existing     # None, or {"private": bool}
        self.info_error = info_error
        self.commit_error = commit_error
        self.created = []
        self.deleted = []
        self.commits = []

    def repo_info(self, repo_id, repo_type="model"):
        if self.info_error is not None:
            raise self.info_error
        if self.existing is None:
            raise RepositoryNotFoundError("404 Client Error: Repository Not Found "
                                          "for url: .../%s" % repo_id)
        return types.SimpleNamespace(private=self.existing["private"])

    def create_repo(self, repo_id, repo_type="model", private=True, exist_ok=False):
        self.created.append((repo_id, private))

    def delete_repo(self, repo_id, repo_type="model"):
        self.deleted.append(repo_id)

    def create_commit(self, repo_id, repo_type, operations, commit_message):
        if self.commit_error is not None:
            raise self.commit_error
        files = {}
        for op in operations:
            data = op.path_or_fileobj
            if isinstance(data, str):
                with open(data, "rb") as fh:
                    data = fh.read()
            files[op.path_in_repo] = data
        self.commits.append({"repo_id": repo_id, "files": files,
                             "message": commit_message})
        return types.SimpleNamespace(
            oid="abc123def456", commit_url="https://huggingface.co/%s/commit/abc" % repo_id)


@pytest.fixture
def project(tmp_path, monkeypatch):
    config = {"task_dir": str(tmp_path), "annotation_task_name": "hub test"}
    artifacts = tmp_path / "artifacts"
    (artifacts / "model").mkdir(parents=True)
    (artifacts / "model" / "config.json").write_text("{}")
    (artifacts / "model" / "model.safetensors").write_bytes(b"weights")
    (artifacts / "model_card.json").write_text(json.dumps({
        "trainer": "hf-text-classification", "base_model": "distilbert-base-uncased",
        "label_order": ["positive", "negative"]}))
    (artifacts / "predictions.jsonl").write_text('{"instance_id": "secret item"}\n')
    (artifacts / ".hidden").write_text("x")
    run = store.TrainingRun(
        run_id="run-hub", trainer="hf-text-classification",
        schema_names=["sentiment"], kinds=["nominal"], status="success",
        n_train=70, n_val=15, n_test=15, model_version="hf-sentiment-run-hub",
        bundle_digest="d1g3st", metrics={"heldout_score": 0.8123,
                                         "heldout_metric": "test macro_f1"})
    store.record_run(config, run)
    monkeypatch.setenv("HF_TOKEN", "hf_test_token")
    return config, run, str(artifacts)


class _HTTPError(Exception):
    def __init__(self, status, text):
        super().__init__(text)
        self.response = types.SimpleNamespace(status_code=status)


def _push(project, fake, **kw):
    config, run, artifacts = project
    return hub.push(config, run, artifacts, kw.pop("repo_id", "my-lab/sentiment"),
                    api_factory=lambda token: fake, **kw)


def test_the_model_goes_up_and_the_projects_data_does_not(project):
    fake = FakeHub()
    outcome = _push(project, fake, pushed_by="admin")
    (commit,) = fake.commits
    assert sorted(commit["files"]) == ["README.md", "model/config.json",
                                       "model/model.safetensors",
                                       "model_card.json"]
    assert fake.created == [("my-lab/sentiment", True)]
    assert outcome["revision"] == "abc123def456"
    readme = commit["files"]["README.md"].decode()
    assert "base_model: distilbert-base-uncased" in readme
    assert "library_name: transformers" in readme
    assert "| Held-out score | 0.8123 (test macro_f1) |" in readme
    assert "| Items | 70 train, 15 val, 15 test |" in readme
    assert "positive, negative" in readme
    assert "secret item" not in readme
    assert store.hub_pushes(project[0], "run-hub") == [{
        "repo_id": "my-lab/sentiment", "revision": "abc123def456",
        "url": "https://huggingface.co/my-lab/sentiment/commit/abc",
        "private": True, "pushed_by": "admin",
        "pushed_at": store.hub_pushes(project[0], "run-hub")[0]["pushed_at"]}]


def test_a_licence_goes_in_the_front_matter(project):
    fake = FakeHub()
    _push(project, fake, licence="apache-2.0")
    readme = fake.commits[0]["files"]["README.md"].decode()
    assert "license: apache-2.0" in readme
    assert "whose licence applies" not in readme


def test_a_public_repo_is_not_pushed_to_when_private_was_asked(project):
    fake = FakeHub(existing={"private": False})
    with pytest.raises(hub.HubPushError, match="exists and is public") as err:
        _push(project, fake)
    assert err.value.status == 409 and fake.commits == []
    _push(project, fake, private=False)
    assert len(fake.commits) == 1 and fake.created == []


@pytest.mark.parametrize("change, needle", [
    ({"repo_id": "no-namespace"}, "repo_id must be"),
    ({"repo_id": "a/../b"}, "repo_id must be"),
    ({"token_env": "NOT_SET_ANYWHERE_TOKEN"}, "NOT_SET_ANYWHERE_TOKEN is not set"),
    ({"token_env": "bad name"}, "must name a token variable"),
    ({"licence": "Apache 2"}, "Hub licence id"),
])
def test_refusals(project, change, needle):
    fake = FakeHub()
    with pytest.raises(hub.HubPushError, match=needle):
        _push(project, fake, **change)
    assert fake.commits == []


def test_a_run_that_did_not_succeed_or_kept_no_model_is_refused(project):
    config, run, artifacts = project
    from dataclasses import replace
    failed = replace(run, status="error", run_id="run-failed")
    with pytest.raises(hub.HubPushError, match="only a successful run"):
        hub.push(config, failed, artifacts, "my-lab/x", api_factory=lambda t: FakeHub())
    empty = os.path.join(os.path.dirname(artifacts), "empty")
    os.makedirs(empty)
    with open(os.path.join(empty, "model_card.json"), "w") as fh:
        fh.write("{}")
    remote = replace(run, artifact_uri="gpu:/x/artifacts")
    with pytest.raises(hub.HubPushError, match="no model files.*gpu:/x/artifacts"):
        hub.push(config, remote, empty, "my-lab/x", api_factory=lambda t: FakeHub())



# ------------------------------------------------------------ audit 100

def test_only_model_files_go_up(project, tmp_path):
    """An allowlist: decision-calibrate's raw_answers.jsonl, YOLO's copy of
    the training data, checkpoints and logs all stayed behind it."""
    _, _, artifacts = project
    extra = {"raw_answers.jsonl": "{}", "train_data.jsonl": "{}",
             "log.txt": "x", "results.csv": "x", "yolo_data/images/a.jpg": "x",
             "wev_data/train.jsonl": "x", "model/checkpoint-10/optimizer.pt": "x",
             "model/optimizer.pt": "x", "model/notes.jsonl": "x",
             "laya_summary.json": "{}", "calibration.json": "{}",
             "head.pkl": "x", "model/tokenizer.json": "{}", "model/vocab.txt": "x"}
    for rel, text in extra.items():
        os.makedirs(os.path.dirname(os.path.join(artifacts, rel)), exist_ok=True)
        with open(os.path.join(artifacts, rel), "w") as fh:
            fh.write(text)
    assert hub.model_files(artifacts) == [
        "calibration.json", "head.pkl", "model/config.json",
        "model/model.safetensors", "model/tokenizer.json", "model/vocab.txt",
        "model_card.json"]


def test_a_symlink_out_of_the_artifacts_is_not_followed(project, tmp_path):
    _, _, artifacts = project
    secret = tmp_path / "secret.pkl"
    secret.write_text("not yours")
    os.symlink(str(secret), os.path.join(artifacts, "model", "weights.pkl"))
    os.symlink("/nonexistent/x.pt", os.path.join(artifacts, "dangling.pt"))
    files = hub.model_files(artifacts)
    assert "model/weights.pkl" not in files and "dangling.pt" not in files


@pytest.mark.parametrize("env, value, needle", [
    ("PATH", None, "must name a token variable"),
    ("DATABASE_PASSWORD", "x", "must name a token variable"),
    ("MY_TOKEN", "not-a-hub-token", "does not hold a Hugging Face token"),
])
def test_only_a_hugging_face_token_is_sent(project, monkeypatch, env, value, needle):
    if value is not None:
        monkeypatch.setenv(env, value)
    fake = FakeHub()
    with pytest.raises(hub.HubPushError, match=needle):
        _push(project, fake, token_env=env)
    assert fake.commits == []


@pytest.mark.parametrize("error", [
    _HTTPError(500, "500 Server Error"), ConnectionError("connection reset"),
    _HTTPError(403, "403 Forbidden")])
def test_when_visibility_cannot_be_checked_nothing_is_pushed(project, error):
    fake = FakeHub(info_error=error)
    with pytest.raises(hub.HubPushError, match="Could not check") as err:
        _push(project, fake)
    assert fake.created == [] and fake.commits == []
    assert err.value.status in (403, 502)


def test_a_repo_with_403_in_its_name_is_not_a_403(project):
    fake = FakeHub()
    _push(project, fake, repo_id="lab/m403")
    assert fake.created == [("lab/m403", True)]


def test_no_local_path_reaches_the_hub_or_the_error(project):
    config, run, artifacts = project
    with open(os.path.join(artifacts, "model_card.json"), "w") as fh:
        json.dump({"base_model": "/home/someone/models/qwen-local",
                   "lora": {"r": 16}}, fh)
    fake = FakeHub()
    _push(project, fake)
    files = fake.commits[0]["files"]
    for name in ("README.md", "model_card.json"):
        assert b"/home/someone" not in files[name], name
    assert b"qwen-local (a local model)" in files["README.md"]
    assert b"base_model:" not in files["README.md"]

    failing = FakeHub(commit_error=RuntimeError(
        "upload of %s/model/x failed with token hf_test_token" % artifacts))
    with pytest.raises(hub.HubPushError) as err:
        _push(project, failing, repo_id="lab/other")
    assert artifacts not in str(err.value) and "hf_test_token" not in str(err.value)
    # The repository it made for this push is removed again.
    assert failing.deleted == ["lab/other"]


@pytest.mark.parametrize("licence", [5, "5", "Apache 2"])
def test_a_licence_must_be_a_hub_id(project, licence):
    with pytest.raises(hub.HubPushError, match="Hub licence id"):
        _push(project, FakeHub(), licence=licence)


def test_pushing_the_same_commit_twice_records_it_once(project):
    fake = FakeHub()
    _push(project, fake)
    fake.existing = {"private": True}
    _push(project, fake)
    assert len(store.hub_pushes(project[0], "run-hub")) == 1


def test_the_readme_says_when_the_model_was_trained_privately(project):
    """Audit 108: DP was recorded in model_card.json only, not in the
    README people read on the Hub."""
    _config, run, _artifacts = project
    card = {"base_model": "distilbert-base-uncased",
            "dp": {"epsilon_target": 8.0, "epsilon_spent": 7.91, "delta": 0.001,
                   "covers": "train split"}}
    text = hub.model_card_markdown(run, card, ["model.safetensors"])
    assert "| Differential privacy | DP-SGD, epsilon 7.91 spent of 8.0, delta 0.001" in text
    partial = hub.model_card_markdown(run, {"dp": {"epsilon_spent": 2.5}}, ["model.safetensors"])
    assert "| Differential privacy | DP-SGD, epsilon 2.5 spent, covering" in partial
    assert "None" not in partial
    assert "Differential privacy" not in hub.model_card_markdown(
        run, {"base_model": "distilbert-base-uncased"}, ["model.safetensors"])
