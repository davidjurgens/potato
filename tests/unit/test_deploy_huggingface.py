"""The HuggingFace Space provider, plus the backup it depends on.

A Space's filesystem is wiped on every rebuild and every restart, so annotations
written to it are temporary by construction. The provider's job is therefore
less "create a Space" than "create a Space and somewhere for the data to live",
and most of what is asserted here is about the second half: that a backup
Dataset is created, that the config is rewritten to use it, that the token
reaches the container as a secret rather than a committed file, and that `pull`
reads the Dataset rather than the Space.
"""

import os

import pytest
import yaml

from potato.deploy.providers.base import DeploySpec, ProviderError, get_provider
from potato.deploy.providers.huggingface import (
    CPU_BASIC_QUOTA,
    DEFAULT_IMAGE,
    HEALTHY_STAGES,
    _inject_backup_config,
    _slug,
    backup_repo_id,
    space_files,
)
from potato.deploy.state import DeploymentRecord


class FakeBundle:
    file_count = 5
    total_bytes = 4096

    def __init__(self, bundle_dir="/tmp/bundle"):
        self.bundle_dir = bundle_dir

    def sha256(self):
        return "d" * 64


class FakeGenerated:
    secret_key = "HF-SECRET-DO-NOT-COMMIT"
    admin_api_key = "HF-ADMIN-DO-NOT-COMMIT"


@pytest.fixture
def spec(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("task_dir: .\n")
    return DeploySpec(name="pilot", config_path=str(config),
                      extra={"config_rel": "config.yaml",
                             "generated": FakeGenerated(), "owner": "alice"})


@pytest.fixture
def provider():
    return get_provider("huggingface", token="hf_test")


class TestSpaceFiles:
    def test_readme_carries_the_frontmatter_hf_requires(self, spec):
        """Without `sdk` and `app_port` in the frontmatter the Space will not build."""
        readme = space_files(spec)["README.md"]
        front = yaml.safe_load(readme.split("---")[1])
        assert front["sdk"] == "docker"
        assert front["app_port"] == 7860

    def test_dockerfile_derives_from_the_published_image(self, spec):
        """Rather than copying the potato package, as the demo catalog does."""
        dockerfile = space_files(spec)["Dockerfile"]
        instructions = [line for line in dockerfile.splitlines()
                        if line.strip() and not line.startswith("#")]
        assert instructions[0] == f"FROM {DEFAULT_IMAGE}"
        assert "pip install" not in dockerfile

    def test_dockerfile_runs_as_uid_1000(self, spec):
        assert "USER potato" in space_files(spec)["Dockerfile"]

    def test_dockerfile_pins_one_worker(self, spec):
        assert "GUNICORN_WORKERS=1" in space_files(spec)["Dockerfile"]

    def test_readme_says_where_the_data_goes(self, spec):
        readme = space_files(spec, backup_repo="alice/pilot-annotations")["README.md"]
        assert "alice/pilot-annotations" in readme

    def test_readme_warns_when_there_is_no_backup(self, spec):
        readme = space_files(spec, backup_repo=None)["README.md"]
        assert "not backed up" in readme

    def test_no_secret_reaches_a_committed_file(self, spec):
        """Everything in space_files is committed to a readable repo."""
        blob = "".join(space_files(spec).values())
        assert FakeGenerated.secret_key not in blob
        assert FakeGenerated.admin_api_key not in blob


class TestBackupConfigInjection:
    def test_enables_the_backup_in_the_bundled_config(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump({"task_dir": ".", "annotation_schemes": []}))
        _inject_backup_config(str(path), "alice/pilot-annotations", 5)
        config = yaml.safe_load(path.read_text())
        assert config["huggingface_backup"]["enabled"] is True
        assert config["huggingface_backup"]["repo_id"] == "alice/pilot-annotations"

    def test_targets_a_dataset_repo(self, tmp_path):
        """CommitScheduler defaults to a model repo, which is not what is wanted."""
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump({"task_dir": "."}))
        _inject_backup_config(str(path), "alice/x-annotations", 5)
        assert yaml.safe_load(path.read_text())["huggingface_backup"]["repo_type"] \
            == "dataset"

    def test_never_writes_the_token_into_the_config(self, tmp_path):
        """The config is committed to the Space repo; the token is a secret."""
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump({"task_dir": "."}))
        _inject_backup_config(str(path), "alice/x-annotations", 5)
        assert "token" not in yaml.safe_load(path.read_text())["huggingface_backup"]

    def test_keeps_the_rest_of_the_config(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump({"task_dir": ".", "data_files": ["d.json"],
                                        "annotation_task_name": "study"}))
        _inject_backup_config(str(path), "alice/x-annotations", 5)
        config = yaml.safe_load(path.read_text())
        assert config["data_files"] == ["d.json"]
        assert config["annotation_task_name"] == "study"

    def test_a_missing_config_is_an_error_not_a_new_file(self, tmp_path):
        with pytest.raises(ProviderError, match="not where it was expected"):
            _inject_backup_config(str(tmp_path / "nope.yaml"), "a/b", 5)


class TestPlan:
    def test_states_the_paid_plan_requirement(self, provider, spec):
        """Docker Spaces stopped being free; a plan that omits this misleads."""
        assert any("paid HuggingFace plan" in w
                   for w in provider.plan(spec, FakeBundle()).warnings)

    def test_states_the_concurrency_cap(self, provider, spec):
        warnings = provider.plan(spec, FakeBundle()).warnings
        assert any(str(CPU_BASIC_QUOTA) in w and "PAUSED" in w for w in warnings)

    def test_creates_a_backup_dataset_by_default(self, provider, spec):
        kinds = [a.kind for a in provider.plan(spec, FakeBundle()).actions]
        assert "hf.dataset" in kinds

    def test_demo_skips_the_backup_and_says_why(self, provider, spec):
        spec.demo = True
        plan = provider.plan(spec, FakeBundle())
        assert "hf.dataset" not in [a.kind for a in plan.actions]
        assert any("will be lost" in w for w in plan.warnings)

    def test_secrets_step_lists_keys_only(self, provider, spec):
        action = next(a for a in provider.plan(spec, FakeBundle()).actions
                      if a.kind == "hf.secrets")
        assert "POTATO_SECRET_KEY" in action.request["secret_keys"]
        assert FakeGenerated.secret_key not in repr(action.request)

    def test_no_secret_value_is_printed(self, provider, spec):
        plan = provider.plan(spec, FakeBundle())
        blob = plan.render() + repr([a.request for a in plan.actions])
        assert FakeGenerated.secret_key not in blob

    def test_plan_needs_no_token(self, spec):
        assert get_provider("huggingface", token=None).plan(spec, FakeBundle()).actions


class TestCreate:
    def test_a_paid_plan_error_names_the_free_alternatives(self, provider, spec,
                                                           tmp_path, monkeypatch):
        """402 is the most likely first failure now that Docker Spaces cost money."""
        from potato.deploy.state import DeploymentStore

        class FakeApi:
            def whoami(self):
                return {"name": "alice"}

            def create_repo(self, repo_id, repo_type=None, **kwargs):
                if repo_type == "space":
                    # huggingface_hub's error classes vary by version; what the
                    # provider can rely on is the 402 in the message.
                    raise RuntimeError("402 Client Error: Payment Required")

        monkeypatch.setattr("potato.deploy.providers.huggingface._hf_api",
                            lambda token: FakeApi())
        spec.demo = True
        with pytest.raises(ProviderError) as excinfo:
            provider.create(spec, FakeBundle(), None,
                            DeploymentStore(spec.config_path))
        message = str(excinfo.value)
        assert "PRO" in message
        assert "--provider render" in message or "potato share" in message

    def test_repo_id_is_persisted_before_the_build_wait(self, provider, spec,
                                                        tmp_path, monkeypatch):
        from potato.deploy.state import DeploymentStore

        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        (bundle_dir / "config.yaml").write_text("task_dir: .\n")

        class FakeRuntime:
            stage = "BUILD_ERROR"
            raw = {}

        class FakeApi:
            def whoami(self):
                return {"name": "alice"}

            def create_repo(self, *a, **k):
                return None

            def add_space_secret(self, **k):
                return None

            def upload_folder(self, **k):
                return None

            def get_space_runtime(self, repo_id):
                return FakeRuntime()

        monkeypatch.setattr("potato.deploy.providers.huggingface._hf_api",
                            lambda token: FakeApi())
        store = DeploymentStore(spec.config_path)
        with pytest.raises(ProviderError, match="BUILD_ERROR"):
            provider.create(spec, FakeBundle(str(bundle_dir)), None, store)
        assert store.get("pilot").provider_ref["repo_id"] == "alice/pilot"

    def test_secrets_go_to_the_space_not_the_repo(self, provider, spec, tmp_path,
                                                  monkeypatch):
        from potato.deploy.state import DeploymentStore

        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        (bundle_dir / "config.yaml").write_text("task_dir: .\n")

        uploaded = {}
        secrets = {}

        class FakeRuntime:
            stage = "RUNNING"
            raw = {}

        class FakeApi:
            def whoami(self):
                return {"name": "alice"}

            def create_repo(self, *a, **k):
                return None

            def add_space_secret(self, repo_id, key, value):
                secrets[key] = value

            def upload_folder(self, folder_path, **k):
                for dirpath, _d, filenames in os.walk(folder_path):
                    for filename in filenames:
                        with open(os.path.join(dirpath, filename)) as handle:
                            uploaded[filename] = handle.read()

            def get_space_runtime(self, repo_id):
                return FakeRuntime()

        monkeypatch.setattr("potato.deploy.providers.huggingface._hf_api",
                            lambda token: FakeApi())
        provider.create(spec, FakeBundle(str(bundle_dir)), None,
                        DeploymentStore(spec.config_path))

        assert secrets["POTATO_SECRET_KEY"] == FakeGenerated.secret_key
        assert secrets["HF_TOKEN"] == "hf_test"
        for name, content in uploaded.items():
            assert FakeGenerated.secret_key not in content, f"leaked into {name}"
            assert "hf_test" not in content, f"token leaked into {name}"

    def test_the_uploaded_config_points_at_the_backup(self, provider, spec,
                                                      tmp_path, monkeypatch):
        from potato.deploy.state import DeploymentStore

        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        (bundle_dir / "config.yaml").write_text("task_dir: .\n")
        uploaded = {}

        class FakeRuntime:
            stage = "RUNNING"
            raw = {}

        class FakeApi:
            def whoami(self):
                return {"name": "alice"}

            def create_repo(self, *a, **k):
                return None

            def add_space_secret(self, **k):
                return None

            def upload_folder(self, folder_path, **k):
                with open(os.path.join(folder_path, "config.yaml")) as handle:
                    uploaded["config"] = yaml.safe_load(handle)

            def get_space_runtime(self, repo_id):
                return FakeRuntime()

        monkeypatch.setattr("potato.deploy.providers.huggingface._hf_api",
                            lambda token: FakeApi())
        provider.create(spec, FakeBundle(str(bundle_dir)), None,
                        DeploymentStore(spec.config_path))
        backup = uploaded["config"]["huggingface_backup"]
        assert backup["enabled"] is True
        assert backup["repo_id"] == "alice/pilot-annotations"


class TestPull:
    def test_reads_the_dataset_not_the_space(self, provider, tmp_path, monkeypatch):
        """Whatever is on the Space right now is at best a partial copy."""
        called = {}

        def fake_download(repo_id, repo_type, token, local_dir):
            called["repo_id"] = repo_id
            called["repo_type"] = repo_type
            os.makedirs(local_dir, exist_ok=True)
            with open(os.path.join(local_dir, "user_state.json"), "w") as handle:
                handle.write("{}")

        monkeypatch.setattr("huggingface_hub.snapshot_download", fake_download)
        record = DeploymentRecord(
            name="pilot", provider="huggingface",
            provider_ref={"repo_id": "alice/pilot",
                          "backup_repo": "alice/pilot-annotations"})
        result = provider.pull(record, str(tmp_path / "pulled"))
        assert called["repo_id"] == "alice/pilot-annotations"
        assert called["repo_type"] == "dataset"
        assert result.files == 1

    def test_demo_deployment_falls_back_to_the_space_itself(self, provider,
                                                            tmp_path, monkeypatch):
        """A --demo Space has no Dataset but may still be running with data on it.

        Reaching it over HTTPS is worth doing before telling the user there is
        nothing to be done.
        """
        from potato.deploy.state import SecretStore

        config = tmp_path / "config.yaml"
        config.write_text("task_dir: .\n")
        SecretStore(str(config)).put("pilot", "admin_api_key", "adm_key")

        called = {}

        def fake_pull(url, admin_key, dest, console=None):
            called.update(url=url)
            from potato.deploy.providers.base import PullResult
            return PullResult(dest=dest, files=2)

        monkeypatch.setattr("potato.deploy.pull.pull_over_https", fake_pull)
        record = DeploymentRecord(name="pilot", provider="huggingface",
                                  provider_ref={"repo_id": "alice/pilot"},
                                  url="https://alice-pilot.hf.space",
                                  spec={"config_path": str(config)})
        assert provider.pull(record, str(tmp_path / "out")).files == 2
        assert called["url"] == "https://alice-pilot.hf.space"

    def test_demo_with_no_key_says_the_data_may_be_gone(self, provider, tmp_path):
        record = DeploymentRecord(name="pilot", provider="huggingface",
                                  provider_ref={"repo_id": "alice/pilot"},
                                  url="https://alice-pilot.hf.space")
        with pytest.raises(ProviderError, match="wiped on"):
            provider.pull(record, str(tmp_path))


class TestDestroy:
    def test_keeps_the_backup_dataset(self, provider, monkeypatch):
        """Deleting the Space is cheap; deleting the annotations is not."""
        deleted = []

        class FakeApi:
            def delete_repo(self, repo_id, repo_type):
                deleted.append((repo_id, repo_type))

        monkeypatch.setattr("potato.deploy.providers.huggingface._hf_api",
                            lambda token: FakeApi())
        messages = []
        provider.console = messages.append
        record = DeploymentRecord(
            name="pilot", provider="huggingface",
            provider_ref={"repo_id": "alice/pilot",
                          "backup_repo": "alice/pilot-annotations"})
        provider.destroy(record)
        assert deleted == [("alice/pilot", "space")]
        assert any("pilot-annotations" in m for m in messages)


class TestStatus:
    def test_paused_is_not_healthy(self, provider, monkeypatch):
        """SLEEPING wakes on a request; PAUSED never does."""
        class FakeRuntime:
            stage = "PAUSED"
            raw = {"errorMessage": "Quota exceeded"}

        class FakeApi:
            def get_space_runtime(self, repo_id):
                return FakeRuntime()

        monkeypatch.setattr("potato.deploy.providers.huggingface._hf_api",
                            lambda token: FakeApi())
        record = DeploymentRecord(name="pilot", provider="huggingface",
                                  provider_ref={"repo_id": "alice/pilot"})
        status = provider.status(record)
        assert not status.healthy
        assert "does not wake" in status.detail

    def test_sleeping_counts_as_healthy(self, provider, monkeypatch):
        class FakeRuntime:
            stage = "SLEEPING"
            raw = {}

        class FakeApi:
            def get_space_runtime(self, repo_id):
                return FakeRuntime()

        monkeypatch.setattr("potato.deploy.providers.huggingface._hf_api",
                            lambda token: FakeApi())
        record = DeploymentRecord(name="pilot", provider="huggingface",
                                  provider_ref={"repo_id": "alice/pilot"})
        assert provider.status(record).healthy

    def test_healthy_stages_are_exactly_these_two(self):
        assert HEALTHY_STAGES == {"RUNNING", "SLEEPING"}


class TestHelpers:
    def test_backup_repo_naming(self):
        assert backup_repo_id("alice", "pilot") == "alice/pilot-annotations"

    @pytest.mark.parametrize("value,expected", [
        ("Alice", "alice"),
        ("my_task", "my-task"),
        ("Study 2026", "study-2026"),
    ])
    def test_subdomain_slug(self, value, expected):
        assert _slug(value) == expected

    def test_logs_are_not_faked(self, provider):
        record = DeploymentRecord(name="pilot", provider="huggingface",
                                  provider_ref={"repo_id": "alice/pilot"})
        with pytest.raises(ProviderError, match="logs=build"):
            list(provider.logs(record))
