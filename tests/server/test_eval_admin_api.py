"""
Server integration tests for the Phase 2.5 eval-admin inspect/control API
(/admin/eval/...) and the trace/annotation curation imports.
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager


@pytest.fixture(scope="class", autouse=True)
def flask_server(request):
    annotation_schemes = [{
        "annotation_type": "radio", "name": "label",
        "description": "label", "labels": ["yes", "no"],
    }]
    extra = {"datasets": {"enabled": True, "storage": "file"}}
    with TestConfigManager(
        "eval_admin_api", annotation_schemes,
        additional_config=extra, admin_api_key="test-admin-api-key",
    ) as test_config:
        server = FlaskTestServer(port=9062, config_file=test_config.config_path)
        if not server.start():
            pytest.fail("Failed to start server")
        request.cls.server = server
        yield server
        server.stop()


class TestEvalAdminAPI:
    def _session(self):
        s = requests.Session()
        base = self.server.base_url
        s.post(f"{base}/register", data={"email": "admin@test.com", "pass": "pw"})
        s.post(f"{base}/auth", data={"email": "admin@test.com", "pass": "pw"})
        s.headers.update({"X-API-Key": self.server.admin_api_key})
        return s, base

    def test_status(self):
        s, base = self._session()
        r = s.get(f"{base}/admin/eval/status")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["assignment_paused"] is False
        assert data["instances"]["total"] >= 1
        assert "datasets" in data and "experiments" in data

    def test_progress(self):
        s, base = self._session()
        r = s.get(f"{base}/admin/eval/progress")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data["instances"], list)
        if data["instances"]:
            row = data["instances"][0]
            assert "num_annotators" in row and "source" in row

    def test_ingested_traces_empty(self):
        s, base = self._session()
        r = s.get(f"{base}/admin/eval/ingested_traces")
        assert r.status_code == 200
        # no trace_ingestion configured -> none
        assert r.json()["total"] == 0

    def test_assignment_pause_resume(self):
        s, base = self._session()
        r = s.post(f"{base}/admin/eval/assignment", json={"action": "pause"})
        assert r.status_code == 200 and r.json()["assignment_paused"] is True
        # reflected in status
        assert s.get(f"{base}/admin/eval/status").json()["assignment_paused"] is True
        r = s.post(f"{base}/admin/eval/assignment", json={"action": "resume"})
        assert r.status_code == 200 and r.json()["assignment_paused"] is False

    def test_assignment_bad_action(self):
        s, base = self._session()
        r = s.post(f"{base}/admin/eval/assignment", json={"action": "nope"})
        assert r.status_code == 400

    def test_import_instances_with_annotations(self):
        s, base = self._session()
        s.post(f"{base}/datasets/api/datasets", json={"name": "curated_ann"})
        r = s.post(f"{base}/datasets/api/datasets/curated_ann/import_instances",
                   json={"include_annotations": True})
        assert r.status_code == 201, r.text
        assert r.json()["example_count"] >= 1

    def test_import_traces_none_available(self):
        s, base = self._session()
        s.post(f"{base}/datasets/api/datasets", json={"name": "from_traces"})
        # no ingested traces -> 400 with a clear message
        r = s.post(f"{base}/datasets/api/datasets/from_traces/import_traces", json={})
        assert r.status_code == 400
        assert "ingested" in r.json()["error"].lower()

    def test_analytics_json(self):
        s, base = self._session()
        r = s.get(f"{base}/admin/eval/analytics")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "analytics" in body and "alerts" in body
        # no ingested traces -> zero count, no alerts
        assert body["analytics"]["count"] == 0
        assert body["alerts"] == []

    def test_analytics_html(self):
        s, base = self._session()
        r = s.get(f"{base}/admin/eval/analytics?format=html")
        assert r.status_code == 200
        assert "Trace analytics" in r.text

    def test_analytics_requires_admin(self):
        r = requests.get(f"{self.server.base_url}/admin/eval/analytics")
        assert r.status_code in (401, 403)

    def test_requires_admin(self):
        # No X-API-Key header -> 403
        base = self.server.base_url
        r = requests.get(f"{base}/admin/eval/status")
        assert r.status_code in (401, 403)
