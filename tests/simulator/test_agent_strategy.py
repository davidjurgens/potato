"""Unit tests for AgentSimulatorStrategy.

These tests use a fake AI endpoint so they run without Ollama / network.
"""

import json
from unittest.mock import MagicMock

import pytest

from potato.simulator.agent_strategy import (
    AgentSimulatorStrategy,
    _AgentLabelResponse,
)
from potato.simulator.config import AgentStrategyConfig
from potato.simulator.competence_profiles import PerfectCompetence


@pytest.fixture
def strategy_with_mock_endpoint():
    """Build a strategy whose endpoint is a MagicMock returning a canned response."""
    cfg = AgentStrategyConfig(endpoint_type="ollama_vision", model="gemma4:e4b")
    strat = AgentSimulatorStrategy.__new__(AgentSimulatorStrategy)
    strat.config = cfg
    strat.endpoint = MagicMock()
    from potato.simulator.annotation_strategies import RandomStrategy
    strat.random_strategy = RandomStrategy()
    strat._cache = {}
    strat._failed_instances = set()
    return strat


@pytest.fixture
def schemas():
    return [
        {
            "name": "task_success",
            "annotation_type": "radio",
            "description": "Did the agent complete the task?",
            "labels": [{"name": "success"}, {"name": "partial"}, {"name": "failure"}],
        },
        {
            "name": "efficiency",
            "annotation_type": "likert",
            "description": "How efficient?",
            "size": 5,
        },
    ]


@pytest.fixture
def agent_trace_instance(schemas):
    return {
        "instance_id": "trace_001",
        "data": {
            "task_description": "Book the cheapest flight from JFK to LHR.",
            "metadata_table": [
                {"Property": "Steps", "Value": "7"},
                {"Property": "Cost", "Value": "$0.12"},
            ],
            "conversation": [
                {"speaker": "Agent (Thought)", "text": "I need to search."},
                {"speaker": "Agent (Action)", "text": "search_flights(...)"},
                {"speaker": "Environment", "text": "Found 5 flights."},
            ],
        },
        "__all_schemas__": schemas,
    }


class TestStructuredTurnsRendering:
    """Verifies that coding-agent traces (structured_turns with tool_calls)
    are rendered in the LLM prompt so the rater can see tool invocations."""

    @pytest.fixture
    def coding_instance(self, schemas):
        return {
            "instance_id": "coding_001",
            "data": {
                "task_description": "Fix the auth bypass in login.py",
                "structured_turns": [
                    {"role": "user", "content": "Fix the auth bypass", "tool_calls": []},
                    {
                        "role": "assistant",
                        "content": "Let me read login.py first.",
                        "tool_calls": [
                            {
                                "tool": "Read",
                                "input": {"file_path": "src/auth/login.py"},
                                "output": "def authenticate(u, p):\n    if u.role=='admin': return create_session(u)",
                                "output_type": "code",
                                "language": "python",
                            }
                        ],
                    },
                    {
                        "role": "assistant",
                        "content": "Now fixing the bypass.",
                        "tool_calls": [
                            {
                                "tool": "Edit",
                                "input": {"file_path": "src/auth/login.py", "old_string": "if u.role=='admin'"},
                                "output": "Edited successfully",
                            }
                        ],
                    },
                ],
            },
            "__all_schemas__": schemas,
        }

    def test_structured_turns_detected_as_dialogue(
        self, strategy_with_mock_endpoint, coding_instance, schemas
    ):
        prompt, _ = strategy_with_mock_endpoint._build_request(
            coding_instance, schemas
        )
        # The structured_turns section should be rendered like a dialogue
        assert "Structured_Turns" in prompt or "structured_turns" in prompt.lower()
        assert "Fix the auth bypass" in prompt
        assert "Let me read login.py" in prompt
        assert "Now fixing the bypass" in prompt

    def test_tool_calls_rendered_with_input_and_output(
        self, strategy_with_mock_endpoint, coding_instance, schemas
    ):
        prompt, _ = strategy_with_mock_endpoint._build_request(
            coding_instance, schemas
        )
        # Tool name + input args
        assert "[tool: Read(" in prompt
        assert "file_path=" in prompt
        assert "src/auth/login.py" in prompt
        # Tool output is included
        assert "def authenticate" in prompt
        assert "Edit" in prompt
        # Edit tool call shows file path
        assert "[tool: Edit(" in prompt

    def test_tool_call_output_truncation(
        self, strategy_with_mock_endpoint, schemas
    ):
        long_output = "x" * 5000
        instance = {
            "instance_id": "long",
            "data": {
                "task_description": "task",
                "structured_turns": [
                    {
                        "role": "assistant",
                        "content": "running",
                        "tool_calls": [{"tool": "Bash", "input": {"cmd": "cat big.txt"}, "output": long_output}],
                    }
                ],
            },
            "__all_schemas__": schemas,
        }
        prompt, _ = strategy_with_mock_endpoint._build_request(instance, schemas)
        # Should NOT contain the full 5000 chars
        assert "x" * 5000 not in prompt
        assert "truncated" in prompt

    def test_tool_call_with_no_output(
        self, strategy_with_mock_endpoint, schemas
    ):
        instance = {
            "instance_id": "no_out",
            "data": {
                "task_description": "task",
                "structured_turns": [
                    {
                        "role": "assistant",
                        "content": "trying",
                        "tool_calls": [{"tool": "Write", "input": {"path": "a.txt", "content": "hi"}}],
                    }
                ],
            },
            "__all_schemas__": schemas,
        }
        prompt, _ = strategy_with_mock_endpoint._build_request(instance, schemas)
        assert "[tool: Write(" in prompt
        # Without output, no `->` arrow
        assert "[tool: Write(" in prompt and prompt.count("->") == 0


class TestPromptBuilding:
    def test_prompt_includes_task_dialogue_and_spreadsheet(
        self, strategy_with_mock_endpoint, agent_trace_instance, schemas
    ):
        prompt, images = strategy_with_mock_endpoint._build_request(
            agent_trace_instance, schemas
        )
        assert "Book the cheapest flight" in prompt
        assert "Agent (Thought)" in prompt
        assert "Agent (Action)" in prompt
        assert "search_flights" in prompt
        assert "Steps" in prompt and "Cost" in prompt
        assert "task_success" in prompt
        assert "efficiency" in prompt
        assert "labels=success, partial, failure" in prompt
        assert "integer 1..5" in prompt
        assert images == []  # no image field

    def test_dialogue_truncation_respects_max(
        self, strategy_with_mock_endpoint, schemas
    ):
        instance = {
            "instance_id": "t",
            "data": {
                "task_description": "x",
                "conversation": [{"speaker": "A", "text": "y" * 5000} for _ in range(10)],
            },
            "__all_schemas__": schemas,
        }
        strategy_with_mock_endpoint.config.max_dialogue_chars = 200
        prompt, _ = strategy_with_mock_endpoint._build_request(instance, schemas)
        # Dialogue section is bounded; full prompt may exceed because of other sections
        dialogue_section = prompt.split("## Conversation\n", 1)[1].split("\n\n", 1)[0]
        assert len(dialogue_section) <= 200


class TestResponseParsing:
    def test_pydantic_model_dump_returns_annotations(self, strategy_with_mock_endpoint):
        response = _AgentLabelResponse(
            annotations={"task_success": "success", "efficiency": 5},
            reasoning="agent did well",
        )
        parsed = strategy_with_mock_endpoint._parse_response(response)
        assert parsed == {"task_success": "success", "efficiency": 5}

    def test_dict_with_annotations_key(self, strategy_with_mock_endpoint):
        parsed = strategy_with_mock_endpoint._parse_response(
            {"annotations": {"task_success": "partial"}, "reasoning": ""}
        )
        assert parsed == {"task_success": "partial"}

    def test_raw_dict_without_wrapping(self, strategy_with_mock_endpoint):
        # When the model returns the annotations dict directly (no wrapper),
        # we still recover it.
        parsed = strategy_with_mock_endpoint._parse_response(
            {"task_success": "success", "efficiency": 4}
        )
        assert parsed == {"task_success": "success", "efficiency": 4}

    def test_string_with_embedded_json(self, strategy_with_mock_endpoint):
        text = 'Sure! Here is the result:\n{"annotations": {"task_success": "failure"}}'
        parsed = strategy_with_mock_endpoint._parse_response(text)
        assert parsed == {"task_success": "failure"}

    def test_none_response_returns_none(self, strategy_with_mock_endpoint):
        assert strategy_with_mock_endpoint._parse_response(None) is None


class TestLabelCoercion:
    def test_radio_exact_match(self, strategy_with_mock_endpoint):
        out = strategy_with_mock_endpoint._format_value(
            "task_success", "success", "radio",
            ["success", "partial", "failure"], {}
        )
        assert out == {"task_success:success": "on"}

    def test_radio_case_insensitive(self, strategy_with_mock_endpoint):
        out = strategy_with_mock_endpoint._format_value(
            "task_success", "SUCCESS", "radio",
            ["success", "partial", "failure"], {}
        )
        assert out == {"task_success:success": "on"}

    def test_radio_substring_fallback(self, strategy_with_mock_endpoint):
        out = strategy_with_mock_endpoint._format_value(
            "task_success", "task was a success", "radio",
            ["success", "partial", "failure"], {}
        )
        assert out == {"task_success:success": "on"}

    def test_radio_unknown_value_returns_none(self, strategy_with_mock_endpoint):
        out = strategy_with_mock_endpoint._format_value(
            "task_success", "completely off", "radio",
            ["success", "partial", "failure"], {}
        )
        assert out is None

    def test_likert_int_in_range(self, strategy_with_mock_endpoint):
        out = strategy_with_mock_endpoint._format_value(
            "efficiency", 4, "likert", [], {"size": 5}
        )
        assert out == {"efficiency:4": "on"}

    def test_likert_int_clamped_high(self, strategy_with_mock_endpoint):
        out = strategy_with_mock_endpoint._format_value(
            "efficiency", 99, "likert", [], {"size": 5}
        )
        assert out == {"efficiency:5": "on"}

    def test_likert_int_clamped_low(self, strategy_with_mock_endpoint):
        out = strategy_with_mock_endpoint._format_value(
            "efficiency", -3, "likert", [], {"size": 5}
        )
        assert out == {"efficiency:1": "on"}

    def test_likert_string_int(self, strategy_with_mock_endpoint):
        out = strategy_with_mock_endpoint._format_value(
            "efficiency", "rating: 3 out of 5", "likert", [], {"size": 5}
        )
        assert out == {"efficiency:3": "on"}

    def test_multiselect_list(self, strategy_with_mock_endpoint):
        out = strategy_with_mock_endpoint._format_value(
            "errors", ["hallucination", "incorrect_fact"], "multiselect",
            ["hallucination", "incorrect_fact", "unnecessary_action"], {}
        )
        assert out == {
            "errors:hallucination": "on",
            "errors:incorrect_fact": "on",
        }

    def test_multiselect_comma_separated_string(self, strategy_with_mock_endpoint):
        out = strategy_with_mock_endpoint._format_value(
            "errors", "hallucination, unnecessary_action", "multiselect",
            ["hallucination", "incorrect_fact", "unnecessary_action"], {}
        )
        assert out == {
            "errors:hallucination": "on",
            "errors:unnecessary_action": "on",
        }

    def test_text_truncates_to_1000(self, strategy_with_mock_endpoint):
        long_text = "x" * 5000
        out = strategy_with_mock_endpoint._format_value(
            "comments", long_text, "text", [], {}
        )
        assert out == {"comments:text": "x" * 1000}


class TestKeyNormalization:
    """The LLM occasionally keys responses by annotation_type instead of
    schema name (e.g. ``code_review`` instead of ``review``). The strategy
    rewrites those keys so per-schema lookups still find the value."""

    def test_annotation_type_key_remapped_to_schema_name(
        self, strategy_with_mock_endpoint
    ):
        schemas = [
            {"name": "review", "annotation_type": "code_review"},
            {"name": "summary", "annotation_type": "text"},
        ]
        parsed = {
            "code_review": {"verdict": "approve"},  # wrong key
            "summary": "ok",
        }
        out = strategy_with_mock_endpoint._normalize_keys_to_schema_names(
            parsed, schemas
        )
        assert "review" in out
        assert out["review"] == {"verdict": "approve"}
        assert out["summary"] == "ok"

    def test_case_insensitive_schema_name_match(
        self, strategy_with_mock_endpoint
    ):
        schemas = [{"name": "Quality", "annotation_type": "likert"}]
        parsed = {"quality": 4}
        out = strategy_with_mock_endpoint._normalize_keys_to_schema_names(
            parsed, schemas
        )
        assert out["Quality"] == 4

    def test_correct_keys_are_passthrough(self, strategy_with_mock_endpoint):
        schemas = [{"name": "task_success", "annotation_type": "radio"}]
        parsed = {"task_success": "success"}
        out = strategy_with_mock_endpoint._normalize_keys_to_schema_names(
            parsed, schemas
        )
        assert out == {"task_success": "success"}


class TestProcessRewardFormatting:
    """Verify the wire format for process_reward (PRM) annotations."""

    @pytest.fixture
    def coding_instance_5_steps(self):
        return {
            "instance_id": "prm_001",
            "data": {
                "task_description": "fix bug",
                "structured_turns": [
                    {"role": "user", "content": "fix"},
                    {"role": "assistant", "content": "thinking"},
                    {"role": "assistant", "content": "edit"},
                    {"role": "assistant", "content": "test"},
                    {"role": "assistant", "content": "done"},
                ],
            },
        }

    @pytest.fixture
    def first_error_schema(self):
        return {
            "name": "step_rewards",
            "annotation_type": "process_reward",
            "steps_key": "structured_turns",
            "mode": "first_error",
        }

    @pytest.fixture
    def per_step_schema(self):
        return {
            "name": "step_rewards",
            "annotation_type": "process_reward",
            "steps_key": "structured_turns",
            "mode": "per_step",
        }

    def test_first_error_marks_index_and_after_wrong(
        self, strategy_with_mock_endpoint, first_error_schema, coding_instance_5_steps
    ):
        out = strategy_with_mock_endpoint._format_value(
            "step_rewards", 2, "process_reward", [], first_error_schema,
            instance=coding_instance_5_steps,
        )
        # Wire format: single key with ::: and JSON-encoded value
        assert list(out.keys()) == ["step_rewards:::step_rewards"]
        payload = json.loads(out["step_rewards:::step_rewards"])
        assert payload["mode"] == "first_error"
        rewards = [s["reward"] for s in payload["steps"]]
        assert rewards == [1, 1, -1, -1, -1]
        assert [s["index"] for s in payload["steps"]] == [0, 1, 2, 3, 4]

    def test_first_error_none_means_all_correct(
        self, strategy_with_mock_endpoint, first_error_schema, coding_instance_5_steps
    ):
        out = strategy_with_mock_endpoint._format_value(
            "step_rewards", None, "process_reward", [], first_error_schema,
            instance=coding_instance_5_steps,
        )
        payload = json.loads(out["step_rewards:::step_rewards"])
        assert all(s["reward"] == 1 for s in payload["steps"])

    def test_first_error_dict_with_index_key_unwrapped(
        self, strategy_with_mock_endpoint, first_error_schema, coding_instance_5_steps
    ):
        out = strategy_with_mock_endpoint._format_value(
            "step_rewards", {"index": 1}, "process_reward", [], first_error_schema,
            instance=coding_instance_5_steps,
        )
        payload = json.loads(out["step_rewards:::step_rewards"])
        rewards = [s["reward"] for s in payload["steps"]]
        assert rewards == [1, -1, -1, -1, -1]

    def test_first_error_string_null_treated_as_all_correct(
        self, strategy_with_mock_endpoint, first_error_schema, coding_instance_5_steps
    ):
        out = strategy_with_mock_endpoint._format_value(
            "step_rewards", "null", "process_reward", [], first_error_schema,
            instance=coding_instance_5_steps,
        )
        payload = json.loads(out["step_rewards:::step_rewards"])
        assert all(s["reward"] == 1 for s in payload["steps"])

    def test_first_error_clamps_out_of_range(
        self, strategy_with_mock_endpoint, first_error_schema, coding_instance_5_steps
    ):
        out = strategy_with_mock_endpoint._format_value(
            "step_rewards", 99, "process_reward", [], first_error_schema,
            instance=coding_instance_5_steps,
        )
        payload = json.loads(out["step_rewards:::step_rewards"])
        rewards = [s["reward"] for s in payload["steps"]]
        # Last step (index 4) is the first wrong one
        assert rewards == [1, 1, 1, 1, -1]

    def test_per_step_list_of_ints(
        self, strategy_with_mock_endpoint, per_step_schema, coding_instance_5_steps
    ):
        out = strategy_with_mock_endpoint._format_value(
            "step_rewards", [1, 1, -1, 0, 1], "process_reward", [],
            per_step_schema, instance=coding_instance_5_steps,
        )
        payload = json.loads(out["step_rewards:::step_rewards"])
        assert payload["mode"] == "per_step"
        assert [s["reward"] for s in payload["steps"]] == [1, 1, -1, 0, 1]

    def test_per_step_list_of_strings(
        self, strategy_with_mock_endpoint, per_step_schema, coding_instance_5_steps
    ):
        out = strategy_with_mock_endpoint._format_value(
            "step_rewards",
            ["correct", "correct", "wrong", "unmarked", "good"],
            "process_reward", [], per_step_schema,
            instance=coding_instance_5_steps,
        )
        payload = json.loads(out["step_rewards:::step_rewards"])
        assert [s["reward"] for s in payload["steps"]] == [1, 1, -1, 0, 1]

    def test_per_step_pads_short_list(
        self, strategy_with_mock_endpoint, per_step_schema, coding_instance_5_steps
    ):
        out = strategy_with_mock_endpoint._format_value(
            "step_rewards", [1, -1], "process_reward", [], per_step_schema,
            instance=coding_instance_5_steps,
        )
        payload = json.loads(out["step_rewards:::step_rewards"])
        # Pads with 0 (unmarked) to 5 entries
        assert [s["reward"] for s in payload["steps"]] == [1, -1, 0, 0, 0]

    def test_no_steps_returns_none(
        self, strategy_with_mock_endpoint, first_error_schema
    ):
        instance = {"instance_id": "x", "data": {}}
        out = strategy_with_mock_endpoint._format_value(
            "step_rewards", 0, "process_reward", [], first_error_schema,
            instance=instance,
        )
        assert out is None


class TestCodeReviewFormatting:
    """Verify the wire format for code_review annotations."""

    @pytest.fixture
    def review_schema(self):
        return {
            "name": "review",
            "annotation_type": "code_review",
            "verdict_options": ["approve", "request_changes", "comment_only"],
            "comment_categories": ["bug", "style", "suggestion", "security", "question"],
            "file_rating_dimensions": ["correctness", "readability", "maintainability"],
        }

    def test_full_review_payload(
        self, strategy_with_mock_endpoint, review_schema
    ):
        raw = {
            "verdict": "request_changes",
            "comments": [
                {"file": "auth.py", "line": 42, "category": "security",
                 "body": "Missing input validation"},
                {"file": "auth.py", "category": "style", "body": "Use snake_case"},
            ],
            "file_ratings": {
                "auth.py": {"correctness": 2, "readability": 4, "maintainability": 3},
            },
        }
        out = strategy_with_mock_endpoint._format_value(
            "review", raw, "code_review", [], review_schema,
        )
        assert list(out.keys()) == ["review:::review"]
        payload = json.loads(out["review:::review"])
        assert payload["verdict"] == "request_changes"
        assert len(payload["comments"]) == 2
        assert payload["comments"][0]["file"] == "auth.py"
        assert payload["comments"][0]["line"] == 42
        assert payload["comments"][0]["category"] == "security"
        assert payload["file_ratings"]["auth.py"]["correctness"] == 2

    def test_unknown_category_falls_back_to_first(
        self, strategy_with_mock_endpoint, review_schema
    ):
        raw = {
            "verdict": "approve",
            "comments": [{"file": "a.py", "category": "nonsense", "body": "nit"}],
        }
        out = strategy_with_mock_endpoint._format_value(
            "review", raw, "code_review", [], review_schema,
        )
        payload = json.loads(out["review:::review"])
        assert payload["comments"][0]["category"] == "bug"  # first option

    def test_unknown_file_rating_dim_dropped(
        self, strategy_with_mock_endpoint, review_schema
    ):
        raw = {
            "verdict": "approve",
            "file_ratings": {"a.py": {"correctness": 5, "made_up_dim": 3}},
        }
        out = strategy_with_mock_endpoint._format_value(
            "review", raw, "code_review", [], review_schema,
        )
        payload = json.loads(out["review:::review"])
        assert payload["file_ratings"]["a.py"] == {"correctness": 5}

    def test_string_response_treated_as_verdict(
        self, strategy_with_mock_endpoint, review_schema
    ):
        out = strategy_with_mock_endpoint._format_value(
            "review", "approve", "code_review", [], review_schema,
        )
        payload = json.loads(out["review:::review"])
        assert payload["verdict"] == "approve"
        assert payload["comments"] == []

    def test_unknown_verdict_falls_back_to_comment_only(
        self, strategy_with_mock_endpoint, review_schema
    ):
        out = strategy_with_mock_endpoint._format_value(
            "review", "lgtm", "code_review", [], review_schema,
        )
        payload = json.loads(out["review:::review"])
        assert payload["verdict"] == "comment_only"


class TestEndToEndWithMockEndpoint:
    def test_batches_one_call_for_two_schemas(
        self, strategy_with_mock_endpoint, agent_trace_instance, schemas
    ):
        # Mock endpoint returns one response covering both schemas
        strategy_with_mock_endpoint.endpoint.query.return_value = _AgentLabelResponse(
            annotations={"task_success": "success", "efficiency": 4},
            reasoning="ok",
        )
        # Only the text-only path is reachable since there are no images
        comp = PerfectCompetence()

        ann1 = strategy_with_mock_endpoint.generate_annotation(
            agent_trace_instance, schemas[0], comp, None
        )
        ann2 = strategy_with_mock_endpoint.generate_annotation(
            agent_trace_instance, schemas[1], comp, None
        )

        assert ann1 == {"task_success:success": "on"}
        assert ann2 == {"efficiency:4": "on"}
        # Cache means only one LLM call
        assert strategy_with_mock_endpoint.endpoint.query.call_count == 1

    def test_endpoint_failure_returns_random_fallback(
        self, strategy_with_mock_endpoint, agent_trace_instance, schemas
    ):
        strategy_with_mock_endpoint.endpoint.query.side_effect = RuntimeError("boom")
        comp = PerfectCompetence()
        ann = strategy_with_mock_endpoint.generate_annotation(
            agent_trace_instance, schemas[0], comp, None
        )
        # Random strategy still returns *something* for radio with labels
        assert ann
        assert any(k.startswith("task_success:") for k in ann.keys())

    def test_no_schemas_attached_falls_back(self, strategy_with_mock_endpoint):
        instance = {"instance_id": "x", "data": {"text": "hi"}}
        comp = PerfectCompetence()
        schema = {"name": "label", "annotation_type": "radio", "labels": ["a", "b"]}
        ann = strategy_with_mock_endpoint.generate_annotation(instance, schema, comp, None)
        assert ann  # falls back to random
        # No LLM call attempted (returns None from _get_or_query)
        strategy_with_mock_endpoint.endpoint.query.assert_not_called()
