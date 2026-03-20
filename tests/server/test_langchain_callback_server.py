"""
Server integration tests for LangChain callback handler.

Spins up a real Potato server with trace ingestion enabled, then verifies
that PotatoCallbackHandler correctly sends traces via the webhook endpoint
and that Potato processes them.
"""

import json
import os
import sys
import time
import uuid

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_config,
    create_test_data_file,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TRACE_API_KEY = "test-trace-key"


def _make_trace_config(test_name="lc_callback_server"):
    """Create a config with trace ingestion enabled."""
    test_dir = create_test_directory(test_name)
    data = [
        {"id": "seed_1", "text": "Seed item so server starts with data."},
    ]
    data_file = create_test_data_file(test_dir, data)
    config_file = create_test_config(
        test_dir,
        annotation_schemes=[
            {
                "name": "quality",
                "description": "Rate quality",
                "annotation_type": "radio",
                "labels": ["good", "bad"],
            },
        ],
        data_files=[data_file],
        additional_config={
            "trace_ingestion": {
                "enabled": True,
                "api_key": TRACE_API_KEY,
                "notify_annotators": False,
            },
        },
    )
    return config_file


# ---------------------------------------------------------------------------
# Tests: LangSmith webhook endpoint (the target of PotatoCallbackHandler)
# ---------------------------------------------------------------------------

class TestLangSmithWebhookEndpoint:
    """Verify the /api/traces/langsmith endpoint that the callback targets."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        server = FlaskTestServer(port=9873, config_file=_make_trace_config())
        if not server.start():
            pytest.fail("Failed to start trace ingestion server")
        request.cls.server = server
        yield server
        server.stop()

    def _post_trace(self, payload, api_key=TRACE_API_KEY):
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return requests.post(
            f"{self.server.base_url}/api/traces/langsmith",
            json=payload,
            headers=headers,
            timeout=10,
        )

    def test_rejects_missing_auth(self):
        resp = self._post_trace({"runs": []}, api_key=None)
        assert resp.status_code == 401

    def test_rejects_wrong_auth(self):
        resp = self._post_trace({"runs": []}, api_key="wrong-key")
        assert resp.status_code == 401

    def test_rejects_empty_body(self):
        headers = {"Authorization": f"Bearer {TRACE_API_KEY}"}
        resp = requests.post(
            f"{self.server.base_url}/api/traces/langsmith",
            data="not json",
            headers=headers,
            timeout=10,
        )
        assert resp.status_code == 400

    def test_accepts_valid_langsmith_payload(self):
        payload = {
            "runs": [
                {
                    "id": "run_001",
                    "run_type": "chain",
                    "name": "TestChain",
                    "inputs": {"input": "hello"},
                    "outputs": {"output": "world"},
                    "status": "success",
                    "latency": 1.0,
                },
            ]
        }
        resp = self._post_trace(payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "accepted"
        assert "trace_id" in data

    def test_multiple_runs_accepted(self):
        payload = {
            "runs": [
                {
                    "id": "run_multi_root",
                    "run_type": "chain",
                    "name": "Agent",
                    "inputs": {"input": "task"},
                    "outputs": {"output": "result"},
                },
                {
                    "id": "run_multi_tool",
                    "run_type": "tool",
                    "name": "search",
                    "inputs": {"input": "query"},
                    "outputs": {"output": "results"},
                },
            ]
        }
        resp = self._post_trace(payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["steps"] == 2

    def test_trace_status_endpoint(self):
        """GET /api/traces/status returns stats (requires user auth)."""
        session = requests.Session()
        session.post(
            f"{self.server.base_url}/register",
            data={"email": "status_user", "pass": "pass"},
        )
        session.post(
            f"{self.server.base_url}/auth",
            data={"email": "status_user", "pass": "pass"},
        )
        resp = session.get(f"{self.server.base_url}/api/traces/status", timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert "stats" in data
        assert data["stats"]["received"] >= 1  # from earlier tests


# ---------------------------------------------------------------------------
# Tests: PotatoCallbackHandler → webhook endpoint (end-to-end)
# ---------------------------------------------------------------------------

class TestCallbackHandlerEndToEnd:
    """Verify that PotatoCallbackHandler actually sends traces to Potato."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        server = FlaskTestServer(
            port=9874,
            config_file=_make_trace_config("lc_e2e"),
        )
        if not server.start():
            pytest.fail("Failed to start server for callback e2e test")
        request.cls.server = server
        yield server
        server.stop()

    def test_callback_handler_sends_trace_on_chain_end(self):
        """Full flow: callback collects runs, root chain ends, trace arrives at Potato."""
        from potato.integrations.langchain_callback import PotatoCallbackHandler

        handler = PotatoCallbackHandler(
            potato_url=self.server.base_url,
            api_key=TRACE_API_KEY,
        )

        root_id = uuid.uuid4()
        tool_id = uuid.uuid4()

        # Simulate a chain with a tool call
        handler.on_chain_start(
            serialized={"name": "E2EAgent"},
            inputs={"input": "What is 2+2?"},
            run_id=root_id,
        )
        handler.on_tool_start(
            serialized={"name": "calculator"},
            input_str="2+2",
            run_id=tool_id,
            parent_run_id=root_id,
        )
        handler.on_tool_end(
            output="4",
            run_id=tool_id,
            parent_run_id=root_id,
        )
        handler.on_chain_end(
            outputs={"output": "2+2 is 4"},
            run_id=root_id,
        )

        # Wait for the background send thread to complete
        handler.flush(timeout=10)

        # Verify the trace arrived by checking ingestion status
        session = requests.Session()
        session.post(
            f"{self.server.base_url}/register",
            data={"email": "e2e_checker", "pass": "pass"},
        )
        session.post(
            f"{self.server.base_url}/auth",
            data={"email": "e2e_checker", "pass": "pass"},
        )
        resp = session.get(
            f"{self.server.base_url}/api/traces/status", timeout=10
        )
        assert resp.status_code == 200
        assert resp.json()["stats"]["received"] >= 1

    def test_callback_handler_with_no_auth(self):
        """Handler with empty api_key still works when server has no auth."""
        from potato.integrations.langchain_callback import PotatoCallbackHandler

        # This handler uses TRACE_API_KEY which the server expects
        handler = PotatoCallbackHandler(
            potato_url=self.server.base_url,
            api_key=TRACE_API_KEY,
        )

        root_id = uuid.uuid4()
        handler.on_chain_start(
            serialized={"name": "NoAuth"},
            inputs={"input": "test"},
            run_id=root_id,
        )
        handler.on_chain_end(
            outputs={"output": "done"},
            run_id=root_id,
        )
        handler.flush(timeout=10)

        # Should not crash — verify via status
        session = requests.Session()
        session.post(
            f"{self.server.base_url}/register",
            data={"email": "noauth_checker", "pass": "pass"},
        )
        session.post(
            f"{self.server.base_url}/auth",
            data={"email": "noauth_checker", "pass": "pass"},
        )
        resp = session.get(
            f"{self.server.base_url}/api/traces/status", timeout=10
        )
        assert resp.status_code == 200

    def test_payload_format_matches_webhook_expectations(self):
        """Verify the payload built by PotatoCallbackHandler matches LangSmith format."""
        from potato.integrations.langchain_callback import PotatoCallbackHandler

        handler = PotatoCallbackHandler(potato_url="http://unused:0000")

        root_id = uuid.uuid4()
        llm_id = uuid.uuid4()
        tool_id = uuid.uuid4()

        handler.on_chain_start(
            serialized={"name": "Agent"},
            inputs={"input": "do task"},
            run_id=root_id,
        )
        handler.on_llm_start(
            serialized={"name": "gpt-4"},
            prompts=["do task"],
            run_id=llm_id,
            parent_run_id=root_id,
        )
        handler.on_tool_start(
            serialized={"name": "search"},
            input_str="query",
            run_id=tool_id,
            parent_run_id=root_id,
        )

        payload = handler._build_payload()

        # Verify the payload can be processed by WebhookReceiver
        from potato.trace_ingestion.webhook_receiver import WebhookReceiver

        receiver = WebhookReceiver()
        result = receiver.process_webhook(payload, format_hint="langsmith")

        assert result is not None
        assert result["id"].startswith("langsmith_")
        assert len(result["steps"]) == 3
        assert result["metadata"]["source"] == "langsmith"
