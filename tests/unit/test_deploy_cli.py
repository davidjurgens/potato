"""Tests for the `potato deploy` and `potato share` command line.

The properties worth guarding are the ones that protect the user's money and
data: `up` must not create anything without confirmation, `--dry-run` must not
touch a provider, `destroy` must not discard un-pulled annotations, and no
command may print a secret.
"""

import os

import pytest
import yaml

from potato.deploy import cli
from potato.deploy.providers.base import (
    Action,
    DeployPlan,
    DeploymentStatus,
    DeploySpec,
    Provider,
    ProviderError,
    PullResult,
    register_provider,
)
from potato.deploy.state import DeploymentRecord, DeploymentStore, SecretStore


@pytest.fixture
def project(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "items.json").write_text('[{"id":"1","text":"hi"}]')
    config = {
        "task_dir": ".", "annotation_task_name": "cli test",
        "data_files": ["data/items.json"],
        "output_annotation_dir": "annotation_output/",
        "item_properties": {"id_key": "id", "text_key": "text"},
        "annotation_schemes": [{"annotation_type": "radio", "name": "s",
                                "description": "d", "labels": ["a", "b"]}],
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False))
    return str(path)


class RecordingProvider(Provider):
    """A provider that records calls instead of making them."""

    name = "recording"
    ephemeral_fs = False
    public = False
    supports_logs = True
    supports_pull = True
    calls = []

    def plan(self, spec, bundle):
        RecordingProvider.calls.append(("plan", spec.name))
        return DeployPlan(actions=[Action("noop", "does nothing")],
                          estimated_cost_usd_month=0.0,
                          result_url_pattern="http://recorded.test")

    def create(self, spec, bundle, existing, store):
        RecordingProvider.calls.append(("create", spec.name))
        record = existing or DeploymentRecord(name=spec.name, provider=self.name)
        record.url = "http://recorded.test"
        record.status = "running"
        store.upsert(record)
        return record

    def status(self, record):
        RecordingProvider.calls.append(("status", record.name))
        return DeploymentStatus(state="running", url=record.url, healthy=True)

    def destroy(self, record, *, keep_data=False):
        RecordingProvider.calls.append(("destroy", record.name))

    def logs(self, record, *, lines=200, follow=False):
        RecordingProvider.calls.append(("logs", record.name))
        yield "log line one"

    def pull(self, record, dest):
        RecordingProvider.calls.append(("pull", record.name))
        # Write something real: cmd_pull verifies what landed rather than
        # trusting the count a provider reports, so an empty directory is
        # treated as a failed pull.
        os.makedirs(os.path.join(dest, "annotation_output", "alice"), exist_ok=True)
        with open(os.path.join(dest, "annotation_output", "alice",
                               "user_state.json"), "w") as handle:
            handle.write("{}")
        return PullResult(dest=dest, files=1, bytes=10)


@pytest.fixture(autouse=True)
def recording_provider():
    register_provider(RecordingProvider)
    RecordingProvider.calls = []
    yield RecordingProvider


class TestCheck:
    def test_passes_on_a_clean_config(self, project, capsys):
        assert cli.main(["check", project, "--provider", "local"]) == cli.EXIT_OK
        assert "PASS" in capsys.readouterr().out

    def test_blocks_on_debug(self, project, capsys, tmp_path):
        config = yaml.safe_load(open(project))
        config["debug"] = True
        open(project, "w").write(yaml.safe_dump(config))
        assert cli.main(["check", project, "--provider", "local"]) == cli.EXIT_BLOCKED
        assert "BLOCKED" in capsys.readouterr().out

    def test_json_output_is_parseable(self, project, capsys):
        import json
        cli.main(["check", project, "--provider", "local", "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["config_file"] == project
        assert "findings" in payload


class TestBuild:
    def test_writes_a_bundle(self, project, capsys, tmp_path):
        out = tmp_path / "bundle"
        assert cli.main(["build", project, "--provider", "local",
                         "--out", str(out)]) == cli.EXIT_OK
        assert (out / "config.yaml").is_file()
        assert "files" in capsys.readouterr().out

    def test_bundled_config_is_hardened(self, project, tmp_path):
        out = tmp_path / "bundle"
        cli.main(["build", project, "--provider", "local", "--out", str(out)])
        bundled = yaml.safe_load(open(out / "config.yaml"))
        assert bundled["debug"] is False
        assert bundled["persist_sessions"] is True
        assert bundled["server"]["workers"] == 1

    def test_bundled_config_keeps_access_settings(self, project, tmp_path):
        config = yaml.safe_load(open(project))
        config["user_config"] = {"allow_all_users": False, "users": ["alice"]}
        open(project, "w").write(yaml.safe_dump(config))

        out = tmp_path / "bundle"
        cli.main(["build", project, "--provider", "local", "--out", str(out)])
        bundled = yaml.safe_load(open(out / "config.yaml"))
        assert bundled["user_config"] == {"allow_all_users": False, "users": ["alice"]}

    def test_tarball_is_written_on_request(self, project, tmp_path):
        archive = tmp_path / "bundle.tar.gz"
        cli.main(["build", project, "--provider", "local",
                  "--out", str(tmp_path / "b"), "--tarball", str(archive)])
        assert archive.is_file()


class TestUp:
    def test_dry_run_creates_nothing(self, project, capsys):
        code = cli.main(["up", project, "--provider", "recording", "--dry-run"])
        assert code == cli.EXIT_OK
        assert ("create", "cli-test") not in RecordingProvider.calls
        assert "Dry run" in capsys.readouterr().out

    def test_yes_provisions(self, project, capsys):
        code = cli.main(["up", project, "--provider", "recording", "--yes"])
        assert code == cli.EXIT_OK
        assert ("create", "cli-test") in RecordingProvider.calls

    def test_refuses_without_confirmation_when_not_a_tty(self, project, capsys, monkeypatch):
        """Never spend money because stdin happened to be a pipe."""
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        code = cli.main(["up", project, "--provider", "recording"])
        assert code == cli.EXIT_ABORTED
        assert ("create", "cli-test") not in RecordingProvider.calls

    def test_blocked_config_is_not_deployed(self, project):
        config = yaml.safe_load(open(project))
        config["debug"] = True
        open(project, "w").write(yaml.safe_dump(config))
        code = cli.main(["up", project, "--provider", "recording", "--yes"])
        assert code == cli.EXIT_BLOCKED
        assert ("create", "cli-test") not in RecordingProvider.calls

    def test_records_the_deployment(self, project):
        cli.main(["up", project, "--provider", "recording", "--yes"])
        record = DeploymentStore(project).get("cli-test")
        assert record is not None
        assert record.url == "http://recorded.test"

    def test_stores_the_admin_key_separately(self, project):
        cli.main(["up", project, "--provider", "recording", "--yes"])
        assert SecretStore(project).get("cli-test", "admin_api_key")

    def test_admin_key_is_not_in_the_bundle(self, project):
        cli.main(["up", project, "--provider", "recording", "--yes"])
        key = SecretStore(project).get("cli-test", "admin_api_key")
        bundle_dir = os.path.join(os.path.dirname(project), ".potato", "bundle", "cli-test")
        for dirpath, _dirnames, filenames in os.walk(bundle_dir):
            for filename in filenames:
                content = open(os.path.join(dirpath, filename), "rb").read()
                assert key.encode() not in content, f"admin key leaked into {filename}"

    def test_named_deployments_are_independent(self, project):
        cli.main(["up", project, "--provider", "recording", "--yes", "--name", "pilot"])
        cli.main(["up", project, "--provider", "recording", "--yes", "--name", "main"])
        assert {r.name for r in DeploymentStore(project).list()} == {"pilot", "main"}

    def test_rerun_updates_rather_than_duplicates(self, project):
        cli.main(["up", project, "--provider", "recording", "--yes"])
        cli.main(["up", project, "--provider", "recording", "--yes"])
        assert len(DeploymentStore(project).list()) == 1

    def test_env_and_secret_flags_are_parsed(self, project):
        code = cli.main(["up", project, "--provider", "recording", "--dry-run",
                         "--env", "A=1", "--secret", "B=2"])
        assert code == cli.EXIT_OK

    def test_malformed_env_flag_is_rejected(self, project):
        with pytest.raises(SystemExit, match="KEY=VALUE"):
            cli.main(["up", project, "--provider", "recording", "--dry-run",
                      "--env", "not-a-pair"])


class TestDestroySafety:
    def test_refuses_when_never_pulled(self, project, capsys):
        """Annotations that exist only on the host must not be discarded silently."""
        cli.main(["up", project, "--provider", "recording", "--yes"])
        code = cli.main(["destroy", project, "--yes"])
        assert code == cli.EXIT_BLOCKED
        assert "never been pulled" in capsys.readouterr().out
        assert ("destroy", "cli-test") not in RecordingProvider.calls

    def test_force_overrides(self, project):
        cli.main(["up", project, "--provider", "recording", "--yes"])
        assert cli.main(["destroy", project, "--yes", "--force"]) == cli.EXIT_OK
        assert ("destroy", "cli-test") in RecordingProvider.calls

    def test_allowed_after_a_pull(self, project, tmp_path):
        cli.main(["up", project, "--provider", "recording", "--yes"])
        cli.main(["pull", project, "--dest", str(tmp_path / "pulled")])
        assert cli.main(["destroy", project, "--yes"]) == cli.EXIT_OK

    def test_destroy_clears_state_and_secrets(self, project):
        cli.main(["up", project, "--provider", "recording", "--yes"])
        cli.main(["destroy", project, "--yes", "--force"])
        assert DeploymentStore(project).get("cli-test") is None
        assert SecretStore(project).get("cli-test", "admin_api_key") is None


class TestPullVerification:
    """`destroy` treats "pulled" as permission to delete the host.

    So a pull that returned nothing must not count as one. An empty result and
    a study nobody has annotated look identical from the outside, and only one
    of them means the data is safe.
    """

    def test_an_empty_pull_is_not_recorded(self, project, tmp_path, capsys, monkeypatch):
        cli.main(["up", project, "--provider", "recording", "--yes"])

        def empty_pull(self, record, dest):
            os.makedirs(dest, exist_ok=True)
            return PullResult(dest=dest, files=0, bytes=0)

        monkeypatch.setattr(RecordingProvider, "pull", empty_pull)
        code = cli.main(["pull", project, "--dest", str(tmp_path / "empty")])
        assert code == cli.EXIT_ERROR
        assert DeploymentStore(project).get("cli-test").last_pull_at is None
        assert "Nothing came back" in capsys.readouterr().out

    def test_destroy_still_refuses_after_an_empty_pull(self, project, tmp_path, monkeypatch):
        cli.main(["up", project, "--provider", "recording", "--yes"])

        def empty_pull(self, record, dest):
            os.makedirs(dest, exist_ok=True)
            return PullResult(dest=dest)

        monkeypatch.setattr(RecordingProvider, "pull", empty_pull)
        cli.main(["pull", project, "--dest", str(tmp_path / "empty")])
        assert cli.main(["destroy", project, "--yes"]) == cli.EXIT_BLOCKED

    def test_allow_empty_records_it(self, project, tmp_path, monkeypatch):
        """A task genuinely not annotated yet still has to be destroyable."""
        cli.main(["up", project, "--provider", "recording", "--yes"])

        def empty_pull(self, record, dest):
            os.makedirs(dest, exist_ok=True)
            return PullResult(dest=dest)

        monkeypatch.setattr(RecordingProvider, "pull", empty_pull)
        assert cli.main(["pull", project, "--allow-empty",
                         "--dest", str(tmp_path / "empty")]) == cli.EXIT_OK
        assert DeploymentStore(project).get("cli-test").last_pull_at

    def test_a_corrupt_database_is_not_a_successful_pull(self, project, tmp_path, capsys,
                                                         monkeypatch):
        """The whole point of snapshotting rather than copying."""
        cli.main(["up", project, "--provider", "recording", "--yes"])

        def broken_pull(self, record, dest):
            os.makedirs(dest, exist_ok=True)
            with open(os.path.join(dest, "project.sqlite"), "wb") as handle:
                handle.write(b"this is not a database")
            return PullResult(dest=dest, files=1)

        monkeypatch.setattr(RecordingProvider, "pull", broken_pull)
        assert cli.main(["pull", project,
                         "--dest", str(tmp_path / "broken")]) == cli.EXIT_ERROR
        assert "CORRUPT" in capsys.readouterr().out
        assert DeploymentStore(project).get("cli-test").last_pull_at is None

    def test_reports_how_many_annotators_came_back(self, project, capsys, tmp_path):
        cli.main(["up", project, "--provider", "recording", "--yes"])
        cli.main(["pull", project, "--dest", str(tmp_path / "pulled")])
        assert "annotators 1" in capsys.readouterr().out


class TestStatusLogsPullList:
    def test_status_reports_state(self, project, capsys):
        cli.main(["up", project, "--provider", "recording", "--yes"])
        assert cli.main(["status", project]) == cli.EXIT_OK
        assert "running" in capsys.readouterr().out

    def test_status_on_unknown_deployment_explains(self, project):
        with pytest.raises(SystemExit, match="No deployment named"):
            cli.main(["status", project])

    def test_logs_stream(self, project, capsys):
        cli.main(["up", project, "--provider", "recording", "--yes"])
        cli.main(["logs", project])
        assert "log line one" in capsys.readouterr().out

    def test_pull_marks_the_record(self, project, tmp_path):
        cli.main(["up", project, "--provider", "recording", "--yes"])
        cli.main(["pull", project, "--dest", str(tmp_path / "pulled")])
        assert DeploymentStore(project).get("cli-test").last_pull_at

    def test_list_shows_nothing_before_a_deploy(self, project, capsys):
        assert cli.main(["list", project]) == cli.EXIT_OK
        assert "No deployments" in capsys.readouterr().out

    def test_list_shows_deployments(self, project, capsys):
        cli.main(["up", project, "--provider", "recording", "--yes"])
        cli.main(["list", project])
        assert "cli-test" in capsys.readouterr().out


class TestRecordContext:
    """Every command must be able to reach the project's secret store.

    A VM provider keeps its SSH deploy key there, and without it `pull` and
    `logs` cannot open a connection to the host they are pointed at.
    """

    def test_loaded_records_carry_the_live_config_path(self, project):
        cli.main(["up", project, "--provider", "recording", "--yes"])
        record = DeploymentStore(project).get("cli-test")
        # Nothing wrote it at create time for this fake provider...
        assert not record.spec.get("config_path")

        # ...but every command stamps it on load, so a project that moved on
        # disk since it was deployed still resolves.
        class Args:
            config_file = project
            name = None
        _store, loaded = cli._load_record(Args())
        assert loaded.spec["config_path"] == os.path.abspath(project)

    def test_pull_records_where_annotations_live(self, project):
        """Defaulting to the usual directory would silently fetch nothing from
        a task that sets its own."""
        import yaml
        config = yaml.safe_load(open(project))
        config["output_annotation_dir"] = "my_results/"
        open(project, "w").write(yaml.safe_dump(config))

        captured = {}
        original = RecordingProvider.plan

        def capture(self, spec, bundle):
            captured["dir"] = spec.extra.get("output_annotation_dir")
            return original(self, spec, bundle)

        RecordingProvider.plan = capture
        try:
            cli.main(["up", project, "--provider", "recording", "--dry-run"])
        finally:
            RecordingProvider.plan = original
        assert captured["dir"] == "my_results/"


class TestProvidersCommand:
    def test_lists_targets_and_credential_status(self, capsys):
        assert cli.main(["providers"]) == cli.EXIT_OK
        out = capsys.readouterr().out
        assert "local" in out and "tunnel" in out
        assert "Credentials:" in out

    def test_flags_a_provider_whose_extra_is_missing(self, capsys, monkeypatch):
        """Say it here, not after someone has chosen a target and pasted a token."""
        from potato.deploy.providers.base import Provider
        monkeypatch.setattr(Provider, "check_requirements",
                            lambda self: ["paramiko"] if self.name == "digitalocean"
                            else [])
        cli.main(["providers"])
        out = capsys.readouterr().out
        assert "potato-annotation[deploy]" in out

    def test_never_prints_a_whole_token(self, capsys, monkeypatch):
        monkeypatch.setenv("DIGITALOCEAN_TOKEN", "dop_v1_supersecretvalue")
        cli.main(["providers"])
        assert "dop_v1_supersecretvalue" not in capsys.readouterr().out


class TestShareCli:
    def test_missing_config_is_reported(self, capsys):
        from potato.deploy import share_cli
        assert share_cli.main(["/nonexistent/config.yaml"]) == 1
        assert "not found" in capsys.readouterr().out

    def test_blocked_config_is_not_shared(self, project, capsys):
        from potato.deploy import share_cli
        config = yaml.safe_load(open(project))
        config["debug"] = True
        open(project, "w").write(yaml.safe_dump(config))
        assert share_cli.main([project, "--yes"]) == 2
        assert "Refusing to share" in capsys.readouterr().out

    def test_parser_accepts_the_documented_backends(self):
        from potato.deploy import share_cli
        for backend in ("cloudflared", "tailscale", "ngrok"):
            args = share_cli.build_parser().parse_args(["cfg.yaml", "--backend", backend])
            assert args.backend == backend


class TestBundleDirectoryIsScopedByProvider:
    """One bundle directory per provider, not one per deployment name.

    The `local` provider bind-mounts its bundle as the running task's
    directory. Sharing that path with a cloud provider meant that building for
    DigitalOcean — a `--dry-run` was enough, since the plan needs the bundle
    size — deleted the running local deployment's annotations on the way past.
    """

    def test_two_providers_get_two_directories(self, tmp_path):
        from potato.deploy.cli import _bundle_dir
        config = str(tmp_path / "config.yaml")
        local = _bundle_dir(config, "local", "study")
        cloud = _bundle_dir(config, "digitalocean", "study")
        assert local != cloud

    def test_the_provider_name_is_in_the_path(self, tmp_path):
        from potato.deploy.cli import _bundle_dir
        path = _bundle_dir(str(tmp_path / "config.yaml"), "local", "study")
        assert os.path.join("bundle", "local", "study") in path

    def test_it_sits_beside_the_config(self, tmp_path):
        from potato.deploy.cli import _bundle_dir
        project = tmp_path / "project"
        project.mkdir()
        path = _bundle_dir(str(project / "config.yaml"), "local", "study")
        assert path.startswith(str(project))


class TestCredentialVerification:
    """`deploy providers --verify` answers "is this token any good" for $0.

    A token that is expired, read-only, or pasted with a trailing newline looks
    identical to a working one until `up` is several billable resources deep.
    """

    def test_every_credentialled_provider_can_be_asked(self):
        """A provider with a token but no identity call is a gap, not a design."""
        from potato.deploy.providers.base import (
            Provider, available_providers, get_provider)
        from potato.deploy import credentials as creds

        for name in available_providers():
            if not creds.requires_credential(name):
                continue
            if name == "tunnel":
                continue  # NGROK_AUTHTOKEN is optional and has no whoami
            assert type(get_provider(name)).verify_credential is not \
                Provider.verify_credential, f"{name} cannot verify its token"

    def test_the_base_implementation_returns_none(self):
        """None means "not checkable", never "the token is fine"."""
        from potato.deploy.providers.base import get_provider
        assert get_provider("tunnel").verify_credential() is None

    def test_digitalocean_reports_the_account(self, monkeypatch):
        from potato.deploy.providers.base import get_provider
        monkeypatch.setattr(
            "potato.deploy.providers.digitalocean.DigitalOceanAPI",
            lambda token: type("A", (), {
                "verify_token": lambda self: {
                    "email": "researcher@example.edu", "droplet_limit": 10,
                    "status": "active"}})())
        detail = get_provider("digitalocean", token="dop_v1_x").verify_credential()
        assert "researcher@example.edu" in detail
        assert "10" in detail

    def test_digitalocean_surfaces_a_locked_account(self, monkeypatch):
        """A `warning` status still authenticates and still cannot create."""
        from potato.deploy.providers.base import get_provider
        monkeypatch.setattr(
            "potato.deploy.providers.digitalocean.DigitalOceanAPI",
            lambda token: type("A", (), {
                "verify_token": lambda self: {
                    "email": "r@example.edu", "status": "locked"}})())
        assert "locked" in get_provider(
            "digitalocean", token="dop_v1_x").verify_credential()


class TestProviderListingMatchesReality:
    """The listing must not advertise a target `--provider` would reject."""

    def test_only_registered_providers_are_listed(self):
        from potato.deploy import credentials as creds
        from potato.deploy.providers.base import available_providers

        listed = {line.split()[0]
                  for line in creds.describe_available(
                      providers=available_providers())}
        assert listed <= set(available_providers())

    def test_the_unrestricted_listing_still_covers_the_table(self):
        """Passing no filter keeps the old behaviour for other callers."""
        from potato.deploy import credentials as creds
        assert len(creds.describe_available()) == len(creds.PROVIDER_CREDENTIALS)

    def test_tunnel_is_not_described_as_durable(self):
        """It has a persistent filesystem and is the least durable target there is."""
        from potato.deploy.providers.base import get_provider
        assert "durable" not in get_provider("tunnel").summary
        assert get_provider("tunnel").summary
