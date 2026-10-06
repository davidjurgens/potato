"""The shared VM half: where the task lives, cloud-init, and non-root SSH.

The volume regression: with --volume-gb the volume was mounted at DATA_DIR but
the task, and so every annotation, stayed in APP_DIR on the root disk. The
volume held only TLS certificates, and the documentation said otherwise.
"""

import io
import os
import tarfile

import pytest
import yaml

from potato.deploy.providers.base import DeploySpec, ProviderError
from potato.deploy.providers.vm_base import (
    APP_DIR,
    DATA_DIR,
    VOLUME_APP_DIR,
    app_dir_for,
    build_cloud_init,
    record_app_dir,
)
from potato.deploy.remote import SSHSession, _safe_extract
from potato.deploy.state import DeploymentRecord


def spec(**kwargs):
    return DeploySpec(name="pilot", config_path="/tmp/x/config.yaml", **kwargs)


def runcmd(user_data):
    """cloud-init runcmd entries, flattened to strings."""
    document = yaml.safe_load(user_data)
    return [" ".join(map(str, step)) if isinstance(step, list) else step
            for step in document["runcmd"]]


class TestWhereTheTaskLives:
    def test_without_a_volume_it_is_the_root_disk(self):
        assert app_dir_for(False) == APP_DIR

    def test_with_a_volume_it_is_on_the_volume(self):
        assert VOLUME_APP_DIR.startswith(DATA_DIR + "/")
        assert app_dir_for(True) == VOLUME_APP_DIR

    def test_the_container_mounts_the_volume_task_dir(self):
        user_data = build_cloud_init(spec(), public_host="1.2.3.4",
                                     volume_device="/dev/sdb")
        assert f"-v {VOLUME_APP_DIR}:/app" in user_data

    def test_the_volume_script_creates_the_task_dir_after_mounting(self):
        """Created before, it would sit on the root disk under the mount point."""
        from potato.deploy.providers.vm_base import prepare_volume_script

        lines = prepare_volume_script(["/dev/sdb"], VOLUME_APP_DIR).splitlines()
        mount = next(i for i, s in enumerate(lines) if s.strip().startswith("mount "))
        mkdir = next(i for i, s in enumerate(lines) if VOLUME_APP_DIR in s
                     and s.startswith("mkdir"))
        assert mkdir > mount

    def test_the_volume_is_prepared_before_the_upload(self):
        """The upload lands in the task dir, which must already be on the volume."""
        import ast
        import inspect

        from potato.deploy.providers import vm_base

        source = inspect.getsource(vm_base)
        function = next(n for n in ast.walk(ast.parse(source))
                        if isinstance(n, ast.FunctionDef) and n.name == "_configure_host")
        body = ast.get_source_segment(source, function)
        assert body.index("prepare_volume_script") < body.index("put_archive")

    def test_a_deployment_made_before_the_fix_keeps_its_layout(self):
        """Its annotations are in APP_DIR; moving the upload would orphan them."""
        legacy = DeploymentRecord(name="old", provider="digitalocean",
                                  provider_ref={"droplet_id": 1})
        assert record_app_dir(legacy) == APP_DIR

    def test_new_deployments_record_their_layout(self):
        record = DeploymentRecord(name="new", provider="digitalocean",
                                  provider_ref={"app_dir": VOLUME_APP_DIR})
        assert record_app_dir(record) == VOLUME_APP_DIR


class FakeChannel:
    def __init__(self, status=0):
        self._status = status

    def recv_exit_status(self):
        return self._status


class FakeStream(io.BytesIO):
    def __init__(self, data=b"", status=0):
        super().__init__(data)
        self.channel = FakeChannel(status)


class FakeSFTPFile(io.StringIO):
    def __init__(self, store, path):
        super().__init__()
        self.store, self.path, self.mode = store, path, None

    def chmod(self, mode):
        self.mode = mode

    def __exit__(self, *exc):
        self.store[self.path] = (self.getvalue(), self.mode)
        return False


class FakeSFTP:
    def __init__(self, files):
        self.files = files

    def file(self, path, mode):
        return FakeSFTPFile(self.files, path)

    def close(self):
        pass


class FakeClient:
    def __init__(self):
        self.commands = []
        self.files = {}

    def exec_command(self, command, timeout=None, get_pty=False):
        self.commands.append(command)
        return None, FakeStream(), FakeStream()

    def open_sftp(self):
        return FakeSFTP(self.files)


def session(username):
    s = SSHSession("203.0.113.5", username=username)
    s._client = FakeClient()
    return s


class TestNonRootLogin:
    def test_root_runs_commands_as_given(self):
        s = session("root")
        s.run("systemctl restart potato.service")
        assert s._client.commands == ["systemctl restart potato.service"]

    def test_ubuntu_runs_them_through_sudo_without_a_prompt(self):
        s = session("ubuntu")
        s.run("chown -R 1000:1000 /opt/potato/app")
        assert s._client.commands == ["sudo -n sh -c 'chown -R 1000:1000 /opt/potato/app'"]

    def test_quoting_survives_sudo(self):
        s = session("ubuntu")
        s.run("sqlite3 /a.sqlite \".backup '/tmp/x'\"")
        command = s._client.commands[0]
        assert command.startswith("sudo -n sh -c ")
        import shlex
        assert shlex.split(command)[-1] == "sqlite3 /a.sqlite \".backup '/tmp/x'\""

    def test_secrets_file_is_staged_then_installed_as_root(self):
        s = session("ubuntu")
        s.put_text("POTATO_SECRET_KEY=x\n", "/opt/potato/potato.env", mode=0o600)
        staged = [p for p in s._client.files if p.startswith("/tmp/")]
        assert len(staged) == 1
        assert s._client.files[staged[0]][1] == 0o600, \
            "the staged copy must never be world-readable"
        install = s._client.commands[-1]
        assert "install -m 600 -o root -g root" in install
        assert "/opt/potato/potato.env" in install
        assert install.startswith("sudo -n sh -c")

    def test_root_writes_the_file_directly(self):
        s = session("root")
        s.put_text("A=1\n", "/opt/potato/potato.env", mode=0o600)
        assert list(s._client.files) == ["/opt/potato/potato.env"]
        assert not s._client.commands


class TestSafeExtract:
    def _archive(self, tmp_path, entries):
        path = tmp_path / "a.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            for name, body in entries:
                info = tarfile.TarInfo(name)
                info.size = len(body)
                archive.addfile(info, io.BytesIO(body))
        return str(path)

    def test_unpacks_regular_files(self, tmp_path):
        archive = self._archive(tmp_path, [("./alice/user_state.json", b"{}")])
        written = _safe_extract(archive, str(tmp_path / "out"))
        assert written == ["alice/user_state.json"]
        assert (tmp_path / "out" / "alice" / "user_state.json").read_bytes() == b"{}"

    def test_refuses_to_escape(self, tmp_path):
        archive = self._archive(tmp_path, [("../../evil", b"x")])
        with pytest.raises(ProviderError, match="outside"):
            _safe_extract(archive, str(tmp_path / "out"))
        assert not (tmp_path / "evil").exists()


@pytest.mark.parametrize("provider_name", ["digitalocean"])
class TestCloudInitFitsTheProvider:
    """Each provider caps user_data; a plan over the cap is a bug, not a config."""

    def test_rendered_script_is_under_the_cap(self, provider_name):
        from potato.deploy.providers.base import get_provider

        provider = get_provider(provider_name)
        rendered = build_cloud_init(spec(volume_gb=5), public_host="1.2.3.4",
                                    volume_device="/dev/sdb")
        assert len(rendered.encode()) <= provider.user_data_limit


class TestUpdatingAnExistingMachine:
    """`up` on an existing VM used to print a fresh-provision plan, record a new
    --size/--region/--volume-gb/--domain it never applied, and restart the old
    container without pulling, so no deployment could pick up a new --image or
    a newer :latest."""

    def _record(self, **spec_fields):
        record = DeploymentRecord(name="pilot", provider="digitalocean")
        record.provider_ref.update({"droplet_id": 7, "ipv4": "203.0.113.5",
                                    "host": "203.0.113.5", "app_dir": "/opt/potato/app"})
        record.url = "https://203.0.113.5"
        record.spec = {"size": "s-1vcpu-2gb", "region": "nyc3", "volume_gb": None,
                       "domain": None, **spec_fields}
        return record

    def test_a_changed_size_is_refused(self, tmp_path):
        from potato.deploy.providers.base import get_provider
        s = spec(size="s-2vcpu-4gb")
        s.extra["existing_record"] = self._record()
        message = get_provider("digitalocean").refusal(s, None)
        assert message and "--size s-2vcpu-4gb (it has s-1vcpu-2gb)" in message

    def test_unchanged_or_omitted_settings_update_in_place(self):
        from potato.deploy.providers.base import get_provider
        s = spec(size="s-1vcpu-2gb")
        s.extra["existing_record"] = self._record()
        assert get_provider("digitalocean").refusal(s, None) is None

    def test_the_plan_describes_an_update(self):
        from potato.deploy.providers.base import get_provider
        s = spec(image="ghcr.io/davidjurgens/potato:2.10.2")
        s.extra["existing_record"] = self._record()
        plan = get_provider("digitalocean").plan(s, None)
        kinds = [a.kind for a in plan.actions]
        assert "docker.pull" in kinds and not any(k.startswith("do.") for k in kinds)

    def test_the_update_rewrites_the_unit_and_pulls_before_restarting(self, monkeypatch):
        from potato.deploy.providers import vm_base
        from potato.deploy.providers.base import get_provider

        log = []

        class Result:
            def output(self):
                return ""

        class FakeSession:
            def __init__(self, *a, **k): pass
            def wait_for_ssh(self, timeout): pass
            def run(self, cmd, **k):
                log.append(("run", cmd))
                return Result()
            def put_archive(self, src, dest): return 1024
            def put_text(self, text, path, mode=0o644): log.append(("put", path, text))
            def wait_for_http(self, url, timeout): return True
            def close(self): pass

        class Bundle:
            bundle_dir = "/tmp/b"
            file_count = 1
            def sha256(self): return "a" * 64

        monkeypatch.setattr(vm_base, "SSHSession", FakeSession)
        s = spec(image="ghcr.io/davidjurgens/potato:2.10.2")
        get_provider("digitalocean", console=lambda *a: None)._configure_host(
            s, Bundle(), self._record(), "PEM", skip_cloud_init=True)

        unit = next(e for e in log if e[0] == "put" and e[1].endswith("potato.service"))
        assert "ghcr.io/davidjurgens/potato:2.10.2" in unit[2]
        commands = [e[1] for e in log if e[0] == "run"]
        pull = commands.index("docker pull ghcr.io/davidjurgens/potato:2.10.2")
        restart = commands.index("systemctl restart potato.service")
        assert pull < restart
