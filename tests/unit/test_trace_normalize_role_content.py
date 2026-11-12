"""A trace in `{role, content}` form is parsed, not quietly shortened.

`{role, content}` is what an agent log is on disk and what every
chat-completions API returns. `normalize_steps` matched three shapes and had no
`else`, so such a turn fell off the end of the chain and disappeared: a
three-turn trace rendered two cards and a summary reading "2 steps", a
four-turn one rendered "No trace steps found". No exception, no log line.

The family did not agree with itself about this input, which is what makes it a
parser out of step rather than an unsupported format. `coding_trace` and
`audio_dialogue` parse it; `dialogue` and `multi_agent_discussion` render the
Python dict repr; `agent_trace`, `cot_trace` and `eval_trace` -- the three on
this normalizer -- dropped it. The mapping already existed in
`coding_trace_display._normalize_single_turn`.

Second-order, and the reason the silent drop is worse than a missing feature:
turn ids fall back to `t{index}` over the NORMALIZED sequence when the data
carries no id of its own. Dropping a turn shortens that sequence, so an
annotation saved on the third source turn is stored as `t1`, and anyone
indexing the source at 1 gets the turn that was dropped.
"""

import logging

import pytest

from potato.server_utils.displays._trace_normalize import (
    format_action_text, normalize_steps)


TRACE = [
    {"role": "user", "content": "Fix the auth bug."},
    {"role": "assistant", "content": "I need to read auth.py first."},
    {"role": "tool", "content": "opened auth.py, 210 lines"},
    {"role": "system", "content": "session started"},
]


class TestEveryTurnSurvives:

    def test_all_four_turns_are_parsed(self):
        steps = normalize_steps(TRACE)
        assert len(steps) == 4, (
            "a four-message role/content trace rendered 'No trace steps found'")

    def test_the_text_is_the_content(self):
        assert [s["text"] for s in normalize_steps(TRACE)] == [
            t["content"] for t in TRACE]

    def test_the_speaker_is_the_role(self):
        assert [s["speaker"] for s in normalize_steps(TRACE)] == [
            "user", "assistant", "tool", "system"]

    def test_position_is_preserved(self):
        """The whole point of the second-order finding: index N of the output
        must be source turn N, or positional turn ids point at the wrong
        message."""
        steps = normalize_steps(TRACE)
        assert steps[2]["text"] == TRACE[2]["content"]


class TestTheStepTypeIsUseful:
    """A chat role mostly does not name a step type, so a role that says
    nothing defers to the text."""

    @pytest.mark.parametrize("role,text,expected", [
        ("system", "session started", "system"),
        ("tool", "opened auth.py", "observation"),
        ("function", "returned 3", "observation"),
        ("assistant", "I need to read auth.py first.", "thought"),
        ("user", "Fix the auth bug.", "observation"),
    ])
    def test_type(self, role, text, expected):
        step = normalize_steps([{"role": role, "content": text}])[0]
        assert step["type"] == expected

    def test_an_explicit_step_type_wins(self):
        step = normalize_steps(
            [{"role": "user", "content": "x", "step_type": "error"}])[0]
        assert step["type"] == "error"


class TestTheOtherShapesAreUnchanged:
    """Format 4 sits last, so nothing that used to parse now parses
    differently."""

    def test_speaker_text_still_takes_format_1(self):
        step = normalize_steps(
            [{"speaker": "Thought", "text": "hm", "role": "assistant"}])[0]
        assert step["speaker"] == "Thought" and step["text"] == "hm"
        assert step["role"] == "assistant", "role is still passed through"

    def test_thought_action_observation_still_expands(self):
        steps = normalize_steps([{"thought": "a", "action": "b",
                                  "observation": "c"}])
        assert [s["type"] for s in steps] == ["thought", "action",
                                              "observation"]

    def test_step_type_content_still_parses(self):
        step = normalize_steps([{"step_type": "error", "content": "boom"}])[0]
        assert step["type"] == "error" and step["text"] == "boom"

    def test_a_bare_string_still_parses(self):
        assert normalize_steps(["just text"])[0]["text"] == "just text"


class TestContentBlocks:
    """`content` is a string or the API's list of typed blocks. A block list
    rendered with str() reaches the annotator as a Python repr."""

    def test_text_blocks_are_joined(self):
        step = normalize_steps([{"role": "assistant", "content": [
            {"type": "text", "text": "Let me check."},
            {"type": "text", "text": "Then patch it."}]}])[0]
        assert step["text"] == "Let me check.\nThen patch it."

    def test_a_tool_use_block_keeps_its_arguments(self):
        step = normalize_steps([{"role": "assistant", "content": [
            {"type": "tool_use", "name": "read_file",
             "input": {"path": "auth.py"}}]}])[0]
        assert "read_file" in step["text"] and "auth.py" in step["text"], (
            "the call named a file and the annotator saw read_file()")

    def test_no_repr_reaches_the_page(self):
        step = normalize_steps([{"role": "assistant", "content": [
            {"type": "text", "text": "hi"}]}])[0]
        assert "{'" not in step["text"] and "'type':" not in step["text"]

    def test_a_null_content_is_empty_not_the_word_none(self):
        step = normalize_steps([{"role": "assistant", "content": None}])[0]
        assert step["text"] == ""


class TestStructuredActionArguments:
    """`input` is the key a tool-use block uses; it was not in the lookup, so
    the arguments were dropped from every such action."""

    @pytest.mark.parametrize("key", ["params", "parameters", "input", "args",
                                     "arguments"])
    def test_every_spelling_keeps_the_arguments(self, key):
        rendered = format_action_text({"name": "read_file",
                                       key: {"path": "auth.py"}})
        assert rendered == "read_file(path='auth.py')"

    def test_no_arguments_still_renders_the_call(self):
        assert format_action_text({"tool": "noop"}) == "noop()"

    def test_a_string_action_is_unchanged(self):
        assert format_action_text("ran the thing") == "ran the thing"


class TestAnUnparseableTurnIsNamed:

    def test_it_warns_with_the_index_and_the_keys(self, caplog):
        with caplog.at_level(logging.WARNING):
            steps = normalize_steps([{"role": "user", "content": "ok"},
                                     {"wat": 1, "huh": 2}])
        assert len(steps) == 1
        message = " ".join(r.getMessage() for r in caplog.records)
        assert "1" in message and "huh" in message and "wat" in message, (
            "a dropped turn shortens the sequence and re-points every "
            "positional turn id after it; it cannot be silent")

    def test_a_fully_parseable_trace_says_nothing(self, caplog):
        with caplog.at_level(logging.WARNING):
            normalize_steps(TRACE)
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
