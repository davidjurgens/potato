"""
Integration tests verifying PotatoCallbackHandler's payload is compatible
with WebhookReceiver's _normalize_langsmith() parser.

These are fast unit-level tests (no server) that verify the contract
between the two components.
"""

import uuid

import pytest

from potato.integrations.langchain_callback import PotatoCallbackHandler
from potato.trace_ingestion.webhook_receiver import WebhookReceiver


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _simulate_simple_chain(handler):
    """Simulate a minimal chain: chain → tool → chain end."""
    root_id = uuid.uuid4()
    tool_id = uuid.uuid4()

    handler.on_chain_start(
        serialized={"name": "SimpleAgent"},
        inputs={"input": "What is the capital of France?"},
        run_id=root_id,
    )
    handler.on_tool_start(
        serialized={"name": "search"},
        input_str="capital of France",
        run_id=tool_id,
        parent_run_id=root_id,
    )
    handler.on_tool_end(
        output="The capital of France is Paris.",
        run_id=tool_id,
        parent_run_id=root_id,
    )
    # Don't end root chain yet — caller decides
    return root_id, tool_id


def _simulate_full_agent(handler):
    """Simulate a ReAct-style agent: chain → LLM → tool → LLM → chain end."""
    root_id = uuid.uuid4()
    llm1_id = uuid.uuid4()
    tool_id = uuid.uuid4()
    llm2_id = uuid.uuid4()

    handler.on_chain_start(
        serialized={"name": "ReActAgent"},
        inputs={"input": "Book a flight"},
        run_id=root_id,
    )

    # LLM decides to use tool
    handler.on_llm_start(
        serialized={"name": "gpt-4"},
        prompts=["You are a helpful assistant. Book a flight."],
        run_id=llm1_id,
        parent_run_id=root_id,
    )

    class FakeGen:
        text = "I should search for flights."

    class FakeResp:
        generations = [[FakeGen()]]

    handler.on_llm_end(response=FakeResp(), run_id=llm1_id, parent_run_id=root_id)

    # Tool execution
    handler.on_tool_start(
        serialized={"name": "flight_search"},
        input_str="NYC to LAX",
        run_id=tool_id,
        parent_run_id=root_id,
    )
    handler.on_tool_end(
        output="Found 3 flights: AA100 $300, UA200 $350, DL300 $280",
        run_id=tool_id,
        parent_run_id=root_id,
    )

    # Final LLM response
    handler.on_llm_start(
        serialized={"name": "gpt-4"},
        prompts=["Based on search results, recommend a flight."],
        run_id=llm2_id,
        parent_run_id=root_id,
    )

    class FinalGen:
        text = "The cheapest flight is DL300 at $280."

    class FinalResp:
        generations = [[FinalGen()]]

    handler.on_llm_end(response=FinalResp(), run_id=llm2_id, parent_run_id=root_id)

    return root_id


# ---------------------------------------------------------------------------
# Tests: payload compatibility
# ---------------------------------------------------------------------------

class TestPayloadCompatibility:
    """Verify callback payload is parseable by WebhookReceiver."""

    def test_simple_chain_payload_is_valid_langsmith(self):
        handler = PotatoCallbackHandler(potato_url="http://unused:0")
        root_id, _ = _simulate_simple_chain(handler)
        payload = handler._build_payload()

        receiver = WebhookReceiver()
        result = receiver.process_webhook(payload, format_hint="langsmith")

        assert result is not None
        assert result["id"].startswith("langsmith_")
        assert len(result["steps"]) == 2  # chain + tool

    def test_full_agent_payload_is_valid_langsmith(self):
        handler = PotatoCallbackHandler(potato_url="http://unused:0")
        _simulate_full_agent(handler)
        payload = handler._build_payload()

        receiver = WebhookReceiver()
        result = receiver.process_webhook(payload, format_hint="langsmith")

        assert result is not None
        assert len(result["steps"]) == 4  # chain + llm + tool + llm

    def test_auto_detection_recognizes_callback_payload(self):
        """WebhookReceiver auto-detects callback payload as langsmith."""
        handler = PotatoCallbackHandler(potato_url="http://unused:0")
        _simulate_simple_chain(handler)
        payload = handler._build_payload()

        receiver = WebhookReceiver()
        # Auto-detect should work because payload has "runs" key
        assert receiver._detect_format(payload) == "langsmith"

    def test_payload_runs_have_required_fields(self):
        """Each run in payload has the fields WebhookReceiver expects."""
        handler = PotatoCallbackHandler(potato_url="http://unused:0")
        _simulate_simple_chain(handler)
        payload = handler._build_payload()

        required_fields = {"id", "run_type", "name", "inputs", "outputs"}
        for run in payload["runs"]:
            missing = required_fields - set(run.keys())
            assert not missing, f"Run missing fields: {missing}"

    def test_run_types_are_valid(self):
        """Run types produced by callback are recognized by WebhookReceiver."""
        handler = PotatoCallbackHandler(potato_url="http://unused:0")
        _simulate_full_agent(handler)
        payload = handler._build_payload()

        valid_types = {"chain", "llm", "tool", "retriever"}
        for run in payload["runs"]:
            assert run["run_type"] in valid_types, (
                f"Unknown run_type: {run['run_type']}"
            )

    def test_parent_run_id_structure(self):
        """Root run has parent_run_id=None, children reference the root."""
        handler = PotatoCallbackHandler(potato_url="http://unused:0")
        root_id, tool_id = _simulate_simple_chain(handler)
        payload = handler._build_payload()

        runs_by_id = {r["id"]: r for r in payload["runs"]}
        root_run = runs_by_id[str(root_id)]
        tool_run = runs_by_id[str(tool_id)]

        assert root_run["parent_run_id"] is None
        assert tool_run["parent_run_id"] == str(root_id)

    def test_inputs_outputs_are_dicts(self):
        """Inputs and outputs are JSON-serializable dicts."""
        handler = PotatoCallbackHandler(potato_url="http://unused:0")
        _simulate_simple_chain(handler)
        payload = handler._build_payload()

        import json
        for run in payload["runs"]:
            assert isinstance(run["inputs"], dict)
            assert isinstance(run["outputs"], dict)
            # Should be JSON-serializable
            json.dumps(run["inputs"])
            json.dumps(run["outputs"])


# ---------------------------------------------------------------------------
# Tests: WebhookReceiver parses callback payloads correctly
# ---------------------------------------------------------------------------

class TestWebhookReceiverParsesCallback:
    """Verify WebhookReceiver extracts meaningful data from callback payloads."""

    def test_task_description_from_root_chain_name(self):
        handler = PotatoCallbackHandler(potato_url="http://unused:0")
        root_id = uuid.uuid4()
        handler.on_chain_start(
            serialized={"name": "BookFlightAgent"},
            inputs={"input": "book flight"},
            run_id=root_id,
        )
        payload = handler._build_payload()

        receiver = WebhookReceiver()
        result = receiver.process_webhook(payload, format_hint="langsmith")

        assert result["task_description"] == "BookFlightAgent"

    def test_steps_preserve_order(self):
        handler = PotatoCallbackHandler(potato_url="http://unused:0")
        _simulate_full_agent(handler)
        payload = handler._build_payload()

        receiver = WebhookReceiver()
        result = receiver.process_webhook(payload, format_hint="langsmith")

        # Steps should have sequential indices
        for i, step in enumerate(result["steps"]):
            assert step["step_index"] == i

    def test_tool_inputs_become_thought(self):
        handler = PotatoCallbackHandler(potato_url="http://unused:0")
        root_id = uuid.uuid4()
        tool_id = uuid.uuid4()

        handler.on_chain_start(
            serialized={"name": "Root"}, inputs={}, run_id=root_id
        )
        handler.on_tool_start(
            serialized={"name": "calc"},
            input_str="2+2",
            run_id=tool_id,
            parent_run_id=root_id,
        )
        handler.on_tool_end(output="4", run_id=tool_id, parent_run_id=root_id)

        payload = handler._build_payload()
        receiver = WebhookReceiver()
        result = receiver.process_webhook(payload, format_hint="langsmith")

        tool_step = result["steps"][1]  # tool is second run
        assert tool_step["thought"] == "2+2"
        assert tool_step["observation"] == "4"

    def test_chain_inputs_become_thought(self):
        handler = PotatoCallbackHandler(potato_url="http://unused:0")
        root_id = uuid.uuid4()
        handler.on_chain_start(
            serialized={"name": "Root"},
            inputs={"input": "Find restaurants"},
            run_id=root_id,
        )
        payload = handler._build_payload()

        receiver = WebhookReceiver()
        result = receiver.process_webhook(payload, format_hint="langsmith")

        assert result["steps"][0]["thought"] == "Find restaurants"

    def test_error_run_outputs_captured(self):
        handler = PotatoCallbackHandler(potato_url="http://unused:0")
        root_id = uuid.uuid4()
        tool_id = uuid.uuid4()

        handler.on_chain_start(
            serialized={"name": "Root"}, inputs={}, run_id=root_id
        )
        handler.on_tool_start(
            serialized={"name": "failing_tool"},
            input_str="bad input",
            run_id=tool_id,
            parent_run_id=root_id,
        )
        handler.on_tool_error(
            error=RuntimeError("API timeout"),
            run_id=tool_id,
            parent_run_id=root_id,
        )

        payload = handler._build_payload()
        receiver = WebhookReceiver()
        result = receiver.process_webhook(payload, format_hint="langsmith")

        tool_step = result["steps"][1]
        # Error info is in the run outputs; the receiver maps
        # outputs.output → observation.  Since the error is stored
        # under "error" key, observation may be empty, but the step
        # metadata should capture the error status.
        assert tool_step["metadata"]["status"] == "error"


# ---------------------------------------------------------------------------
# Tests: retriever callback compatibility
# ---------------------------------------------------------------------------

class TestRetrieverCallbackCompatibility:
    """Verify retriever callbacks produce valid payloads."""

    def test_retriever_run_in_payload(self):
        handler = PotatoCallbackHandler(potato_url="http://unused:0")
        root_id = uuid.uuid4()
        retriever_id = uuid.uuid4()

        handler.on_chain_start(
            serialized={"name": "RAGChain"},
            inputs={"input": "what is X?"},
            run_id=root_id,
        )
        handler.on_retriever_start(
            serialized={"name": "VectorStore"},
            query="what is X?",
            run_id=retriever_id,
            parent_run_id=root_id,
        )
        handler.on_retriever_end(
            documents=["doc1 content", "doc2 content"],
            run_id=retriever_id,
            parent_run_id=root_id,
        )

        payload = handler._build_payload()

        # Retriever run should be present
        retriever_runs = [r for r in payload["runs"] if r["run_type"] == "retriever"]
        assert len(retriever_runs) == 1
        assert retriever_runs[0]["name"] == "VectorStore"

        # WebhookReceiver should handle it
        receiver = WebhookReceiver()
        result = receiver.process_webhook(payload, format_hint="langsmith")
        assert result is not None
        assert len(result["steps"]) == 2
