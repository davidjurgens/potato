"""The SSH layer every VM provider shares.

The behaviour worth guarding is `sqlite_safe_fetch`. `project.sqlite` runs in
WAL mode with a live writer, so copying the file yields a database that is
corrupt or missing recent work — and nothing reports it. A researcher discovers
their memos and codebook are gone weeks later, with no way back. So the fetch
must refuse to fall back to a plain copy when the snapshot fails, and a test has
to hold that line.

The session is driven against a fake transport rather than a real host, which is
what lets the failure paths be exercised at all.
"""

import os

import pytest

from potato.deploy.providers.base import ProviderError
from potato.deploy.remote import (
    PULL_EXCLUDES,
    WAL_DATABASES,
    CommandResult,
    SSHSession,
)


class FakeSFTP:
    def __init__(self):
        self.fetched = []
        self.written = {}
        self.modes = {}

    def get(self, remote, local):
        self.fetched.append(remote)
        os.makedirs(os.path.dirname(os.path.abspath(local)), exist_ok=True)
        with open(local, "w") as handle:
            handle.write("payload")

    def close(self):
        pass


class FakeSession(SSHSession):
    """An SSHSession whose commands are scripted instead of executed."""

    def __init__(self, responses=None, **kwargs):
        super().__init__("203.0.113.9", **kwargs)
        self.responses = responses or {}
        self.commands = []
        self.sftp = FakeSFTP()

    def run(self, command, *, timeout=300, check=False):
        self.commands.append(command)
        for pattern, (status, out) in self.responses.items():
            if pattern in command:
                result = CommandResult(command, status, out)
                break
        else:
            result = CommandResult(command, 0, "")
        if check and not result.ok:
            raise ProviderError(f"Command failed: {command}")
        return result

    def connect(self, timeout=20):
        return self

    def open_sftp(self):
        return self.sftp

    def close(self):
        pass


class TestSqliteSafeFetch:
    def test_uses_backup_rather_than_copying(self, tmp_path):
        session = FakeSession()
        session.sqlite_safe_fetch("/app/project.sqlite",
                                  str(tmp_path / "project.sqlite"))
        backup = [c for c in session.commands if ".backup" in c]
        assert backup, "the database was copied without a snapshot"
        assert "sqlite3 /app/project.sqlite" in backup[0]

    def test_fetches_the_snapshot_not_the_live_file(self, tmp_path):
        session = FakeSession()
        session.sqlite_safe_fetch("/app/project.sqlite",
                                  str(tmp_path / "project.sqlite"))
        assert session.sftp.fetched
        assert all("/tmp/potato-snapshot" in path for path in session.sftp.fetched)
        assert "/app/project.sqlite" not in session.sftp.fetched

    def test_refuses_to_fall_back_to_a_plain_copy(self, tmp_path):
        """The whole point. A silent plain copy is unrecoverable data loss."""
        session = FakeSession({".backup": (1, "database is locked")})
        with pytest.raises(ProviderError, match="silent"):
            session.sqlite_safe_fetch("/app/project.sqlite",
                                      str(tmp_path / "project.sqlite"))
        assert not session.sftp.fetched

    def test_a_missing_database_is_not_an_error(self, tmp_path):
        """A task with no codebook has no project.sqlite; that is normal."""
        session = FakeSession({"test -f": (1, "")})
        assert session.sqlite_safe_fetch("/app/project.sqlite",
                                         str(tmp_path / "p.sqlite")) is False

    def test_the_snapshot_is_cleaned_up(self, tmp_path):
        session = FakeSession()
        session.sqlite_safe_fetch("/app/project.sqlite", str(tmp_path / "p.sqlite"))
        assert any(c.startswith("rm -f /tmp/potato-snapshot")
                   for c in session.commands)

    def test_both_databases_are_covered(self):
        assert "project.sqlite" in WAL_DATABASES
        assert "datasets.sqlite" in WAL_DATABASES


class TestPullExcludes:
    def test_skips_the_regenerable_cache(self):
        assert ".item_cache.sqlite" in PULL_EXCLUDES

    def test_never_downloads_the_admin_key(self):
        assert "admin_api_key.txt" in PULL_EXCLUDES


class TestWaits:
    def test_ssh_wait_reports_the_last_error(self, monkeypatch):
        """"it hangs" is the complaint this message exists to prevent."""
        monkeypatch.setattr("potato.deploy.remote.time.sleep", lambda _s: None)

        class NeverConnects(SSHSession):
            def connect(self, timeout=20):
                raise OSError("Connection refused")

        session = NeverConnects("203.0.113.9")
        with pytest.raises(ProviderError, match="Connection refused"):
            session.wait_for_ssh(timeout=0.1, interval=0)

    def test_cloud_init_success_is_quiet(self):
        session = FakeSession({"cloud-init status": (0, "status: done")})
        session.wait_for_cloud_init()

    def test_cloud_init_failure_surfaces_the_log(self):
        """The status code alone says nothing about what broke."""
        session = FakeSession({
            "cloud-init status": (0, "status: error"),
            "cloud-init-output.log": (0, "E: Unable to locate package docker-ce"),
        })
        with pytest.raises(ProviderError, match="Unable to locate package"):
            session.wait_for_cloud_init()

    def test_http_wait_returns_false_rather_than_raising(self, monkeypatch):
        """The caller wants to attach service logs to its own error."""
        monkeypatch.setattr("potato.deploy.remote.time.sleep", lambda _s: None)
        import requests
        monkeypatch.setattr(
            requests, "get",
            lambda *a, **k: (_ for _ in ()).throw(requests.RequestException("x")))
        assert SSHSession("h").wait_for_http("https://h/health", timeout=0.1,
                                             interval=0) is False


class TestPutText:
    def test_environment_file_is_written_0600(self, monkeypatch):
        """It carries the Flask signing key and the admin API key."""
        recorded = {}

        class RecordingFile:
            def chmod(self, mode):
                recorded["mode"] = mode

            def write(self, content):
                recorded["content"] = content

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        class RecordingSFTP(FakeSFTP):
            def file(self, path, mode):
                recorded["path"] = path
                return RecordingFile()

        session = FakeSession()
        session.sftp = RecordingSFTP()
        session.put_text("POTATO_SECRET_KEY=abc\n", "/opt/potato/potato.env",
                         mode=0o600)
        assert recorded["mode"] == 0o600
        assert recorded["path"] == "/opt/potato/potato.env"

    def test_mode_is_set_before_the_content(self, monkeypatch):
        """Otherwise the secret is world-readable for the length of the write."""
        order = []

        class OrderedFile:
            def chmod(self, mode):
                order.append("chmod")

            def write(self, content):
                order.append("write")

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        class OrderedSFTP(FakeSFTP):
            def file(self, path, mode):
                return OrderedFile()

        session = FakeSession()
        session.sftp = OrderedSFTP()
        session.put_text("secret", "/opt/potato/potato.env", mode=0o600)
        assert order == ["chmod", "write"]


class TestKeypair:
    def test_generates_an_ed25519_pair(self):
        pytest.importorskip("paramiko")
        from potato.deploy.remote import generate_keypair
        private, public = generate_keypair("potato-pilot")
        assert "PRIVATE KEY" in private
        assert public.startswith("ssh-ed25519 ")
        assert public.endswith(" potato-pilot")

    def test_each_call_is_a_fresh_key(self):
        """A deployment must be revocable without affecting any other."""
        pytest.importorskip("paramiko")
        from potato.deploy.remote import generate_keypair
        assert generate_keypair()[1] != generate_keypair()[1]


class TestParamikoIsOptional:
    def test_a_helpful_error_when_it_is_missing(self, monkeypatch):
        import builtins
        real_import = builtins.__import__

        def refuse(name, *args, **kwargs):
            if name == "paramiko":
                raise ImportError("no module named paramiko")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", refuse)
        from potato.deploy.remote import _paramiko
        with pytest.raises(ProviderError, match=r"potato-annotation\[deploy\]"):
            _paramiko()
