"""Server integration test for the annotation-integrity (LLM-cheating) route (E2)."""

import time
import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager

ADMIN_KEY = "test-integrity-key"
PORT = 9074
SCHEMES = [{"annotation_type": "radio", "name": "sentiment",
            "description": "Sentiment", "labels": ["positive", "negative"]}]


@pytest.fixture(scope="class", autouse=True)
def server(request):
    with TestConfigManager("integrity_api", SCHEMES, num_instances=3,
                           additional_config={"admin_api_key": ADMIN_KEY}) as cfg:
        srv = FlaskTestServer(port=PORT, config_file=cfg.config_path)
        if not srv.start():
            pytest.fail("server failed to start")
        request.cls.base = srv.base_url
        yield srv
        srv.stop()


class TestAnnotationIntegrity:
    def _annotate_as(self, email, label):
        s = requests.Session()
        s.post(f"{self.base}/register", data={"email": email, "pass": "x", "action": "signup"})
        s.post(f"{self.base}/auth", data={"email": email, "pass": "x", "action": "login"})
        s.get(f"{self.base}/annotate")
        j = s.get(f"{self.base}/api/current_instance").json()
        iid = j.get("instance_id")
        s.post(f"{self.base}/updateinstance",
               json={"instance_id": iid, "annotations": {f"sentiment:{label}": label}})
        return iid

    def test_requires_api_key(self):
        r = requests.get(f"{self.base}/admin/annotation-integrity")
        assert r.status_code == 403

    def test_report_structure(self):
        self._annotate_as("alice@test.com", "positive")
        self._annotate_as("bob@test.com", "positive")
        time.sleep(0.3)
        r = requests.get(f"{self.base}/admin/annotation-integrity",
                         headers={"X-API-Key": ADMIN_KEY})
        assert r.status_code == 200, r.text
        data = r.json()
        assert "reports" in data and "n_annotators" in data
        for rep in data["reports"]:
            assert "annotator" in rep and "suspicion" in rep and "flags" in rep
            assert 0.0 <= rep["suspicion"] <= 1.0

    def test_html_renders(self):
        r = requests.get(f"{self.base}/admin/annotation-integrity?format=html",
                         headers={"X-API-Key": ADMIN_KEY})
        assert r.status_code == 200
        assert "Annotation integrity" in r.text
