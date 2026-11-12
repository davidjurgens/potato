"""
Reading Claude Code's own session transcripts.

The converter named `claude_code` read the Anthropic Messages API shape, not
the JSONL Claude Code writes to ~/.claude/projects. Against a real 1369-line
session it returned ``detect() == False`` and then converted it into 50 empty
traces without raising: point it at a session and you got one blank annotation
item per line.

It passed its tests because the fixtures were written from the converter's own
docstring, so they matched it by construction — the same mistake as building an
exporter's fixture by hand instead of from what the client emits, one layer up.

So the fixture here (tests/data/claude_code_session.jsonl) is shaped from a real
transcript: the record types, the field names, the nesting, the empty
``thinking`` blocks, the tool_result-as-user-message convention, the sidechain
flag and a genuine rewind branch. TestAgainstARealTranscript then runs the same
reader over whatever real sessions exist on the machine, and skips when there
are none.
"""

import json
from pathlib import Path

import pytest

from potato.trace_converter.converters.claude_code_session import (
    count_thinking_blocks,
    first_user_prompt,
    is_command_envelope,
    looks_like_session_transcript,
    parse_sessions,
    to_messages,
    _live_chain,
)
from potato.trace_converter.registry import converter_registry

FIXTURE = Path(__file__).resolve().parents[1] / "data" / "claude_code_session.jsonl"
REAL_TRANSCRIPTS = sorted(Path.home().glob(".claude/projects/*/*.jsonl"))


@pytest.fixture(scope="module")
def rows():
    return [json.loads(line) for line in FIXTURE.read_text().splitlines() if line.strip()]


@pytest.fixture(scope="module")
def converter():
    return converter_registry.get("claude_code")


class TestDetection:
    def test_a_real_transcript_is_recognised(self, rows, converter):
        """The regression: this returned False for its own format."""
        assert looks_like_session_transcript(rows) is True
        assert converter.detect(rows) is True

    def test_the_messages_api_shape_is_not_mistaken_for_one(self, converter):
        api_payload = {
            "id": "msg_abc",
            "model": "claude-sonnet-4",
            "messages": [{"role": "user", "content": "hi"}],
        }
        assert looks_like_session_transcript(api_payload) is False
        # …and is still handled by the converter's original path.
        assert converter.convert(api_payload)[0].id == "msg_abc"

    def test_bookkeeping_alone_is_not_a_transcript(self):
        assert looks_like_session_transcript(
            [{"type": "file-history-snapshot", "messageId": "m"}]) is False

    def test_empty_input(self):
        assert looks_like_session_transcript([]) is False
        assert looks_like_session_transcript(None) is False


class TestTheLiveChain:
    def test_abandoned_branches_are_left_out(self, rows):
        """A rewind leaves the abandoned attempt in the file, with its own
        parent links. Reading the file as a flat list would replay `rm -rf
        build` as though the session had run it."""
        chain_uuids = [r.get("uuid") for r in _live_chain(rows)]
        assert "a_dead" not in chain_uuids
        assert ["u0", "u1", "a1", "u2", "a2", "u3", "a3"] == chain_uuids

    def test_the_surviving_path_is_in_order(self, rows):
        chain = _live_chain(rows)
        stamps = [r["timestamp"] for r in chain]
        assert stamps == sorted(stamps)

    def test_a_cycle_does_not_hang(self):
        looped = [
            {"type": "user", "uuid": "x", "parentUuid": "y", "sessionId": "s",
             "message": {"role": "user", "content": "a"}},
            {"type": "assistant", "uuid": "y", "parentUuid": "x", "sessionId": "s",
             "message": {"role": "assistant", "content": []}},
        ]
        assert len(_live_chain(looped)) <= 2


class TestMessageExtraction:
    def test_cli_injected_rows_are_not_user_turns(self, rows):
        """`/clear` and its output are the CLI talking to itself."""
        messages = to_messages(_live_chain(rows))
        assert not any("command-name" in str(m["content"]) for m in messages)

    def test_tool_results_stay_attached_to_their_call(self, rows):
        session = parse_sessions(rows)[0]
        traces = converter_registry.get("claude_code").convert(rows)
        turns = traces[0].extra_fields["structured_turns"]
        calls = [tc for turn in turns for tc in turn.get("tool_calls", [])]
        by_tool = {c["tool"]: c for c in calls}
        assert by_tool["Read"]["output"].startswith("def test_login()")
        assert "has been updated" in by_tool["Edit"]["output"]
        assert session["messages"]

    def test_the_task_is_the_request_not_the_slash_command(self, rows):
        assert first_user_prompt(_live_chain(rows)) == "Fix the failing auth test."

    def test_command_envelopes_are_recognised(self):
        assert is_command_envelope("<command-name>/clear</command-name>")
        assert is_command_envelope("<local-command-stdout>ok</local-command-stdout>")
        assert not is_command_envelope("please run /clear on the cache")


class TestConversion:
    def test_a_session_is_one_trace_not_one_per_line(self, rows, converter):
        traces = converter.convert(rows)
        assert len(traces) == 1
        assert traces[0].id == "sess-fixture-1"

    def test_the_trace_is_not_empty(self, rows, converter):
        trace = converter.convert(rows)[0]
        assert trace.extra_fields["structured_turns"]
        assert trace.conversation
        assert trace.agent_name == "claude-opus-5"

    def test_an_unreadable_transcript_raises_instead_of_going_quiet(self, converter):
        """The worst part of the original bug was not that it failed."""
        headless = [{"type": "user", "uuid": "u1", "sessionId": "s1",
                     "parentUuid": None, "message": None}]
        # Detected as a transcript (uuid + sessionId + conversation type)…
        assert looks_like_session_transcript(headless) is True
        with pytest.raises(ValueError, match="no user or assistant messages"):
            converter.convert(headless)

    def test_tool_calls_are_enriched_for_the_display(self, rows, converter):
        turns = converter.convert(rows)[0].extra_fields["structured_turns"]
        calls = {tc["tool"]: tc for turn in turns
                 for tc in turn.get("tool_calls", [])}
        assert calls["Edit"]["output_type"] == "diff"
        assert calls["Read"]["language"] == "python"


class TestMetadata:
    def test_session_provenance_is_carried_through(self, rows, converter):
        table = {r["Property"]: r["Value"]
                 for r in converter.convert(rows)[0].metadata_table}
        assert table["Session"] == "sess-fixture-1"
        assert table["Working directory"] == "/repo"
        assert table["Git branch"] == "master"
        assert table["Claude Code version"] == "2.1.233"
        assert table["Model"] == "claude-opus-5"

    def test_token_usage_is_summed(self, rows, converter):
        table = {r["Property"]: r["Value"]
                 for r in converter.convert(rows)[0].metadata_table}
        assert table["Input tokens"] == "62"          # 12 + 20 + 30
        assert table["Cache read tokens"] == "2100"   # 900 + 1200

    def test_dropped_branch_messages_are_reported_not_hidden(self, rows, converter):
        table = {r["Property"]: r["Value"]
                 for r in converter.convert(rows)[0].metadata_table}
        assert table["Messages on abandoned branches"] == "1"

    def test_thinking_is_counted_and_its_absence_is_stated(self, rows, converter):
        """The CLI writes the thinking block and drops the thinking.

        Checked across 40 local sessions: 6393 thinking blocks, none with any
        text. Reporting the count keeps that visible instead of leaving people
        to conclude the model never reasoned.
        """
        assert count_thinking_blocks(rows) == 1
        table = {r["Property"]: r["Value"]
                 for r in converter.convert(rows)[0].metadata_table}
        assert table["Thinking blocks (text not persisted by the CLI)"] == "1"


class TestSubAgents:
    def test_sidechain_work_is_kept_separate(self, rows, converter):
        """A sub-agent's messages are another agent's transcript; folding them
        in would attribute its tool calls to the session's own turns."""
        trace = converter.convert(rows)[0]
        main_tools = [tc["tool"] for turn in trace.extra_fields["structured_turns"]
                      for tc in turn.get("tool_calls", [])]
        assert "Grep" not in main_tools

        runs = trace.extra_fields["sidechain_runs"]
        assert len(runs) == 1
        side_tools = [tc["tool"] for turn in runs[0]["structured_turns"]
                      for tc in turn.get("tool_calls", [])]
        assert side_tools == ["Grep"]

    def test_the_run_count_is_reported(self, rows, converter):
        table = {r["Property"]: r["Value"]
                 for r in converter.convert(rows)[0].metadata_table}
        assert table["Sub-agent runs"] == "1"


@pytest.mark.skipif(not REAL_TRANSCRIPTS,
                    reason="no Claude Code transcripts on this machine")
class TestAgainstARealTranscript:
    """The fixture is a model of the format; this is the format itself.

    Runs over the local session files, which is the only way to notice that the
    CLI's on-disk shape has moved. Skipped where there are none, so CI without
    Claude Code installed is unaffected.
    """

    @pytest.fixture(scope="class")
    def sample(self):
        # The largest few: small ones can be a single aborted prompt.
        biggest = sorted(REAL_TRANSCRIPTS,
                         key=lambda p: p.stat().st_size, reverse=True)[:3]
        loaded = []
        for path in biggest:
            rows = []
            for line in path.read_text(errors="replace").splitlines():
                if line.strip():
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass        # a half-written last line while a session runs
            if rows:
                loaded.append(rows)
        if not loaded:
            pytest.skip("no readable transcripts")
        return loaded

    def test_real_sessions_are_detected(self, sample, converter):
        for rows in sample:
            assert converter.detect(rows) is True

    def test_real_sessions_convert_to_something(self, sample, converter):
        for rows in sample:
            traces = converter.convert(rows)
            assert traces
            for trace in traces:
                assert trace.extra_fields["structured_turns"], (
                    f"{trace.id} converted to an empty trace")

    def test_tool_calls_keep_their_outputs(self, sample, converter):
        """Pairing tool_use to tool_result across rows is the part most likely
        to break quietly if the CLI changes how it stores results."""
        matched = unmatched = 0
        for rows in sample:
            for trace in converter.convert(rows):
                for turn in trace.extra_fields["structured_turns"]:
                    for call in turn.get("tool_calls", []):
                        if call.get("output"):
                            matched += 1
                        else:
                            unmatched += 1
        if matched + unmatched == 0:
            pytest.skip("no tool calls in the sampled sessions")
        assert matched > unmatched, (
            f"only {matched} of {matched + unmatched} tool calls kept an output")
