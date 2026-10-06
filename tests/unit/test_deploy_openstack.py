"""The OpenStack provider, Jetstream2 first, against a fake openstacksdk connection."""

from types import SimpleNamespace

import pytest
import yaml

from potato.deploy.providers import openstack as os_provider
from potato.deploy.providers import vm_base
from potato.deploy.providers.base import DeploySpec, ProviderError, get_provider
from potato.deploy.providers.openstack import (
    DEPLOY_USER,
    dns_label,
    preset_for,
    security_rules,
)
from potato.deploy.state import DeploymentRecord, DeploymentStore


class FakeBundle:
    bundle_dir = "/tmp/bundle"
    file_count = 3
    total_bytes = 1024

    def sha256(self):
        return "c" * 64


class Recorder:
    def __init__(self, log, prefix, **methods):
        self._log, self._prefix, self._methods = log, prefix, methods

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self._log.append((f"{self._prefix}.{name}", args, kwargs))
            handler = self._methods.get(name)
            return handler(*args, **kwargs) if handler else None
        return call


def fake_connection(flavor="m3.small", project="CIS230045"):
    log = []
    server = SimpleNamespace(id="srv-1", status="ACTIVE", name="potato-pilot")
    conn = SimpleNamespace(
        log=log,
        current_project_id="p1",
        current_project=SimpleNamespace(name=project),
        compute=Recorder(log, "compute",
                         find_flavor=lambda name: SimpleNamespace(id="f1", name=name)
                         if name == flavor else None,
                         flavors=lambda: [SimpleNamespace(name=flavor)],
                         create_server=lambda **k: server,
                         wait_for_server=lambda s, **k: s,
                         find_server=lambda sid: server),
        image=Recorder(log, "image",
                       find_image=lambda name: SimpleNamespace(id="img-1")),
        network=Recorder(log, "network",
                         get_auto_allocated_topology=lambda: SimpleNamespace(id="net-1"),
                         get_network=lambda nid: SimpleNamespace(id=nid),
                         find_network=lambda name: SimpleNamespace(id="ext-1"),
                         create_security_group=lambda **k: SimpleNamespace(
                             id="sg-1", name=k["name"]),
                         create_ip=lambda **k: SimpleNamespace(
                             id="fip-1", floating_ip_address="149.165.0.10")),
        block_storage=Recorder(log, "block_storage",
                               create_volume=lambda **k: SimpleNamespace(
                                   id="0123456789abcdef0123456789")),
    )
    return conn


@pytest.fixture
def project(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("task_dir: .\n")
    return str(config)


@pytest.fixture
def spec(project):
    return DeploySpec(name="pilot", config_path=project,
                      extra={"config_rel": "config.yaml", "cloud": "jetstream2"})


@pytest.fixture
def conn(monkeypatch):
    connection = fake_connection()
    monkeypatch.setattr(os_provider, "connect", lambda cloud, region=None: connection)
    # openstacksdk itself is replaced by the fake connection above.
    monkeypatch.setattr(os_provider.OpenStackProvider, "check_requirements",
                        lambda self: [])
    monkeypatch.setattr(vm_base.VMProvider, "_configure_host", lambda self, *a, **k: None)
    monkeypatch.setattr(vm_base, "generate_keypair",
                        lambda comment="": ("PEM", "ssh-ed25519 AAAA potato"))
    monkeypatch.setattr(os_provider.OpenStackProvider, "_wait_for_dns",
                        lambda self, host, addr, timeout=300: None)
    return connection


@pytest.fixture
def provider():
    return get_provider("openstack", console=lambda *a: None)


def calls(conn, name):
    return [entry for entry in conn.log if entry[0] == name]


class TestJetstream2:
    def test_hostname_becomes_the_domain_so_the_cert_is_a_normal_one(
            self, provider, spec, project, conn):
        record = provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        assert record.url == "https://potato-pilot.cis230045.projects.jetstream-cloud.org"
        user_data = calls(conn, "compute.create_server")[0][2]["user_data"]
        import base64
        decoded = base64.b64decode(user_data).decode()
        caddyfile = yaml.safe_load(decoded)["write_files"][1]["content"]
        assert "potato-pilot.cis230045.projects.jetstream-cloud.org {" in caddyfile
        assert "shortlived" not in caddyfile

    def test_logs_in_as_its_own_user(self, provider, spec, project, conn):
        assert provider.ssh_user == DEPLOY_USER
        provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        import base64
        decoded = base64.b64decode(
            calls(conn, "compute.create_server")[0][2]["user_data"]).decode()
        users = yaml.safe_load(decoded)["users"]
        assert users[1]["name"] == DEPLOY_USER
        assert users[1]["sudo"] == "ALL=(ALL) NOPASSWD:ALL"

    def test_defaults_come_from_the_preset(self, provider, spec):
        assert preset_for("jetstream2").flavor == "m3.small"
        assert any("Featured-Ubuntu24" in a.description
                   for a in provider.plan(spec, FakeBundle()).actions)

    def test_plan_does_not_warn_about_ip_certificates(self, provider, spec):
        assert not any("IP address" in w for w in provider.plan(spec, FakeBundle()).warnings)

    def test_the_plan_shows_the_flavor_up_would_create(self, provider, spec):
        """--cloud reached default_size only inside create(), so the dry run
        printed the generic m1.small while `up` created an m3.small."""
        descriptions = [a.description for a in provider.plan(spec, FakeBundle()).actions]
        assert any("m3.small" in d for d in descriptions), descriptions
        assert not any("m1.small" in d for d in descriptions), descriptions

    def test_another_cloud_gets_no_jetstream2_su_note(self, provider, spec):
        spec.extra["cloud"] = "campus"
        plan = provider.plan(spec, FakeBundle())
        assert not any("SU" in w for w in plan.warnings)
        assert any("m1.small" in a.description for a in plan.actions)

    def test_plan_counts_allocation_units_not_dollars(self, provider, spec):
        plan = provider.plan(spec, FakeBundle())
        assert plan.estimated_cost_usd_month is None
        assert any("SU" in w for w in plan.warnings)


class TestCreate:
    def test_server_recorded_before_the_floating_ip(self, provider, spec, project,
                                                    conn, monkeypatch):
        conn.network._methods["create_ip"] = lambda **k: (_ for _ in ()).throw(
            ProviderError("quota exceeded"))
        store = DeploymentStore(project)
        with pytest.raises(ProviderError):
            provider.create(spec, FakeBundle(), None, store)
        assert store.get("pilot").provider_ref["server_id"] == "srv-1"

    def test_unknown_flavor_lists_the_real_ones(self, provider, spec, project, conn):
        spec.size = "m9.huge"
        with pytest.raises(ProviderError, match="m3.small"):
            provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        assert not calls(conn, "compute.create_server")

    def test_only_22_80_443_both_families(self):
        rules = security_rules()
        assert sorted({r["port_range_min"] for r in rules}) == [22, 80, 443]
        assert {r["ethertype"] for r in rules} == {"IPv4", "IPv6"}

    def test_volume_candidates_name_it_by_id(self, provider, spec, project, conn):
        spec.volume_gb = 20
        record = provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        assert record.provider_ref["volume_devices"][0] == \
            "/dev/disk/by-id/virtio-0123456789abcdef0123"
        assert calls(conn, "compute.create_volume_attachment")

    def test_a_generic_cloud_falls_back_to_an_ip_certificate(self, provider, spec,
                                                             project, conn):
        spec.extra["cloud"] = "campus"
        conn.compute._methods["find_flavor"] = lambda name: SimpleNamespace(id="f", name=name)
        record = provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        assert record.url == "https://149.165.0.10"


class TestDestroy:
    def test_removes_server_ip_group_and_volume(self, provider, conn):
        provider.destroy(DeploymentRecord(name="pilot", provider="openstack", provider_ref={
            "server_id": "srv-1", "floating_ip_id": "fip-1",
            "security_group_id": "sg-1", "volume_id": "vol-1", "cloud": "jetstream2"}))
        names = [entry[0] for entry in conn.log]
        assert names.index("compute.delete_server") < names.index("network.delete_ip")
        assert "network.delete_security_group" in names
        assert "block_storage.delete_volume" in names


def test_dns_label():
    assert dns_label("Potato_My Study!") == "potato-my-study"
