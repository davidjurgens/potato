"""
Unit tests for WebhookReceiver.

Tests authentication validation, format auto-detection, and payload
normalization for generic and LangSmith webhook formats.
"""

import pytest
from unittest.mock import patch

from potato.trace_ingestion.webhook_receiver import WebhookReceiver


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_generic_payload(
    trace_id="trace_001",
    task="Search for a product",
    steps=None,
):
    """Build a minimal generic webhook payload."""
    if steps is None:
        steps = [
            {
                "step_index": 0,
                "action_type": "click",
                "thought": "I will click the button",
                "observation": "Button was clicked",
                "timestamp": 0,
            }
        ]
    return {
        "id": trace_id,
        "task_description": task,
        "steps": steps,
    }


def _make_langsmith_payload(
    trace_id="ls_001",
    name="My Chain",
    runs=None,
):
    """Build a minimal LangSmith webhook payload."""
    if runs is None:
        runs = [
            {
                "id": trace_id,
                "name": name,
                "run_type": "chain",
                "inputs": {"input": "Search for sweaters"},
                "outputs": {"output": "Found sweaters"},
                "status": "success",
                "latency": 1.2,
            }
        ]
    return {"runs": runs}


# ---------------------------------------------------------------------------
# validate_auth
# ---------------------------------------------------------------------------

class TestValidateAuth:
    """Tests for WebhookReceiver.validate_auth()."""

    def test_no_api_key_always_passes(self):
        """When no api_key is configured, any request is accepted."""
        receiver = WebhookReceiver(api_key="")
        assert receiver.validate_auth({}) is True
        assert receiver.validate_auth({"Authorization": "Bearer anything"}) is True
        assert receiver.validate_auth({"X-API-Key": "random"}) is True

    def test_bearer_token_correct(self):
        receiver = WebhookReceiver(api_key="secret123")
        assert receiver.validate_auth({"Authorization": "Bearer secret123"}) is True

    def test_bearer_token_incorrect(self):
        receiver = WebhookReceiver(api_key="secret123")
        assert receiver.validate_auth({"Authorization": "Bearer wrong"}) is False

    def test_bearer_token_empty(self):
        receiver = WebhookReceiver(api_key="secret123")
        assert receiver.validate_auth({"Authorization": "Bearer "}) is False

    def test_x_api_key_correct(self):
        receiver = WebhookReceiver(api_key="mykey")
        assert receiver.validate_auth({"X-API-Key": "mykey"}) is True

    def test_x_api_key_incorrect(self):
        receiver = WebhookReceiver(api_key="mykey")
        assert receiver.validate_auth({"X-API-Key": "wrongkey"}) is False

    def test_no_auth_header_with_required_key(self):
        """Empty headers when key is required returns False."""
        receiver = WebhookReceiver(api_key="secret")
        assert receiver.validate_auth({}) is False

    def test_authorization_header_without_bearer_prefix(self):
        """Authorization without 'Bearer ' prefix is not recognized."""
        receiver = WebhookReceiver(api_key="token")
        assert receiver.validate_auth({"Authorization": "token"}) is False

    def test_bearer_takes_priority_over_x_api_key(self):
        """When both headers present, Authorization/Bearer is checked first."""
        receiver = WebhookReceiver(api_key="correct")
        # Bearer is correct, X-API-Key is wrong -> should pass
        headers = {"Authorization": "Bearer correct", "X-API-Key": "wrong"}
        assert receiver.validate_auth(headers) is True

    def test_wrong_bearer_then_no_x_api_key(self):
        """Wrong Bearer token and no X-API-Key header -> False."""
        receiver = WebhookReceiver(api_key="correct")
        assert receiver.validate_auth({"Authorization": "Bearer wrong"}) is False


# ---------------------------------------------------------------------------
# _detect_format
# ---------------------------------------------------------------------------

class TestDetectFormat:
    """Tests for WebhookReceiver._detect_format()."""

    def test_generic_payload_detected_as_generic(self):
        receiver = WebhookReceiver()
        payload = _make_generic_payload()
        assert receiver._detect_format(payload) == "generic"

    def test_langsmith_runs_key_detected(self):
        receiver = WebhookReceiver()
        assert receiver._detect_format({"runs": []}) == "langsmith"

    def test_langsmith_run_type_key_detected(self):
        receiver = WebhookReceiver()
        assert receiver._detect_format({"run_type": "chain"}) == "langsmith"

    def test_empty_payload_detected_as_generic(self):
        receiver = WebhookReceiver()
        assert receiver._detect_format({}) == "generic"

    def test_payload_with_steps_only_is_generic(self):
        receiver = WebhookReceiver()
        assert receiver._detect_format({"steps": []}) == "generic"

    def test_payload_with_both_runs_and_steps_is_langsmith(self):
        """runs key takes precedence over generic keys."""
        receiver = WebhookReceiver()
        assert receiver._detect_format({"runs": [], "steps": []}) == "langsmith"


# ---------------------------------------------------------------------------
# process_webhook – generic format
# ---------------------------------------------------------------------------

class TestProcessWebhookGeneric:
    """Tests for process_webhook() with generic payload format."""

    def test_returns_dict(self):
        receiver = WebhookReceiver()
        result = receiver.process_webhook(_make_generic_payload())
        assert isinstance(result, dict)

    def test_id_prefixed_with_webhook(self):
        receiver = WebhookReceiver()
        result = receiver.process_webhook(_make_generic_payload(trace_id="abc"))
        assert result["id"] == "webhook_abc"

    def test_task_description_preserved(self):
        receiver = WebhookReceiver()
        result = receiver.process_webhook(
            _make_generic_payload(task="Find blue shoes")
        )
        assert result["task_description"] == "Find blue shoes"

    def test_task_description_aliases(self):
        """'task' and 'description' keys also populate task_description."""
        receiver = WebhookReceiver()
        result = receiver.process_webhook({"steps": [], "task": "Buy milk"})
        assert result["task_description"] == "Buy milk"

        result2 = receiver.process_webhook({"steps": [], "description": "Sell milk"})
        assert result2["task_description"] == "Sell milk"

    def test_site_field_preserved(self):
        receiver = WebhookReceiver()
        payload = _make_generic_payload()
        payload["site"] = "amazon.com"
        result = receiver.process_webhook(payload)
        assert result["site"] == "amazon.com"

    def test_site_url_alias(self):
        """'url' key is used as site fallback."""
        receiver = WebhookReceiver()
        result = receiver.process_webhook({"steps": [], "url": "example.com"})
        assert result["site"] == "example.com"

    def test_steps_normalized(self):
        receiver = WebhookReceiver()
        result = receiver.process_webhook(_make_generic_payload())
        assert "steps" in result
        assert len(result["steps"]) == 1

    def test_step_action_type_preserved(self):
        receiver = WebhookReceiver()
        result = receiver.process_webhook(_make_generic_payload())
        assert result["steps"][0]["action_type"] == "click"

    def test_step_action_type_alias(self):
        """'type' key is used as action_type fallback."""
        receiver = WebhookReceiver()
        payload = {"id": "x", "steps": [{"type": "scroll", "timestamp": 0}]}
        result = receiver.process_webhook(payload)
        assert result["steps"][0]["action_type"] == "scroll"

    def test_step_observation_alias(self):
        """'output' key is used as observation fallback."""
        receiver = WebhookReceiver()
        payload = {"steps": [{"action_type": "click", "output": "Page loaded"}]}
        result = receiver.process_webhook(payload)
        assert result["steps"][0]["observation"] == "Page loaded"

    def test_step_index_defaults_to_enumeration(self):
        receiver = WebhookReceiver()
        steps = [{"action_type": "click"}, {"action_type": "type"}]
        result = receiver.process_webhook({"steps": steps})
        assert result["steps"][0]["step_index"] == 0
        assert result["steps"][1]["step_index"] == 1

    def test_metadata_source_is_webhook(self):
        receiver = WebhookReceiver()
        result = receiver.process_webhook(_make_generic_payload())
        assert result["metadata"]["source"] == "webhook"
        assert result["metadata"]["format"] == "generic"

    def test_metadata_original_id_preserved(self):
        receiver = WebhookReceiver()
        result = receiver.process_webhook(_make_generic_payload(trace_id="orig_id"))
        assert result["metadata"]["original_id"] == "orig_id"

    def test_metadata_received_at_is_float(self):
        receiver = WebhookReceiver()
        result = receiver.process_webhook(_make_generic_payload())
        assert isinstance(result["metadata"]["received_at"], float)

    def test_normalized_structure_has_required_keys(self):
        """Output always has id, task_description, site, steps, metadata."""
        receiver = WebhookReceiver()
        result = receiver.process_webhook(_make_generic_payload())
        for key in ("id", "task_description", "site", "steps", "metadata"):
            assert key in result

    def test_empty_steps_list(self):
        receiver = WebhookReceiver()
        result = receiver.process_webhook({"id": "x", "steps": []})
        assert result["steps"] == []

    def test_format_hint_generic_bypasses_detection(self):
        """Explicit format_hint='generic' does not trigger auto-detect."""
        receiver = WebhookReceiver()
        # Payload has 'runs' key but format_hint forces generic handling
        payload = {"runs": [], "id": "x", "steps": []}
        result = receiver.process_webhook(payload, format_hint="generic")
        assert result["id"] == "webhook_x"

    def test_exception_returns_none(self):
        """If normalization raises an error, None is returned."""
        receiver = WebhookReceiver()
        with patch.object(receiver, "_normalize_generic", side_effect=RuntimeError("fail")):
            result = receiver.process_webhook({"steps": []})
        assert result is None


# ---------------------------------------------------------------------------
# process_webhook – LangSmith format
# ---------------------------------------------------------------------------

class TestProcessWebhookLangsmith:
    """Tests for process_webhook() with LangSmith payload format."""

    def test_returns_dict(self):
        receiver = WebhookReceiver()
        result = receiver.process_webhook(_make_langsmith_payload())
        assert isinstance(result, dict)

    def test_id_prefixed_with_langsmith(self):
        receiver = WebhookReceiver()
        result = receiver.process_webhook(
            _make_langsmith_payload(trace_id="ls_abc")
        )
        assert result["id"] == "langsmith_ls_abc"

    def test_task_description_from_run_name(self):
        receiver = WebhookReceiver()
        result = receiver.process_webhook(
            _make_langsmith_payload(name="My Workflow")
        )
        assert result["task_description"] == "My Workflow"

    def test_steps_created_from_runs(self):
        receiver = WebhookReceiver()
        result = receiver.process_webhook(_make_langsmith_payload())
        assert len(result["steps"]) == 1

    def test_run_type_mapped_to_action_type(self):
        """LangSmith run_type values are mapped to action types."""
        receiver = WebhookReceiver()
        runs = [{"id": "r1", "run_type": "tool", "inputs": {}, "outputs": {}}]
        result = receiver.process_webhook({"runs": runs})
        assert result["steps"][0]["action_type"] == "click"  # tool -> click

    def test_run_type_llm_maps_to_type(self):
        receiver = WebhookReceiver()
        runs = [{"id": "r1", "run_type": "llm", "inputs": {}, "outputs": {}}]
        result = receiver.process_webhook({"runs": runs})
        assert result["steps"][0]["action_type"] == "type"  # llm -> type

    def test_run_type_chain_maps_to_navigate(self):
        receiver = WebhookReceiver()
        runs = [{"id": "r1", "run_type": "chain", "inputs": {}, "outputs": {}}]
        result = receiver.process_webhook({"runs": runs})
        assert result["steps"][0]["action_type"] == "navigate"  # chain -> navigate

    def test_run_type_unknown_maps_to_wait(self):
        receiver = WebhookReceiver()
        runs = [{"id": "r1", "run_type": "custom_type", "inputs": {}, "outputs": {}}]
        result = receiver.process_webhook({"runs": runs})
        assert result["steps"][0]["action_type"] == "wait"

    def test_thought_from_inputs_input(self):
        receiver = WebhookReceiver()
        runs = [{"id": "r1", "run_type": "chain", "inputs": {"input": "Do X"}, "outputs": {}}]
        result = receiver.process_webhook({"runs": runs})
        assert result["steps"][0]["thought"] == "Do X"

    def test_thought_from_inputs_prompt(self):
        receiver = WebhookReceiver()
        runs = [{"id": "r1", "run_type": "llm", "inputs": {"prompt": "Tell me"}, "outputs": {}}]
        result = receiver.process_webhook({"runs": runs})
        assert result["steps"][0]["thought"] == "Tell me"

    def test_observation_from_outputs_output(self):
        receiver = WebhookReceiver()
        runs = [{"id": "r1", "run_type": "chain", "inputs": {}, "outputs": {"output": "Done"}}]
        result = receiver.process_webhook({"runs": runs})
        assert result["steps"][0]["observation"] == "Done"

    def test_observation_from_outputs_text(self):
        receiver = WebhookReceiver()
        runs = [{"id": "r1", "run_type": "llm", "inputs": {}, "outputs": {"text": "Result"}}]
        result = receiver.process_webhook({"runs": runs})
        assert result["steps"][0]["observation"] == "Result"

    def test_step_metadata_contains_run_info(self):
        receiver = WebhookReceiver()
        result = receiver.process_webhook(_make_langsmith_payload())
        step_meta = result["steps"][0]["metadata"]
        assert "run_id" in step_meta
        assert "run_type" in step_meta
        assert "status" in step_meta

    def test_metadata_source_is_langsmith(self):
        receiver = WebhookReceiver()
        result = receiver.process_webhook(_make_langsmith_payload())
        assert result["metadata"]["source"] == "langsmith"
        assert result["metadata"]["format"] == "langsmith"

    def test_auto_detection_picks_langsmith_for_runs(self):
        """Auto-detection routes runs-keyed payloads to langsmith handler."""
        receiver = WebhookReceiver()
        payload = _make_langsmith_payload(trace_id="auto_ls")
        result = receiver.process_webhook(payload, format_hint="auto")
        assert result["id"].startswith("langsmith_")

    def test_single_run_with_run_type_auto_detected(self):
        """Payload with run_type (not runs) is detected as langsmith."""
        receiver = WebhookReceiver()
        payload = {
            "id": "single_run",
            "run_type": "chain",
            "name": "Solo",
            "inputs": {"input": "hi"},
            "outputs": {"output": "bye"},
        }
        result = receiver.process_webhook(payload, format_hint="auto")
        assert result is not None
        assert result["id"].startswith("langsmith_")

    def test_multiple_runs_become_multiple_steps(self):
        receiver = WebhookReceiver()
        runs = [
            {"id": "r1", "run_type": "chain", "inputs": {}, "outputs": {}},
            {"id": "r2", "run_type": "llm", "inputs": {}, "outputs": {}},
            {"id": "r3", "run_type": "tool", "inputs": {}, "outputs": {}},
        ]
        result = receiver.process_webhook({"runs": runs})
        assert len(result["steps"]) == 3
        assert result["steps"][0]["step_index"] == 0
        assert result["steps"][2]["step_index"] == 2

    def test_normalized_structure_has_required_keys(self):
        receiver = WebhookReceiver()
        result = receiver.process_webhook(_make_langsmith_payload())
        for key in ("id", "task_description", "site", "steps", "metadata"):
            assert key in result

    def test_empty_runs_list_falls_back_to_generic(self):
        """Empty runs list falls back to _normalize_generic."""
        receiver = WebhookReceiver()
        result = receiver.process_webhook({"runs": []}, format_hint="langsmith")
        # Falls back to generic - will have webhook_ prefix
        assert result is not None


# ---------------------------------------------------------------------------
# Normalized output structure
# ---------------------------------------------------------------------------

class TestNormalizedOutputStructure:
    """Verify normalized output structure keys for both formats."""

    def test_generic_step_has_all_normalized_keys(self):
        receiver = WebhookReceiver()
        step = {
            "step_index": 0,
            "action_type": "click",
            "thought": "thinking",
            "observation": "observed",
            "screenshot_url": "img.png",
            "timestamp": 1.5,
            "coordinates": {"x": 10, "y": 20},
            "element": {"tag": "button"},
            "viewport": {"width": 1280, "height": 720},
        }
        result = receiver.process_webhook({"id": "x", "steps": [step]})
        s = result["steps"][0]
        for key in (
            "step_index",
            "action_type",
            "thought",
            "observation",
            "screenshot_url",
            "timestamp",
            "coordinates",
            "element",
            "viewport",
        ):
            assert key in s, f"Missing key '{key}' in normalized step"

    def test_langsmith_step_has_all_normalized_keys(self):
        receiver = WebhookReceiver()
        runs = [
            {
                "id": "r1",
                "run_type": "chain",
                "inputs": {"input": "test"},
                "outputs": {"output": "result"},
                "status": "success",
                "latency": 0.5,
            }
        ]
        result = receiver.process_webhook({"runs": runs})
        s = result["steps"][0]
        for key in ("step_index", "action_type", "thought", "observation", "timestamp"):
            assert key in s, f"Missing key '{key}' in normalized LangSmith step"
