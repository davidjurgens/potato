"""Security reports triaged on 2026-11-04.

Generated templates: with the package directory read-only, generated Jinja
templates went to a predictably named directory in the shared temp dir, made
with no owner or mode check. Another local user could create it first and
plant a template the server would render as the Potato user.

Debug mode on the container path (gunicorn on create_app, bound to 0.0.0.0)
let an anonymous remote caller mint any user's password-reset token. Fixed in a14b7097 (2.11.1); this pins it end to end.

Found while there: the generated admin API key was written with the umask's
mode, and logged in full when the file could not be written; the deploy
uploaded its bundle and snapshotted databases under fixed names in the
host's /tmp.
"""

import logging
import os
import stat

import pytest

from potato.server_utils import generated_templates
from potato.server_utils.generated_templates import (
    ENV_VAR,
    resolve_generated_templates_dir,
)

POSIX = hasattr(os, "geteuid")
not_root = pytest.mark.skipif(not POSIX or os.geteuid() == 0,
                              reason="needs a non-root POSIX user")


@pytest.fixture
def readonly_package(tmp_path, monkeypatch):
    """A read-only package templates dir, with the shared temp dir pointed
    at a directory this test owns."""
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setattr(generated_templates, "_logged", False)
    monkeypatch.setattr(generated_templates, "_private_fallbacks", {}, raising=False)
    shared = tmp_path / "shared-tmp"
    shared.mkdir()
    monkeypatch.setattr(generated_templates.tempfile, "tempdir", str(shared))
    package = tmp_path / "site-packages" / "potato" / "templates"
    package.mkdir(parents=True)
    package.chmod(stat.S_IRUSR | stat.S_IXUSR)
    yield str(package), shared
    package.chmod(stat.S_IRWXU)


def _predicted(package):
    """The name another local user computes from the install path."""
    return generated_templates._fallback_dir(package)


@not_root
class TestGeneratedTemplatesInTheSharedTempDir:
    def test_the_fallback_is_private_to_this_user(self, readonly_package):
        package, shared = readonly_package
        chosen = resolve_generated_templates_dir(package)
        info = os.lstat(chosen)
        assert stat.S_IMODE(info.st_mode) == 0o700
        assert info.st_uid == os.geteuid()
        assert os.path.dirname(chosen) == str(shared)
        assert str(os.geteuid()) in os.path.basename(chosen)

    def test_a_directory_others_can_write_is_not_used(self, readonly_package, caplog):
        """The report's proof of concept: pre-create the directory, plant a
        template, wait for the server to render it."""
        package, _ = readonly_package
        planted = _predicted(package)
        os.mkdir(planted)
        os.chmod(planted, 0o777)
        with open(os.path.join(planted, "task-annotation.html"), "w") as handle:
            handle.write("{{ cycler.__init__.__globals__.os.popen('id').read() }}")
        with caplog.at_level(logging.WARNING):
            chosen = resolve_generated_templates_dir(package)
        assert chosen != planted
        assert os.listdir(chosen) == []
        assert stat.S_IMODE(os.lstat(chosen).st_mode) == 0o700
        assert any("other users can write to it" in r.getMessage() for r in caplog.records)

    def test_the_loader_reads_where_the_generator_wrote(self, readonly_package):
        """The loader asks with create=False; it must get the private
        directory too, not the planted one."""
        package, _ = readonly_package
        planted = _predicted(package)
        os.mkdir(planted)
        os.chmod(planted, 0o777)
        writer = resolve_generated_templates_dir(package)
        reader = resolve_generated_templates_dir(package, create=False)
        assert reader == writer != planted

    def test_a_symlink_is_not_followed(self, readonly_package, tmp_path):
        package, _ = readonly_package
        target = tmp_path / "attacker-dir"
        target.mkdir(mode=0o700)
        os.symlink(str(target), _predicted(package))
        chosen = resolve_generated_templates_dir(package)
        assert os.path.realpath(chosen) != str(target)

    def test_a_directory_another_user_owns_is_not_used(self, readonly_package, monkeypatch):
        package, _ = readonly_package
        planted = _predicted(package)
        os.mkdir(planted, 0o700)
        real = os.geteuid()
        # The directory now reads as someone else's: this process is "another
        # user" whose name happens to match.
        monkeypatch.setattr(generated_templates, "_fallback_dir", lambda _p: planted)
        monkeypatch.setattr(os, "geteuid", lambda: real + 1)
        chosen = resolve_generated_templates_dir(package)
        assert chosen != planted

    def test_this_users_loosened_directory_is_reused_and_closed(self, readonly_package):
        """Potato makes it 0700; this user may have opened it to reading since
        (0755). Nobody else can write to it, so it is kept, closed again, and
        the cache survives."""
        package, _ = readonly_package
        mine = _predicted(package)
        os.mkdir(mine, 0o700)
        os.chmod(mine, 0o755)
        with open(os.path.join(mine, "task.html"), "w") as handle:
            handle.write("<html></html>")
        assert resolve_generated_templates_dir(package) == mine
        assert stat.S_IMODE(os.lstat(mine).st_mode) == 0o700
        assert os.path.isfile(os.path.join(mine, "task.html"))

    def test_a_temp_dir_anyone_can_rename_in_is_refused(self, readonly_package):
        """World-writable without the sticky bit: another user could rename
        the checked directory away and put their own in its place."""
        package, shared = readonly_package
        shared.chmod(0o777)
        with pytest.raises(RuntimeError, match=ENV_VAR):
            resolve_generated_templates_dir(package)
        shared.chmod(0o1777)   # /tmp's usual mode
        assert stat.S_IMODE(os.lstat(resolve_generated_templates_dir(package)).st_mode) == 0o700
        shared.chmod(0o700)


@not_root
class TestGeneratedTemplatesOnWindows:
    def test_a_per_user_temp_dir_is_reused_without_mode_checks(self, readonly_package,
                                                               monkeypatch):
        """Windows stats every directory as 0o777 and has no geteuid; the
        owner and mode checks would send every boot to a new mkdtemp."""
        package, _ = readonly_package
        monkeypatch.delattr(os, "geteuid", raising=False)
        first = resolve_generated_templates_dir(package)
        os.chmod(first, 0o777)
        generated_templates._private_fallbacks.clear()
        assert resolve_generated_templates_dir(package) == first
        assert not generated_templates._private_fallbacks


@pytest.fixture
def fresh_key_cache(monkeypatch):
    from potato.server_utils import admin_key
    monkeypatch.setattr(admin_key, "_generated_admin_api_key", None)
    monkeypatch.delenv("POTATO_ADMIN_API_KEY", raising=False)
    return admin_key


class TestGeneratedAdminKey:
    @pytest.mark.skipif(not POSIX, reason="POSIX file modes")
    def test_the_key_file_is_readable_by_its_owner_only(self, tmp_path, fresh_key_cache):
        key = fresh_key_cache.get_admin_api_key({"task_dir": str(tmp_path)})
        path = tmp_path / "admin_api_key.txt"
        assert path.read_text() == key
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    @pytest.mark.skipif(not POSIX, reason="POSIX file modes")
    def test_an_older_world_readable_key_file_is_tightened(self, tmp_path, fresh_key_cache):
        path = tmp_path / "admin_api_key.txt"
        path.write_text("older-key")
        path.chmod(0o644)
        assert fresh_key_cache.get_admin_api_key({"task_dir": str(tmp_path)}) == "older-key"
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_a_key_that_cannot_be_saved_is_not_logged(self, tmp_path, fresh_key_cache,
                                                      caplog):
        missing = tmp_path / "no-such-dir"
        with caplog.at_level(logging.DEBUG, logger="potato"):
            key = fresh_key_cache.get_admin_api_key({"task_dir": str(missing)})
        text = "\n".join(r.getMessage() for r in caplog.records)
        assert key and key not in text
        assert "POTATO_ADMIN_API_KEY" in text


class TestDeployHostTempFiles:
    def _session(self):
        from tests.unit.test_deploy_remote import FakeSession
        return FakeSession()

    def test_the_snapshot_has_an_unguessable_name_and_a_private_mode(self, tmp_path):
        names = set()
        for _ in range(2):
            session = self._session()
            session.sqlite_safe_fetch("/app/project.sqlite", str(tmp_path / "p.sqlite"))
            (backup,) = [c for c in session.commands if ".backup" in c]
            assert backup.startswith("umask 077 && ")
            names.update(session.sftp.fetched)
        assert len(names) == 2

    def test_the_bundle_is_uploaded_mode_0600_under_an_unguessable_name(self, tmp_path):
        order, paths, modes = [], [], []

        class File:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def chmod(self, mode):
                order.append(("chmod", mode))

            def write(self, data):
                order.append("write")

        class SFTP:
            def file(self, path, mode):
                paths.append(path)
                modes.append(mode)
                return File()

            def close(self):
                pass

        (tmp_path / "bundle").mkdir()
        (tmp_path / "bundle" / "config.yaml").write_text("x: 1\n")
        for _ in range(2):
            session = self._session()
            session.sftp = SFTP()
            session.put_archive(str(tmp_path / "bundle"), "/opt/potato/app")
        assert order[0] == ("chmod", 0o600) and "write" in order
        assert len(set(paths)) == 2
        assert all(p.startswith("/tmp/potato-bundle-") for p in paths)
        # Exclusive create: a file already at the name is an error.
        assert all("x" in m and "w" in m for m in modes)


class TestPullOnANonRootLogin:
    """A host whose login is not root (Ubuntu on EC2, Lightsail, OpenStack).

    `deploy pull` runs tar and sqlite3 there as root through sudo, then
    downloads the result over SFTP as the login. The pull archive was made
    mode 644, readable by every user on the host. The snapshot went the other
    way: under umask 077 it was root's alone, so the login could not download
    it and every pull of a database failed.

    The commands run for real in a local shell standing in for the host,
    with /tmp and /app mapped into tmp_path. Files a command makes belong to
    root unless it chowns them; chown is a shim that records the new owner.
    The fake SFTP reads a file only as the host would let the login read it.
    """

    LOGIN = "ubuntu"

    def _host(self, tmp_path):
        import shlex
        import shutil
        import subprocess
        from potato.deploy.providers.base import ProviderError
        from potato.deploy.remote import CommandResult
        from tests.unit.test_deploy_remote import FakeSession

        roots = {"/tmp/": str(tmp_path / "tmp") + "/", "/app": str(tmp_path / "app")}
        for path in roots.values():
            os.makedirs(path, exist_ok=True)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        chowned = tmp_path / "chowned.log"
        (bin_dir / "chown").write_text(
            f'#!/bin/sh\necho "$1 $2" >> {shlex.quote(str(chowned))}\n')
        (bin_dir / "chown").chmod(0o755)

        def local(path):
            for remote, here in roots.items():
                path = path.replace(remote, here)
            return path

        def owner(path):
            lines = chowned.read_text().splitlines() if chowned.exists() else []
            owners = {line.split(" ", 1)[1]: line.split(" ", 1)[0] for line in lines}
            return owners.get(path, "root")

        login = self.LOGIN
        fetched_modes = []

        class SFTP:
            fetched = []

            def get(self, remote, local_path):
                path = local(remote)
                mode = stat.S_IMODE(os.stat(path).st_mode)
                readable = (mode & 0o004) or (owner(path) == login and mode & 0o400)
                if not readable:
                    raise PermissionError(f"{login} cannot read {remote}")
                fetched_modes.append(mode)
                self.fetched.append(remote)
                shutil.copy(path, local_path)

            def close(self):
                pass

        class Host(FakeSession):
            def run(self, command, *, timeout=300, check=False):
                self.commands.append(command)
                env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
                done = subprocess.run(["sh", "-c", local(command)], env=env,
                                      capture_output=True, text=True)
                result = CommandResult(command, done.returncode, done.stdout, done.stderr)
                if check and not result.ok:
                    raise ProviderError(f"{command}: {done.stderr}")
                return result

        session = Host(username=login)
        session.sftp = SFTP()
        return session, roots["/app"], fetched_modes

    @not_root
    def test_the_database_snapshot_is_private_and_the_login_can_download_it(self, tmp_path):
        import sqlite3
        session, app, modes = self._host(tmp_path)
        with sqlite3.connect(os.path.join(app, "project.sqlite")) as db:
            db.execute("create table memos (text)")
            db.execute("insert into memos values ('kept')")
        out = tmp_path / "pulled.sqlite"
        assert session.sqlite_safe_fetch("/app/project.sqlite", str(out)) is True
        assert modes == [0o600]
        with sqlite3.connect(out) as db:
            assert db.execute("select text from memos").fetchall() == [("kept",)]

    @not_root
    def test_the_pull_archive_is_private_and_the_login_can_download_it(self, tmp_path):
        session, app, modes = self._host(tmp_path)
        os.makedirs(os.path.join(app, "annotation_output", "u1"))
        with open(os.path.join(app, "annotation_output", "u1", "user_state.json"), "w") as handle:
            handle.write("{}")
        written = session.fetch_dir("/app/annotation_output", str(tmp_path / "pulled"))
        assert modes == [0o600]
        assert os.path.join("u1", "user_state.json") in written


def test_debug_on_the_container_path_does_not_mint_reset_tokens_for_strangers():
    """The report's steps: debug: true, gunicorn's create_app,
    an unauthenticated POST /admin/create_reset_token from another machine."""
    from tests.unit.test_boot_paths_init_parity import _boot_factory_and_run, _write_config
    path = _write_config("ghsa_366p", {"debug": True,
                                       "user_config": {"allow_all_users": True}})
    out = _boot_factory_and_run(path, (
        "from potato.authentication import UserAuthenticator\n"
        "UserAuthenticator.get_instance().add_single_user("
        "{'username': 'victim', 'password': 'pw'})\n"
        "def post(addr, headers=None):\n"
        "    r = client.post('/admin/create_reset_token', json={'username': 'victim'},\n"
        "                    environ_base={'REMOTE_ADDR': addr}, headers=headers or {})\n"
        "    return [r.status_code, 'token' in (r.get_json(silent=True) or {})]\n"
        "out['remote'] = post('203.0.113.7')\n"
        "out['forwarded'] = post('127.0.0.1', {'X-Forwarded-For': '203.0.113.7'})\n"
        "out['local'] = post('127.0.0.1')\n"))
    assert out["remote"] == [403, False]
    assert out["forwarded"] == [403, False]
    # Debug still serves the developer on this machine.
    assert out["local"] == [200, True]
