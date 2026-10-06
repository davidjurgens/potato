"""The Fly.io provider, against faked Machines and GraphQL APIs."""

import base64
import json

import pytest
import responses
import yaml

from potato.deploy.backup_options import BackupOptions
from potato.deploy.bundle import build_bundle
from potato.deploy.bundle_store import BundleLocation
from potato.deploy.providers import fly
from potato.deploy.providers.base import DeploySpec, ProviderError, get_provider
from potato.deploy.providers.fly import (
    GRAPHQL_API,
    INLINE_BUNDLE_PATH,
    MACHINES_API,
    app_name,
    machine_config,
)
from potato.deploy.state import DeploymentRecord, DeploymentStore

M = MACHINES_API


class FakeGenerated:
    secret_key = "FLY-SECRET-DO-NOT-PRINT"
    admin_api_key = "FLY-ADMIN-DO-NOT-PRINT"


@pytest.fixture
def project(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "items.json").write_text('[{"id":"1","text":"hi"}]')
    config = {"task_dir": ".", "annotation_task_name": "fly",
              "data_files": ["data/items.json"],
              "item_properties": {"id_key": "id", "text_key": "text"},
              "annotation_schemes": []}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    return str(path)


@pytest.fixture
def bundle(project, tmp_path):
    return build_bundle(project, str(tmp_path / "bundle"))


@pytest.fixture
def spec(project, tmp_path):
    return DeploySpec(name="pilot", config_path=project,
                      extra={"config_rel": "config.yaml", "generated": FakeGenerated(),
                             "bundle_workdir": str(tmp_path / "dist")})


@pytest.fixture
def provider():
    return get_provider("fly", token="fo1_test", console=lambda *a: None)


@pytest.fixture(autouse=True)
def healthy(monkeypatch):
    monkeypatch.setattr(fly, "_healthy", lambda url, timeout: True)


def stub_fly(app="potato-pilot"):
    responses.add(responses.POST, f"{M}/apps", json={})
    responses.add(responses.POST, GRAPHQL_API, json={"data": {}})
    responses.add(responses.POST, f"{M}/apps/{app}/volumes", json={"id": "vol_1"})
    responses.add(responses.POST, f"{M}/apps/{app}/machines", json={"id": "m_1"})
    responses.add(responses.GET, f"{M}/apps/{app}/machines/m_1/wait?state=started&timeout=60",
                  json={"ok": True})


def posted(fragment):
    return [json.loads(c.request.body) for c in responses.calls
            if c.request.method == "POST" and c.request.url.endswith(fragment)]


class TestConfig:
    def test_one_always_on_machine(self, spec):
        config = machine_config(spec, image="img", env={}, volume_id="v", memory_mb=1024)
        service = config["services"][0]
        assert service["autostop"] == "off" and service["min_machines_running"] == 1
        assert service["internal_port"] == 7860

    def test_the_volume_is_the_task_directory(self, spec):
        config = machine_config(spec, image="img", env={}, volume_id="v", memory_mb=1024)
        assert config["mounts"] == [{"volume": "v", "path": "/app"}]

    def test_https_is_forced(self, spec):
        ports = machine_config(spec, image="i", env={}, volume_id=None,
                               memory_mb=512)["services"][0]["ports"]
        assert {"port": 80, "handlers": ["http"], "force_https": True} in ports

    def test_app_names_are_dns_safe(self):
        assert app_name("My Study_2") == "potato-my-study-2"


class TestCreate:
    @responses.activate
    def test_small_project_travels_inline(self, provider, spec, bundle, project):
        stub_fly()
        record = provider.create(spec, bundle, None, DeploymentStore(project))
        assert record.url == "https://potato-pilot.fly.dev"
        config = posted("/machines")[0]["config"]
        assert config["env"]["POTATO_BUNDLE_URL"] == f"file://{INLINE_BUNDLE_PATH}"
        inline = config["files"][0]
        assert inline["guest_path"] == INLINE_BUNDLE_PATH
        assert base64.b64decode(inline["raw_value"])[:2] == b"\x1f\x8b"  # gzip

    @responses.activate
    def test_secrets_go_to_the_secret_store_not_env(self, provider, spec, bundle,
                                                    project):
        stub_fly()
        provider.create(spec, bundle, None, DeploymentStore(project))
        env = posted("/machines")[0]["config"]["env"]
        assert "POTATO_SECRET_KEY" not in env
        mutations = [b for b in posted("/graphql") if "setSecrets" in b["query"]]
        keys = {s["key"] for s in mutations[0]["variables"]["input"]["secrets"]}
        assert {"POTATO_SECRET_KEY", "POTATO_ADMIN_API_KEY"} <= keys

    @responses.activate
    def test_a_large_project_uses_the_backup_storage(self, provider, spec, bundle,
                                                     project, monkeypatch):
        monkeypatch.setattr(fly, "INLINE_BUNDLE_LIMIT", 1)
        spec.extra["backup"] = BackupOptions(kinds=["hf"], hf_token="hf_x",
                                             hf_repo="me/r")
        monkeypatch.setattr("potato.deploy.bundle_store.publish",
                            lambda m, s, w: BundleLocation(url="https://hf/b", sha256="d" * 64,
                                                           token="hf_x"))
        stub_fly()
        provider.create(spec, bundle, None, DeploymentStore(project))
        config = posted("/machines")[0]["config"]
        assert config["env"]["POTATO_BUNDLE_URL"] == "https://hf/b"
        assert "files" not in config
        assert "POTATO_BUNDLE_TOKEN" not in config["env"]

    @responses.activate
    def test_a_large_project_with_nowhere_to_go_is_refused(self, provider, spec,
                                                           bundle, project, monkeypatch):
        monkeypatch.setattr(fly, "INLINE_BUNDLE_LIMIT", 1)
        with pytest.raises(ProviderError, match="--backup"):
            provider.create(spec, bundle, None, DeploymentStore(project))
        assert not responses.calls

    @responses.activate
    def test_app_recorded_before_the_volume_fails(self, provider, spec, bundle, project):
        responses.add(responses.POST, f"{M}/apps", json={})
        responses.add(responses.POST, GRAPHQL_API, json={"data": {}})
        responses.add(responses.POST, f"{M}/apps/potato-pilot/volumes", status=422,
                      json={"error": "region full"})
        store = DeploymentStore(project)
        with pytest.raises(ProviderError):
            provider.create(spec, bundle, None, store)
        assert store.get("pilot").provider_ref["app"] == "potato-pilot"

    @responses.activate
    def test_a_redeploy_updates_the_same_machine(self, provider, spec, bundle, project):
        responses.add(responses.POST, GRAPHQL_API, json={"data": {}})
        responses.add(responses.POST, f"{M}/apps/potato-pilot/machines/m_1", json={})
        responses.add(responses.GET,
                      f"{M}/apps/potato-pilot/machines/m_1/wait?state=started&timeout=60",
                      json={})
        existing = DeploymentRecord(name="pilot", provider="fly",
                                    url="https://potato-pilot.fly.dev",
                                    provider_ref={"app": "potato-pilot",
                                                  "volume_id": "vol_1",
                                                  "machine_id": "m_1"})
        provider.create(spec, bundle, existing, DeploymentStore(project))
        assert not posted("/apps/potato-pilot/machines")
        assert not posted("/volumes")


class TestOther:
    def test_logs_point_at_flyctl(self, provider):
        with pytest.raises(ProviderError, match="fly logs"):
            provider.logs(DeploymentRecord(name="p", provider="fly",
                                           provider_ref={"app": "potato-p"}))

    def test_plan_prints_no_secret(self, provider, spec, bundle):
        rendered = provider.plan(spec, bundle).render()
        assert "FLY-SECRET" not in rendered and "FLY-ADMIN" not in rendered

    def test_plan_needs_no_network(self, provider, spec, bundle, monkeypatch):
        import requests

        def refuse(*a, **k):
            raise AssertionError("plan() made a request")
        monkeypatch.setattr(requests.Session, "request", refuse)
        assert provider.plan(spec, bundle).actions
