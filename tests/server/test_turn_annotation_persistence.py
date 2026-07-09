"""
Server round-trip tests for the turn-level annotation framework.

The turn-level pipeline persists all per-turn values for a scheme as one
hidden annotation-data-input ("{schema}:::_data" -> Label(schema, "_data")).
These tests exercise:
  1. the anchor hidden input + turn slots render server-side
  2. POST /updateinstance stores the turn JSON
  3. /get_annotations returns it
  4. the next page render restores value + data-server-set on the anchor
"""

import json
import re

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory, create_test_config, create_test_data_file,
)

PORT = 9721

TRACE = [
    {"speaker": "User", "text": "What is 2+2?"},
    {"speaker": "Assistant", "text": "Let me compute that."},
    {"speaker": "Agent (Action)", "text": "calculator(expression=\"2+2\")"},
    {"speaker": "Assistant", "text": "The answer is 4."},
]


def _turn_config(test_dir):
    data_file = create_test_data_file(test_dir, [
        {"id": "t1", "conversation": TRACE, "task": "evaluate the agent"},
        {"id": "t2", "conversation": TRACE, "task": "evaluate the agent"},
    ])
    return create_test_config(
        test_dir,
        [
            {
                "annotation_type": "multiselect",
                "name": "turn_errors",
                "description": "Errors in this turn",
                "labels": ["hallucination", "contradiction"],
                "turn_level": True,
                "turn_binding": {"field": "conversation", "speakers": ["Assistant"]},
            },
            {
                "annotation_type": "radio",
                "name": "task_success",
                "description": "success",
                "labels": ["yes", "no"],
            },
        ],
        data_files=[data_file],
        additional_config={
            "item_properties": {"id_key": "id", "text_key": "task"},
            "instance_display": {
                "fields": [
                    {"key": "conversation", "type": "dialogue", "label": "Trace"},
                ]
            },
        },
    )


class TestTurnAnnotationServerPersistence:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("turn_anno_persist")
        cfg = _turn_config(test_dir)
        server = FlaskTestServer(port=PORT, config_file=cfg)
        if not server.start():
            pytest.fail("Failed to start server")
        yield server
        server.stop()

    def _session(self, server, name):
        s = requests.Session()
        s.post(f"{server.base_url}/register",
               data={"email": name, "pass": "x", "action": "signup"})
        s.post(f"{server.base_url}/auth",
               data={"email": name, "pass": "x", "action": "login"})
        return s

    def test_anchor_and_slots_render(self, flask_server):
        s = self._session(flask_server, "turn_u1")
        html = s.get(f"{flask_server.base_url}/annotate").text

        # The persistence anchor (hidden data input) must exist.
        m = re.search(r'<input[^>]*turn-anno-hidden[^>]*>', html)
        assert m, "turn-level scheme must render its hidden anchor input"
        assert 'name="turn_errors"' in m.group(0), m.group(0)

        # Turn slots render only on matching (Assistant) turns.
        slots = re.findall(r'class="turn-anno-slot"[^>]*', html)
        assert len(slots) == 2, f"expected 2 Assistant slots, got {len(slots)}"
        assert 'data-speaker="Assistant"' in slots[0]

        # Proxy contract: no real annotation inputs inside slots.
        slot_chunk = html.split('class="turn-anno-slot"', 1)[1].split("</div>")[0]
        assert "annotation-input" not in slot_chunk

    def test_turn_annotation_round_trip(self, flask_server):
        s = self._session(flask_server, "turn_u2")
        s.get(f"{flask_server.base_url}/annotate")
        iid = s.get(f"{flask_server.base_url}/api/current_instance").json()["instance_id"]

        payload = json.dumps({
            "v": 1, "schema_type": "multiselect",
            "turns": {
                "t1": {"values": ["hallucination"], "speaker": "Assistant"},
                "t3": {"values": ["contradiction"], "speaker": "Assistant"},
            },
        })
        r = s.post(f"{flask_server.base_url}/updateinstance",
                   json={"instance_id": iid,
                         "annotations": {"turn_errors:::_data": payload}})
        assert r.status_code == 200, r.text

        # Stored server-side under the schema name as a _data label.
        # (/get_annotations flattens to {schema: [label names]}.)
        ga = s.get(f"{flask_server.base_url}/get_annotations?instance_id={iid}").json()
        labels = ga.get("label_annotations", {})
        assert "turn_errors" in labels, ga
        assert "_data" in labels["turn_errors"], ga

        # Full JSON restored into the anchor on next render (value +
        # data-server-set), which is what turn-annotations.js seeds its
        # visual state from.
        html2 = s.get(f"{flask_server.base_url}/annotate").text
        m2 = re.search(r'<input[^>]*turn-anno-hidden[^>]*>', html2)
        assert m2, "anchor input missing after restore"
        assert "data-server-set" in m2.group(0), m2.group(0)
        assert "hallucination" in m2.group(0)
        assert "t3" in m2.group(0)

    def test_turn_and_trace_level_coexist(self, flask_server):
        s = self._session(flask_server, "turn_u3")
        s.get(f"{flask_server.base_url}/annotate")
        iid = s.get(f"{flask_server.base_url}/api/current_instance").json()["instance_id"]

        payload = json.dumps({"v": 1, "schema_type": "multiselect",
                              "turns": {"t1": {"values": ["contradiction"]}}})
        r = s.post(f"{flask_server.base_url}/updateinstance",
                   json={"instance_id": iid,
                         "annotations": {"turn_errors:::_data": payload,
                                         "task_success:::yes": "yes"}})
        assert r.status_code == 200, r.text

        ga = s.get(f"{flask_server.base_url}/get_annotations?instance_id={iid}").json()
        labels = ga.get("label_annotations", {})
        assert "turn_errors" in labels and "task_success" in labels, ga

    def test_overwrite_clears_previous_turns(self, flask_server):
        """An all-cleared state must overwrite the stored value (the JS
        serializes a non-empty {"turns":{}} doc after modification)."""
        s = self._session(flask_server, "turn_u4")
        s.get(f"{flask_server.base_url}/annotate")
        iid = s.get(f"{flask_server.base_url}/api/current_instance").json()["instance_id"]

        first = json.dumps({"v": 1, "schema_type": "multiselect",
                            "turns": {"t1": {"values": ["hallucination"]}}})
        s.post(f"{flask_server.base_url}/updateinstance",
               json={"instance_id": iid, "annotations": {"turn_errors:::_data": first}})

        cleared = json.dumps({"v": 1, "schema_type": "multiselect", "turns": {}})
        s.post(f"{flask_server.base_url}/updateinstance",
               json={"instance_id": iid, "annotations": {"turn_errors:::_data": cleared}})

        # The cleared doc must overwrite the old value: the restored anchor
        # no longer contains the previous turn annotation.
        html = s.get(f"{flask_server.base_url}/annotate").text
        m = re.search(r'<input[^>]*turn-anno-hidden[^>]*>', html)
        assert m, "anchor input missing after clear"
        assert "hallucination" not in m.group(0), m.group(0)
