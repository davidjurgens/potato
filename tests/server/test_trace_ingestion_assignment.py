"""
Regression test for F-037: ingested traces must become annotatable.

The LangChain / trace-ingestion path adds items to the pool at runtime via
/api/traces/*. Previously the per-user annotation quota defaulted to the
instance count frozen at load, so runtime-added items exceeded every user's cap
and were never assigned to any annotator. The fix defaults the quota to
unlimited when a dynamic source (trace ingestion / directory watching) is
enabled. This test drives a real LangChain callback trace through the live
endpoint and asserts a fresh user can be assigned the ingested trace.
"""

import time
import uuid

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager

INGEST_PORT = 9655
STATIC_PORT = 9656


def _send_langchain_trace(base_url):
    """Drive a minimal LangChain callback trace into Potato's ingestion endpoint."""
    from potato.integrations.langchain_callback import PotatoCallbackHandler

    handler = PotatoCallbackHandler(potato_url=base_url)
    root_id = uuid.uuid4()
    tool_id = uuid.uuid4()
    handler.on_chain_start(
        serialized={"name": "SimpleAgent"},
        inputs={"input": "What is the capital of France?"},
        run_id=root_id,
    )
    handler.on_tool_start(
        serialized={"name": "search"}, input_str="capital of France",
        run_id=tool_id, parent_run_id=root_id,
    )
    handler.on_tool_end(
        output="The capital of France is Paris.",
        run_id=tool_id, parent_run_id=root_id,
    )
    handler.on_chain_end(outputs={"output": "Paris"}, run_id=root_id)
    handler.flush()


def _drain_assigned_ids(server, user):
    s = requests.Session()
    s.post(f"{server.base_url}/register",
           data={"email": user, "pass": "x", "action": "signup"})
    s.post(f"{server.base_url}/auth",
           data={"email": user, "pass": "x", "action": "login"})
    s.get(f"{server.base_url}/annotate")
    ids = []
    for _ in range(15):
        j = s.get(f"{server.base_url}/api/current_instance").json()
        iid = j.get("instance_id")
        if not iid or iid in ids:
            break
        ids.append(iid)
        s.post(f"{server.base_url}/updateinstance",
               json={"instance_id": iid, "annotations": {"q:::good": "true"}})
        time.sleep(0.2)
        s.post(f"{server.base_url}/annotate", json={"action": "next_instance"})
    return ids


SCHEMES = [{"annotation_type": "radio", "name": "q",
            "description": "Quality", "labels": ["good", "bad"]}]


class TestIngestedTraceBecomesAnnotatable:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        with TestConfigManager(
            "trace_ingest_assign", SCHEMES, num_instances=2,
            additional_config={"trace_ingestion": {"enabled": True, "api_key": ""}},
        ) as cfg:
            server = FlaskTestServer(port=INGEST_PORT, config_file=cfg.config_path)
            if not server.start():
                pytest.fail("Failed to start server")
            yield server
            server.stop()

    def test_fresh_user_can_annotate_ingested_trace(self, flask_server):
        # Ingest a trace at runtime via the real LangChain callback path.
        _send_langchain_trace(flask_server.base_url)
        time.sleep(1.0)

        ids = _drain_assigned_ids(flask_server, "ingest_user")
        assert any(str(i).startswith("langsmith_") for i in ids), (
            f"ingested trace must be assignable to a fresh user; got {ids}")


class TestStaticDatasetStillCapped:
    """Guard: the dynamic-source default must NOT change static-dataset behavior."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        with TestConfigManager(
            "trace_ingest_static", SCHEMES, num_instances=3,
        ) as cfg:
            server = FlaskTestServer(port=STATIC_PORT, config_file=cfg.config_path)
            if not server.start():
                pytest.fail("Failed to start server")
            yield server
            server.stop()

    def test_static_user_gets_exactly_the_dataset(self, flask_server):
        ids = _drain_assigned_ids(flask_server, "static_user")
        assert len(ids) == 3, f"static user should get all 3 items, got {ids}"
        assert not any(str(i).startswith("langsmith_") for i in ids)
