"""The Lightsail provider (`--provider aws`), against a fake Lightsail API.

What these hold in place: every resource name is written down before the next
call can fail; the static IP is released on destroy (an unattached one bills);
only 22/80/443 are opened; and planning needs no credentials at all.
"""

import pytest

from potato.deploy.providers import vm_base
from potato.deploy.providers.aws import lightsail
from potato.deploy.providers.aws.lightsail import (
    BUNDLE_PRICES,
    DISK_CANDIDATES,
    LightsailProvider,
    instance_request,
    port_request,
)
from potato.deploy.providers.base import DeploySpec, ProviderError, get_provider
from potato.deploy.state import DeploymentRecord, DeploymentStore


class FakeBundle:
    bundle_dir = "/tmp/bundle"
    file_count = 3
    total_bytes = 1024

    def sha256(self):
        return "e" * 64


class FakeGenerated:
    secret_key = "LS-SECRET-DO-NOT-PRINT"
    admin_api_key = "LS-ADMIN-DO-NOT-PRINT"


class NotFound(Exception):
    response = {"Error": {"Code": "NotFoundException"}}


class FakeLightsail:
    """Records calls; behaves like enough of Lightsail for the provider."""

    def __init__(self, fail_on=None, bundles=("small_3_0", "medium_3_0")):
        self.calls = []
        self.fail_on = fail_on
        self.bundles = bundles
        self.instances = {}
        self.ips = {}
        self.disks = {}

    def call(self, method, **kwargs):
        self.calls.append((method, kwargs))
        if method == self.fail_on:
            raise ProviderError(f"AWS lightsail.{method} failed: boom")
        handler = getattr(self, method, None)
        return handler(**kwargs) if handler else {}

    def get_bundles(self):
        return {"bundles": [{"bundleId": b, "isActive": True} for b in self.bundles]}

    def create_instances(self, instanceNames, **kwargs):
        for name in instanceNames:
            self.instances[name] = "running"
        return {}

    def get_instance(self, instanceName):
        if instanceName not in self.instances:
            raise _not_found()
        return {"instance": {"state": {"name": self.instances[instanceName]}}}

    def allocate_static_ip(self, staticIpName):
        self.ips[staticIpName] = "198.51.100.7"
        return {}

    def get_static_ip(self, staticIpName):
        return {"staticIp": {"ipAddress": self.ips[staticIpName]}}

    def create_disk(self, diskName, **kwargs):
        self.disks[diskName] = "available"
        return {}

    def get_disk(self, diskName):
        return {"disk": {"state": self.disks[diskName]}}

    def delete_instance(self, instanceName, **kwargs):
        if instanceName not in self.instances:
            raise _not_found()
        del self.instances[instanceName]
        return {}

    def methods(self):
        return [method for method, _ in self.calls]


def _not_found():
    error = ProviderError("not found")
    error.__cause__ = NotFound()
    return error


@pytest.fixture
def project(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("task_dir: .\n")
    return str(config)


@pytest.fixture
def spec(project):
    return DeploySpec(name="pilot", config_path=project,
                      extra={"config_rel": "config.yaml",
                             "generated": FakeGenerated(),
                             "acme_email": "pi@example.edu"})


@pytest.fixture
def fake(monkeypatch):
    api = FakeLightsail()
    monkeypatch.setattr(LightsailProvider, "_api", lambda self, region=None: api)
    monkeypatch.setattr(lightsail, "caller_identity", lambda *a, **k: "arn:aws:iam::1:user/pi")
    monkeypatch.setattr(lightsail, "wait_until", lambda predicate, **k: predicate())
    # No SSH in unit tests; the VM half has its own tests.
    monkeypatch.setattr(vm_base.VMProvider, "_configure_host",
                        lambda self, *a, **k: None)
    monkeypatch.setattr(vm_base, "generate_keypair",
                        lambda comment="": ("PRIVATE-PEM", "ssh-ed25519 AAAA potato"))
    return api


@pytest.fixture
def provider():
    return get_provider("aws", console=lambda *a: None)


class TestRequests:
    def test_instance_is_ubuntu_in_the_first_zone(self, spec):
        request = instance_request(spec, region="eu-west-2", bundle="small_3_0",
                                   user_data="#cloud-config")
        assert request["instanceNames"] == ["potato-pilot"]
        assert request["availabilityZone"] == "eu-west-2a"
        assert request["blueprintId"].startswith("ubuntu_")
        assert request["bundleId"] == "small_3_0"
        assert {"key": "potato", "value": "pilot"} in request["tags"]

    def test_only_ssh_http_https_are_opened(self):
        ports = port_request("potato-pilot")["portInfos"]
        assert sorted(p["fromPort"] for p in ports) == [22, 80, 443]
        assert all(p["fromPort"] == p["toPort"] for p in ports)


class TestPlan:
    def test_needs_no_credentials_or_network(self, provider, spec, monkeypatch):
        def refuse(*a, **k):
            raise AssertionError("plan() touched AWS")
        monkeypatch.setattr(lightsail, "AWSClient", refuse)
        monkeypatch.setattr(lightsail, "caller_identity", refuse)
        plan = provider.plan(spec, FakeBundle())
        assert plan.actions

    def test_default_is_the_2gb_bundle_at_its_price(self, provider, spec):
        plan = provider.plan(spec, FakeBundle())
        assert plan.estimated_cost_usd_month == BUNDLE_PRICES["small_3_0"] == 12.0

    def test_a_small_bundle_is_warned_about(self, provider, spec):
        spec.size = "micro_3_0"
        assert any("RAM" in w for w in provider.plan(spec, FakeBundle()).warnings)

    def test_the_static_ip_is_planned(self, provider, spec):
        kinds = [a.kind for a in provider.plan(spec, FakeBundle()).actions]
        assert "lightsail.static_ip" in kinds
        assert kinds.index("lightsail.instance") < kinds.index("state.persist")

    def test_no_secret_value_is_printed(self, provider, spec):
        rendered = provider.plan(spec, FakeBundle()).render()
        assert FakeGenerated.secret_key not in rendered
        assert FakeGenerated.admin_api_key not in rendered

    def test_cloud_init_carries_the_deploy_key_and_fits(self, provider, spec):
        user_data = vm_base.build_cloud_init(
            spec, public_host="x", volume_device="/dev/xvdf",
            ssh_authorized_key="ssh-ed25519 AAAA potato")
        assert "ssh-ed25519 AAAA potato" in user_data
        assert len(user_data.encode()) <= provider.user_data_limit


class TestCreate:
    def test_happy_path(self, provider, spec, project, fake):
        record = provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        assert record.status == "running"
        assert record.url == "https://198.51.100.7"
        assert record.provider_ref["instance_name"] == "potato-pilot"
        assert record.provider_ref["static_ip_name"] == "potato-pilot-ip"
        assert fake.methods().index("create_instances") < \
            fake.methods().index("allocate_static_ip")

    def test_logs_in_as_ubuntu(self, provider):
        assert provider.ssh_user == "ubuntu"

    def test_instance_is_recorded_before_a_later_failure(self, provider, spec,
                                                         project, fake):
        fake.fail_on = "allocate_static_ip"
        store = DeploymentStore(project)
        with pytest.raises(ProviderError):
            provider.create(spec, FakeBundle(), None, store)
        record = store.get("pilot")
        assert record.provider_ref["instance_name"] == "potato-pilot"
        assert record.status == "failed"

    def test_a_retired_bundle_is_refused_before_anything_is_created(
            self, provider, spec, project, fake):
        spec.size = "small_2_0"
        with pytest.raises(ProviderError, match="small_3_0"):
            provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        assert "create_instances" not in fake.methods()

    def test_a_disk_is_attached_and_its_device_candidates_recorded(
            self, provider, spec, project, fake):
        spec.volume_gb = 8
        record = provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        assert "attach_disk" in fake.methods()
        assert record.provider_ref["volume_devices"] == DISK_CANDIDATES
        assert record.provider_ref["app_dir"] == vm_base.VOLUME_APP_DIR

    def test_the_profile_is_remembered_for_later_commands(self, provider, spec,
                                                          project, fake):
        spec.extra["aws_profile"] = "lab"
        record = provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        assert record.provider_ref["aws_profile"] == "lab"


class TestStatusAndDestroy:
    def _record(self, **ref):
        reference = {"instance_name": "potato-pilot",
                     "static_ip_name": "potato-pilot-ip", "region": "us-east-1"}
        reference.update(ref)
        return DeploymentRecord(name="pilot", provider="aws", url="https://198.51.100.7",
                                provider_ref=reference)

    def test_a_deleted_instance_reads_as_absent(self, provider, fake):
        assert provider.status(self._record()).state == "absent"

    def test_destroy_releases_the_static_ip(self, provider, fake):
        """An unattached static IP bills; leaving it is a slow leak."""
        fake.instances["potato-pilot"] = "running"
        provider.destroy(self._record())
        assert "release_static_ip" in fake.methods()
        assert fake.methods().index("delete_instance") < \
            fake.methods().index("release_static_ip")

    def test_keep_data_keeps_the_disk(self, provider, fake):
        fake.instances["potato-pilot"] = "running"
        provider.destroy(self._record(disk_name="potato-pilot-data"), keep_data=True)
        assert "delete_disk" not in fake.methods()

    def test_destroy_finishes_a_half_deleted_deployment(self, provider, fake):
        """The instance is already gone; the IP must still be released."""
        provider.destroy(self._record())
        assert "release_static_ip" in fake.methods()


class TestCredentials:
    def test_aws_needs_no_token_string(self):
        from potato.deploy import credentials as creds
        assert creds.is_ambient("aws")
        assert not creds.requires_credential("aws")

    def test_verify_asks_sts(self, provider, monkeypatch):
        monkeypatch.setattr(lightsail, "caller_identity",
                            lambda profile=None, region=None: f"arn ({profile})")
        provider.profile = "lab"
        assert provider.verify_credential() == "arn (lab)"


class TestAgainstTheLightsailModel:
    """botocore validates parameters against AWS's model before sending."""

    def _client(self):
        boto3 = pytest.importorskip("boto3")
        return boto3.client("lightsail", region_name="us-east-1",
                            aws_access_key_id="x", aws_secret_access_key="y")

    def test_instance_and_port_requests_are_valid(self, spec):
        from botocore.stub import Stubber

        client = self._client()
        with Stubber(client) as stubber:
            stubber.add_response("create_instances", {}, None)
            stubber.add_response("put_instance_public_ports", {}, None)
            client.create_instances(**instance_request(
                spec, region="us-east-1", bundle="small_3_0", user_data="#cloud-config"))
            client.put_instance_public_ports(**port_request("potato-pilot"))
