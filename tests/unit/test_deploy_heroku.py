"""The Heroku provider.

The behaviour that matters most is the refusal: a dyno's filesystem is wiped on
every restart and dynos restart at least daily, so a deploy with nowhere to
keep the data loses it within a day, silently.
"""

import io
import json
import os
import tarfile

import pytest
import responses

from potato.deploy.providers import heroku
from potato.deploy.providers.base import DeploySpec, ProviderError, get_provider
from potato.deploy.providers.heroku import (
    API_ROOT,
    DYNO_PRICES,
    HEROKU_YML,
    app_name,
    build_source_tarball,
    source_files,
)
from potato.deploy.state import DeploymentRecord, DeploymentStore


class FakeGenerated:
    secret_key = "HK-SECRET-DO-NOT-PRINT"
    admin_api_key = "HK-ADMIN-DO-NOT-PRINT"


@pytest.fixture
def bundle(tmp_path):
    root = tmp_path / "bundle"
    (root / "data").mkdir(parents=True)
    (root / "config.yaml").write_text("task_dir: .\n")
    (root / "data" / "items.json").write_text("[]")

    class Bundle:
        bundle_dir = str(root)
        file_count = 2
        total_bytes = 20

        def sha256(self):
            return "f" * 64
    return Bundle()


@pytest.fixture
def project(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("task_dir: .\n")
    return str(config)


@pytest.fixture
def spec(project, tmp_path):
    return DeploySpec(name="pilot", config_path=project,
                      extra={"config_rel": "config.yaml",
                             "generated": FakeGenerated(),
                             "backup_kinds": ["hf"],
                             "bundle_workdir": str(tmp_path / "dist")})


@pytest.fixture
def provider():
    return get_provider("heroku", token="hk_test", console=lambda *a: None)


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(heroku.time, "sleep", lambda s: None)
    monkeypatch.setattr(heroku, "_wait_for_http", lambda url, timeout: True)


def stub_happy_path(name="potato-pilot"):
    responses.add(responses.GET, f"{API_ROOT}/account", json={"email": "pi@x.edu"})
    responses.add(responses.POST, f"{API_ROOT}/apps",
                  json={"name": name, "web_url": f"https://{name}-abc.herokuapp.com/"})
    responses.add(responses.PATCH, f"{API_ROOT}/apps/{name}/config-vars", json={})
    responses.add(responses.POST, f"{API_ROOT}/sources",
                  json={"source_blob": {"put_url": "https://s3.test/put",
                                        "get_url": "https://s3.test/get"}})
    responses.add(responses.PUT, "https://s3.test/put", status=200)
    responses.add(responses.POST, f"{API_ROOT}/apps/{name}/builds",
                  json={"id": "b1", "status": "pending"})
    responses.add(responses.GET, f"{API_ROOT}/apps/{name}/builds/b1",
                  json={"id": "b1", "status": "succeeded"})
    responses.add(responses.PATCH, f"{API_ROOT}/apps/{name}/formation/web", json={})


class TestNames:
    def test_lowercase_dashes_at_most_30(self):
        name = app_name("My_Study.With Spaces and a very long name indeed")
        assert len(name) <= 30
        assert name == name.lower()
        assert all(c.isalnum() or c == "-" for c in name)
        assert not name.endswith("-")


class TestSource:
    def test_dockerfile_derives_from_the_published_image(self, spec):
        dockerfile = source_files(spec)["Dockerfile"]
        assert dockerfile.startswith("#") and "FROM ghcr.io/davidjurgens/potato:latest" in dockerfile

    def test_the_task_is_writable_by_an_arbitrary_uid(self, spec):
        """Heroku runs the container as a random non-root uid, not 1000."""
        dockerfile = source_files(spec)["Dockerfile"]
        assert "chmod -R a+rwX /app" in dockerfile
        assert "HOME=/tmp" in dockerfile

    def test_heroku_yml_builds_the_dockerfile(self, spec):
        assert source_files(spec)["heroku.yml"] == HEROKU_YML

    def test_tarball_has_bundle_and_build_files_but_no_secret(self, spec, bundle,
                                                              tmp_path):
        path = build_source_tarball(spec, bundle, str(tmp_path / "src.tar.gz"))
        with tarfile.open(path) as archive:
            names = archive.getnames()
            blob = b"".join(archive.extractfile(m).read()
                            for m in archive.getmembers() if m.isfile())
        assert {"config.yaml", "Dockerfile", "heroku.yml"} <= set(names)
        assert b"HK-SECRET" not in blob and b"HK-ADMIN" not in blob


class TestRefusal:
    @responses.activate
    def test_refuses_without_a_backup(self, provider, spec, bundle, project):
        spec.extra["backup_kinds"] = []
        with pytest.raises(ProviderError, match="wiped on every restart"):
            provider.create(spec, bundle, None, DeploymentStore(project))
        assert not responses.calls, "it must refuse before calling the API"

    @responses.activate
    def test_demo_is_allowed(self, provider, spec, bundle, project):
        spec.extra["backup_kinds"] = []
        spec.demo = True
        stub_happy_path()
        assert provider.create(spec, bundle, None,
                               DeploymentStore(project)).status == "running"

    def test_refusal_is_known_before_create(self, provider, spec, bundle):
        """`deploy up --dry-run` asks refusal(); it must say what create() will."""
        spec.extra["backup_kinds"] = []
        assert "wiped" in provider.refusal(spec, bundle)

    def test_demo_is_accepted_on_heroku(self, provider, spec, bundle):
        spec.extra["backup_kinds"] = []
        spec.demo = True
        assert provider.refusal(spec, bundle) is None


class TestCreate:
    @responses.activate
    def test_happy_path(self, provider, spec, bundle, project):
        stub_happy_path()
        record = provider.create(spec, bundle, None, DeploymentStore(project))
        assert record.status == "running"
        assert record.url == "https://potato-pilot-abc.herokuapp.com"
        app = next(c for c in responses.calls if c.request.url == f"{API_ROOT}/apps")
        assert json.loads(app.request.body)["stack"] == "container"

    @responses.activate
    def test_secrets_travel_as_config_vars(self, provider, spec, bundle, project):
        stub_happy_path()
        provider.create(spec, bundle, None, DeploymentStore(project))
        config = next(c for c in responses.calls if "config-vars" in c.request.url)
        sent = json.loads(config.request.body)
        assert sent["POTATO_SECRET_KEY"] == FakeGenerated.secret_key
        assert sent["GUNICORN_WORKERS"] == "1"

    @responses.activate
    def test_one_dyno_of_the_requested_size(self, provider, spec, bundle, project):
        spec.size = "standard-2x"
        stub_happy_path()
        provider.create(spec, bundle, None, DeploymentStore(project))
        scale = next(c for c in responses.calls if "formation/web" in c.request.url)
        assert json.loads(scale.request.body) == {"quantity": 1, "size": "standard-2x"}

    @responses.activate
    def test_app_is_recorded_before_a_failed_build(self, provider, spec, bundle,
                                                   project):
        responses.add(responses.GET, f"{API_ROOT}/account", json={})
        responses.add(responses.POST, f"{API_ROOT}/apps",
                      json={"name": "potato-pilot", "web_url": "https://p.herokuapp.com/"})
        responses.add(responses.PATCH, f"{API_ROOT}/apps/potato-pilot/config-vars",
                      status=500, json={"message": "boom"})
        store = DeploymentStore(project)
        with pytest.raises(ProviderError):
            provider.create(spec, bundle, None, store)
        record = store.get("pilot")
        assert record.provider_ref["app"] == "potato-pilot"
        assert record.status == "failed"

    @responses.activate
    def test_a_taken_name_gets_a_suffix(self, provider, spec, bundle, project):
        responses.add(responses.GET, f"{API_ROOT}/account", json={})
        responses.add(responses.POST, f"{API_ROOT}/apps", status=422,
                      json={"message": "Name potato-pilot is already taken"})
        responses.add(responses.POST, f"{API_ROOT}/apps",
                      json={"name": "potato-pilot-1a2b",
                            "web_url": "https://potato-pilot-1a2b.herokuapp.com/"})
        responses.add(responses.PATCH, f"{API_ROOT}/apps/potato-pilot-1a2b/config-vars",
                      json={})
        responses.add(responses.POST, f"{API_ROOT}/sources",
                      json={"source_blob": {"put_url": "https://s3.test/put",
                                            "get_url": "https://s3.test/get"}})
        responses.add(responses.PUT, "https://s3.test/put")
        responses.add(responses.POST, f"{API_ROOT}/apps/potato-pilot-1a2b/builds",
                      json={"id": "b"})
        responses.add(responses.GET, f"{API_ROOT}/apps/potato-pilot-1a2b/builds/b",
                      json={"status": "succeeded"})
        responses.add(responses.PATCH,
                      f"{API_ROOT}/apps/potato-pilot-1a2b/formation/web", json={})
        record = provider.create(spec, bundle, None, DeploymentStore(project))
        assert record.provider_ref["app"] == "potato-pilot-1a2b"

    @responses.activate
    def test_a_failed_build_points_at_the_registry_fallback(self, provider, spec,
                                                            bundle, project):
        stub_happy_path()
        responses.replace(responses.GET, f"{API_ROOT}/apps/potato-pilot/builds/b1",
                          json={"status": "failed"})
        with pytest.raises(ProviderError, match="--heroku-registry"):
            provider.create(spec, bundle, None, DeploymentStore(project))

    @responses.activate
    def test_a_second_up_rebuilds_the_same_app(self, provider, spec, bundle, project):
        stub_happy_path()
        responses.add(responses.GET, f"{API_ROOT}/apps/potato-pilot",
                      json={"name": "potato-pilot"})
        existing = DeploymentRecord(name="pilot", provider="heroku",
                                    url="https://potato-pilot-abc.herokuapp.com",
                                    provider_ref={"app": "potato-pilot"})
        provider.create(spec, bundle, existing, DeploymentStore(project))
        assert not any(c.request.method == "POST" and c.request.url == f"{API_ROOT}/apps"
                       for c in responses.calls)


class TestPlan:
    def test_basic_is_the_default_and_priced(self, provider, spec, bundle):
        assert provider.plan(spec, bundle).estimated_cost_usd_month == DYNO_PRICES["basic"]

    def test_no_secret_value_is_printed(self, provider, spec, bundle):
        rendered = provider.plan(spec, bundle).render()
        assert "HK-SECRET" not in rendered and "HK-ADMIN" not in rendered

    def test_plan_needs_no_network(self, provider, spec, bundle, monkeypatch):
        import requests

        def refuse(*a, **k):
            raise AssertionError("plan() made a request")
        monkeypatch.setattr(requests.Session, "request", refuse)
        assert provider.plan(spec, bundle).actions


class TestDestroyAndStatus:
    @responses.activate
    def test_destroy_deletes_the_app_and_keeps_the_backup(self, provider):
        responses.add(responses.DELETE, f"{API_ROOT}/apps/potato-pilot", json={})
        messages = []
        provider.console = messages.append
        provider.destroy(DeploymentRecord(name="pilot", provider="heroku",
                                          provider_ref={"app": "potato-pilot"}))
        assert any("not touched" in m for m in messages)

    @responses.activate
    def test_a_deleted_app_reads_as_absent(self, provider):
        responses.add(responses.GET, f"{API_ROOT}/apps/potato-pilot", status=404,
                      json={"message": "not found"})
        status = provider.status(DeploymentRecord(
            name="pilot", provider="heroku", provider_ref={"app": "potato-pilot"}))
        assert status.state == "absent"
