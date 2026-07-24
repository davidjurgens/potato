"""Server integration tests for the cross-document event registry endpoints.

Verifies the blueprint is actually registered under the live ``create_app`` server
(the route-registration gotcha), and that auth (401) and CSRF (403) guards fire.
Only ``event_template`` is enabled here (no ``corpus_map``) so the test is fast and
needs no ML stack; the ingest pipeline is covered by unit tests.
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager


EVENT_TEMPLATE = {
    "enabled": True,
    "name": "disaster_event",
    "allow_annotator_create": True,
    "slots": [
        {"name": "event_type", "description": "kind", "type": "text"},
        {"name": "where", "description": "location", "type": "text"},
    ],
}

SCHEMES = [
    {
        "annotation_type": "multi_document_event",
        "name": "events",
        "description": "Cross-document events",
        "slots": EVENT_TEMPLATE["slots"],
        "allow_annotator_create": True,
    }
]


class TestEventRegistryRoutes:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self):
        with TestConfigManager(
            "mde_routes",
            SCHEMES,
            num_instances=3,
            additional_config={"event_template": EVENT_TEMPLATE},
        ) as test_config:
            server = FlaskTestServer(port=9061, config_file=test_config.config_path)
            if not server.start():
                pytest.fail("Failed to start server")
            yield server
            server.stop()

    def _session(self, server):
        s = requests.Session()
        s.post(f"{server.base_url}/register", data={"email": "u", "pass": "p", "action": "register"})
        s.post(f"{server.base_url}/auth", data={"email": "u", "pass": "p"})
        return s

    def test_blueprint_is_registered(self, flask_server):
        # Authenticated GET must not 404 (route-registration gotcha).
        s = self._session(flask_server)
        r = s.get(f"{flask_server.base_url}/corpus/api/event_template")
        assert r.status_code == 200
        body = r.json()
        assert body["template_name"] == "disaster_event"
        assert [s["name"] for s in body["slots"]] == ["event_type", "where"]

    def test_requires_auth(self, flask_server):
        r = requests.get(f"{flask_server.base_url}/corpus/api/events?doc_id=1")
        assert r.status_code == 401

    def test_create_fill_and_persist(self, flask_server):
        s = self._session(flask_server)
        base = flask_server.base_url

        # create
        r = s.post(f"{base}/corpus/api/event", json={"title": "Flood", "doc_id": "1"},
                   headers={"Origin": base})
        assert r.status_code == 201
        eid = r.json()["id"]
        assert "1" in r.json()["member_doc_ids"]

        # fill slot
        r = s.post(f"{base}/corpus/api/event/{eid}/slot",
                   json={"slot": "event_type", "value": "flood"}, headers={"Origin": base})
        assert r.status_code == 200
        assert r.json()["slot_values"]["event_type"] == "flood"

        # evidence (implies membership of another doc)
        r = s.post(f"{base}/corpus/api/event/{eid}/evidence",
                   json={"slot": "where", "doc_id": "2", "start": 0, "end": 4, "text": "Test"},
                   headers={"Origin": base})
        assert r.status_code == 200
        assert set(r.json()["member_doc_ids"]) == {"1", "2"}

        # list by doc
        r = s.get(f"{base}/corpus/api/events?doc_id=2")
        assert r.status_code == 200
        assert any(e["id"] == eid for e in r.json()["events"])

    def test_csrf_cross_origin_rejected(self, flask_server):
        s = self._session(flask_server)
        r = s.post(f"{flask_server.base_url}/corpus/api/event",
                   json={"title": "x"}, headers={"Origin": "http://evil.example"})
        assert r.status_code == 403

    def test_optimistic_locking_conflict(self, flask_server):
        s = self._session(flask_server)
        base = flask_server.base_url
        eid = s.post(f"{base}/corpus/api/event", json={"doc_id": "1"},
                     headers={"Origin": base}).json()["id"]
        # Read a stale stamp, write once to advance it, then write again stale -> 409.
        ev = s.get(f"{base}/corpus/api/event/{eid}").json()
        stale = ev["updated_at"]
        s.post(f"{base}/corpus/api/event/{eid}/slot",
               json={"slot": "event_type", "value": "a", "expected_updated_at": stale},
               headers={"Origin": base})
        r = s.post(f"{base}/corpus/api/event/{eid}/slot",
                   json={"slot": "event_type", "value": "b", "expected_updated_at": stale},
                   headers={"Origin": base})
        assert r.status_code == 409
        assert r.json()["error"] == "stale_write"
