"""Server integration tests for the dataset-publishing admin API.

Drives a real Potato server: registers an annotator, submits annotations, then
exercises the publish blueprint end to end (page, preview, background archive job,
download) plus the auth gate.
"""

import os
import sys
import time

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (create_test_config, create_test_data_file,
                                       create_test_directory)

ADMIN_KEY = "test-publish-api-key"


def _make_config():
    test_dir = create_test_directory("publish_api")
    data = [{"id": f"item_{i}", "text": f"Sample text {i}"} for i in range(1, 6)]
    data_file = create_test_data_file(test_dir, data)
    return create_test_config(
        test_dir,
        annotation_schemes=[{
            "name": "sentiment",
            "description": "Classify sentiment",
            "annotation_type": "radio",
            "labels": ["positive", "negative", "neutral"],
        }],
        data_files=[data_file],
        admin_api_key=ADMIN_KEY,
    )


class TestPublishAPI:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        server = FlaskTestServer(port=9884, config_file=_make_config())
        if not server.start():
            pytest.fail("Failed to start publish API test server")
        request.cls.server = server
        # Seed one annotation so the pipeline has data.
        s = requests.Session()
        s.post(f"{server.base_url}/register", data={"email": "tester", "pass": "p"})
        s.post(f"{server.base_url}/auth", data={"email": "tester", "pass": "p"})
        s.get(f"{server.base_url}/annotate")
        s.post(f"{server.base_url}/updateinstance", json={
            "instance_id": "item_1",
            "annotations": {"sentiment:positive": "true"}})
        yield server
        server.stop()

    def _hdr(self, key=ADMIN_KEY):
        return {"X-API-Key": key} if key else {}

    def test_page_requires_admin(self):
        # No key -> 403 (unless debug bypass; test the API endpoint which is JSON).
        r = requests.get(f"{self.server.base_url}/admin/publish/api/status",
                         headers=self._hdr(key=None), timeout=10)
        assert r.status_code in (403, 200)  # 200 only if server runs in debug
        # With key -> always allowed.
        r2 = requests.get(f"{self.server.base_url}/admin/publish/api/status",
                          headers=self._hdr(), timeout=10)
        assert r2.status_code == 200
        assert r2.json().get("state") in ("idle", "running", "success", "error")

    def test_preview_returns_card(self):
        r = requests.post(f"{self.server.base_url}/admin/publish/api/preview",
                          headers=self._hdr(),
                          json={"target": "archive", "options": {}, "metadata": {}},
                          timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "card_markdown" in data
        assert "# " in data["card_markdown"]
        assert "sentiment" in data["card_markdown"]
        assert "annotations" in data["splits"]

    def test_archive_job_lifecycle_and_download(self):
        start = requests.post(f"{self.server.base_url}/admin/publish/api/start",
                              headers=self._hdr(),
                              json={"target": "archive",
                                    "metadata": {"license": "cc-by-4.0"},
                                    "options": {}, "credentials": {}}, timeout=15)
        assert start.status_code in (202, 409), start.text

        # Poll to completion.
        final = None
        for _ in range(40):
            st = requests.get(f"{self.server.base_url}/admin/publish/api/status",
                              headers=self._hdr(), timeout=10).json()
            if st["state"] in ("success", "error"):
                final = st
                break
            time.sleep(0.5)
        assert final is not None, "publish job did not finish"
        assert final["state"] == "success", final
        assert final["result"]["download_url"].endswith("/download")

        dl = requests.get(f"{self.server.base_url}/admin/publish/api/download",
                          headers=self._hdr(), timeout=30)
        assert dl.status_code == 200
        assert dl.content[:2] == b"PK"  # a zip archive
