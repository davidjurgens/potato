"""
Tests for potato.integrations.langchain_callback — PotatoCallbackHandler
"""

import json
import threading
import uuid
from unittest.mock import MagicMock, patch

import pytest

from potato.integrations.langchain_callback import (
    PotatoCallbackHandler,
    _safe_serialize,
)


# ---------------------------------------------------------------------------
# _safe_serialize
# ---------------------------------------------------------------------------

class TestSafeSerialize:
    def test_primitives(self):
        assert _safe_serialize(42) == 42
        assert _safe_serialize("hi") == "hi"
        assert _safe_serialize(None) is None
        assert _safe_serialize(True) is True

    def test_dict(self):
        assert _safe_serialize({"a": 1}) == {"a": 1}

    def test_list(self):
        assert _safe_serialize([1, "two", None]) == [1, "two", None]

    def test_unserializable_object(self):
        class Weird:
            def __str__(self):
                return "weird_obj"
        result = _safe_serialize(Weird())
        assert result == "weird_obj"

    def test_nested(self):
        data = {"a": [{"b": object()}]}
        result = _safe_serialize(data)
        assert isinstance(result["a"][0]["b"], str)


# ---------------------------------------------------------------------------
# PotatoCallbackHandler — run collection
# ---------------------------------------------------------------------------

class TestRunCollection:
    def setup_method(self):
        self.handler = PotatoCallbackHandler(
            potato_url="http://localhost:9999",
            api_key="test-key",
        )

    def test_chain_start_creates_run(self):
        rid = uuid.uuid4()
        self.handler.on_chain_start(
            serialized={"name": "TestChain"},
            inputs={"input": "hello"},
            run_id=rid,
        )
        assert str(rid) in self.handler._runs
        run = self.handler._runs[str(rid)]
        assert run["run_type"] == "chain"
        assert run["name"] == "TestChain"
        assert run["status"] == "running"

    def test_root_run_tracked(self):
        rid = uuid.uuid4()
        self.handler.on_chain_start(
            serialized={"name": "Root"},
            inputs={},
            run_id=rid,
        )
        assert self.handler._root_run_id == str(rid)

    def test_nested_run_not_root(self):
        root_id = uuid.uuid4()
        child_id = uuid.uuid4()
        self.handler.on_chain_start(
            serialized={"name": "Root"},
            inputs={},
            run_id=root_id,
        )
        self.handler.on_llm_start(
            serialized={"name": "MyLLM"},
            prompts=["Say hi"],
            run_id=child_id,
            parent_run_id=root_id,
        )
        assert self.handler._root_run_id == str(root_id)

    def test_llm_start_and_end(self):
        rid = uuid.uuid4()
        parent = uuid.uuid4()

        # Create root first to avoid triggering send
        self.handler.on_chain_start(
            serialized={"name": "Root"},
            inputs={},
            run_id=parent,
        )

        self.handler.on_llm_start(
            serialized={"name": "gpt-4"},
            prompts=["hello"],
            run_id=rid,
            parent_run_id=parent,
        )

        # Mock LLM response
        mock_response = MagicMock()
        mock_gen = MagicMock()
        mock_gen.text = "Hi there!"
        mock_response.generations = [[mock_gen]]

        self.handler.on_llm_end(response=mock_response, run_id=rid, parent_run_id=parent)

        run = self.handler._runs[str(rid)]
        assert run["status"] == "completed"
        assert "Hi there!" in run["outputs"]["text"]

    def test_tool_start_and_end(self):
        root_id = uuid.uuid4()
        self.handler.on_chain_start(
            serialized={"name": "Root"}, inputs={}, run_id=root_id
        )

        rid = uuid.uuid4()
        self.handler.on_tool_start(
            serialized={"name": "calculator"},
            input_str="2+2",
            run_id=rid,
            parent_run_id=root_id,
        )
        self.handler.on_tool_end(output="4", run_id=rid, parent_run_id=root_id)

        run = self.handler._runs[str(rid)]
        assert run["run_type"] == "tool"
        assert run["outputs"] == {"output": "4"}

    def test_error_sets_status(self):
        root_id = uuid.uuid4()
        self.handler.on_chain_start(
            serialized={"name": "Root"}, inputs={}, run_id=root_id
        )

        rid = uuid.uuid4()
        self.handler.on_tool_start(
            serialized={"name": "bad_tool"},
            input_str="x",
            run_id=rid,
            parent_run_id=root_id,
        )
        self.handler.on_tool_error(
            error=RuntimeError("boom"), run_id=rid, parent_run_id=root_id
        )

        run = self.handler._runs[str(rid)]
        assert run["status"] == "error"
        assert "boom" in run["outputs"]["error"]


# ---------------------------------------------------------------------------
# Payload format
# ---------------------------------------------------------------------------

class TestPayloadFormat:
    def test_payload_matches_langsmith_format(self):
        handler = PotatoCallbackHandler(potato_url="http://localhost:9999")

        root_id = uuid.uuid4()
        tool_id = uuid.uuid4()

        handler.on_chain_start(
            serialized={"name": "Agent"}, inputs={"input": "do stuff"}, run_id=root_id
        )
        handler.on_tool_start(
            serialized={"name": "search"},
            input_str="query",
            run_id=tool_id,
            parent_run_id=root_id,
        )
        handler.on_tool_end(output="result", run_id=tool_id, parent_run_id=root_id)

        payload = handler._build_payload()

        # Must have 'runs' key (LangSmith format)
        assert "runs" in payload
        assert len(payload["runs"]) == 2

        # Runs have required fields
        for run in payload["runs"]:
            assert "id" in run
            assert "run_type" in run
            assert "name" in run
            assert "inputs" in run
            assert "outputs" in run

        # Root run has no parent
        root = [r for r in payload["runs"] if r["id"] == str(root_id)][0]
        assert root["parent_run_id"] is None

        # Child references parent
        child = [r for r in payload["runs"] if r["id"] == str(tool_id)][0]
        assert child["parent_run_id"] == str(root_id)


# ---------------------------------------------------------------------------
# Send behavior
# ---------------------------------------------------------------------------

class TestSendBehavior:
    @patch("potato.integrations.langchain_callback.requests")
    def test_root_chain_end_triggers_send(self, mock_requests):
        """Completing the root chain should POST to Potato."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "accepted"}
        mock_requests.post.return_value = mock_resp

        handler = PotatoCallbackHandler(
            potato_url="http://localhost:8000",
            api_key="secret",
        )

        root_id = uuid.uuid4()
        handler.on_chain_start(
            serialized={"name": "Root"},
            inputs={"input": "test"},
            run_id=root_id,
        )
        handler.on_chain_end(
            outputs={"output": "done"},
            run_id=root_id,
        )
        handler.flush(timeout=5)

        mock_requests.post.assert_called_once()
        call_args = mock_requests.post.call_args
        assert "/api/traces/langsmith" in call_args[0][0]

    @patch("potato.integrations.langchain_callback.requests")
    def test_nested_chain_end_does_not_send(self, mock_requests):
        """Completing a nested chain should NOT trigger send."""
        handler = PotatoCallbackHandler(potato_url="http://localhost:8000")

        root_id = uuid.uuid4()
        child_id = uuid.uuid4()

        handler.on_chain_start(
            serialized={"name": "Root"}, inputs={}, run_id=root_id
        )
        handler.on_chain_start(
            serialized={"name": "SubChain"},
            inputs={},
            run_id=child_id,
            parent_run_id=root_id,
        )
        handler.on_chain_end(outputs={}, run_id=child_id, parent_run_id=root_id)

        # No send should have happened (root hasn't ended)
        mock_requests.post.assert_not_called()

    @patch("potato.integrations.langchain_callback.requests")
    def test_auth_header_included(self, mock_requests):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_requests.post.return_value = mock_resp

        handler = PotatoCallbackHandler(
            potato_url="http://localhost:8000",
            api_key="my-secret-key",
        )
        root_id = uuid.uuid4()
        handler.on_chain_start(
            serialized={"name": "R"}, inputs={}, run_id=root_id
        )
        handler.on_chain_end(outputs={}, run_id=root_id)
        handler.flush(timeout=5)

        call_kwargs = mock_requests.post.call_args
        headers = call_kwargs[1]["headers"]
        assert headers["Authorization"] == "Bearer my-secret-key"

    @patch("potato.integrations.langchain_callback.requests")
    def test_send_failure_does_not_crash(self, mock_requests):
        """Network errors should be logged, not raised."""
        mock_requests.post.side_effect = ConnectionError("unreachable")

        handler = PotatoCallbackHandler(potato_url="http://bad-host:9999")
        root_id = uuid.uuid4()
        handler.on_chain_start(
            serialized={"name": "R"}, inputs={}, run_id=root_id
        )
        # Should not raise
        handler.on_chain_end(outputs={}, run_id=root_id)
        handler.flush(timeout=5)


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

class TestThreadSafety:
    def test_concurrent_starts(self):
        handler = PotatoCallbackHandler(potato_url="http://localhost:9999")

        def add_run(i):
            handler.on_chain_start(
                serialized={"name": f"chain_{i}"},
                inputs={},
                run_id=uuid.uuid4(),
                parent_run_id=uuid.uuid4(),  # not root
            )

        threads = [threading.Thread(target=add_run, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(handler._runs) == 50


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

class TestReset:
    def test_reset_clears_state(self):
        handler = PotatoCallbackHandler(potato_url="http://localhost:9999")
        rid = uuid.uuid4()
        handler.on_chain_start(
            serialized={"name": "X"}, inputs={}, run_id=rid
        )
        assert len(handler._runs) == 1

        handler.reset()
        assert len(handler._runs) == 0
        assert handler._root_run_id is None
