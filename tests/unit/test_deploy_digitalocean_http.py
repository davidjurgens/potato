"""DigitalOcean API behaviour, against a mocked HTTP layer.

`responses` intercepts at the transport, so these exercise the real client
including retry, error unwrapping and pagination. No token, no network.

The case that matters most is the mid-create failure: a droplet exists, then
something later throws. The record must already name the droplet, because a
billable machine whose id was never written down is the characteristic way tools
in this category cost people money.
"""

import json

import pytest
import responses

from potato.deploy.do_api import DigitalOceanAPI
from potato.deploy.providers.base import DeploySpec, ProviderError, get_provider
from potato.deploy.state import DeploymentRecord, DeploymentStore, SecretStore

API = "https://api.digitalocean.com/v2"


@pytest.fixture
def api():
    return DigitalOceanAPI("dop_v1_test")


class FakeBundle:
    bundle_dir = "/tmp/bundle"
    file_count = 3
    total_bytes = 100

    def sha256(self):
        return "b" * 64


@pytest.fixture
def project(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("task_dir: .\n")
    return str(config)


@pytest.fixture
def spec(project):
    return DeploySpec(name="pilot", config_path=project,
                      extra={"config_rel": "config.yaml"})


class TestTransport:
    @responses.activate
    def test_token_travels_as_a_bearer_header(self, api):
        responses.add(responses.GET, f"{API}/account", json={"account": {}})
        api.verify_token()
        assert responses.calls[0].request.headers["Authorization"] == "Bearer dop_v1_test"

    @responses.activate
    def test_401_names_the_scope_problem(self, api):
        """"401 Client Error" tells someone nothing about what to do."""
        responses.add(responses.GET, f"{API}/account", status=401,
                      json={"message": "Unable to authenticate you"})
        with pytest.raises(ProviderError, match="write scope"):
            api.verify_token()

    @responses.activate
    def test_error_body_is_unwrapped_into_the_message(self, api):
        responses.add(responses.POST, f"{API}/droplets", status=422,
                      json={"id": "unprocessable_entity",
                            "message": "You specified an invalid region"})
        with pytest.raises(ProviderError, match="invalid region"):
            api.create_droplet({})

    @responses.activate
    def test_rate_limit_honours_retry_after(self, api, monkeypatch):
        """The server's own number beats guessing with exponential backoff."""
        slept = []
        monkeypatch.setattr("potato.deploy.do_api.time.sleep", slept.append)
        responses.add(responses.GET, f"{API}/account", status=429,
                      headers={"Retry-After": "7"})
        responses.add(responses.GET, f"{API}/account", json={"account": {"uuid": "x"}})
        assert api.verify_token()["uuid"] == "x"
        assert slept == [7]

    @responses.activate
    def test_retry_after_is_capped(self, api, monkeypatch):
        """A server that says 'wait an hour' must not hang the command."""
        slept = []
        monkeypatch.setattr("potato.deploy.do_api.time.sleep", slept.append)
        responses.add(responses.GET, f"{API}/account", status=429,
                      headers={"Retry-After": "3600"})
        responses.add(responses.GET, f"{API}/account", json={"account": {}})
        api.verify_token()
        assert slept == [120]

    @responses.activate
    def test_gives_up_rather_than_retrying_forever(self, api, monkeypatch):
        monkeypatch.setattr("potato.deploy.do_api.time.sleep", lambda _s: None)
        for _ in range(20):
            responses.add(responses.GET, f"{API}/account", status=429)
        with pytest.raises(ProviderError, match="429"):
            api.verify_token()

    @responses.activate
    def test_network_failure_says_so(self, api):
        import requests
        responses.add(responses.GET, f"{API}/account",
                      body=requests.exceptions.ConnectionError("no route to host"))
        with pytest.raises(ProviderError, match="Could not reach"):
            api.verify_token()

    @responses.activate
    def test_pagination_is_followed(self, api):
        responses.add(responses.GET, f"{API}/account/keys",
                      json={"ssh_keys": [{"id": 1}],
                            "links": {"pages": {"next": f"{API}/account/keys?page=2"}}})
        responses.add(responses.GET, f"{API}/account/keys?page=2",
                      json={"ssh_keys": [{"id": 2}], "links": {}})
        assert [k["id"] for k in api.list_ssh_keys()] == [1, 2]


class TestIdempotence:
    @responses.activate
    def test_duplicate_ssh_key_is_reused(self, api):
        """Re-running `up` after a partial failure hits this every time."""
        public = "ssh-ed25519 AAAAC3Nz key"
        responses.add(responses.POST, f"{API}/account/keys", status=422,
                      json={"message": "SSH Key is already in use on your account"})
        responses.add(responses.GET, f"{API}/account/keys",
                      json={"ssh_keys": [{"id": 99, "public_key": public}], "links": {}})
        assert api.create_ssh_key("potato-pilot", public)["id"] == 99

    @responses.activate
    def test_deleting_a_missing_droplet_is_success(self, api):
        """Destroy must be able to finish a partly-destroyed deployment."""
        responses.add(responses.DELETE, f"{API}/droplets/123", status=404,
                      json={"message": "not found"})
        api.delete_droplet(123)

    @responses.activate
    def test_a_real_delete_error_still_raises(self, api):
        responses.add(responses.DELETE, f"{API}/droplets/123", status=500,
                      json={"message": "internal"})
        with pytest.raises(ProviderError):
            api.delete_droplet(123)

    @responses.activate
    def test_missing_droplet_reads_as_none(self, api):
        responses.add(responses.GET, f"{API}/droplets/7", status=404,
                      json={"message": "not found"})
        assert api.get_droplet(7) is None


class TestMidCreateFailure:
    """A droplet that exists but whose id was never recorded bills forever.

    create() refuses without paramiko, so these need the `deploy` extra.
    """

    @pytest.fixture(autouse=True)
    def _needs_paramiko(self):
        pytest.importorskip("paramiko",
                            reason="pip install 'potato-annotation[deploy]'")

    @responses.activate
    def test_droplet_id_is_persisted_before_the_firewall_call(self, spec, project,
                                                              monkeypatch):
        responses.add(responses.GET, f"{API}/account",
                      json={"account": {"status": "active"}})
        responses.add(responses.POST, f"{API}/account/keys",
                      json={"ssh_key": {"id": 5}})
        responses.add(responses.POST, f"{API}/droplets",
                      json={"droplet": {"id": 4242}})
        # The step right after the droplet exists fails.
        responses.add(responses.POST, f"{API}/firewalls", status=500,
                      json={"message": "boom"})

        monkeypatch.setattr(
            "potato.deploy.providers.digitalocean.generate_keypair",
            lambda comment="": ("PRIVATE", "ssh-ed25519 AAAA key"))

        store = DeploymentStore(project)
        provider = get_provider("digitalocean", token="dop_v1_test",
                                console=lambda *a: None)
        with pytest.raises(ProviderError):
            provider.create(spec, FakeBundle(), None, store)

        record = store.get("pilot")
        assert record is not None
        assert record.provider_ref["droplet_id"] == 4242, (
            "the droplet id must be written down before any later call can fail")
        assert record.status == "failed"

    @responses.activate
    def test_the_deploy_key_survives_the_failure(self, spec, project, monkeypatch):
        """Without it the machine that is now billing cannot be reached."""
        responses.add(responses.GET, f"{API}/account", json={"account": {}})
        responses.add(responses.POST, f"{API}/account/keys",
                      json={"ssh_key": {"id": 5}})
        responses.add(responses.POST, f"{API}/droplets", status=500,
                      json={"message": "no capacity"})
        monkeypatch.setattr(
            "potato.deploy.providers.digitalocean.generate_keypair",
            lambda comment="": ("PRIVATE-PEM", "ssh-ed25519 AAAA key"))

        provider = get_provider("digitalocean", token="t", console=lambda *a: None)
        with pytest.raises(ProviderError):
            provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        assert SecretStore(project).get("pilot", "ssh_private_key") == "PRIVATE-PEM"

    @responses.activate
    def test_a_suspended_account_fails_before_creating_anything(self, spec, project):
        responses.add(responses.GET, f"{API}/account",
                      json={"account": {"status": "locked",
                                        "status_message": "billing"}})
        provider = get_provider("digitalocean", token="t", console=lambda *a: None)
        with pytest.raises(ProviderError, match="locked"):
            provider.create(spec, FakeBundle(), None, DeploymentStore(project))
        # Nothing beyond the account check was attempted.
        assert len(responses.calls) == 1


class TestDestroy:
    @responses.activate
    def test_removes_every_resource(self, project):
        for path in ("/droplets/1", "/firewalls/fw", "/account/keys/5",
                     "/volumes/vol"):
            responses.add(responses.DELETE, f"{API}{path}", status=204)
        responses.add(responses.GET, f"{API}/droplets?tag_name=potato-pilot",
                      json={"droplets": [], "links": {}})

        record = DeploymentRecord(
            name="pilot", provider="digitalocean",
            provider_ref={"droplet_id": 1, "firewall_id": "fw", "ssh_key_id": 5,
                          "volume_id": "vol", "tag": "potato-pilot"})
        get_provider("digitalocean", token="t",
                     console=lambda *a: None).destroy(record)

        deleted = {c.request.url for c in responses.calls
                   if c.request.method == "DELETE"}
        assert any("/droplets/1" in u for u in deleted)
        assert any("/firewalls/fw" in u for u in deleted)
        assert any("/account/keys/5" in u for u in deleted)
        assert any("/volumes/vol" in u for u in deleted)

    @responses.activate
    def test_keep_data_spares_the_volume(self, project):
        responses.add(responses.DELETE, f"{API}/droplets/1", status=204)
        responses.add(responses.DELETE, f"{API}/firewalls/fw", status=204)
        responses.add(responses.DELETE, f"{API}/account/keys/5", status=204)
        responses.add(responses.GET, f"{API}/droplets?tag_name=potato-pilot",
                      json={"droplets": [], "links": {}})

        record = DeploymentRecord(
            name="pilot", provider="digitalocean",
            provider_ref={"droplet_id": 1, "firewall_id": "fw", "ssh_key_id": 5,
                          "volume_id": "vol", "tag": "potato-pilot"})
        get_provider("digitalocean", token="t",
                     console=lambda *a: None).destroy(record, keep_data=True)
        assert not any("/volumes/" in c.request.url for c in responses.calls)

    @responses.activate
    def test_tagged_orphans_are_found_and_removed(self, project):
        """The recovery path when a crash created a droplet nothing recorded."""
        responses.add(responses.DELETE, f"{API}/droplets/1", status=204)
        responses.add(responses.GET, f"{API}/droplets?tag_name=potato-pilot",
                      json={"droplets": [{"id": 777, "name": "potato-pilot"}],
                            "links": {}})
        responses.add(responses.DELETE, f"{API}/droplets/777", status=204)

        messages = []
        record = DeploymentRecord(
            name="pilot", provider="digitalocean",
            provider_ref={"droplet_id": 1, "tag": "potato-pilot"})
        get_provider("digitalocean", token="t",
                     console=messages.append).destroy(record)

        assert any("777" in m for m in messages)
        assert any("/droplets/777" in c.request.url for c in responses.calls
                   if c.request.method == "DELETE")


class TestStatus:
    @responses.activate
    def test_absent_droplet_is_reported_as_absent(self):
        responses.add(responses.GET, f"{API}/droplets/9", status=404,
                      json={"message": "not found"})
        record = DeploymentRecord(name="pilot", provider="digitalocean",
                                  provider_ref={"droplet_id": 9},
                                  url="https://203.0.113.9")
        status = get_provider("digitalocean", token="t").status(record)
        assert status.state == "absent"
        assert not status.healthy

    @responses.activate
    def test_a_provisioning_droplet_is_not_called_running(self):
        responses.add(responses.GET, f"{API}/droplets/9",
                      json={"droplet": {"id": 9, "status": "new"}})
        record = DeploymentRecord(name="pilot", provider="digitalocean",
                                  provider_ref={"droplet_id": 9},
                                  url="https://203.0.113.9")
        assert get_provider("digitalocean", token="t").status(record).state == "new"

    @responses.activate
    def test_healthy_when_the_app_answers(self):
        responses.add(responses.GET, f"{API}/droplets/9",
                      json={"droplet": {"id": 9, "status": "active"}})
        responses.add(responses.GET, "https://203.0.113.9/health",
                      json={"status": "ok"})
        record = DeploymentRecord(name="pilot", provider="digitalocean",
                                  provider_ref={"droplet_id": 9},
                                  url="https://203.0.113.9")
        status = get_provider("digitalocean", token="t").status(record)
        assert status.state == "running" and status.healthy

    @responses.activate
    def test_still_loading_is_distinguished_from_broken(self):
        responses.add(responses.GET, f"{API}/droplets/9",
                      json={"droplet": {"id": 9, "status": "active"}})
        responses.add(responses.GET, "https://203.0.113.9/health", status=503)
        record = DeploymentRecord(name="pilot", provider="digitalocean",
                                  provider_ref={"droplet_id": 9},
                                  url="https://203.0.113.9")
        status = get_provider("digitalocean", token="t").status(record)
        assert not status.healthy
        assert "still loading" in status.detail

    @responses.activate
    def test_tls_failure_points_at_certificate_renewal(self):
        """An IP certificate lives ~6 days, so this is the first symptom."""
        import requests
        responses.add(responses.GET, f"{API}/droplets/9",
                      json={"droplet": {"id": 9, "status": "active"}})
        responses.add(responses.GET, "https://203.0.113.9/health",
                      body=requests.exceptions.SSLError("certificate has expired"))
        record = DeploymentRecord(name="pilot", provider="digitalocean",
                                  provider_ref={"droplet_id": 9},
                                  url="https://203.0.113.9")
        status = get_provider("digitalocean", token="t").status(record)
        assert "renewal" in status.detail


class TestSSHKeyRequirement:
    def test_pull_without_a_deploy_key_explains_the_alternative(self, project):
        record = DeploymentRecord(
            name="pilot", provider="digitalocean",
            provider_ref={"droplet_id": 1, "ipv4": "203.0.113.9"},
            spec={"config_path": project})
        provider = get_provider("digitalocean", token="t")
        with pytest.raises(ProviderError, match="admin export API"):
            provider.pull(record, "/tmp/nowhere")

    def test_a_record_with_no_address_says_so(self, project):
        record = DeploymentRecord(name="pilot", provider="digitalocean",
                                  provider_ref={"droplet_id": 1},
                                  spec={"config_path": project})
        with pytest.raises(ProviderError, match="No host address"):
            get_provider("digitalocean", token="t").pull(record, "/tmp/nowhere")
