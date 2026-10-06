"""Off-host backup: settings, snapshots, both sinks, and restore on boot.

The restore half is the one that matters on an ephemeral host. Before it
existed the backup only uploaded: after a restart the server came back empty, a
returning annotator got a fresh user_state.json, and the next sync overwrote
the copy holding their earlier work. TestRestoreProtectsEarlierWork reproduces
that sequence end to end against a fake bucket.
"""

import os
import sqlite3
import sys
import types

import pytest

from potato.server_utils import backup
from potato.server_utils.backup import hf_sink, s3_sink


@pytest.fixture(autouse=True)
def _reset_backups():
    backup.reset()
    yield
    backup.reset()


def make_config(tmp_path, **extra):
    task = tmp_path / "task"
    task.mkdir(parents=True, exist_ok=True)
    config = {"task_dir": str(task),
              "output_annotation_dir": str(task / "annotation_output")}
    config.update(extra)
    return config


def write_user(config, user, body='{"annotations": 1}'):
    path = os.path.join(config["output_annotation_dir"], user, "user_state.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(body)
    return path


def make_db(config, name="project.sqlite", rows=("memo one",)):
    path = os.path.join(config["task_dir"], name)
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE IF NOT EXISTS memos (body TEXT)")
    con.executemany("INSERT INTO memos VALUES (?)", [(r,) for r in rows])
    con.commit()
    con.close()
    return path


class FakeS3:
    """Enough of a boto3 S3 client for the sink, backed by a dict."""

    def __init__(self):
        self.objects = {}
        self.buckets = {"bucket"}

    def head_bucket(self, Bucket):
        if Bucket not in self.buckets:
            raise RuntimeError("404 NoSuchBucket")

    def upload_file(self, path, bucket, key):
        with open(path, "rb") as handle:
            self.objects[key] = handle.read()

    def download_file(self, bucket, key, target):
        with open(target, "wb") as handle:
            handle.write(self.objects[key])

    def get_paginator(self, _name):
        objects = self.objects

        class Paginator:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [{"Key": k} for k in sorted(objects)
                                    if k.startswith(Prefix)]}
        return Paginator()


@pytest.fixture
def fake_s3(monkeypatch):
    client = FakeS3()
    monkeypatch.setattr(s3_sink.S3Sink, "client", lambda self: client)
    return client


def s3_config(tmp_path, **block):
    settings = {"sinks": [{"type": "s3", "bucket": "bucket", "prefix": "study"}]}
    settings.update(block)
    return make_config(tmp_path, backup=settings)


class TestSettings:
    def test_nothing_configured_means_no_backup(self, tmp_path):
        assert not backup.resolve_settings(make_config(tmp_path)).enabled

    def test_legacy_block_becomes_one_huggingface_sink(self, tmp_path):
        config = make_config(tmp_path, huggingface_backup={
            "enabled": True, "repo_id": "me/x", "schedule_minutes": 3})
        settings = backup.resolve_settings(config)
        assert settings.sinks == [{"type": "huggingface", "repo_id": "me/x"}]
        assert settings.schedule_minutes == 3

    def test_legacy_block_does_not_start_restoring_unasked(self, tmp_path):
        """An existing deployment's behaviour must not change under it."""
        config = make_config(tmp_path, huggingface_backup={
            "enabled": True, "repo_id": "me/x"})
        assert backup.resolve_settings(config).restore_on_boot is False

    def test_new_block_restores_by_default(self, tmp_path):
        assert backup.resolve_settings(s3_config(tmp_path)).restore_on_boot is True

    def test_new_block_wins_over_legacy(self, tmp_path):
        config = s3_config(tmp_path)
        config["huggingface_backup"] = {"enabled": True, "repo_id": "me/x"}
        assert [s["type"] for s in backup.resolve_settings(config).sinks] == ["s3"]


class TestSnapshots:
    def test_snapshot_is_a_readable_database(self, tmp_path):
        config = make_config(tmp_path)
        make_db(config, rows=("a", "b"))
        written = backup.snapshot_databases(config)
        assert len(written) == 1
        con = sqlite3.connect(written[0])
        assert con.execute("SELECT count(*) FROM memos").fetchone()[0] == 2
        con.close()

    def test_no_database_is_not_an_error(self, tmp_path):
        assert backup.snapshot_databases(make_config(tmp_path)) == []

    def test_no_partial_file_is_left_behind(self, tmp_path):
        config = make_config(tmp_path)
        make_db(config)
        backup.snapshot_databases(config)
        assert not any(name.endswith(".partial")
                       for name in os.listdir(backup.snapshot_dir(config)))


class TestS3Sink:
    def test_uploads_annotations_and_snapshots(self, tmp_path, fake_s3):
        config = s3_config(tmp_path)
        write_user(config, "alice")
        make_db(config)
        sinks = backup.start_backups(config)
        assert len(sinks) == 1
        backup.flush()
        assert "study/annotations/alice/user_state.json" in fake_s3.objects
        assert "study/_databases/project.sqlite" in fake_s3.objects

    def test_unchanged_files_are_not_sent_again(self, tmp_path, fake_s3):
        config = s3_config(tmp_path)
        write_user(config, "alice")
        sink = backup.start_backups(config)[0]
        backup.flush()
        assert sink._sync(config["output_annotation_dir"], "annotations") == 0

    def test_missing_bucket_logs_and_does_not_raise(self, tmp_path, fake_s3, caplog):
        config = make_config(tmp_path, backup={
            "sinks": [{"type": "s3", "bucket": "nope"}]})
        assert backup.start_backups(config) == []
        assert "NOT be backed up" in caplog.text

    def test_unknown_sink_type_logs(self, tmp_path, caplog):
        config = make_config(tmp_path, backup={"sinks": [{"type": "ftp"}]})
        assert backup.start_backups(config) == []
        assert "not supported" in caplog.text


class TestRestore:
    def test_restores_annotations_and_databases_into_an_empty_task(
            self, tmp_path, fake_s3):
        fake_s3.objects["study/annotations/alice/user_state.json"] = b"{}"
        donor = make_config(tmp_path / "donor")
        make_db(donor, rows=("kept memo",))
        backup.snapshot_databases(donor)
        with open(os.path.join(backup.snapshot_dir(donor), "project.sqlite"), "rb") as h:
            fake_s3.objects["study/_databases/project.sqlite"] = h.read()

        config = s3_config(tmp_path)
        assert backup.restore_on_boot(config) is True
        assert os.path.isfile(os.path.join(
            config["output_annotation_dir"], "alice", "user_state.json"))
        con = sqlite3.connect(os.path.join(config["task_dir"], "project.sqlite"))
        assert con.execute("SELECT body FROM memos").fetchone()[0] == "kept memo"
        con.close()

    def test_never_overwrites_a_task_that_has_data(self, tmp_path, fake_s3):
        fake_s3.objects["study/annotations/alice/user_state.json"] = b"REMOTE"
        config = s3_config(tmp_path)
        path = write_user(config, "alice", body="LOCAL")
        assert backup.restore_on_boot(config) is False
        assert open(path).read() == "LOCAL"

    def test_a_gitkeep_alone_counts_as_empty(self, tmp_path, fake_s3):
        fake_s3.objects["study/annotations/bob/user_state.json"] = b"{}"
        config = s3_config(tmp_path)
        os.makedirs(config["output_annotation_dir"])
        open(os.path.join(config["output_annotation_dir"], ".gitkeep"), "w").close()
        assert backup.restore_on_boot(config) is True

    def test_off_when_restore_on_boot_is_false(self, tmp_path, fake_s3):
        fake_s3.objects["study/annotations/alice/user_state.json"] = b"{}"
        assert backup.restore_on_boot(
            s3_config(tmp_path, restore_on_boot=False)) is False

    def test_keys_escaping_the_task_are_skipped(self, tmp_path, fake_s3):
        fake_s3.objects["study/annotations/../../evil.txt"] = b"x"
        fake_s3.objects["study/annotations/ok/user_state.json"] = b"{}"
        config = s3_config(tmp_path)
        backup.restore_on_boot(config)
        assert not (tmp_path / "evil.txt").exists()
        assert not (tmp_path / "task" / "evil.txt").exists()

    def test_restore_failure_does_not_raise(self, tmp_path, monkeypatch, caplog):
        def broken(self):
            raise RuntimeError("network down")
        monkeypatch.setattr(s3_sink.S3Sink, "client", broken)
        assert backup.restore_on_boot(s3_config(tmp_path)) is False
        assert "network down" in caplog.text


class TestRestoreProtectsEarlierWork:
    """Back up, lose the disk, boot, and the earlier annotations are there."""

    def test_round_trip_through_an_ephemeral_restart(self, tmp_path, fake_s3):
        first_boot = s3_config(tmp_path / "first")
        write_user(first_boot, "alice", body='{"items_done": 40}')
        backup.start_backups(first_boot)
        backup.flush()
        backup.reset()

        # A new container: same bucket, empty disk.
        second_boot = s3_config(tmp_path / "second")
        backup.restore_on_boot(second_boot)
        restored = os.path.join(second_boot["output_annotation_dir"],
                                "alice", "user_state.json")
        assert open(restored).read() == '{"items_done": 40}'


class FakeHub:
    """huggingface_hub stand-in: snapshot_download copies a local 'repo'."""

    def __init__(self, repo_dir):
        self.repo_dir = repo_dir
        self.schedulers = []
        hub = self

        class CommitScheduler:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                hub.schedulers.append(self)

            def stop(self):
                pass

        self.module = types.SimpleNamespace(
            CommitScheduler=CommitScheduler, snapshot_download=self.snapshot_download)

    def snapshot_download(self, repo_id, repo_type, token, local_dir):
        import shutil
        shutil.copytree(self.repo_dir, local_dir, dirs_exist_ok=True)
        os.makedirs(os.path.join(local_dir, ".cache", "huggingface"), exist_ok=True)
        open(os.path.join(local_dir, ".cache", "huggingface", "x.lock"), "w").close()
        return local_dir


@pytest.fixture
def fake_hub(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    hub = FakeHub(str(repo))
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub.module)
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    return hub


def hf_config(tmp_path):
    return make_config(tmp_path, backup={
        "sinks": [{"type": "huggingface", "repo_id": "me/task-annotations"}]})


class TestHuggingFaceSink:
    def test_two_schedulers_annotations_at_root_databases_under_prefix(
            self, tmp_path, fake_hub):
        config = hf_config(tmp_path)
        assert len(backup.start_backups(config)) == 1
        folders = {s.kwargs["folder_path"]: s.kwargs.get("path_in_repo")
                   for s in fake_hub.schedulers}
        assert folders[config["output_annotation_dir"]] is None
        assert folders[backup.snapshot_dir(config)] == "_databases"
        assert all(s.kwargs["repo_type"] == "dataset" for s in fake_hub.schedulers)

    def test_restore_skips_bundles_readme_and_cache(self, tmp_path, fake_hub):
        repo = fake_hub.repo_dir
        os.makedirs(os.path.join(repo, "alice"))
        open(os.path.join(repo, "alice", "user_state.json"), "w").write("{}")
        os.makedirs(os.path.join(repo, "_bundle"))
        open(os.path.join(repo, "_bundle", "abc.tar.gz"), "w").write("tar")
        open(os.path.join(repo, "README.md"), "w").write("# card")
        config = hf_config(tmp_path)
        assert backup.restore_on_boot(config) is True
        out = config["output_annotation_dir"]
        assert os.path.isfile(os.path.join(out, "alice", "user_state.json"))
        assert not os.path.exists(os.path.join(out, "_bundle"))
        assert not os.path.exists(os.path.join(out, "README.md"))
        assert not os.path.exists(os.path.join(out, ".cache"))

    def test_no_token_logs_and_does_not_start(self, tmp_path, fake_hub,
                                              monkeypatch, caplog):
        monkeypatch.delenv("HF_TOKEN")
        assert backup.start_backups(hf_config(tmp_path)) == []
        assert "no token" in caplog.text


class TestBootWiring:
    """Restore must run before anything reads what it restores.

    The authenticator reads the registered accounts (user_config.json) at init
    and load_all_data reads every user_state.json, so restoring after either
    leaves the annotator unable to log in, or logged in with no work.
    """

    @staticmethod
    def _call_lines(function_name):
        import ast
        import inspect

        import potato.flask_server as fs

        source = inspect.getsource(fs)
        tree = ast.parse(source)
        function = next(node for node in ast.walk(tree)
                        if isinstance(node, ast.FunctionDef)
                        and node.name == function_name)
        lines = {}
        for node in ast.walk(function):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                lines.setdefault(name, node.lineno)
        return lines

    @pytest.mark.parametrize("path", ["_initialize_from_config", "run_server"])
    def test_restore_precedes_the_authenticator_and_the_data(self, path):
        lines = self._call_lines(path)
        restore = lines["_restore_backup_before_state_loads"]
        assert restore < lines["init_from_config"]
        assert restore < lines["load_all_data"]


class TestEmptiness:
    def test_startup_bookkeeping_does_not_count_as_data(self, tmp_path, fake_s3):
        """The regression: potato.log and user_config.json are written before
        restore runs, so judging by "any file" meant restore never ran."""
        fake_s3.objects["study/annotations/alice/user_state.json"] = b"{}"
        config = s3_config(tmp_path)
        out = config["output_annotation_dir"]
        os.makedirs(os.path.join(out, "pocket"))
        for name in ("potato.log", "user_config.json", "pocket/device_visits.json"):
            open(os.path.join(out, name), "w").write("x")
        assert backup.output_is_empty(config)
        assert backup.restore_on_boot(config) is True

    def test_logs_are_not_written_back(self, tmp_path, fake_s3):
        fake_s3.objects["study/annotations/potato.log"] = b"OLD LOG"
        fake_s3.objects["study/annotations/alice/user_state.json"] = b"{}"
        config = s3_config(tmp_path)
        os.makedirs(config["output_annotation_dir"])
        log = os.path.join(config["output_annotation_dir"], "potato.log")
        open(log, "w").write("LIVE LOG")
        backup.restore_on_boot(config)
        assert open(log).read() == "LIVE LOG"

    def test_restored_accounts_overwrite_the_fresh_ones(self, tmp_path, fake_s3):
        """user_config.json holds the registered accounts; the remote copy is
        the one with the annotators in it."""
        fake_s3.objects["study/annotations/user_config.json"] = b'{"alice": 1}'
        fake_s3.objects["study/annotations/alice/user_state.json"] = b"{}"
        config = s3_config(tmp_path)
        os.makedirs(config["output_annotation_dir"])
        accounts = os.path.join(config["output_annotation_dir"], "user_config.json")
        open(accounts, "w").write("{}")
        backup.restore_on_boot(config)
        assert open(accounts).read() == '{"alice": 1}'
