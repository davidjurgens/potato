"""What a DigitalOcean deploy would do, asserted without a token or a network.

`plan()` takes no credentials and performs no I/O, which makes it both the
`--dry-run` output and the whole unit-test surface. Everything here runs offline.

The properties worth guarding are the ones that cost money or expose a task:
which ports the firewall opens, that port 8000 never appears in it, that the
plan never prints a secret, and that the cloud-init a real deploy would install
is valid YAML small enough for DigitalOcean to accept.
"""

import os

import pytest
import yaml

from potato.deploy.providers.base import DeploySpec, get_provider
from potato.deploy.providers.digitalocean import (
    APP_PORT,
    BASE_IMAGE,
    CADDY_IMAGE,
    DEFAULT_IMAGE,
    DEFAULT_REGION,
    DEFAULT_SIZE,
    build_cloud_init,
    droplet_payload,
    firewall_rules,
    _estimate_cost,
    _memory_mb,
    _render_env_file,
)

# DigitalOcean rejects user_data above this. A bundle never travels this way,
# but the unit files and Caddyfile do, and they grow.
USER_DATA_LIMIT = 65536


class FakeBundle:
    bundle_dir = "/tmp/bundle"
    file_count = 12
    total_bytes = 34567

    def sha256(self):
        return "a" * 64


class FakeGenerated:
    secret_key = "SECRET-KEY-VALUE-DO-NOT-PRINT"
    admin_api_key = "ADMIN-KEY-VALUE-DO-NOT-PRINT"


@pytest.fixture
def spec(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("task_dir: .\n")
    return DeploySpec(
        name="pilot", config_path=str(config),
        extra={"config_rel": "config.yaml", "generated": FakeGenerated()})


@pytest.fixture
def provider():
    return get_provider("digitalocean")


@pytest.fixture
def bundle():
    return FakeBundle()


class TestRegistration:
    def test_provider_is_registered(self):
        from potato.deploy.providers.base import available_providers
        assert "digitalocean" in available_providers()

    def test_declares_what_it_supports(self, provider):
        assert provider.supports_pull and provider.supports_logs
        assert provider.public
        assert not provider.ephemeral_fs
        assert provider.requires == ("paramiko",)


class TestFirewall:
    def test_opens_only_ssh_and_web(self):
        rules = firewall_rules("pilot", "potato-pilot")
        ports = {r["ports"] for r in rules["inbound_rules"]}
        assert ports == {"22", "80", "443"}

    def test_never_exposes_the_app_port(self):
        """The container binds 127.0.0.1 and Caddy proxies over loopback.

        Opening 8000 would serve the task over plaintext HTTP alongside the
        HTTPS one, with sessions and annotations in the clear.
        """
        rules = firewall_rules("pilot", "potato-pilot")
        assert str(APP_PORT) not in {r["ports"] for r in rules["inbound_rules"]}

    def test_is_tagged_for_recovery(self):
        """Losing the state file must not mean losing the ability to clean up."""
        assert firewall_rules("pilot", "potato-pilot")["tags"] == ["potato-pilot"]


class TestCloudInit:
    def test_is_valid_yaml(self, spec):
        document = yaml.safe_load(build_cloud_init(spec, public_host="203.0.113.9"))
        assert isinstance(document, dict)

    def test_starts_with_the_cloud_config_marker(self, spec):
        """Without this exact first line cloud-init ignores the file entirely."""
        text = build_cloud_init(spec, public_host="203.0.113.9")
        assert text.splitlines()[0] == "#cloud-config"

    def test_fits_the_user_data_limit(self, spec):
        text = build_cloud_init(spec, public_host="203.0.113.9")
        assert len(text.encode()) < USER_DATA_LIMIT

    def test_installs_sqlite3(self, spec):
        """`pull` snapshots WAL databases with `sqlite3 .backup` over SSH."""
        document = yaml.safe_load(build_cloud_init(spec, public_host="203.0.113.9"))
        assert "sqlite3" in document["packages"]

    def test_pulls_both_images_at_first_boot(self, spec):
        document = yaml.safe_load(build_cloud_init(spec, public_host="203.0.113.9"))
        commands = " ".join(str(c) for c in document["runcmd"])
        assert DEFAULT_IMAGE in commands
        assert CADDY_IMAGE in commands

    def test_enables_both_services(self, spec):
        document = yaml.safe_load(build_cloud_init(spec, public_host="203.0.113.9"))
        commands = " ".join(str(c) for c in document["runcmd"])
        assert "potato.service" in commands and "caddy-potato.service" in commands

    def test_carries_no_secret(self, spec):
        """Secrets go over SSH into a 0600 file, never into user_data.

        user_data is readable from the droplet's metadata service by any process
        on the machine, and DigitalOcean shows it in the console.
        """
        text = build_cloud_init(spec, public_host="203.0.113.9")
        assert FakeGenerated.secret_key not in text
        assert FakeGenerated.admin_api_key not in text

    def test_app_binds_to_loopback_only(self, spec):
        document = yaml.safe_load(build_cloud_init(spec, public_host="203.0.113.9"))
        unit = _write_file(document, "/etc/systemd/system/potato.service")
        assert f"127.0.0.1:{APP_PORT}:7860" in unit

    def test_service_restarts_on_failure(self, spec):
        document = yaml.safe_load(build_cloud_init(spec, public_host="203.0.113.9"))
        unit = _write_file(document, "/etc/systemd/system/potato.service")
        assert "Restart=always" in unit
        assert "WantedBy=multi-user.target" in unit


class TestVolumeHandling:
    def test_volume_is_formatted_only_when_blank(self, spec):
        """A re-attached volume holds the study's data. Reformatting is fatal."""
        spec.volume_gb = 10
        document = yaml.safe_load(build_cloud_init(
            spec, public_host="203.0.113.9", volume_device="/dev/sda"))
        commands = " ".join(str(c) for c in document["runcmd"])
        assert "blkid /dev/sda" in commands
        assert "mkfs.ext4" in commands
        # The guard and the format must be one command, not two steps.
        formatting = [str(c) for c in document["runcmd"] if "mkfs" in str(c)]
        assert all("blkid" in c for c in formatting)

    def test_fstab_entry_is_not_duplicated_on_reboot(self, spec):
        spec.volume_gb = 10
        document = yaml.safe_load(build_cloud_init(
            spec, public_host="203.0.113.9", volume_device="/dev/sda"))
        fstab = [str(c) for c in document["runcmd"] if "fstab" in str(c)]
        assert fstab and all("grep -q" in c for c in fstab)

    def test_fstab_uses_nofail(self, spec):
        """A detached volume must not leave the droplet unbootable."""
        spec.volume_gb = 10
        document = yaml.safe_load(build_cloud_init(
            spec, public_host="203.0.113.9", volume_device="/dev/sda"))
        fstab = " ".join(str(c) for c in document["runcmd"] if "fstab" in str(c))
        assert "nofail" in fstab

    def test_certificates_go_on_the_volume_when_there_is_one(self, spec):
        """An IP certificate lives ~6 days; re-issuing on every restart would
        run into rate limits."""
        spec.volume_gb = 10
        document = yaml.safe_load(build_cloud_init(
            spec, public_host="203.0.113.9", volume_device="/dev/sda"))
        unit = _write_file(document, "/etc/systemd/system/caddy-potato.service")
        assert "/opt/potato/data/caddy" in unit

    def test_no_volume_means_no_mount_commands(self, spec):
        document = yaml.safe_load(build_cloud_init(spec, public_host="203.0.113.9"))
        commands = " ".join(str(c) for c in document["runcmd"])
        assert "mkfs" not in commands and "fstab" not in commands


class TestCaddyfile:
    def _caddyfile(self, spec, host):
        document = yaml.safe_load(build_cloud_init(spec, public_host=host))
        return _write_file(document, "/etc/caddy/Caddyfile")

    def test_ip_host_names_an_acme_issuer(self, spec):
        """Caddy issues a *self-signed* certificate for an IP host by default.

        That produces a browser warning indistinguishable from a
        misconfiguration, which sends annotators away.
        """
        text = self._caddyfile(spec, "203.0.113.9")
        assert "issuer acme" in text
        assert "acme-v02.api.letsencrypt.org" in text

    def test_ip_host_requests_the_shortlived_profile(self, spec):
        """Let's Encrypt only issues IP certificates under this profile."""
        assert "profile shortlived" in self._caddyfile(spec, "203.0.113.9")

    def test_a_real_domain_uses_caddy_defaults(self, spec):
        spec.domain = "annotate.example.edu"
        text = self._caddyfile(spec, "annotate.example.edu")
        assert "annotate.example.edu {" in text
        # Ninety-day certificates over HTTP-01; no issuer override wanted.
        assert "profile shortlived" not in text

    def test_never_uses_sslip_io(self, spec):
        """sslip.io is absent from the Public Suffix List, so browsers treat
        every *.sslip.io host as one site for cookies.

        Directives only: the file explains in a comment why it is rejected.
        """
        directives = [line for line in self._caddyfile(spec, "203.0.113.9").splitlines()
                      if line.strip() and not line.strip().startswith("#")]
        assert not any("sslip.io" in line for line in directives)

    def test_proxies_to_the_loopback_app_port(self, spec):
        text = self._caddyfile(spec, "203.0.113.9")
        assert f"reverse_proxy 127.0.0.1:{APP_PORT}" in text

    def test_does_not_buffer_responses(self, spec):
        """Potato streams uploads and holds long polls."""
        assert "flush_interval -1" in self._caddyfile(spec, "203.0.113.9")


class TestDropletPayload:
    def test_uses_a_docker_base_image(self, spec):
        payload = droplet_payload(spec, tag="potato-pilot", ssh_key_id=1,
                                  user_data="#cloud-config\n",
                                  region=DEFAULT_REGION, size=DEFAULT_SIZE)
        assert payload["image"] == BASE_IMAGE

    def test_is_tagged_twice_for_recovery(self, spec):
        payload = droplet_payload(spec, tag="potato-pilot", ssh_key_id=1,
                                  user_data="", region="nyc3", size="s-2vcpu-2gb")
        assert "potato-pilot" in payload["tags"] and "potato" in payload["tags"]

    def test_does_not_enable_paid_backups(self, spec):
        payload = droplet_payload(spec, tag="t", ssh_key_id=1, user_data="",
                                  region="nyc3", size="s-2vcpu-2gb")
        assert payload["backups"] is False

    def test_carries_only_the_generated_key(self, spec):
        """Never the operator's own key: a deployment must be revocable on its own."""
        payload = droplet_payload(spec, tag="t", ssh_key_id=42, user_data="",
                                  region="nyc3", size="s-2vcpu-2gb")
        assert payload["ssh_keys"] == [42]


class TestPlan:
    def test_persists_state_before_creating_the_firewall(self, provider, spec, bundle):
        """The droplet id must be written down before anything else can fail."""
        kinds = [a.kind for a in provider.plan(spec, bundle).actions]
        assert kinds.index("state.persist") < kinds.index("do.firewall")
        assert kinds.index("do.droplet") < kinds.index("state.persist")

    def test_verifies_the_token_first(self, provider, spec, bundle):
        assert provider.plan(spec, bundle).actions[0].kind == "do.account"

    def test_waits_are_separate_steps(self, provider, spec, bundle):
        """Droplet-active, SSH-ready and cloud-init-done are minutes apart.

        Collapsing them into one wait is what makes a deploy tool look hung.
        """
        kinds = [a.kind for a in provider.plan(spec, bundle).actions]
        for kind in ("wait.active", "wait.ssh", "wait.cloud_init", "wait.http"):
            assert kind in kinds
        assert (kinds.index("wait.active") < kinds.index("wait.ssh")
                < kinds.index("wait.cloud_init"))

    def test_no_secret_value_appears_anywhere(self, provider, spec, bundle):
        """A plan is printed to a terminal and often pasted into an issue."""
        rendered = provider.plan(spec, bundle).render()
        blob = rendered + repr([a.request for a in provider.plan(spec, bundle).actions])
        assert FakeGenerated.secret_key not in blob
        assert FakeGenerated.admin_api_key not in blob

    def test_env_step_lists_keys_only(self, provider, spec, bundle):
        action = next(a for a in provider.plan(spec, bundle).actions
                      if a.kind == "ssh.env")
        assert "POTATO_SECRET_KEY" in action.request["env_keys"]
        assert FakeGenerated.secret_key not in repr(action.request)

    def test_costs_are_reported_before_confirmation(self, provider, spec, bundle):
        assert provider.plan(spec, bundle).estimated_cost_usd_month == 18.0

    def test_volume_adds_to_the_cost(self, provider, spec, bundle):
        spec.volume_gb = 100
        assert provider.plan(spec, bundle).estimated_cost_usd_month == 28.0

    def test_warns_about_an_undersized_droplet(self, provider, spec, bundle):
        spec.size = "s-1vcpu-1gb"
        warnings = provider.plan(spec, bundle).warnings
        assert any("swapping" in w for w in warnings)

    def test_warns_that_ip_certificates_are_short_lived(self, provider, spec, bundle):
        warnings = provider.plan(spec, bundle).warnings
        assert any("6 days" in w for w in warnings)

    def test_no_short_lived_warning_with_a_domain(self, provider, spec, bundle):
        spec.domain = "annotate.example.edu"
        assert not any("6 days" in w for w in provider.plan(spec, bundle).warnings)

    def test_warns_when_data_lives_only_on_the_droplet(self, provider, spec, bundle):
        assert any("destroyed with the droplet" in w
                   for w in provider.plan(spec, bundle).warnings)

    def test_plan_makes_no_network_call(self, provider, spec, bundle, monkeypatch):
        """The contract that makes --dry-run safe and these tests possible."""
        def explode(*args, **kwargs):
            raise AssertionError("plan() performed I/O")
        import requests
        monkeypatch.setattr(requests.Session, "request", explode)
        monkeypatch.setattr(requests, "get", explode)
        provider.plan(spec, bundle)

    def test_plan_needs_no_token(self, spec, bundle):
        assert get_provider("digitalocean", token=None).plan(spec, bundle).actions


class TestHelpers:
    @pytest.mark.parametrize("slug,expected", [
        ("s-1vcpu-1gb", 1024),
        ("s-2vcpu-2gb", 2048),
        ("s-4vcpu-8gb", 8192),
        ("weird-slug", None),
    ])
    def test_memory_parsing(self, slug, expected):
        assert _memory_mb(slug) == expected

    def test_unknown_size_does_not_invent_a_price(self):
        assert _estimate_cost("s-96vcpu-mystery", None) == 0.0

    def test_env_file_is_systemd_format(self):
        rendered = _render_env_file({"B": "2", "A": "1"})
        assert rendered == "A=1\nB=2\n"

    def test_env_file_rejects_a_newline(self):
        """systemd silently truncates at the newline, so the value would be wrong."""
        from potato.deploy.providers.base import ProviderError
        with pytest.raises(ProviderError, match="newline"):
            _render_env_file({"KEY": "line one\nline two"})


class TestTemplatesArePackaged:
    """A provider renders these from an installed wheel, not the source tree.

    They live under potato/deploy/templates and are only shipped because
    setup.py names them in package_data. Nothing else would notice them going
    missing until a deploy failed on a machine that pip-installed Potato.
    """

    TEMPLATES = ("cloud-init.yaml.j2", "Caddyfile.j2", "potato.service.j2",
                 "caddy.service.j2")

    def test_setup_py_ships_the_template_directory(self):
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        with open(os.path.join(root, "setup.py")) as handle:
            assert "deploy/templates/*.j2" in handle.read()

    @pytest.mark.parametrize("name", TEMPLATES)
    def test_every_template_exists(self, name):
        import potato.deploy as deploy_package
        path = os.path.join(os.path.dirname(deploy_package.__file__),
                            "templates", name)
        assert os.path.isfile(path), f"{name} is missing"

    def test_a_missing_variable_is_an_error_not_an_empty_string(self):
        """Jinja renders an undefined name as "" by default.

        Here that would silently produce a Caddyfile with no host, or a unit
        file with no image, and the failure would surface on the droplet.
        """
        from jinja2 import UndefinedError
        from potato.deploy.providers.digitalocean import render_template
        with pytest.raises(UndefinedError):
            render_template("Caddyfile.j2")


def _write_file(document, path):
    for entry in document["write_files"]:
        if entry["path"] == path:
            return entry["content"]
    raise AssertionError(f"cloud-init writes no {path}")
