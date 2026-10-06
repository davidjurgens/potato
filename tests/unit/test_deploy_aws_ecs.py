"""The ECS Express provider, with botocore's Stubber.

Stubber validates every request against AWS's own service model, so a wrong
parameter name fails here rather than on a researcher's account.
"""

import pytest
from botocore.stub import ANY, Stubber

from potato.deploy.backup_options import BackupOptions
from potato.deploy.bundle_store import BundleLocation
from potato.deploy.providers.aws import _aws, ecs as ecs_module
from potato.deploy.providers.aws.ecs import (
    EXECUTION_ROLE,
    INFRASTRUCTURE_ROLE,
    ECSExpressProvider,
    express_request,
)
from potato.deploy.providers.base import DeploySpec, ProviderError, get_provider
from potato.deploy.state import DeploymentRecord, DeploymentStore

boto3 = pytest.importorskip("boto3")

REGION = "us-east-1"
ACCOUNT = "123456789012"
SERVICE_ARN = f"arn:aws:ecs:{REGION}:{ACCOUNT}:service/default/potato-pilot"


class FakeBundle:
    bundle_dir = "/tmp/bundle"
    file_count = 3
    total_bytes = 1024

    def sha256(self):
        return "f" * 64


class FakeGenerated:
    secret_key = "ECS-SECRET-DO-NOT-PRINT"
    admin_api_key = "ECS-ADMIN-DO-NOT-PRINT"


@pytest.fixture
def project(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("task_dir: .\n")
    return str(config)


@pytest.fixture
def spec(project):
    return DeploySpec(name="pilot", config_path=project, extra={
        "config_rel": "config.yaml", "generated": FakeGenerated(),
        "backup": BackupOptions(kinds=["hf"], hf_token="hf_x", hf_repo="me/r"),
        "backup_kinds": ["hf"]})


class Stubs:
    def __init__(self):
        self.clients = {name: boto3.client(name, region_name=REGION,
                                           aws_access_key_id="x",
                                           aws_secret_access_key="y")
                        for name in ("ecs", "iam", "ssm", "logs")}
        self.stubbers = {name: Stubber(c) for name, c in self.clients.items()}

    def __getitem__(self, name):
        return self.stubbers[name]

    def activate(self):
        for stubber in self.stubbers.values():
            stubber.activate()

    def assert_done(self):
        for stubber in self.stubbers.values():
            stubber.assert_no_pending_responses()


@pytest.fixture
def stubs(monkeypatch):
    stubs = Stubs()
    monkeypatch.setattr(ECSExpressProvider, "_client",
                        lambda self, service, region: _aws.AWSClient(
                            service, client=stubs.clients[service]))
    monkeypatch.setattr(ecs_module, "caller_identity", lambda *a, **k: "arn")
    monkeypatch.setattr(ecs_module, "wait_until", lambda predicate, **k: predicate())
    monkeypatch.setattr(ecs_module, "_healthy", lambda url, timeout: True)
    monkeypatch.setattr(ecs_module.time, "sleep", lambda s: None)
    monkeypatch.setattr("potato.deploy.bundle_store.publish",
                        lambda m, s, w: BundleLocation(url="https://hf/b",
                                                       sha256="e" * 64, token="hf_x"))
    return stubs


def role(name):
    return {"Role": {"Path": "/", "RoleName": name, "RoleId": "AROAEXAMPLE1234567890",
                     "Arn": f"arn:aws:iam::{ACCOUNT}:role/{name}",
                     "CreateDate": "2026-01-01T00:00:00Z"}}


def stub_roles(stubs):
    stubs["iam"].add_response("get_role", role(EXECUTION_ROLE), {"RoleName": EXECUTION_ROLE})
    stubs["iam"].add_response("put_role_policy", {}, {
        "RoleName": EXECUTION_ROLE, "PolicyName": "potato-pilot-parameters",
        "PolicyDocument": ANY})
    stubs["iam"].add_response("get_role", role(INFRASTRUCTURE_ROLE),
                              {"RoleName": INFRASTRUCTURE_ROLE})


def stub_secrets(stubs, keys=("POTATO_ADMIN_API_KEY", "POTATO_BUNDLE_TOKEN",
                              "POTATO_SECRET_KEY")):
    for key in sorted(keys):
        name = f"/potato/pilot/{key}"
        stubs["ssm"].add_response("put_parameter", {"Version": 1}, {
            "Name": name, "Value": ANY, "Type": "SecureString", "Overwrite": True})
        stubs["ssm"].add_response("get_parameter", {"Parameter": {
            "Name": name, "ARN": f"arn:aws:ssm:{REGION}:{ACCOUNT}:parameter{name}"}},
            {"Name": name})


def stub_logs(stubs):
    stubs["logs"].add_response("create_log_group", {}, {"logGroupName": "/potato/pilot"})
    stubs["logs"].add_response("put_retention_policy", {}, {
        "logGroupName": "/potato/pilot", "retentionInDays": 30})


def describe_services(maximum=100):
    return {"services": [{"serviceName": "potato-pilot", "deploymentConfiguration": {
        "maximumPercent": maximum, "minimumHealthyPercent": 0}}]}


def stub_express(stubs):
    stubs["ecs"].add_response("create_express_gateway_service", {"service": {
        "serviceArn": SERVICE_ARN, "cluster": "default", "serviceName": "potato-pilot"}},
        # botocore validates the parameters against the model before the stub
        # sees them, so a wrong name still fails here.
        None)
    stubs["ecs"].add_response("update_service", {}, {
        "cluster": "default", "service": "potato-pilot",
        "deploymentConfiguration": {"strategy": "ROLLING", "maximumPercent": 100,
                                    "minimumHealthyPercent": 0}})
    stubs["ecs"].add_response("describe_services", describe_services(),
                              {"cluster": "default", "services": ["potato-pilot"]})
    stubs["ecs"].add_response("describe_express_gateway_service", {"service": {
        "serviceArn": SERVICE_ARN, "activeConfigurations": [{"ingressPaths": [
            {"accessType": "PUBLIC", "endpoint": "pilot.ecs.us-east-1.on.aws"}]}]}},
        {"serviceArn": SERVICE_ARN})


class TestCreate:
    def test_happy_path_against_the_real_service_model(self, spec, project, stubs):
        stub_roles(stubs)
        stub_secrets(stubs)
        stub_logs(stubs)
        stub_express(stubs)
        stubs.activate()
        provider = get_provider("aws-ecs", console=lambda *a: None)
        record = provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        stubs.assert_done()
        assert record.url == "https://pilot.ecs.us-east-1.on.aws"
        assert record.provider_ref["service_arn"] == SERVICE_ARN

    def test_refuses_without_a_backup(self, spec, project, stubs):
        spec.extra["backup_kinds"] = []
        with pytest.raises(ProviderError, match="no volume"):
            get_provider("aws-ecs").create(spec, FakeBundle(), None,
                                           DeploymentStore(project))

    def test_demo_does_not_replace_the_backup(self, spec, project, stubs):
        """ECS uploads the project to the backup's storage, so --demo alone
        used to pass the plan and then fail in create()."""
        spec.extra["backup_kinds"] = []
        spec.extra["backup"] = None
        spec.demo = True
        provider = get_provider("aws-ecs")
        message = provider.refusal(spec, FakeBundle())
        assert message and "--demo" in message and "not an option" in message
        with pytest.raises(ProviderError, match="not an option"):
            provider.create(spec, FakeBundle(), None, DeploymentStore(project))

    def test_a_redeploy_refuses_when_deploys_would_overlap(self, spec, project, stubs):
        stubs["ecs"].add_response("describe_services", describe_services(maximum=200),
                                  {"cluster": "default", "services": ["potato-pilot"]})
        stubs.activate()
        existing = DeploymentRecord(name="pilot", provider="aws-ecs", provider_ref={
            "service_arn": SERVICE_ARN, "cluster": "default",
            "service_name": "potato-pilot", "region": REGION})
        with pytest.raises(ProviderError, match="later write"):
            get_provider("aws-ecs").create(spec, FakeBundle(), existing,
                                           DeploymentStore(project))


class TestRequest:
    def test_exactly_one_task(self, spec):
        request = express_request(spec, execution_role="e", infrastructure_role="i",
                                  env={}, secrets={}, log_group="g", image="img")
        assert request["scalingTarget"] == {"minTaskCount": 1, "maxTaskCount": 1}

    def test_secrets_are_references_not_values(self, spec):
        request = express_request(spec, execution_role="e", infrastructure_role="i",
                                  env={"PORT": "7860"},
                                  secrets={"POTATO_SECRET_KEY": "arn:ssm:x"},
                                  log_group="g", image="img")
        container = request["primaryContainer"]
        assert container["secrets"] == [{"name": "POTATO_SECRET_KEY",
                                         "valueFrom": "arn:ssm:x"}]
        assert all(e["name"] != "POTATO_SECRET_KEY" for e in container["environment"])

    def test_the_request_validates_against_the_ecs_model(self, spec):
        """Stubber raises on any parameter the real API would reject."""
        client = boto3.client("ecs", region_name=REGION, aws_access_key_id="x",
                              aws_secret_access_key="y")
        request = express_request(spec, execution_role="arn:e",
                                  infrastructure_role="arn:i", env={"A": "1"},
                                  secrets={"B": "arn:b"}, log_group="g", image="img")
        with Stubber(client) as stubber:
            stubber.add_response("create_express_gateway_service",
                                 {"service": {"serviceArn": "a"}}, request)
            client.create_express_gateway_service(**request)

    def test_plan_prints_no_secret(self, spec):
        rendered = get_provider("aws-ecs").plan(spec, FakeBundle()).render()
        assert "ECS-SECRET" not in rendered and "ECS-ADMIN" not in rendered
