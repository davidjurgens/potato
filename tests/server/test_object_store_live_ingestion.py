"""
Live ingestion from an object store, end to end: a server reading a GCS
prefix (the real google-cloud-storage SDK against a local fake of the JSON
API) picks up an object uploaded while it runs, without a restart.
"""

import json
import os
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import requests

pytest.importorskip("google.cloud.storage")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.test_utils import TestConfigManager  # noqa: E402

ADMIN_KEY = "object-store-live"
SCHEMES = [{"annotation_type": "radio", "name": "q", "description": "Q", "labels": ["good", "bad"]}]
STORE = {"in/first.jsonl": ("2026-10-19T10:00:00.000Z",
                            b'{"id": "f1", "text": "one"}\n{"id": "f2", "text": "two"}\n')}


class Fake(BaseHTTPRequestHandler):
    def _meta(self, name):
        updated, content = STORE[name]
        return {"kind": "storage#object", "name": name, "bucket": "data", "size": str(len(content)),
                "updated": updated, "contentType": "application/x-ndjson",
                "generation": "1", "metageneration": "1"}

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(url.query)
        if url.path == "/storage/v1/b/data/o":
            prefix = query.get("prefix", [""])[0]
            body = json.dumps({"items": [self._meta(n) for n in sorted(STORE) if n.startswith(prefix)]}).encode()
            ctype = "application/json"
        else:
            name = urllib.parse.unquote(url.path.rsplit("/o/", 1)[1])
            body, ctype = ((STORE[name][1], "application/octet-stream") if "alt" in query
                           else (json.dumps(self._meta(name)).encode(), "application/json"))
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    fake = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    previous = os.environ.get("STORAGE_EMULATOR_HOST")
    os.environ["STORAGE_EMULATOR_HOST"] = f"http://127.0.0.1:{fake.server_port}"
    config = {"admin_api_key": ADMIN_KEY, "data_sources": [{
        "id": "gcs_in", "type": "gcs", "bucket": "data", "prefix": "in/", "anonymous": True,
        "live_ingestion": {"enabled": True, "poll_interval_seconds": 0.5}}]}
    try:
        with TestConfigManager("object_store_live", SCHEMES, num_instances=1,
                               additional_config=config) as cfg:
            srv = FlaskTestServer(config_file=cfg.config_path)
            if not srv.start():
                pytest.fail("Failed to start server")
            yield srv
            srv.stop()
    finally:
        fake.shutdown()
        if previous is None:
            os.environ.pop("STORAGE_EMULATOR_HOST", None)
        else:
            os.environ["STORAGE_EMULATOR_HOST"] = previous


def _item_ids(server):
    r = requests.get(f"{server.base_url}/admin/api/instances", headers={"X-API-Key": ADMIN_KEY},
                     params={"page_size": 100})
    r.raise_for_status()
    return {i["id"] for i in r.json().get("instances", [])}


def test_an_object_uploaded_while_running_becomes_items(server):
    assert {"f1", "f2"} <= _item_ids(server)
    STORE["in/second.jsonl"] = ("2026-10-19T10:05:00.000Z", b'{"id": "s1", "text": "three"}\n')
    deadline = time.time() + 15
    while time.time() < deadline and "s1" not in _item_ids(server):
        time.sleep(0.5)
    assert "s1" in _item_ids(server)
