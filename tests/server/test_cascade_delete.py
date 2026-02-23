"""
Integration tests for cascade deletion: span → link/event cleanup.

When a span is deleted, any links or events referencing that span
must be automatically removed to prevent orphaned references.
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_config,
    create_test_data_file,
    cleanup_test_directory,
)


class TestSpanDeleteCascade:
    """Verify that deleting a span cascades to links and events."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("cascade_delete_test")
        test_data = [
            {"id": "cascade_1", "text": "John attacked the building with a rifle."},
            {"id": "cascade_2", "text": "Microsoft hired Sarah as CTO."},
        ]
        data_file = create_test_data_file(test_dir, test_data)
        config_file = create_test_config(
            test_dir,
            annotation_schemes=[
                {
                    "annotation_type": "span",
                    "name": "entities",
                    "description": "Mark entities",
                    "labels": [
                        {"name": "PERSON"},
                        {"name": "ORG"},
                        {"name": "EVENT_TRIGGER"},
                    ],
                },
                {
                    "annotation_type": "span_link",
                    "name": "relations",
                    "description": "Link spans",
                    "span_schema": "entities",
                    "link_types": [
                        {"name": "WORKS_FOR", "directed": True},
                    ],
                },
                {
                    "annotation_type": "event_annotation",
                    "name": "events",
                    "description": "Annotate events",
                    "span_schema": "entities",
                    "event_types": [
                        {
                            "type": "ATTACK",
                            "arguments": [
                                {"role": "attacker", "required": True},
                                {"role": "target", "required": True},
                            ],
                        }
                    ],
                },
            ],
            data_files=[data_file],
        )
        server = FlaskTestServer(config=config_file)
        if not server.start():
            pytest.fail("Failed to start server")
        request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(test_dir)))
        yield server

    def _auth_session(self, flask_server, username):
        session = requests.Session()
        session.post(
            f"{flask_server.base_url}/register",
            data={"action": "signup", "email": username, "pass": "pass"},
            timeout=5,
        )
        session.post(
            f"{flask_server.base_url}/auth",
            data={"action": "login", "email": username, "pass": "pass"},
            timeout=5,
        )
        # Initialise annotation state
        session.get(f"{flask_server.base_url}/annotate", timeout=5)
        return session

    # ------------------------------------------------------------------
    # Helpers to manipulate spans / links / events via the API
    # ------------------------------------------------------------------

    def _create_span(self, session, base_url, instance_id, schema, name, start, end):
        """Create a span and return its id from the server."""
        data = {
            "instance_id": instance_id,
            "span_annotations": [
                {
                    "schema": schema,
                    "name": name,
                    "start": start,
                    "end": end,
                    "value": name,
                }
            ],
        }
        resp = session.post(f"{base_url}/updateinstance", json=data, timeout=5)
        assert resp.status_code == 200

        # Retrieve the span id that was created
        resp = session.get(f"{base_url}/api/spans/{instance_id}", timeout=5)
        assert resp.status_code == 200
        spans = resp.json().get("spans", [])
        for s in spans:
            if s.get("start") == start and s.get("end") == end and s.get("label") == name:
                return s.get("id")
        return None

    def _delete_span(self, session, base_url, instance_id, schema, name, start, end):
        """Delete a span by sending value=None via the backend format.

        The cascade cleanup code lives in the backend format path
        (schema/state/type) which handles value=None as a deletion.
        """
        data = {
            "instance_id": instance_id,
            "schema": schema,
            "type": "span",
            "state": [
                {
                    "name": name,
                    "start": start,
                    "end": end,
                    "value": None,
                }
            ],
        }
        resp = session.post(f"{base_url}/updateinstance", json=data, timeout=5)
        assert resp.status_code == 200

    def _create_link(self, session, base_url, instance_id, schema, link_type, span_ids, link_id):
        data = {
            "instance_id": instance_id,
            "link_annotations": [
                {
                    "schema": schema,
                    "link_type": link_type,
                    "span_ids": span_ids,
                    "direction": "directed",
                    "id": link_id,
                }
            ],
        }
        resp = session.post(f"{base_url}/updateinstance", json=data, timeout=5)
        assert resp.status_code == 200

    def _create_event(self, session, base_url, instance_id, schema, event_type,
                      trigger_span_id, arguments, event_id):
        data = {
            "instance_id": instance_id,
            "event_annotations": [
                {
                    "schema": schema,
                    "event_type": event_type,
                    "trigger_span_id": trigger_span_id,
                    "arguments": arguments,
                    "id": event_id,
                }
            ],
        }
        resp = session.post(f"{base_url}/updateinstance", json=data, timeout=5)
        assert resp.status_code == 200

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_delete_span_cascades_to_link(self, flask_server):
        """Deleting a span referenced by a link removes the link."""
        session = self._auth_session(flask_server, "cascade_link_user")
        base = flask_server.base_url
        iid = "cascade_1"

        # Create two spans
        sid1 = self._create_span(session, base, iid, "entities", "PERSON", 0, 4)
        sid2 = self._create_span(session, base, iid, "entities", "ORG", 18, 26)
        assert sid1 is not None
        assert sid2 is not None

        # Create a link between them
        self._create_link(session, base, iid, "relations", "WORKS_FOR", [sid1, sid2], "link_cas_1")

        # Verify link exists
        resp = session.get(f"{base}/api/links/{iid}", timeout=5)
        assert resp.status_code == 200
        links_before = resp.json().get("links", [])
        link_ids_before = [l["id"] for l in links_before]
        assert "link_cas_1" in link_ids_before

        # Delete the first span
        self._delete_span(session, base, iid, "entities", "PERSON", 0, 4)

        # Link should now be gone
        resp = session.get(f"{base}/api/links/{iid}", timeout=5)
        assert resp.status_code == 200
        links_after = resp.json().get("links", [])
        link_ids_after = [l["id"] for l in links_after]
        assert "link_cas_1" not in link_ids_after

    def test_delete_span_cascades_to_event_trigger(self, flask_server):
        """Deleting the trigger span of an event removes the event."""
        session = self._auth_session(flask_server, "cascade_evt_trig_user")
        base = flask_server.base_url
        iid = "cascade_1"

        # Create trigger span and argument span
        trigger_sid = self._create_span(session, base, iid, "entities", "EVENT_TRIGGER", 5, 13)
        arg_sid = self._create_span(session, base, iid, "entities", "PERSON", 0, 4)
        assert trigger_sid is not None
        assert arg_sid is not None

        # Create event referencing both spans
        self._create_event(
            session, base, iid, "events", "ATTACK",
            trigger_span_id=trigger_sid,
            arguments=[{"role": "attacker", "span_id": arg_sid}],
            event_id="event_cas_trig",
        )

        # Verify event exists
        resp = session.get(f"{base}/api/events/{iid}", timeout=5)
        assert resp.status_code == 200
        event_ids = [e["id"] for e in resp.json().get("events", [])]
        assert "event_cas_trig" in event_ids

        # Delete the trigger span
        self._delete_span(session, base, iid, "entities", "EVENT_TRIGGER", 5, 13)

        # Event should be removed
        resp = session.get(f"{base}/api/events/{iid}", timeout=5)
        assert resp.status_code == 200
        event_ids = [e["id"] for e in resp.json().get("events", [])]
        assert "event_cas_trig" not in event_ids

    def test_delete_span_cascades_to_event_argument(self, flask_server):
        """Deleting an argument span of an event removes the event."""
        session = self._auth_session(flask_server, "cascade_evt_arg_user")
        base = flask_server.base_url
        iid = "cascade_2"

        trigger_sid = self._create_span(session, base, iid, "entities", "EVENT_TRIGGER", 10, 15)
        attacker_sid = self._create_span(session, base, iid, "entities", "PERSON", 0, 9)
        target_sid = self._create_span(session, base, iid, "entities", "ORG", 16, 25)
        assert all(s is not None for s in [trigger_sid, attacker_sid, target_sid])

        self._create_event(
            session, base, iid, "events", "ATTACK",
            trigger_span_id=trigger_sid,
            arguments=[
                {"role": "attacker", "span_id": attacker_sid},
                {"role": "target", "span_id": target_sid},
            ],
            event_id="event_cas_arg",
        )

        # Verify event exists
        resp = session.get(f"{base}/api/events/{iid}", timeout=5)
        event_ids = [e["id"] for e in resp.json().get("events", [])]
        assert "event_cas_arg" in event_ids

        # Delete the argument span (attacker)
        self._delete_span(session, base, iid, "entities", "PERSON", 0, 9)

        # Event should be removed
        resp = session.get(f"{base}/api/events/{iid}", timeout=5)
        event_ids = [e["id"] for e in resp.json().get("events", [])]
        assert "event_cas_arg" not in event_ids

    def test_delete_unrelated_span_preserves_link(self, flask_server):
        """Deleting a span NOT referenced by a link leaves the link intact."""
        session = self._auth_session(flask_server, "cascade_unrelated_user")
        base = flask_server.base_url
        iid = "cascade_1"

        sid1 = self._create_span(session, base, iid, "entities", "PERSON", 0, 4)
        sid2 = self._create_span(session, base, iid, "entities", "ORG", 18, 26)
        unrelated_sid = self._create_span(session, base, iid, "entities", "EVENT_TRIGGER", 30, 35)
        assert all(s is not None for s in [sid1, sid2, unrelated_sid])

        self._create_link(session, base, iid, "relations", "WORKS_FOR", [sid1, sid2], "link_safe")

        # Delete the unrelated span
        self._delete_span(session, base, iid, "entities", "EVENT_TRIGGER", 30, 35)

        # Link should still be there
        resp = session.get(f"{base}/api/links/{iid}", timeout=5)
        link_ids = [l["id"] for l in resp.json().get("links", [])]
        assert "link_safe" in link_ids

    def test_delete_span_cascades_both_link_and_event(self, flask_server):
        """One span deletion can remove both a link and an event simultaneously."""
        session = self._auth_session(flask_server, "cascade_both_user")
        base = flask_server.base_url
        iid = "cascade_2"

        # Span used in both a link and as an event argument
        shared_sid = self._create_span(session, base, iid, "entities", "PERSON", 0, 5)
        other_sid = self._create_span(session, base, iid, "entities", "ORG", 10, 19)
        trigger_sid = self._create_span(session, base, iid, "entities", "EVENT_TRIGGER", 20, 25)
        assert all(s is not None for s in [shared_sid, other_sid, trigger_sid])

        self._create_link(session, base, iid, "relations", "WORKS_FOR",
                          [shared_sid, other_sid], "link_both")
        self._create_event(session, base, iid, "events", "ATTACK",
                           trigger_span_id=trigger_sid,
                           arguments=[{"role": "attacker", "span_id": shared_sid}],
                           event_id="event_both")

        # Delete the shared span
        self._delete_span(session, base, iid, "entities", "PERSON", 0, 5)

        # Both link and event should be gone
        resp = session.get(f"{base}/api/links/{iid}", timeout=5)
        link_ids = [l["id"] for l in resp.json().get("links", [])]
        assert "link_both" not in link_ids

        resp = session.get(f"{base}/api/events/{iid}", timeout=5)
        event_ids = [e["id"] for e in resp.json().get("events", [])]
        assert "event_both" not in event_ids
