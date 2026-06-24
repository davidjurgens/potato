"""
Server integration tests for the Datasets / Experiments API.

Boots a real Flask server with `datasets.enabled` and exercises the JSON API
end to end (create -> add examples -> tag -> run experiment -> compare).
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager


@pytest.fixture(scope="class", autouse=True)
def flask_server(request):
    annotation_schemes = [{
        "annotation_type": "radio",
        "name": "ok",
        "description": "ok?",
        "labels": ["yes", "no"],
    }]
    extra = {"datasets": {"enabled": True, "storage": "file"}}
    with TestConfigManager(
        "datasets_api", annotation_schemes,
        additional_config=extra, admin_api_key="test-admin-api-key",
    ) as test_config:
        server = FlaskTestServer(port=9061, config_file=test_config.config_path)
        if not server.start():
            pytest.fail("Failed to start server")
        request.cls.server = server
        yield server
        server.stop()


class TestDatasetsAPI:
    def _session(self):
        s = requests.Session()
        base = self.server.base_url
        s.post(f"{base}/register", data={"email": "admin@test.com", "pass": "pw"})
        s.post(f"{base}/auth", data={"email": "admin@test.com", "pass": "pw"})
        # Admin key is read from config; the test server exposes it via session.
        s.headers.update({"X-API-Key": self.server.admin_api_key})
        return s, base

    def test_full_lifecycle(self):
        s, base = self._session()

        # create
        r = s.post(f"{base}/datasets/api/datasets",
                   json={"name": "ds1", "description": "test"})
        assert r.status_code == 201, r.text
        assert r.json()["name"] == "ds1"

        # add examples
        r = s.post(f"{base}/datasets/api/datasets/ds1/examples", json={"examples": [
            {"id": "a", "inputs": {"q": "1+1"}, "reference_outputs": {"output": "2"},
             "metadata": {"outputs": "2"}},
            {"id": "b", "inputs": {"q": "2+2"}, "reference_outputs": {"output": "4"},
             "metadata": {"outputs": "5"}},
        ]})
        assert r.status_code == 201, r.text
        assert r.json()["version_id"] == "v0001"
        assert r.json()["example_count"] == 2

        # tag the version
        r = s.post(f"{base}/datasets/api/datasets/ds1/tag",
                   json={"version_id": "v0001", "tag": "prod"})
        assert r.status_code == 200 and r.json()["tagged"] is True

        # run an experiment (exact_match against metadata outputs)
        r = s.post(f"{base}/datasets/api/experiments/run", json={
            "dataset": "ds1",
            "evaluators": [{"name": "exact_match"}],
        })
        assert r.status_code == 201, r.text
        exp = r.json()
        # a correct (2==2), b wrong (5!=4) -> mean 0.5
        assert exp["aggregate_scores"]["exact_match"] == pytest.approx(0.5)

        # list experiments
        r = s.get(f"{base}/datasets/api/experiments")
        assert r.status_code == 200 and len(r.json()) == 1

    def test_run_unknown_evaluator_400(self):
        s, base = self._session()
        s.post(f"{base}/datasets/api/datasets", json={"name": "ds2"})
        s.post(f"{base}/datasets/api/datasets/ds2/examples",
               json={"examples": [{"id": "a", "inputs": {}}]})
        r = s.post(f"{base}/datasets/api/experiments/run",
                   json={"dataset": "ds2", "evaluators": [{"name": "nope"}]})
        assert r.status_code == 400

    def test_admin_page_renders(self):
        s, base = self._session()
        r = s.get(f"{base}/datasets/admin")
        assert r.status_code == 200
        assert "Datasets" in r.text

    def test_export_sft(self):
        s, base = self._session()
        s.post(f"{base}/datasets/api/datasets", json={"name": "exp_ds"})
        s.post(f"{base}/datasets/api/datasets/exp_ds/examples", json={"examples": [
            {"id": "a", "inputs": {"q": "1+1"}, "reference_outputs": {"output": "2"}},
        ]})
        r = s.get(f"{base}/datasets/api/datasets/exp_ds/export?format=sft")
        assert r.status_code == 200
        assert r.headers["Content-Type"].startswith("application/x-ndjson")
        line = r.text.strip()
        assert '"completion": "2"' in line

    def test_export_unknown_format_400(self):
        s, base = self._session()
        s.post(f"{base}/datasets/api/datasets", json={"name": "exp_ds2"})
        s.post(f"{base}/datasets/api/datasets/exp_ds2/examples",
               json={"examples": [{"id": "a", "inputs": {}, "reference_outputs": {"output": "x"}}]})
        r = s.get(f"{base}/datasets/api/datasets/exp_ds2/export?format=bogus")
        assert r.status_code == 400

    def test_import_from_instances(self):
        s, base = self._session()
        s.post(f"{base}/datasets/api/datasets", json={"name": "curated"})
        # The test task loads 2 instances by default -> imported as examples.
        r = s.post(f"{base}/datasets/api/datasets/curated/import_instances", json={})
        assert r.status_code == 201, r.text
        assert r.json()["example_count"] >= 1

    def test_import_with_dawid_skene_method(self):
        s, base = self._session()
        s.post(f"{base}/datasets/api/datasets", json={"name": "curated_ds"})
        r = s.post(f"{base}/datasets/api/datasets/curated_ds/import_instances",
                   json={"include_annotations": True, "aggregation_method": "dawid_skene"})
        assert r.status_code == 201, r.text

    def test_import_rejects_unknown_aggregation_method(self):
        s, base = self._session()
        s.post(f"{base}/datasets/api/datasets", json={"name": "curated_bad"})
        r = s.post(f"{base}/datasets/api/datasets/curated_bad/import_instances",
                   json={"aggregation_method": "bogus"})
        assert r.status_code == 400
