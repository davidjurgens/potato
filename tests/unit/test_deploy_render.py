"""The Render provider.

Render is the free, no-credit-card target, and the free tier is exactly where
data goes missing: no disk, and the instance stops fifteen minutes after the
last annotator leaves, taking its filesystem with it. The behaviour these tests
hold in place is the refusal — `create` must not produce a free service with no
route for the annotations to leave it.
"""

import pytest
import responses

from potato.deploy.providers.base import DeploySpec, ProviderError, get_provider
from potato.deploy.providers.render import (
    DEFAULT_IMAGE,
    FREE_IDLE_MINUTES,
    RenderAPI,
    _estimate_cost,
    service_payload,
)
from potato.deploy.state import DeploymentRecord, DeploymentStore

API = "https://api.render.com/v1"


class FakeBundle:
    bundle_dir = "/tmp/bundle"
    file_count = 4
    total_bytes = 2048

    def sha256(self):
        return "c" * 64


class FakeGenerated:
    secret_key = "RENDER-SECRET-DO-NOT-PRINT"
    admin_api_key = "RENDER-ADMIN-DO-NOT-PRINT"


@pytest.fixture
def project(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("task_dir: .\n")
    return str(config)


@pytest.fixture
def spec(project):
    return DeploySpec(name="pilot", config_path=project,
                      extra={"config_rel": "config.yaml",
                             "generated": FakeGenerated()})


@pytest.fixture
def provider():
    return get_provider("render", token="rnd_test")


class TestServicePayload:
    def test_deploys_a_prebuilt_image_not_a_repo(self, spec):
        """No git repository is involved, which is the whole appeal."""
        payload = service_payload(spec, owner_id="own", env={})
        assert payload["image"]["imagePath"] == DEFAULT_IMAGE
        assert payload["serviceDetails"]["env"] == "image"
        assert "repo" not in payload

    def test_pins_a_single_instance(self, spec):
        """Potato's item pool and user state are per process.

        A second instance hands out work the first already assigned, and the
        later save silently discards the earlier one.
        """
        payload = service_payload(spec, owner_id="own", env={})
        assert payload["serviceDetails"]["numInstances"] == 1

    def test_environment_is_sorted_key_value_pairs(self, spec):
        payload = service_payload(spec, owner_id="own",
                                  env={"B": "2", "A": "1"})
        assert payload["envVars"] == [{"key": "A", "value": "1"},
                                      {"key": "B", "value": "2"}]

    def test_a_disk_is_mounted_when_asked_for(self, spec):
        spec.volume_gb = 5
        disk = service_payload(spec, owner_id="own", env={})["serviceDetails"]["disk"]
        assert disk["sizeGB"] == 5 and disk["mountPath"] == "/data"

    def test_no_disk_key_without_one(self, spec):
        assert "disk" not in service_payload(
            spec, owner_id="own", env={})["serviceDetails"]


class TestPlan:
    def test_warns_that_a_free_instance_loses_its_filesystem(self, provider, spec):
        warnings = provider.plan(spec, FakeBundle()).warnings
        assert any(str(FREE_IDLE_MINUTES) in w for w in warnings)

    def test_warns_when_nothing_carries_the_data_off(self, provider, spec):
        assert any("carry the data off" in w
                   for w in provider.plan(spec, FakeBundle()).warnings)

    def test_backup_silences_the_durability_warning(self, provider, spec):
        spec.extra["huggingface_backup"] = True
        assert not any("carry the data off" in w
                       for w in provider.plan(spec, FakeBundle()).warnings)

    def test_demo_silences_it_too(self, provider, spec):
        spec.demo = True
        assert not any("carry the data off" in w
                       for w in provider.plan(spec, FakeBundle()).warnings)

    def test_warns_that_free_instances_take_no_disk(self, provider, spec):
        spec.volume_gb = 5
        assert any("free instances" in w
                   for w in provider.plan(spec, FakeBundle()).warnings)

    def test_free_is_reported_as_free(self, provider, spec):
        assert provider.plan(spec, FakeBundle()).estimated_cost_usd_month == 0.0

    def test_a_paid_plan_with_a_disk_is_priced(self, provider, spec):
        spec.extra["plan"] = "starter"
        spec.volume_gb = 4
        assert provider.plan(spec, FakeBundle()).estimated_cost_usd_month == 8.0

    def test_no_secret_value_is_printed(self, provider, spec):
        plan = provider.plan(spec, FakeBundle())
        blob = plan.render() + repr([a.request for a in plan.actions])
        assert FakeGenerated.secret_key not in blob
        assert FakeGenerated.admin_api_key not in blob

    def test_plan_makes_no_network_call(self, provider, spec, monkeypatch):
        import requests

        def explode(*args, **kwargs):
            raise AssertionError("plan() performed I/O")

        monkeypatch.setattr(requests.Session, "request", explode)
        provider.plan(spec, FakeBundle())


class TestFreeTierRefusal:
    """The most important behaviour in this provider."""

    @responses.activate
    def test_refuses_a_free_service_with_no_backup(self, provider, spec, project):
        with pytest.raises(ProviderError, match="no way to keep the annotations"):
            provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        assert not responses.calls, "it must refuse before calling the API"

    @responses.activate
    def test_the_refusal_names_all_three_ways_out(self, provider, spec, project):
        with pytest.raises(ProviderError) as excinfo:
            provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        message = str(excinfo.value)
        assert "--hf-token" in message
        assert "--plan starter" in message
        assert "--demo" in message

    @responses.activate
    def test_a_backup_is_enough_to_proceed(self, provider, spec, project):
        spec.extra["huggingface_backup"] = True
        _stub_successful_create()
        record = provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        assert record.status == "running"

    @responses.activate
    def test_demo_is_enough_to_proceed(self, provider, spec, project):
        spec.demo = True
        _stub_successful_create()
        assert provider.create(spec, FakeBundle(), None,
                               DeploymentStore(project)).status == "running"

    @responses.activate
    def test_a_paid_plan_does_not_need_either(self, provider, spec, project):
        spec.extra["plan"] = "starter"
        _stub_successful_create()
        assert provider.create(spec, FakeBundle(), None,
                               DeploymentStore(project)).status == "running"


class TestCreate:
    @responses.activate
    def test_service_id_is_persisted_before_the_wait(self, provider, spec, project):
        """A service that exists but was never recorded cannot be destroyed."""
        spec.demo = True
        responses.add(responses.GET, f"{API}/owners",
                      json=[{"owner": {"id": "own-1"}}])
        responses.add(responses.POST, f"{API}/services",
                      json={"service": {"id": "srv-1",
                                        "serviceDetails": {"url": "https://x.onrender.com"}}})
        # The deploy never goes live.
        responses.add(responses.GET, f"{API}/services/srv-1/deploys?limit=1",
                      json=[{"deploy": {"status": "build_failed"}}])

        store = DeploymentStore(project)
        with pytest.raises(ProviderError, match="never became live"):
            provider.create(spec, FakeBundle(), None, store)
        assert store.get("pilot").provider_ref["service_id"] == "srv-1"

    @responses.activate
    def test_a_key_with_no_owner_fails_clearly(self, provider, spec, project):
        spec.demo = True
        responses.add(responses.GET, f"{API}/owners", json=[])
        with pytest.raises(ProviderError, match="attached to no owner"):
            provider.create(spec, FakeBundle(), None, DeploymentStore(project))

    @responses.activate
    def test_a_second_up_redeploys_rather_than_duplicating(self, provider, spec,
                                                           project):
        spec.demo = True
        responses.add(responses.GET, f"{API}/owners",
                      json=[{"owner": {"id": "own-1"}}])
        responses.add(responses.POST, f"{API}/services/srv-1/deploys", json={})
        responses.add(responses.GET, f"{API}/services/srv-1/deploys?limit=1",
                      json=[{"deploy": {"status": "live"}}])

        existing = DeploymentRecord(name="pilot", provider="render",
                                    provider_ref={"service_id": "srv-1"})
        provider.create(spec, FakeBundle(), existing, DeploymentStore(project))
        assert not any(c.request.url.endswith("/services")
                       for c in responses.calls), "it created a second service"


class TestTransport:
    @responses.activate
    def test_401_points_at_the_key_page(self):
        responses.add(responses.GET, f"{API}/owners", status=401, json={})
        with pytest.raises(ProviderError, match="api-keys"):
            RenderAPI("bad").verify_token()

    @responses.activate
    def test_error_message_is_unwrapped(self):
        responses.add(responses.POST, f"{API}/services", status=400,
                      json={"message": "name is already taken"})
        with pytest.raises(ProviderError, match="already taken"):
            RenderAPI("k").create_service({})

    @responses.activate
    def test_rate_limit_is_retried(self, monkeypatch):
        monkeypatch.setattr("potato.deploy.providers.render.time.sleep",
                            lambda _s: None)
        responses.add(responses.GET, f"{API}/owners", status=429,
                      headers={"Retry-After": "1"})
        responses.add(responses.GET, f"{API}/owners", json=[{"owner": {"id": "o"}}])
        assert RenderAPI("k").verify_token()[0]["id"] == "o"


class TestUnsupportedVerbs:
    def test_logs_point_at_the_dashboard(self, provider):
        record = DeploymentRecord(name="pilot", provider="render",
                                  provider_ref={"service_id": "srv-1"})
        with pytest.raises(ProviderError, match="dashboard.render.com"):
            list(provider.logs(record))

    def test_pull_without_an_admin_key_says_why(self, provider, tmp_path):
        """Render pulls over HTTPS, which needs the admin key and nothing else.

        Without it there is genuinely no route to the data — no shell to fall
        back to — so the message has to name where the key normally lives.
        """
        record = DeploymentRecord(name="pilot", provider="render",
                                  url="https://x.onrender.com")
        with pytest.raises(ProviderError, match="secrets.json"):
            provider.pull(record, str(tmp_path))

    def test_pull_uses_the_https_archive(self, provider, tmp_path, monkeypatch):
        from potato.deploy.state import SecretStore

        config = tmp_path / "config.yaml"
        config.write_text("task_dir: .\n")
        SecretStore(str(config)).put("pilot", "admin_api_key", "adm_key")

        called = {}

        def fake_pull(url, admin_key, dest, console=None):
            called.update(url=url, admin_key=admin_key)
            from potato.deploy.providers.base import PullResult
            return PullResult(dest=dest, files=3)

        monkeypatch.setattr("potato.deploy.pull.pull_over_https", fake_pull)
        record = DeploymentRecord(name="pilot", provider="render",
                                  url="https://x.onrender.com",
                                  spec={"config_path": str(config)})
        assert provider.pull(record, str(tmp_path / "out")).files == 3
        assert called["url"] == "https://x.onrender.com"
        assert called["admin_key"] == "adm_key"


class TestStatus:
    @responses.activate
    def test_a_deleted_service_reads_as_absent(self, provider):
        responses.add(responses.GET, f"{API}/services/srv-1", status=404, json={})
        record = DeploymentRecord(name="pilot", provider="render",
                                  provider_ref={"service_id": "srv-1"})
        assert provider.status(record).state == "absent"

    @responses.activate
    def test_a_cold_free_instance_is_explained(self, provider):
        """Otherwise "not answering" reads as broken when it is merely asleep."""
        import requests
        responses.add(responses.GET, f"{API}/services/srv-1",
                      json={"id": "srv-1"})
        responses.add(responses.GET, f"{API}/services/srv-1/deploys?limit=1",
                      json=[{"deploy": {"status": "live"}}])
        responses.add(responses.GET, "https://x.onrender.com/health",
                      body=requests.exceptions.ConnectionError("timed out"))
        record = DeploymentRecord(name="pilot", provider="render",
                                  provider_ref={"service_id": "srv-1"},
                                  url="https://x.onrender.com",
                                  spec={"plan": "free"})
        assert "spins down when idle" in provider.status(record).detail

    @responses.activate
    def test_suspension_is_reported_distinctly(self, provider):
        responses.add(responses.GET, f"{API}/services/srv-1",
                      json={"id": "srv-1", "suspended": "suspended"})
        record = DeploymentRecord(name="pilot", provider="render",
                                  provider_ref={"service_id": "srv-1"},
                                  url="https://x.onrender.com")
        assert provider.status(record).state == "suspended"


class TestCost:
    def test_unknown_plan_does_not_invent_a_price(self):
        assert _estimate_cost("enterprise-mystery", None) == 0.0


def _stub_successful_create():
    responses.add(responses.GET, f"{API}/owners", json=[{"owner": {"id": "own-1"}}])
    responses.add(responses.POST, f"{API}/services",
                  json={"service": {"id": "srv-1",
                                    "serviceDetails": {"url": "https://x.onrender.com"}}})
    responses.add(responses.GET, f"{API}/services/srv-1/deploys?limit=1",
                  json=[{"deploy": {"status": "live"}}])
