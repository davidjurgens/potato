"""Unit tests for InteractiveSessionRunner.

Uses MagicMock-backed ``requests.Session`` and a stub persona endpoint so
the tests run without a server or LLM.
"""
from unittest.mock import MagicMock

import pytest

from potato.simulator.config import InteractiveConfig
from potato.simulator.interactive_runner import InteractiveSessionRunner


@pytest.fixture
def runner():
    cfg = InteractiveConfig(
        enabled=True,
        endpoint_type="ollama",
        model="llama3.2",
        max_turns=4,
        first_message_template="TASK: {task}",
        done_marker="[DONE]",
    )
    r = InteractiveSessionRunner(cfg, "http://localhost:9999")
    # Skip real endpoint creation
    r._endpoint = MagicMock()
    return r


def _agent_reply(content):
    """Build a 200 response object the runner expects from /agent_chat/send."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"content": content, "role": "agent"}
    return resp


def _ok_finish():
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"success": True, "message_count": 4}
    return resp


class TestInteractiveSessionRunner:
    def test_first_message_uses_template_no_llm_call(self, runner):
        # Persona endpoint will only be called for turns 2+
        runner._endpoint.chat_query.return_value = "Sure, please proceed. [DONE]"

        session = MagicMock()
        session.post.side_effect = [
            _agent_reply("Hi! I can help with that."),
            _agent_reply("All done."),
            _ok_finish(),
        ]

        result = runner.run(session, "inst_1", "Find me a flight")
        # First user turn should be the templated message; chat_query should
        # be called exactly once (for turn 2)
        runner._endpoint.chat_query.assert_called_once()
        assert result.completed is True
        assert result.turns == 2
        assert result.conversation[0]["speaker"] == "User"
        assert result.conversation[0]["text"] == "TASK: Find me a flight"
        assert result.conversation[1]["speaker"] == "Agent"
        assert result.conversation[1]["text"] == "Hi! I can help with that."

    def test_done_marker_finishes_after_current_turn(self, runner):
        runner._endpoint.chat_query.return_value = "Great, thanks! [DONE]"
        session = MagicMock()
        session.post.side_effect = [
            _agent_reply("Done!"),
            _agent_reply("You're welcome."),
            _ok_finish(),
        ]
        result = runner.run(session, "x", "task")
        assert result.completed is True
        # We should have sent two user messages (templated + done) and gotten
        # two agent replies, then called finish.
        post_calls = session.post.call_args_list
        assert len(post_calls) == 3
        finish_url = post_calls[-1].args[0]
        assert finish_url.endswith("/agent_chat/finish")

    def test_max_turns_terminates_chat(self, runner):
        runner._endpoint.chat_query.return_value = "And then?"
        session = MagicMock()
        # Always return successful agent replies for max_turns iterations
        session.post.side_effect = (
            [_agent_reply(f"reply {i}") for i in range(runner.config.max_turns)]
            + [_ok_finish()]
        )

        result = runner.run(session, "x", "task")
        assert result.completed is True
        assert result.turns == runner.config.max_turns

    def test_persona_failure_breaks_loop_and_finishes(self, runner):
        # First message is templated and succeeds
        # Subsequent persona calls return None (LLM failure)
        runner._endpoint.chat_query.return_value = ""
        session = MagicMock()
        session.post.side_effect = [
            _agent_reply("First reply"),
            _ok_finish(),
        ]

        result = runner.run(session, "x", "task")
        assert result.error is not None
        assert "persona produced no message" in result.error
        # Finish was still attempted
        assert session.post.call_args_list[-1].args[0].endswith("/agent_chat/finish")

    def test_agent_send_failure_breaks_loop_and_finishes(self, runner):
        bad_resp = MagicMock()
        bad_resp.status_code = 400
        bad_resp.text = "boom"
        session = MagicMock()
        session.post.side_effect = [
            bad_resp,
            _ok_finish(),
        ]

        result = runner.run(session, "x", "task")
        assert result.error is not None
        assert "agent send failed" in result.error

    def test_strips_done_marker_before_sending(self, runner):
        runner._endpoint.chat_query.return_value = "All set [DONE]"
        session = MagicMock()
        session.post.side_effect = [
            _agent_reply("ack"),
            _agent_reply("ack 2"),
            _ok_finish(),
        ]

        runner.run(session, "x", "task")
        # The second agent_chat/send call was the persona's "all set"
        # message; the [DONE] marker must not appear in the payload.
        send_calls = [c for c in session.post.call_args_list
                      if c.args[0].endswith("/agent_chat/send")]
        assert len(send_calls) == 2
        second_payload = send_calls[1].kwargs["json"]
        assert "[DONE]" not in second_payload["message"]
