"""
Integration regression tests for outgoing webhooks on the annotation save path.

These lock in four bugs found during QA that the isolated emitter/sender/signing
unit tests did NOT catch, because all four live in the /updateinstance route:

  F-030: webhooks enabled + quality control DISABLED -> every save raised
         UnboundLocalError ('all_annotations') -> HTTP 500.
  F-031: item.fully_annotated required-count read annotation_task_name (a string)
         and always fell back to 3, ignoring num_annotators_per_item.
  F-032: re-saving an existing annotation always emitted annotation.created;
         annotation.updated never fired.
  F-033: task.completed had a payload builder but zero emit sites -> never fired.

A real local HTTP receiver captures deliveries so we assert on actual events.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager

RECEIVER_PORT = 9651
SERVER_PORT = 9650


class _Receiver:
    """Tiny threaded HTTP server that records received webhook payloads."""

    def __init__(self, port):
        self.events = []
        self._lock = threading.Lock()
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(n)
                try:
                    payload = json.loads(body)
                except Exception:
                    payload = {"_raw": body.decode("utf-8", "replace")}
                with parent._lock:
                    parent.events.append({
                        "event": payload.get("event"),
                        "data": payload.get("data"),
                        "has_sig": bool(self.headers.get("webhook-signature")),
                    })
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *a):
                pass

        self._httpd = HTTPServer(("127.0.0.1", port), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._httpd.shutdown()
        self._httpd.server_close()

    def events_of(self, name):
        with self._lock:
            return [e for e in self.events if e["event"] == name]

    def wait_for(self, name, timeout=6.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.events_of(name):
                return True
            time.sleep(0.1)
        return False


class TestWebhookSavePathIntegration:
    @pytest.fixture(scope="class", autouse=True)
    def receiver(self):
        rec = _Receiver(RECEIVER_PORT)
        rec.start()
        yield rec
        rec.stop()

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        schemes = [{
            "annotation_type": "radio",
            "name": "sentiment",
            "description": "Sentiment",
            "labels": ["positive", "negative"],
        }]
        webhook_cfg = {
            "webhooks": {
                "enabled": True,
                "endpoints": [{
                    "name": "test_receiver",
                    "url": f"http://127.0.0.1:{RECEIVER_PORT}/hook",
                    "secret": "s3cret",
                    "events": ["*"],
                    "active": True,
                    "timeout_seconds": 5,
                }],
            },
            # IMPORTANT: no quality_control block -> exercises the F-030 path.
        }
        with TestConfigManager(
            "webhook_integration", schemes, num_instances=3,
            additional_config=webhook_cfg,
        ) as cfg:
            server = FlaskTestServer(port=SERVER_PORT, config_file=cfg.config_path)
            if not server.start():
                pytest.fail("Failed to start server")

            # FlaskTestServer runs in-process and does NOT initialize the webhook
            # emitter (only run_server/create_app do). Initialize it here against
            # the now-loaded global config so the /updateinstance webhook code path
            # is actually exercised. Reset the singleton first to avoid inheriting
            # a stale emitter (and its endpoints) from a previous test.
            import potato.webhooks as wh
            if wh._EMITTER is not None:
                try:
                    wh._EMITTER.stop()
                except Exception:
                    pass
                wh._EMITTER = None
            from potato.server_utils.config_module import config as global_config
            wh.init_webhook_emitter(global_config)

            yield server

            if wh._EMITTER is not None:
                try:
                    wh._EMITTER.stop()
                except Exception:
                    pass
                wh._EMITTER = None
            server.stop()

    def _login(self, server, name):
        s = requests.Session()
        s.post(f"{server.base_url}/register",
               data={"email": name, "pass": "x", "action": "signup"})
        s.post(f"{server.base_url}/auth",
               data={"email": name, "pass": "x", "action": "login"})
        s.get(f"{server.base_url}/annotate")
        return s

    def _current_id(self, s, server):
        return s.get(f"{server.base_url}/api/current_instance").json().get("instance_id")

    def test_save_without_quality_control_returns_200(self, flask_server, receiver):
        """F-030: a save with webhooks on but QC off must NOT 500."""
        s = self._login(flask_server, "wh_a")
        iid = self._current_id(s, flask_server)
        assert iid is not None
        r = s.post(f"{flask_server.base_url}/updateinstance",
                   json={"instance_id": iid,
                         "annotations": {"sentiment:::positive": "true"}})
        assert r.status_code == 200, r.text
        assert r.json().get("status") != "error", r.text
        assert receiver.wait_for("annotation.created")
        created = receiver.events_of("annotation.created")
        assert any(e["has_sig"] for e in created), "webhook must be HMAC-signed"

    def test_resave_emits_annotation_updated(self, flask_server, receiver):
        """F-032: re-saving an annotated instance emits annotation.updated."""
        s = self._login(flask_server, "wh_b")
        iid = self._current_id(s, flask_server)
        s.post(f"{flask_server.base_url}/updateinstance",
               json={"instance_id": iid,
                     "annotations": {"sentiment:::positive": "true"}})
        time.sleep(0.5)
        s.post(f"{flask_server.base_url}/updateinstance",
               json={"instance_id": iid,
                     "annotations": {"sentiment:::negative": "true"}})
        assert receiver.wait_for("annotation.updated")
        updated = receiver.events_of("annotation.updated")
        assert any(e["data"].get("user_id") == "wh_b" for e in updated)

    def test_task_completed_fires_once_on_last_item(self, flask_server, receiver):
        """F-033: task.completed fires when the user's last assigned item is saved."""
        s = self._login(flask_server, "wh_c")
        seen = set()
        for _ in range(8):
            iid = self._current_id(s, flask_server)
            if not iid or iid in seen:
                break
            seen.add(iid)
            s.post(f"{flask_server.base_url}/updateinstance",
                   json={"instance_id": iid,
                         "annotations": {"sentiment:::positive": "true"}})
            time.sleep(0.3)
            s.post(f"{flask_server.base_url}/annotate",
                   json={"action": "next_instance"})
        assert receiver.wait_for("task.completed")
        tc = [e for e in receiver.events_of("task.completed")
              if e["data"].get("user_id") == "wh_c"]
        assert len(tc) == 1, f"task.completed should fire exactly once, got {len(tc)}"
