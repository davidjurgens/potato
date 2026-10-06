"""The EC2 provider (`--provider aws-ec2`), against a fake EC2/SSM API."""

import pytest

from potato.deploy.providers import vm_base
from potato.deploy.providers.aws import ec2
from potato.deploy.providers.aws.ec2 import (
    AMI_PARAMETER,
    EC2Provider,
    architecture,
    ebs_device_candidates,
    ingress_permissions,
    run_request,
)
from potato.deploy.providers.base import DeploySpec, ProviderError, get_provider
from potato.deploy.state import DeploymentRecord, DeploymentStore


class FakeBundle:
    bundle_dir = "/tmp/bundle"
    file_count = 3
    total_bytes = 1024

    def sha256(self):
        return "a" * 64


class FakeEC2:
    def __init__(self, default_vpc=True, fail_on=None):
        self.calls = []
        self.default_vpc = default_vpc
        self.fail_on = fail_on
        self.state = "running"

    def call(self, method, **kwargs):
        self.calls.append((method, kwargs))
        if method == self.fail_on:
            raise ProviderError(f"AWS ec2.{method} failed: boom")
        return getattr(self, method, lambda **k: {})(**kwargs)

    def get_parameter(self, Name):
        return {"Parameter": {"Value": "ami-123"}}

    def describe_vpcs(self, Filters):
        return {"Vpcs": [{"VpcId": "vpc-1"}] if self.default_vpc else []}

    def create_security_group(self, **kwargs):
        return {"GroupId": "sg-1"}

    def run_instances(self, **kwargs):
        return {"Instances": [{"InstanceId": "i-1"}]}

    def describe_instances(self, InstanceIds):
        return {"Reservations": [{"Instances": [{
            "InstanceId": "i-1", "State": {"Name": self.state},
            "Placement": {"AvailabilityZone": "us-east-1b"}}]}]}

    def allocate_address(self, **kwargs):
        return {"AllocationId": "eipalloc-1", "PublicIp": "203.0.113.20"}

    def create_volume(self, **kwargs):
        return {"VolumeId": "vol-0abc"}

    def describe_volumes(self, VolumeIds):
        return {"Volumes": [{"State": "available"}]}

    def terminate_instances(self, InstanceIds):
        self.state = "terminated"
        return {}

    def methods(self):
        return [m for m, _ in self.calls]


@pytest.fixture
def project(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("task_dir: .\n")
    return str(config)


@pytest.fixture
def spec(project):
    return DeploySpec(name="pilot", config_path=project,
                      extra={"config_rel": "config.yaml"})


@pytest.fixture
def fake(monkeypatch):
    api = FakeEC2()
    monkeypatch.setattr(EC2Provider, "_api", lambda self, region=None: api)
    monkeypatch.setattr(EC2Provider, "_ssm", lambda self, region: api)
    monkeypatch.setattr(ec2, "caller_identity", lambda *a, **k: "arn")
    monkeypatch.setattr(ec2, "wait_until", lambda predicate, **k: predicate())
    monkeypatch.setattr(vm_base.VMProvider, "_configure_host", lambda self, *a, **k: None)
    monkeypatch.setattr(vm_base, "generate_keypair",
                        lambda comment="": ("PEM", "ssh-ed25519 AAAA potato"))
    return api


@pytest.fixture
def provider():
    return get_provider("aws-ec2", console=lambda *a: None)


class TestRequests:
    @pytest.mark.parametrize("instance_type,arch", [
        ("t4g.small", "arm64"), ("m7g.large", "arm64"), ("c8g.xlarge", "arm64"),
        ("t3.small", "amd64"), ("m5.large", "amd64")])
    def test_architecture_follows_the_family(self, instance_type, arch):
        assert architecture(instance_type) == arch

    def test_ami_comes_from_canonicals_parameter(self):
        assert AMI_PARAMETER.format(arch="arm64").startswith(
            "/aws/service/canonical/ubuntu/server/24.04/")

    def test_imdsv2_only(self, spec):
        request = run_request(spec, image_id="ami", instance_type="t4g.small",
                              security_group="sg", user_data="x")
        assert request["MetadataOptions"]["HttpTokens"] == "required"
        assert request["MinCount"] == request["MaxCount"] == 1

    def test_only_22_80_443(self):
        assert sorted(p["FromPort"] for p in ingress_permissions()) == [22, 80, 443]

    def test_volume_is_found_by_its_nvme_id_first(self):
        assert ebs_device_candidates("vol-0abc")[0] == \
            "/dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_vol0abc"


class TestPlan:
    def test_cost_includes_the_ipv4_charge(self, provider, spec):
        cost = provider.plan(spec, FakeBundle()).estimated_cost_usd_month
        assert cost > ec2.TYPE_PRICES["t4g.small"] + ec2.IPV4_PRICE

    def test_needs_no_credentials(self, provider, spec, monkeypatch):
        def refuse(*a, **k):
            raise AssertionError("plan() touched AWS")
        monkeypatch.setattr(ec2, "AWSClient", refuse)
        monkeypatch.setattr(ec2, "caller_identity", refuse)
        assert provider.plan(spec, FakeBundle()).actions


class TestCreate:
    def test_happy_path(self, provider, spec, project, fake):
        record = provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        assert record.url == "https://203.0.113.20"
        assert record.provider_ref["instance_id"] == "i-1"
        assert record.provider_ref["allocation_id"] == "eipalloc-1"

    def test_no_default_vpc_names_the_flag(self, provider, spec, project, fake):
        fake.default_vpc = False
        with pytest.raises(ProviderError, match="--subnet"):
            provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        assert "run_instances" not in fake.methods()

    def test_instance_recorded_before_the_address_fails(self, provider, spec,
                                                         project, fake):
        fake.fail_on = "allocate_address"
        store = DeploymentStore(project)
        with pytest.raises(ProviderError):
            provider.create(spec, FakeBundle(), None, store)
        assert store.get("pilot").provider_ref["instance_id"] == "i-1"

    def test_volume_attached_in_the_instance_zone(self, provider, spec, project, fake):
        spec.volume_gb = 10
        record = provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        create = dict(fake.calls)["create_volume"]
        assert create["AvailabilityZone"] == "us-east-1b"
        assert record.provider_ref["volume_devices"][0].endswith("vol0abc")


class TestDestroy:
    def test_releases_the_address_and_removes_the_group(self, provider, fake):
        record = DeploymentRecord(name="pilot", provider="aws-ec2", provider_ref={
            "instance_id": "i-1", "allocation_id": "eipalloc-1",
            "security_group_id": "sg-1", "region": "us-east-1"})
        provider.destroy(record)
        methods = fake.methods()
        assert methods.index("terminate_instances") < methods.index("release_address")
        assert "delete_security_group" in methods

    def test_keep_data_keeps_the_volume(self, provider, fake):
        record = DeploymentRecord(name="pilot", provider="aws-ec2", provider_ref={
            "instance_id": "i-1", "volume_id": "vol-0abc", "region": "us-east-1"})
        provider.destroy(record, keep_data=True)
        assert "delete_volume" not in fake.methods()


class TestAgainstTheEC2Model:
    def test_run_and_ingress_requests_are_valid(self, spec):
        boto3 = pytest.importorskip("boto3")
        from botocore.stub import Stubber

        client = boto3.client("ec2", region_name="us-east-1",
                              aws_access_key_id="x", aws_secret_access_key="y")
        with Stubber(client) as stubber:
            stubber.add_response("run_instances", {"Instances": []}, None)
            stubber.add_response("authorize_security_group_ingress", {}, None)
            client.run_instances(**run_request(
                spec, image_id="ami-1", instance_type="t4g.small",
                security_group="sg-1", user_data="#cloud-config", subnet="subnet-1"))
            client.authorize_security_group_ingress(
                GroupId="sg-1", IpPermissions=ingress_permissions())
