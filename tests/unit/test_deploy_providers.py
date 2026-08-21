"""Tests for the provider interface and the two credential-free providers.

The design constraint that makes this testable: ``plan()`` takes no credentials
and performs no I/O, so the exact set of calls a provider would make is
assertable without a token or a network. Most of the regression value in this
subsystem lives in those assertions — they catch "we stopped setting the
firewall" or "we started putting the admin key in the plan output" without
touching a cloud account.
"""

import json
import os

import pytest
import yaml

from potato.deploy.bundle import build_bundle
from potato.deploy.preflight import generate_secrets
from potato.deploy.providers import base as provider_base
from potato.deploy.providers.base import (
    Action,
    DeployPlan,
    DeploySpec,
    Provider,
    ProviderError,
    PullResult,
    available_providers,
    get_provider,
)
from potato.deploy.providers.tunnel import (
    BACKENDS,
    CLOUDFLARE_URL_RE,
    NGROK_URL_RE,
    TAILSCALE_URL_RE,
    detect_backend,
    install_hint,
)
from potato.deploy.state import DeploymentRecord, DeploymentStore


@pytest.fixture
def bundle(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "data").mkdir()
    (project / "data" / "items.json").write_text('[{"id":"1","text":"hi"}]')
    config = project / "config.yaml"
    config.write_text(yaml.safe_dump({
        "task_dir": ".", "data_files": ["data/items.json"],
        "output_annotation_dir": "annotation_output/"}))
    return build_bundle(str(config), str(tmp_path / "out"))


@pytest.fixture
def spec(tmp_path):
    return DeploySpec(name="study", config_path=str(tmp_path / "config.yaml"),
                      extra={"port": 8000, "generated": generate_secrets()})


class TestRegistry:
    def test_builtin_providers_are_registered(self):
        assert {"local", "tunnel"} <= set(available_providers())

    def test_unknown_provider_lists_alternatives(self):
        with pytest.raises(ProviderError, match="Unknown provider"):
            get_provider("nowhere")

    def test_get_provider_returns_an_instance(self):
        assert isinstance(get_provider("local"), Provider)


class TestPlanIsPureAndSafe:
    def test_local_plan_needs_no_credentials(self, spec, bundle):
        plan = get_provider("local", token=None).plan(spec, bundle)
        assert plan.actions

    def test_plan_never_contains_a_secret_value(self, spec, bundle):
        """A dry-run gets pasted into issues and chat logs."""
        generated = spec.extra["generated"]
        plan = get_provider("local").plan(spec, bundle)
        blob = plan.render() + json.dumps(
            [a.request for a in plan.actions], default=str)
        assert generated.secret_key not in blob
        assert generated.admin_api_key not in blob

    def test_plan_lists_env_keys_so_omissions_are_visible(self, spec, bundle):
        plan = get_provider("local").plan(spec, bundle)
        run = next(a for a in plan.actions if a.kind == "docker.run")
        keys = run.request["env_keys"]
        for expected in ("POTATO_SECRET_KEY", "POTATO_ADMIN_API_KEY",
                         "GUNICORN_WORKERS", "POTATO_CONFIG"):
            assert expected in keys

    def test_local_plan_pins_a_single_worker(self, spec, bundle):
        env = get_provider("local").runtime_env(spec, spec.extra["generated"])
        assert env["GUNICORN_WORKERS"] == "1"

    def test_local_plan_sets_noninteractive(self, spec, bundle):
        """A container has no tty; init_config must not prompt."""
        env = get_provider("local").runtime_env(spec, spec.extra["generated"])
        assert env["POTATO_NONINTERACTIVE"] == "1"

    def test_user_env_overrides_defaults(self, tmp_path):
        spec = DeploySpec(name="s", config_path="x", env={"GUNICORN_THREADS": "16"})
        env = get_provider("local").runtime_env(spec, None)
        assert env["GUNICORN_THREADS"] == "16"

    def test_secrets_reach_the_runtime_env(self, tmp_path):
        spec = DeploySpec(name="s", config_path="x",
                          secrets={"OPENAI_API_KEY": "sk-test"})
        env = get_provider("local").runtime_env(spec, None)
        assert env["OPENAI_API_KEY"] == "sk-test"

    def test_plan_reports_cost(self, spec, bundle):
        assert get_provider("local").plan(spec, bundle).estimated_cost_usd_month == 0.0

    def test_plan_render_is_readable(self, spec, bundle):
        rendered = get_provider("local").plan(spec, bundle).render()
        assert "docker.run" in rendered
        assert "Result URL" in rendered


class TestTunnelPlan:
    def test_binds_to_loopback_only(self):
        """Nothing must be reachable except through the tunnel."""
        spec = DeploySpec(name="s", config_path="x",
                          extra={"port": 8000, "backend": "cloudflared"})
        plan = get_provider("tunnel").plan(spec, None)
        start = next(a for a in plan.actions if a.kind == "server.start")
        assert start.request["host"] == "127.0.0.1"

    def test_sets_proxy_fix(self):
        spec = DeploySpec(name="s", config_path="x", extra={"backend": "cloudflared"})
        plan = get_provider("tunnel").plan(spec, None)
        assert any("POTATO_PROXY_FIX" in a.description for a in plan.actions)

    def test_warns_that_it_is_not_a_deployment(self):
        spec = DeploySpec(name="s", config_path="x", extra={"backend": "cloudflared"})
        plan = get_provider("tunnel").plan(spec, None)
        assert any("not a deployment" in w for w in plan.warnings)

    def test_warns_about_cloudflare_filtering(self):
        """Participants sit behind exactly the networks that filter it."""
        spec = DeploySpec(name="s", config_path="x", extra={"backend": "cloudflared"})
        plan = get_provider("tunnel").plan(spec, None)
        assert any("filter trycloudflare" in w for w in plan.warnings)

    def test_warns_about_ngrok_interstitial(self):
        spec = DeploySpec(name="s", config_path="x", extra={"backend": "ngrok"})
        plan = get_provider("tunnel").plan(spec, None)
        assert any("interstitial" in w for w in plan.warnings)

    def test_tailscale_carries_no_reachability_warning(self):
        spec = DeploySpec(name="s", config_path="x", extra={"backend": "tailscale"})
        plan = get_provider("tunnel").plan(spec, None)
        assert not any("filter" in w or "interstitial" in w for w in plan.warnings)

    @pytest.mark.parametrize("backend,expected", [
        ("cloudflared", "trycloudflare.com"),
        ("ngrok", "ngrok-free.app"),
        ("tailscale", "ts.net"),
    ])
    def test_result_url_pattern_matches_backend(self, backend, expected):
        spec = DeploySpec(name="s", config_path="x", extra={"backend": backend})
        plan = get_provider("tunnel").plan(spec, None)
        assert expected in plan.result_url_pattern

    def test_create_directs_the_user_to_potato_share(self, spec):
        with pytest.raises(ProviderError, match="potato share"):
            get_provider("tunnel").create(spec, None, None, None)


class TestTunnelUrlPatterns:
    def test_cloudflare_url_extracted_from_noise(self):
        line = ("2026-08-20T10:00:00Z INF |  https://brave-tiger-cat.trycloudflare.com  |")
        assert CLOUDFLARE_URL_RE.search(line).group(0) == \
            "https://brave-tiger-cat.trycloudflare.com"

    def test_ngrok_url_extracted(self):
        line = 'url=https://a1b2c3.ngrok-free.app msg="started tunnel"'
        assert NGROK_URL_RE.search(line).group(0) == "https://a1b2c3.ngrok-free.app"

    def test_tailscale_url_extracted(self):
        line = "Available on the internet: https://laptop.tail1234.ts.net/"
        assert TAILSCALE_URL_RE.search(line).group(0) == "https://laptop.tail1234.ts.net"

    def test_patterns_do_not_match_unrelated_urls(self):
        line = "https://example.com/trycloudflare.com"
        assert CLOUDFLARE_URL_RE.search(line) is None


class TestBackendDetection:
    def test_rejects_unknown_backend(self):
        with pytest.raises(ProviderError, match="Unknown tunnel backend"):
            detect_backend("carrier-pigeon")

    def test_missing_binary_gives_an_install_hint(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: None)
        with pytest.raises(ProviderError) as excinfo:
            detect_backend("cloudflared")
        assert "brew install cloudflared" in str(excinfo.value)

    def test_prefers_cloudflared_when_all_present(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
        assert detect_backend() == "cloudflared"

    def test_skips_ngrok_without_an_authtoken(self, monkeypatch):
        monkeypatch.setattr("shutil.which",
                            lambda name: f"/usr/bin/{name}" if name == "ngrok" else None)
        monkeypatch.delenv("NGROK_AUTHTOKEN", raising=False)
        with pytest.raises(ProviderError, match="No tunnel backend found"):
            detect_backend()

    def test_uses_ngrok_when_authtoken_is_set(self, monkeypatch):
        monkeypatch.setattr("shutil.which",
                            lambda name: f"/usr/bin/{name}" if name == "ngrok" else None)
        monkeypatch.setenv("NGROK_AUTHTOKEN", "token")
        assert detect_backend() == "ngrok"

    def test_every_backend_has_an_install_hint(self):
        for backend in BACKENDS:
            assert install_hint(backend)


class TestLocalProviderLifecycle:
    """Behaviour that must hold whether or not docker is installed."""

    def test_create_without_docker_explains_the_alternative(self, monkeypatch, spec, bundle, tmp_path):
        monkeypatch.setattr("potato.deploy.providers.local._docker_available",
                            lambda: False)
        store = DeploymentStore(str(tmp_path / "config.yaml"))
        with pytest.raises(ProviderError, match="potato start"):
            get_provider("local").create(spec, bundle, None, store)

    def test_plan_warns_when_docker_is_not_installed(self, monkeypatch, spec, bundle):
        monkeypatch.setattr("potato.deploy.providers.local.shutil.which",
                            lambda name: None)
        plan = get_provider("local").plan(spec, bundle)
        assert any("docker is not installed" in w for w in plan.warnings)

    def test_plan_distinguishes_a_stopped_daemon(self, monkeypatch, spec, bundle):
        """Installed-but-not-running is the common case and needs its own message."""
        monkeypatch.setattr("potato.deploy.providers.local.shutil.which",
                            lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr("potato.deploy.providers.local._docker_available",
                            lambda: False)
        plan = get_provider("local").plan(spec, bundle)
        assert any("daemon is not running" in w for w in plan.warnings)

    def test_plan_is_quiet_when_docker_works(self, monkeypatch, spec, bundle):
        monkeypatch.setattr("potato.deploy.providers.local.shutil.which",
                            lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr("potato.deploy.providers.local._docker_available",
                            lambda: True)
        plan = get_provider("local").plan(spec, bundle)
        assert not any("docker" in w for w in plan.warnings)

    def test_status_without_a_container_is_unknown(self):
        record = DeploymentRecord(name="s", provider="local", provider_ref={})
        assert get_provider("local").status(record).state == "unknown"

    def test_logs_without_a_container_raises(self):
        record = DeploymentRecord(name="s", provider="local", provider_ref={})
        with pytest.raises(ProviderError):
            list(get_provider("local").logs(record))

    def test_pull_without_a_container_raises(self, tmp_path):
        record = DeploymentRecord(name="s", provider="local", provider_ref={})
        with pytest.raises(ProviderError):
            get_provider("local").pull(record, str(tmp_path))

    def test_destroy_is_safe_with_no_container(self):
        record = DeploymentRecord(name="s", provider="local", provider_ref={})
        get_provider("local").destroy(record)  # must not raise


class TestProviderContract:
    """Every registered provider must satisfy the interface's promises."""

    @pytest.mark.parametrize("name", ["local", "tunnel"])
    def test_declares_capabilities(self, name):
        provider = get_provider(name)
        assert isinstance(provider.ephemeral_fs, bool)
        assert isinstance(provider.supports_logs, bool)
        assert isinstance(provider.supports_pull, bool)
        assert provider.name == name

    @pytest.mark.parametrize("name", ["local", "tunnel"])
    def test_unsupported_operations_raise_rather_than_no_op(self, name):
        """Silently doing nothing would look like a successful pull."""
        provider = get_provider(name)
        record = DeploymentRecord(name="s", provider=name, provider_ref={})
        if not provider.supports_pull:
            with pytest.raises(ProviderError):
                provider.pull(record, "/tmp/nowhere")
        if not provider.supports_logs:
            with pytest.raises(ProviderError):
                list(provider.logs(record))

    def test_check_requirements_reports_missing_modules(self):
        class Fake(Provider):
            name = "fake"
            requires = ("definitely_not_a_real_module_xyz",)

            def plan(self, spec, bundle): return DeployPlan()
            def create(self, spec, bundle, existing, store): return None
            def status(self, record): return None
            def destroy(self, record, *, keep_data=False): return None

        assert Fake().check_requirements() == ["definitely_not_a_real_module_xyz"]


class TestPersistBeforeProvision:
    """A create that dies mid-flight must still leave a record to clean up."""

    def test_record_is_written_before_the_container_starts(self, monkeypatch, spec,
                                                           bundle, tmp_path):
        store = DeploymentStore(str(tmp_path / "config.yaml"))
        monkeypatch.setattr("potato.deploy.providers.local._docker_available",
                            lambda: True)

        calls = []

        def fake_run(args, check=True, timeout=120):
            calls.append(args)
            if "run" in args:
                raise ProviderError("simulated failure right after docker run")
            return ""

        monkeypatch.setattr("potato.deploy.providers.local._run", fake_run)

        with pytest.raises(ProviderError):
            get_provider("local").create(spec, bundle, None, store)

        record = store.get("study")
        assert record is not None, "no record written before provisioning"
        assert record.provider_ref.get("container") == "potato-deploy-study"


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="POSIX ownership only")
class TestLocalRunsAsTheCaller:
    """The bundle directory belongs to whoever ran the CLI, not to uid 1000.

    The image runs as uid 1000, and on a Linux host where the caller's uid is
    something else the server dies during boot on its first write into /app.
    Docker Desktop ignores bind-mount ownership, so this passes on a Mac and
    fails everywhere else. Running as the caller also leaves the annotations
    owned by them rather than by a uid they need root to read.
    """

    def _docker_run_args(self, monkeypatch, spec, bundle, tmp_path):
        store = DeploymentStore(str(tmp_path / "config.yaml"))
        monkeypatch.setattr("potato.deploy.providers.local._docker_available",
                            lambda: True)
        calls = []

        def fake_run(args, check=True, timeout=120):
            calls.append(args)
            return "container-id"

        monkeypatch.setattr("potato.deploy.providers.local._run", fake_run)
        get_provider("local").create(spec, bundle, None, store)
        return next(a for a in calls if "run" in a and "-d" in a)

    def test_passes_the_callers_uid_and_gid(self, monkeypatch, spec, bundle,
                                            tmp_path):
        args = self._docker_run_args(monkeypatch, spec, bundle, tmp_path)
        assert "--user" in args
        assert args[args.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"
