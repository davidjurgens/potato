"""Continuous backup to a HuggingFace Dataset.

This is the only thing keeping annotations on a host whose filesystem does not
survive a restart — a Space, a free container, anything that redeploys in place.

It was started from ``run_server()``, which only ``potato start`` reaches. Every
container starts through the ``create_app`` WSGI factory instead, so on exactly
the hosts where it is load-bearing it had never run at all. The wiring test
below is the one that matters; the rest guard the failure modes it needs to
survive, since a backup that silently does nothing is worse than none.
"""

import ast
import os

import pytest

from potato.server_utils import hf_backup


@pytest.fixture(autouse=True)
def clean_scheduler():
    hf_backup.reset_scheduler()
    yield
    hf_backup.reset_scheduler()


class FakeScheduler:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        FakeScheduler.instances.append(self)


@pytest.fixture
def fake_commit_scheduler(monkeypatch):
    import sys
    import types

    FakeScheduler.instances = []
    module = types.ModuleType("huggingface_hub")
    module.CommitScheduler = FakeScheduler
    monkeypatch.setitem(sys.modules, "huggingface_hub", module)
    return FakeScheduler


def config_with_backup(tmp_path, **overrides):
    backup = {"enabled": True, "repo_id": "alice/study-annotations",
              "token": "hf_secret"}
    backup.update(overrides)
    return {"task_dir": str(tmp_path), "output_annotation_dir": "annotation_output",
            "huggingface_backup": backup}


class TestWiring:
    """The bug: configure_app runs on both startup paths, run_server does not."""

    def test_configure_app_starts_the_backup(self):
        source = open(_flask_server_path()).read()
        tree = ast.parse(source)
        configure_app = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "configure_app")
        calls = [n.func.id for n in ast.walk(configure_app)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
        assert "init_backup" in calls, (
            "configure_app must start the HuggingFace backup: it is the only "
            "startup hook both `potato start` and the gunicorn create_app "
            "factory reach. Wired anywhere else, it never runs in a container.")

    def test_run_server_no_longer_starts_its_own(self):
        """Two schedulers on one directory would race each other's commits."""
        source = open(_flask_server_path()).read()
        tree = ast.parse(source)
        run_server = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "run_server")
        segment = ast.get_source_segment(source, run_server) or ""
        assert "CommitScheduler(" not in segment

    def test_the_factory_path_reaches_configure_app(self):
        """Which is what makes the fix work for every container."""
        source = open(_flask_server_path()).read()
        tree = ast.parse(source)
        create_app = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "create_app")
        segment = ast.get_source_segment(source, create_app) or ""
        assert "configure_app(" in segment


class TestInitBackup:
    def test_disabled_by_default(self, tmp_path, fake_commit_scheduler):
        assert hf_backup.init_backup({"task_dir": str(tmp_path)}) is None
        assert not fake_commit_scheduler.instances

    def test_starts_when_enabled(self, tmp_path, fake_commit_scheduler):
        assert hf_backup.init_backup(config_with_backup(tmp_path)) is not None
        assert len(fake_commit_scheduler.instances) == 1

    def test_targets_a_dataset_repo(self, tmp_path, fake_commit_scheduler):
        """The documentation has always said dataset; the code omitted repo_type
        entirely, so CommitScheduler defaulted to a model repo."""
        hf_backup.init_backup(config_with_backup(tmp_path))
        assert fake_commit_scheduler.instances[0].kwargs["repo_type"] == "dataset"

    def test_backs_up_the_annotation_directory(self, tmp_path, fake_commit_scheduler):
        hf_backup.init_backup(config_with_backup(tmp_path))
        folder = fake_commit_scheduler.instances[0].kwargs["folder_path"]
        assert folder == os.path.join(str(tmp_path), "annotation_output")

    def test_creates_the_directory_if_it_is_missing(self, tmp_path,
                                                    fake_commit_scheduler):
        """CommitScheduler watches a directory; a missing one backs up nothing."""
        hf_backup.init_backup(config_with_backup(tmp_path))
        assert os.path.isdir(os.path.join(str(tmp_path), "annotation_output"))

    def test_private_by_default(self, tmp_path, fake_commit_scheduler):
        hf_backup.init_backup(config_with_backup(tmp_path))
        assert fake_commit_scheduler.instances[0].kwargs["private"] is True

    def test_a_second_call_does_not_start_a_second_uploader(self, tmp_path,
                                                            fake_commit_scheduler):
        """Two schedulers on one folder race each other over the same commits."""
        config = config_with_backup(tmp_path)
        hf_backup.init_backup(config)
        hf_backup.init_backup(config)
        assert len(fake_commit_scheduler.instances) == 1


class TestFailuresAreLoudButNotFatal:
    """A broken backup must not stop the server, and must not be silent either."""

    def test_missing_repo_id_logs_an_error(self, tmp_path, fake_commit_scheduler,
                                           caplog):
        config = config_with_backup(tmp_path)
        del config["huggingface_backup"]["repo_id"]
        assert hf_backup.init_backup(config) is None
        assert "NOT be backed up" in caplog.text

    def test_missing_token_logs_an_error(self, tmp_path, fake_commit_scheduler,
                                         caplog, monkeypatch):
        monkeypatch.delenv("HF_TOKEN", raising=False)
        monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
        config = config_with_backup(tmp_path)
        del config["huggingface_backup"]["token"]
        assert hf_backup.init_backup(config) is None
        assert "NOT be backed up" in caplog.text

    def test_scheduler_failure_does_not_propagate(self, tmp_path, monkeypatch,
                                                  caplog):
        import sys
        import types

        def explode(**kwargs):
            raise RuntimeError("repo is gated")

        module = types.ModuleType("huggingface_hub")
        module.CommitScheduler = explode
        monkeypatch.setitem(sys.modules, "huggingface_hub", module)

        assert hf_backup.init_backup(config_with_backup(tmp_path)) is None
        assert "NOT be backed up" in caplog.text

    def test_missing_library_names_the_extra(self, tmp_path, monkeypatch, caplog):
        import builtins
        real_import = builtins.__import__

        def refuse(name, *args, **kwargs):
            if name == "huggingface_hub":
                raise ImportError("no module")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", refuse)
        assert hf_backup.init_backup(config_with_backup(tmp_path)) is None
        assert "potato-annotation[huggingface]" in caplog.text


class TestTokenResolution:
    def test_config_token_wins(self, monkeypatch):
        monkeypatch.setenv("HF_TOKEN", "from-env")
        assert hf_backup.resolve_token({"token": "from-config"}) == "from-config"

    def test_falls_back_to_the_environment(self, monkeypatch):
        monkeypatch.setenv("HF_TOKEN", "from-env")
        assert hf_backup.resolve_token({}) == "from-env"

    def test_env_var_reference_is_substituted_before_it_gets_here(self, tmp_path):
        """The documented form is `token: "${HF_TOKEN}"`.

        Without substitution that string reaches CommitScheduler literally and
        the backup silently never authenticates.
        """
        import yaml
        from potato.server_utils.config_module import _substitute_llm_block_env_vars

        os.environ["HF_TOKEN"] = "hf_real_value"
        try:
            config = yaml.safe_load(
                'huggingface_backup:\n  enabled: true\n  repo_id: a/b\n'
                '  token: "${HF_TOKEN}"\n')
            result = _substitute_llm_block_env_vars(config)
            assert result["huggingface_backup"]["token"] == "hf_real_value"
        finally:
            os.environ.pop("HF_TOKEN", None)


def _flask_server_path():
    import potato.flask_server as flask_server
    return flask_server.__file__
