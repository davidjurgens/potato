"""The Railway provider, against a faked GraphQL endpoint."""

import json

import pytest
import responses

from potato.deploy.backup_options import BackupOptions
from potato.deploy.bundle_store import BundleLocation
from potato.deploy.providers import railway
from potato.deploy.providers.base import DeploySpec, ProviderError, get_provider
from potato.deploy.providers.railway import GRAPHQL_API, instance_settings
from potato.deploy.state import DeploymentRecord, DeploymentStore


class FakeBundle:
    bundle_dir = "/tmp/bundle"
    file_count = 3
    total_bytes = 1024

    def sha256(self):
        return "d" * 64


class FakeGenerated:
    secret_key = "RW-SECRET-DO-NOT-PRINT"
    admin_api_key = "RW-ADMIN-DO-NOT-PRINT"


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


@pytest.fixture
def provider():
    return get_provider("railway", token="rw", console=lambda *a: None)


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    monkeypatch.setattr(railway.time, "sleep", lambda s: None)
    monkeypatch.setattr("potato.deploy.bundle_store.publish",
                        lambda m, s, w: BundleLocation(url="https://hf/b",
                                                       sha256="e" * 64, token="hf_x"))


def graphql_responder(status="SUCCESS"):
    """Answer each operation by name, recording what was sent."""
    sent = []

    def callback(request):
        payload = json.loads(request.body)
        sent.append(payload)
        query = payload["query"]
        if "projectCreate" in query:
            data = {"projectCreate": {"id": "proj", "environments": {
                "edges": [{"node": {"id": "env", "name": "production"}}]}}}
        elif "serviceCreate" in query:
            data = {"serviceCreate": {"id": "svc"}}
        elif "serviceDomainCreate" in query:
            data = {"serviceDomainCreate": {"domain": "potato-pilot.up.railway.app"}}
        elif "deployments" in query:
            data = {"deployments": {"edges": [{"node": {"id": "dep", "status": status}}]}}
        else:
            data = {"ok": True}
        return 200, {}, json.dumps({"data": data})

    responses.add_callback(responses.POST, GRAPHQL_API, callback=callback)
    return sent


def by_operation(sent, name):
    return [p for p in sent if name in p["query"]]


class TestCreate:
    @responses.activate
    def test_happy_path(self, provider, spec, project):
        sent = graphql_responder()
        record = provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        assert record.url == "https://potato-pilot.up.railway.app"
        assert record.status == "running"

    @responses.activate
    def test_volume_is_the_task_directory_and_runs_as_root_then_drops(
            self, provider, spec, project):
        sent = graphql_responder()
        provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        assert by_operation(sent, "volumeCreate")[0]["variables"]["input"]["mountPath"] == "/app"
        variables = by_operation(sent, "serviceCreate")[0]["variables"]["input"]["variables"]
        assert variables["RAILWAY_RUN_UID"] == "0"
        assert variables["POTATO_BUNDLE_URL"] == "https://hf/b"

    @responses.activate
    def test_one_replica_and_no_deploy_overlap(self, provider, spec, project):
        sent = graphql_responder()
        provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        settings = by_operation(sent, "serviceInstanceUpdate")[0]["variables"]["input"]
        assert settings["numReplicas"] == 1
        assert settings["overlapSeconds"] == 0
        assert settings["sleepApplication"] is False

    @responses.activate
    def test_refuses_without_somewhere_to_put_the_project(self, provider, spec, project):
        spec.extra["backup"] = BackupOptions()
        with pytest.raises(ProviderError, match="--backup"):
            provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        assert not responses.calls

    @responses.activate
    def test_project_recorded_before_the_service_fails(self, provider, spec, project):
        def callback(request):
            query = json.loads(request.body)["query"]
            if "projectCreate" in query:
                return 200, {}, json.dumps({"data": {"projectCreate": {
                    "id": "proj", "environments": {"edges": [{"node": {"id": "env"}}]}}}})
            return 200, {}, json.dumps({"errors": [{"message": "quota"}]})
        responses.add_callback(responses.POST, GRAPHQL_API, callback=callback)
        store = DeploymentStore(project)
        with pytest.raises(ProviderError, match="quota"):
            provider.create(spec, FakeBundle(), None, store)
        assert store.get("pilot").provider_ref["project_id"] == "proj"

    @responses.activate
    def test_a_failed_deployment_is_reported(self, provider, spec, project):
        graphql_responder(status="CRASHED")
        with pytest.raises(ProviderError, match="CRASHED"):
            provider.create(spec, FakeBundle(), None, DeploymentStore(project))

    @responses.activate
    def test_a_redeploy_upserts_variables_without_a_second_service(
            self, provider, spec, project):
        sent = graphql_responder()
        existing = DeploymentRecord(name="pilot", provider="railway",
                                    url="https://potato-pilot.up.railway.app",
                                    provider_ref={"project_id": "proj",
                                                  "environment_id": "env",
                                                  "service_id": "svc"})
        provider.create(spec, FakeBundle(), existing, DeploymentStore(project))
        assert not by_operation(sent, "serviceCreate")
        assert by_operation(sent, "variableCollectionUpsert")

    @responses.activate
    def test_a_redeploy_sets_the_requested_image(self, provider, spec, project):
        """Only serviceCreate set the image, so a redeploy kept the first one."""
        sent = graphql_responder()
        spec.image = "ghcr.io/davidjurgens/potato:2.10.2"
        existing = DeploymentRecord(name="pilot", provider="railway",
                                    url="https://potato-pilot.up.railway.app",
                                    provider_ref={"project_id": "proj",
                                                  "environment_id": "env",
                                                  "service_id": "svc"})
        provider.create(spec, FakeBundle(), existing, DeploymentStore(project))
        updates = by_operation(sent, "serviceInstanceUpdate")
        assert any(u["variables"]["input"].get("source") == {"image": spec.image}
                   for u in updates), updates


class TestPlan:
    def test_prints_no_secret(self, provider, spec):
        rendered = provider.plan(spec, FakeBundle()).render()
        assert "RW-SECRET" not in rendered and "RW-ADMIN" not in rendered

    def test_needs_no_network(self, provider, spec, monkeypatch):
        import requests

        def refuse(*a, **k):
            raise AssertionError("plan() made a request")
        monkeypatch.setattr(requests.Session, "request", refuse)
        assert provider.plan(spec, FakeBundle()).actions


INPUT_TYPES = {
    "projectCreate": "ProjectCreateInput",
    "serviceCreate": "ServiceCreateInput",
    "volumeCreate": "VolumeCreateInput",
    "variableCollectionUpsert": "VariableCollectionUpsertInput",
    "serviceInstanceUpdate": "ServiceInstanceUpdateInput",
    "serviceDomainCreate": "ServiceDomainCreateInput",
    "deployments": "DeploymentListInput",
}


@responses.activate
def test_every_input_field_exists_in_railways_schema(provider, spec, project):
    """Checked against a snapshot of Railway's introspected schema, not against
    this module: a renamed field fails here instead of on someone's deploy."""
    import os

    schema_path = os.path.join(os.path.dirname(__file__), os.pardir, "data",
                               "deploy", "railway_schema_inputs.json")
    with open(schema_path) as handle:
        schema = json.load(handle)

    sent = graphql_responder()
    provider.create(spec, FakeBundle(), None, DeploymentStore(project))
    existing = DeploymentRecord(name="pilot", provider="railway", url="https://x",
                                provider_ref={"project_id": "proj",
                                              "environment_id": "env",
                                              "service_id": "svc"})
    provider.create(spec, FakeBundle(), existing, DeploymentStore(project))

    checked = set()
    for payload in sent:
        for operation, input_type in INPUT_TYPES.items():
            if operation in payload["query"] and "input" in payload["variables"]:
                fields = set(payload["variables"]["input"])
                assert fields <= set(schema[input_type]), (
                    f"{operation} sends {fields - set(schema[input_type])}, "
                    f"which {input_type} does not have")
                checked.add(operation)
                if operation == "serviceCreate":
                    source = set(payload["variables"]["input"]["source"])
                    assert source <= set(schema["ServiceSourceInput"])
    assert checked == set(INPUT_TYPES)
