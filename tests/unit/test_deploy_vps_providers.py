"""Hetzner, Vultr and Linode: the three REST-driven VPS providers.

Each is a VMProvider, so SSH, cloud-init and Caddy are tested elsewhere. These
hold the API half: the request bodies, recording the server before a later
call can fail, opening only 22/80/443, and destroy cleaning up every resource.
"""

import base64
import json

import pytest
import responses

from potato.deploy.providers import hetzner, linode, vm_base, vultr
from potato.deploy.providers.base import DeploySpec, ProviderError, get_provider
from potato.deploy.state import DeploymentRecord, DeploymentStore, SecretStore


class FakeBundle:
    bundle_dir = "/tmp/bundle"
    file_count = 3
    total_bytes = 1024

    def sha256(self):
        return "b" * 64


class FakeGenerated:
    secret_key = "VPS-SECRET-DO-NOT-PRINT"
    admin_api_key = "VPS-ADMIN-DO-NOT-PRINT"


@pytest.fixture
def project(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("task_dir: .\n")
    return str(config)


@pytest.fixture
def spec(project):
    return DeploySpec(name="pilot", config_path=project,
                      extra={"config_rel": "config.yaml", "generated": FakeGenerated()})


@pytest.fixture(autouse=True)
def no_ssh(monkeypatch):
    monkeypatch.setattr(vm_base.VMProvider, "_configure_host", lambda self, *a, **k: None)
    monkeypatch.setattr(vm_base, "generate_keypair",
                        lambda comment="": ("PEM", "ssh-ed25519 AAAA potato"))
    for module in (hetzner, vultr, linode):
        monkeypatch.setattr(module.time, "sleep", lambda s: None)


def body(call):
    return json.loads(call.request.body or "{}")


def calls_to(fragment, method=None):
    return [c for c in responses.calls if fragment in c.request.url
            and (method is None or c.request.method == method)]


# --------------------------------------------------------------- hetzner --

H = hetzner.API_ROOT


def stub_hetzner(server_status="running"):
    responses.add(responses.GET, f"{H}/servers?per_page=1",
                  json={"servers": [], "meta": {"pagination": {"total_entries": 0}}})
    responses.add(responses.GET, f"{H}/server_types?name=cx23",
                  json={"server_types": [{"name": "cx23", "prices": [
                      {"location": "nbg1"}, {"location": "fsn1"}]}]})
    responses.add(responses.POST, f"{H}/ssh_keys", json={"ssh_key": {"id": 11}})
    responses.add(responses.POST, f"{H}/firewalls", json={"firewall": {"id": 22}})
    responses.add(responses.POST, f"{H}/volumes",
                  json={"volume": {"id": 33,
                                   "linux_device": "/dev/disk/by-id/scsi-0HC_Volume_33"}})
    responses.add(responses.POST, f"{H}/servers", json={"server": {"id": 44}})
    responses.add(responses.GET, f"{H}/servers/44", json={"server": {
        "id": 44, "status": server_status,
        "public_net": {"ipv4": {"ip": "192.0.2.44"}}}})


class TestHetzner:
    @pytest.fixture
    def provider(self):
        return get_provider("hetzner", token="hz", console=lambda *a: None)

    @responses.activate
    def test_happy_path_with_a_volume(self, provider, spec, project):
        spec.volume_gb = 10
        stub_hetzner()
        record = provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        assert record.url == "https://192.0.2.44"
        assert record.provider_ref["volume_devices"] == [
            "/dev/disk/by-id/scsi-0HC_Volume_33"]
        server = body(calls_to("/servers", "POST")[0])
        assert server["volumes"] == [33] and server["automount"] is False
        assert server["firewalls"] == [{"firewall": 22}]
        assert server["ssh_keys"] == [11]
        assert "ssh-ed25519 AAAA potato" in server["user_data"]

    @responses.activate
    def test_only_22_80_443(self, provider, spec, project):
        stub_hetzner()
        provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        rules = body(calls_to("/firewalls", "POST")[0])["rules"]
        assert sorted(int(r["port"]) for r in rules) == [22, 80, 443]

    @responses.activate
    def test_a_type_not_sold_there_is_refused_first(self, provider, spec, project):
        spec.region = "ash"
        stub_hetzner()
        with pytest.raises(ProviderError, match="not sold in ash"):
            provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        assert not calls_to("/servers", "POST")

    @responses.activate
    def test_server_recorded_before_it_fails_to_start(self, provider, spec, project,
                                                      monkeypatch):
        stub_hetzner(server_status="initializing")
        clock = iter(range(0, 10_000, 100))
        monkeypatch.setattr(hetzner.time, "time", lambda: next(clock))
        store = DeploymentStore(project)
        with pytest.raises(ProviderError, match="did not start"):
            provider.create(spec, FakeBundle(), None, store)
        assert store.get("pilot").provider_ref["server_id"] == 44
        assert store.get("pilot").status == "failed"

    def test_price_is_shown_in_euros(self, provider, spec):
        assert any("€" in w for w in provider.plan(spec, FakeBundle()).warnings)

    @responses.activate
    def test_destroy_removes_everything(self, provider):
        for path in ("servers/44", "firewalls/22", "ssh_keys/11", "volumes/33"):
            responses.add(responses.DELETE, f"{H}/{path}", status=204)
        responses.add(responses.GET, f"{H}/servers/44", status=404,
                      json={"error": {"message": "not found"}})
        provider.destroy(DeploymentRecord(name="pilot", provider="hetzner", provider_ref={
            "server_id": 44, "firewall_id": 22, "ssh_key_id": 11, "volume_id": 33}))
        deleted = {c.request.url.rsplit("/", 2)[-2] for c in responses.calls
                   if c.request.method == "DELETE"}
        assert deleted == {"servers", "firewalls", "ssh_keys", "volumes"}


# ----------------------------------------------------------------- vultr --

V = vultr.API_ROOT


def stub_vultr():
    responses.add(responses.GET, f"{V}/account", json={"account": {"email": "a@x"}})
    responses.add(responses.GET, f"{V}/os?per_page=500", json={
        "os": [{"id": 9, "name": "Debian"}, {"id": 2284, "name": vultr.OS_NAME}],
        "meta": {"links": {"next": ""}}})
    responses.add(responses.POST, f"{V}/ssh-keys", json={"ssh_key": {"id": "k1"}})
    responses.add(responses.POST, f"{V}/firewalls", json={"firewall_group": {"id": "fw1"}})
    responses.add(responses.POST, f"{V}/firewalls/fw1/rules", json={})
    responses.add(responses.POST, f"{V}/instances", json={"instance": {"id": "i1"}})
    responses.add(responses.GET, f"{V}/instances/i1", json={"instance": {
        "id": "i1", "status": "active", "main_ip": "192.0.2.55"}})
    responses.add(responses.POST, f"{V}/blocks", json={"block": {"id": "b1"}})
    responses.add(responses.POST, f"{V}/blocks/b1/attach", json={})


class TestVultr:
    @pytest.fixture
    def provider(self):
        return get_provider("vultr", token="vk", console=lambda *a: None)

    @responses.activate
    def test_happy_path(self, provider, spec, project):
        stub_vultr()
        record = provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        assert record.url == "https://192.0.2.55"
        instance = body(calls_to("/instances", "POST")[0])
        assert instance["os_id"] == 2284
        assert instance["firewall_group_id"] == "fw1"
        decoded = base64.b64decode(instance["user_data"]).decode()
        assert decoded.startswith("#cloud-config")

    @responses.activate
    def test_firewall_rules_cover_both_address_families(self, provider, spec, project):
        stub_vultr()
        provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        rules = [body(c) for c in calls_to("/firewalls/fw1/rules")]
        assert sorted({r["port"] for r in rules}) == ["22", "443", "80"]
        assert {r["ip_type"] for r in rules} == {"v4", "v6"}

    @responses.activate
    def test_block_attaches_after_the_instance(self, provider, spec, project):
        spec.volume_gb = 5
        stub_vultr()
        record = provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        assert record.provider_ref["block_id"] == "b1"
        assert body(calls_to("/blocks/b1/attach")[0])["instance_id"] == "i1"


# ---------------------------------------------------------------- linode --

L = linode.API_ROOT


def stub_linode():
    responses.add(responses.GET, f"{L}/profile", json={"email": "a@x"})
    responses.add(responses.POST, f"{L}/networking/firewalls", json={"id": 7})
    responses.add(responses.POST, f"{L}/linode/instances", json={"id": 8})
    responses.add(responses.GET, f"{L}/linode/instances/8",
                  json={"id": 8, "status": "running", "ipv4": ["192.0.2.66"]})
    responses.add(responses.POST, f"{L}/volumes", json={"id": 9})


class TestLinode:
    @pytest.fixture
    def provider(self):
        return get_provider("linode", token="lt", console=lambda *a: None)

    @responses.activate
    def test_happy_path(self, provider, spec, project):
        stub_linode()
        record = provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        assert record.url == "https://192.0.2.66"
        instance = body(calls_to("/linode/instances", "POST")[0])
        assert instance["firewall_id"] == 7
        assert instance["authorized_keys"] == ["ssh-ed25519 AAAA potato"]

    @responses.activate
    def test_root_password_is_stored_and_password_login_disabled(
            self, provider, spec, project):
        stub_linode()
        provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        instance = body(calls_to("/linode/instances", "POST")[0])
        stored = SecretStore(project).get("pilot", "linode_root_password")
        assert stored and instance["root_pass"] == stored
        user_data = base64.b64decode(instance["metadata"]["user_data"]).decode()
        assert "ssh_pwauth: false" in user_data

    def test_plan_never_carries_a_real_password(self, provider, spec):
        """The plan is printed and pasted into issues; it shows a placeholder."""
        action = next(a for a in provider.plan(spec, FakeBundle()).actions
                      if a.kind == "linode.instance")
        assert action.request["root_pass"].startswith("<generated")

    @responses.activate
    def test_firewall_drops_all_but_web_and_ssh(self, provider, spec, project):
        stub_linode()
        provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        rules = body(calls_to("/networking/firewalls", "POST")[0])["rules"]
        assert rules["inbound_policy"] == "DROP"
        assert rules["inbound"][0]["ports"] == "22,80,443"


# --------------------------------------------------------------- shared --

@pytest.mark.parametrize("name", ["hetzner", "vultr", "linode"])
class TestEveryVPS:
    def test_plan_makes_no_request(self, name, spec, monkeypatch):
        import requests

        def refuse(*a, **k):
            raise AssertionError("plan() made a request")
        monkeypatch.setattr(requests.Session, "request", refuse)
        provider = get_provider(name, token="t")
        assert provider.plan(spec, FakeBundle()).actions

    def test_plan_prints_no_secret(self, name, spec):
        rendered = get_provider(name, token="t").plan(spec, FakeBundle()).render()
        assert "VPS-SECRET" not in rendered and "VPS-ADMIN" not in rendered

    def test_cloud_init_fits(self, name, spec):
        provider = get_provider(name, token="t")
        user_data = vm_base.build_cloud_init(spec, public_host="x",
                                             volume_device="/dev/sdb",
                                             ssh_authorized_key="ssh-ed25519 AAAA k")
        assert len(user_data.encode()) <= provider.user_data_limit
