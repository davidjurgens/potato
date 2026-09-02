"""The admin data archive, and the pull that consumes it.

This is the transport of last resort: the only one available on a Space, a
Render service, or anything serverless, which are also the hosts most likely to
lose their disk. So the properties worth guarding are what it includes, what it
must never include, and that the SQLite snapshot is a real snapshot rather than
a file copy.

The copy-versus-snapshot distinction is the one that costs data. A WAL-mode
database copied while a writer holds it is corrupt or stale and says nothing
about it; the loss surfaces weeks later.
"""

import io
import os
import sqlite3
import tarfile

import pytest

from potato.deploy.providers.base import ProviderError
from potato.deploy.pull import _safe_extract, verify_pull
from potato.server_utils.data_archive import (
    DATABASES,
    EXCLUDED_NAMES,
    archive_manifest,
    build_archive,
    collect_entries,
    snapshot_sqlite,
    stream_archive,
)


@pytest.fixture
def task(tmp_path):
    """A task directory that looks like one a real study leaves behind."""
    output = tmp_path / "annotation_output"
    for annotator in ("alice", "bob"):
        directory = output / annotator
        directory.mkdir(parents=True)
        (directory / "user_state.json").write_text('{"user_id": "%s"}' % annotator)
        (directory / "annotated_instances.jsonl").write_text('{"id": "1"}\n')
    (output / "potato.log").write_text("started\n")

    # A credential and a regenerable cache, neither of which may travel.
    (tmp_path / "admin_api_key.txt").write_text("SECRET-ADMIN-KEY")
    (output / "admin_api_key.txt").write_text("SECRET-ADMIN-KEY")
    (tmp_path / ".item_cache.sqlite").write_bytes(b"cache")

    database = tmp_path / "project.sqlite"
    connection = sqlite3.connect(str(database))
    connection.execute("CREATE TABLE memos (id INTEGER PRIMARY KEY, body TEXT)")
    connection.execute("INSERT INTO memos (body) VALUES ('a memo')")
    connection.commit()
    connection.close()
    return tmp_path, output


class TestSnapshot:
    def test_produces_a_valid_database(self, task):
        task_dir, _output = task
        target = task_dir / "copy.sqlite"
        assert snapshot_sqlite(str(task_dir / "project.sqlite"), str(target))
        connection = sqlite3.connect(str(target))
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT body FROM memos").fetchone()[0] == "a memo"
        connection.close()

    def test_captures_writes_still_in_the_wal(self, task):
        """The reason a file copy is wrong.

        In WAL mode a committed row can live in the -wal sidecar rather than the
        main file. `.backup` sees it; `shutil.copy` of the .sqlite alone does not.
        """
        task_dir, _output = task
        source = task_dir / "wal.sqlite"
        connection = sqlite3.connect(str(source))
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE t (v TEXT)")
        connection.execute("INSERT INTO t VALUES ('committed')")
        connection.commit()
        # Deliberately left open, holding the WAL, as a running server would.
        try:
            target = task_dir / "wal-copy.sqlite"
            assert snapshot_sqlite(str(source), str(target))
            copied = sqlite3.connect(str(target))
            assert copied.execute("SELECT v FROM t").fetchone()[0] == "committed"
            copied.close()
        finally:
            connection.close()

    def test_a_missing_database_is_not_an_error(self, tmp_path):
        """A task with no memos and no codebook has no project.sqlite."""
        assert snapshot_sqlite(str(tmp_path / "nope.sqlite"),
                               str(tmp_path / "out.sqlite")) is False

    def test_both_databases_are_covered(self):
        assert set(DATABASES) == {"project.sqlite", "datasets.sqlite"}


class TestArchiveContents:
    def _names(self, task):
        task_dir, output = task
        buffer = io.BytesIO()
        build_archive(str(output), str(task_dir), buffer)
        buffer.seek(0)
        with tarfile.open(fileobj=buffer, mode="r:gz") as archive:
            return archive.getnames()

    def test_carries_every_annotator(self, task):
        names = self._names(task)
        assert any("alice/user_state.json" in n for n in names)
        assert any("bob/user_state.json" in n for n in names)

    def test_carries_the_log(self, task):
        assert any(n.endswith("potato.log") for n in self._names(task))

    def test_carries_the_project_database(self, task):
        assert "project.sqlite" in self._names(task)

    def test_never_carries_the_admin_key(self, task):
        """It is the credential guarding this very endpoint."""
        assert not any("admin_api_key" in n for n in self._names(task))

    def test_never_carries_the_item_cache(self, task):
        """Regenerable from the data files, and often the largest file there."""
        assert not any("item_cache" in n for n in self._names(task))

    def test_the_archive_is_a_valid_tarball(self, task):
        task_dir, output = task
        buffer = io.BytesIO()
        result = build_archive(str(output), str(task_dir), buffer)
        assert result["files"] > 0
        buffer.seek(0)
        with tarfile.open(fileobj=buffer, mode="r:gz") as archive:
            assert archive.getmembers()

    def test_a_locked_database_costs_only_itself(self, task, monkeypatch):
        """The annotation files are the larger loss and must still come back."""
        def refuse(source, destination):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr("potato.server_utils.data_archive.snapshot_sqlite",
                            refuse)
        task_dir, output = task
        buffer = io.BytesIO()
        result = build_archive(str(output), str(task_dir), buffer)
        assert any("snapshot failed" in s for s in result["skipped"])
        assert result["files"] > 0

    def test_excluded_names_include_the_credential(self):
        assert "admin_api_key.txt" in EXCLUDED_NAMES


class TestManifest:
    def test_counts_files_without_building_the_archive(self, task):
        task_dir, output = task
        manifest = archive_manifest(str(output), str(task_dir))
        assert manifest["files"] > 0
        assert manifest["bytes"] > 0

    def test_lists_the_databases(self, task):
        task_dir, output = task
        manifest = archive_manifest(str(output), str(task_dir))
        assert [d["name"] for d in manifest["databases"]] == ["project.sqlite"]

    def test_an_empty_task_reports_zero(self, tmp_path):
        empty = tmp_path / "annotation_output"
        empty.mkdir()
        assert archive_manifest(str(empty), str(tmp_path))["files"] == 0


class TestStreaming:
    def test_yields_the_whole_archive(self, task):
        task_dir, output = task
        chunks = list(stream_archive(str(output), str(task_dir)))
        blob = b"".join(chunks)
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
            assert archive.getnames()

    def test_does_not_hold_it_all_in_memory(self, task):
        """A study with media makes an archive larger than a small container's RAM."""
        import inspect
        from potato.server_utils import data_archive
        source = inspect.getsource(data_archive.stream_archive)
        assert "SpooledTemporaryFile" in source


class TestSafeExtract:
    def test_refuses_a_path_that_escapes_the_destination(self, tmp_path):
        """This runs on the researcher's laptop with their own privileges."""
        archive_path = tmp_path / "evil.tar.gz"
        payload = tmp_path / "payload"
        payload.write_text("owned")
        with tarfile.open(archive_path, "w:gz") as archive:
            archive.add(payload, arcname="../../escaped.txt")

        with pytest.raises(ProviderError, match="outside the destination"):
            _safe_extract(str(archive_path), str(tmp_path / "dest"))

    def test_refuses_a_symlink(self, tmp_path):
        archive_path = tmp_path / "link.tar.gz"
        with tarfile.open(archive_path, "w:gz") as archive:
            info = tarfile.TarInfo("link")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            archive.addfile(info)

        with pytest.raises(ProviderError, match="link"):
            _safe_extract(str(archive_path), str(tmp_path / "dest"))

    def test_extracts_an_ordinary_archive(self, task, tmp_path):
        task_dir, output = task
        archive_path = tmp_path / "ok.tar.gz"
        with open(archive_path, "wb") as handle:
            build_archive(str(output), str(task_dir), handle)
        written = _safe_extract(str(archive_path), str(tmp_path / "dest"))
        assert written


class TestVerifyPull:
    def test_counts_annotators(self, task, tmp_path):
        task_dir, output = task
        dest = tmp_path / "pulled"
        archive_path = tmp_path / "a.tar.gz"
        with open(archive_path, "wb") as handle:
            build_archive(str(output), str(task_dir), handle)
        _safe_extract(str(archive_path), str(dest))

        verification = verify_pull(str(dest))
        assert verification.annotators == 2
        assert verification.ok

    def test_an_empty_result_is_not_ok(self, tmp_path):
        dest = tmp_path / "empty"
        dest.mkdir()
        verification = verify_pull(str(dest))
        assert not verification.ok
        assert any("Nothing was downloaded" in w for w in verification.warnings)

    def test_a_corrupt_database_is_reported(self, tmp_path):
        """The failure mode the whole snapshot rule exists to prevent."""
        dest = tmp_path / "pulled"
        dest.mkdir()
        (dest / "project.sqlite").write_bytes(b"not a database at all")
        (dest / "user_state.json").write_text("{}")
        verification = verify_pull(str(dest))
        assert "project.sqlite" in verification.corrupt
        assert not verification.ok

    def test_verifying_a_snapshot_leaves_no_wal_sidecars(self, tmp_path):
        """Checking the snapshot must not deposit the files it exists to avoid.

        A read-only connection to a WAL-mode database still builds a
        shared-memory index, so the integrity check used to leave
        `project.sqlite-wal` and `project.sqlite-shm` beside the snapshot it
        had just verified. Those are the live sidecars the whole
        snapshot-rather-than-copy rule exists to keep out of a pulled
        directory, and finding them in the copy labelled safe is exactly the
        wrong signal.
        """
        import sqlite3

        dest = tmp_path / "pulled"
        dest.mkdir()
        database = dest / "project.sqlite"
        connection = sqlite3.connect(str(database))
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE memo (id INTEGER PRIMARY KEY, body TEXT)")
        connection.execute("INSERT INTO memo (body) VALUES ('kept')")
        connection.commit()
        connection.close()
        for sidecar in ("project.sqlite-wal", "project.sqlite-shm"):
            (dest / sidecar).unlink(missing_ok=True)
        (dest / "user_state.json").write_text("{}")

        verification = verify_pull(str(dest))

        assert "project.sqlite" not in verification.corrupt
        stray = sorted(f.name for f in dest.iterdir()
                       if f.name.startswith("project.sqlite-"))
        assert stray == [], f"verification left {stray} beside the snapshot"

    def test_files_without_annotators_is_called_out(self, tmp_path):
        """Files arrived, so the transport worked; the path must be wrong."""
        dest = tmp_path / "pulled"
        dest.mkdir()
        (dest / "notes.txt").write_text("hello")
        verification = verify_pull(str(dest))
        assert any("no annotator" in w for w in verification.warnings)


class TestRoutes:
    """The endpoint itself, through the real app."""

    @pytest.fixture(scope="class")
    def client(self):
        from potato.flask_server import create_app
        app = create_app("examples/classification/single-choice/config.yaml")
        return app.test_client()

    @pytest.fixture(scope="class")
    def admin_key(self):
        from potato.server_utils.admin_key import get_admin_api_key
        from potato.server_utils.config_module import config
        return get_admin_api_key(config)

    @pytest.fixture(autouse=True)
    def debug_off(self, monkeypatch):
        """Force debug off for the whole class.

        `validate_admin_api_key` returns True unconditionally when `debug` is
        set, so a leftover `debug: True` in the process-global config turns
        every assertion below into a false pass. Another unit test does leave
        one behind, which is how this was found.
        """
        from potato.server_utils.config_module import config
        monkeypatch.setitem(config, "debug", False)

    @pytest.mark.parametrize("path", ["/admin/api/data/manifest",
                                      "/admin/api/data/archive"])
    def test_requires_the_admin_key(self, client, path):
        assert client.get(path).status_code == 403

    @pytest.mark.parametrize("path", ["/admin/api/data/manifest",
                                      "/admin/api/data/archive"])
    def test_rejects_a_wrong_key(self, client, path):
        assert client.get(path, headers={"X-API-Key": "nope"}).status_code == 403

    def test_manifest_reports_the_task(self, client, admin_key):
        payload = client.get("/admin/api/data/manifest",
                             headers={"X-API-Key": admin_key}).get_json()
        assert payload["task_name"]
        assert payload["files"] >= 0

    def test_archive_downloads_as_a_file(self, client, admin_key):
        response = client.get("/admin/api/data/archive",
                              headers={"X-API-Key": admin_key})
        assert response.status_code == 200
        assert response.headers["Content-Type"] == "application/gzip"
        assert "attachment" in response.headers["Content-Disposition"]
        assert response.headers["Cache-Control"] == "no-store"

    def test_archive_is_openable_and_holds_a_valid_database(self, client, admin_key,
                                                            tmp_path):
        response = client.get("/admin/api/data/archive",
                              headers={"X-API-Key": admin_key})
        with tarfile.open(fileobj=io.BytesIO(response.get_data()),
                          mode="r:gz") as archive:
            names = archive.getnames()
            archive.extractall(tmp_path)
        assert names
        database = tmp_path / "project.sqlite"
        if database.exists():
            connection = sqlite3.connect(str(database))
            assert connection.execute(
                "PRAGMA integrity_check").fetchone()[0] == "ok"
            connection.close()

    def test_debug_mode_opens_the_archive_to_anyone(self, client):
        """Stated because it is load-bearing, not because it is desirable.

        `validate_admin_api_key` short-circuits on `debug`, so a debug server
        serves the whole study's data to an unauthenticated request. Preflight
        blocks `debug: true` for any public deploy for this reason.
        """
        from potato.server_utils.config_module import config

        original = config.get("debug", False)
        config["debug"] = True
        try:
            assert client.get("/admin/api/data/manifest").status_code == 200
        finally:
            config["debug"] = original

    def test_preflight_blocks_a_debug_deploy(self, tmp_path):
        """Which is what keeps the above from mattering in practice."""
        import yaml
        from potato.deploy.preflight import run_preflight

        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.safe_dump({
            "task_dir": ".", "debug": True,
            "annotation_task_name": "t",
            "data_files": ["data/items.json"],
            "output_annotation_dir": "annotation_output/",
            "item_properties": {"id_key": "id", "text_key": "text"},
            "annotation_schemes": [{"annotation_type": "radio", "name": "s",
                                    "description": "d", "labels": ["a", "b"]}],
        }))
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "items.json").write_text('[{"id":"1","text":"x"}]')

        report = run_preflight(str(config_path), provider="render", public=True)
        assert not report.ok
        assert any(f.code == "D002" for f in report.findings)

    def test_routes_are_registered_for_the_live_server(self):
        """A module-level @app.route alone 404s on a `potato start` server.

        Read as text rather than imported: importing routes.py a second time
        re-runs its decorators against an app that has already served a request,
        which Flask refuses.
        """
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        with open(os.path.join(root, "potato", "routes.py")) as handle:
            source = handle.read()
        for name in ("admin_api_data_manifest", "admin_api_data_archive"):
            assert f'"{name}", {name}' in source, (
                f"{name} must be registered in configure_routes with "
                "add_url_rule, or it 404s on the live server")
