"""
Unit tests for Phase B multi-agent identity + discussion support:

- multi_agent converter populates agent_id / addressee / step_type and the
  agents roster (regression: AutoGen receiver used to be dropped)
- multi_agent_discussion display: legend, colors, addressee chips, reply
  threading, turn-level slots, span-target contract
- consensus_tracking schema layout basics
"""

from potato.trace_converter.converters.multi_agent_converter import MultiAgentConverter
from potato.server_utils.displays.multi_agent_discussion_display import (
    MultiAgentDiscussionDisplay, agent_color, AGENT_PALETTE,
)


class TestMultiAgentConverterIdentity:
    def test_autogen_populates_agent_id_and_addressee(self):
        """Regression: receiver was read but dropped from turns."""
        trace = {
            "id": "ag1",
            "task": "solve",
            "messages": [
                {"sender": "user_proxy", "receiver": "assistant", "content": "solve 2+2"},
                {"sender": "assistant", "receiver": "user_proxy", "content": "4"},
            ],
        }
        result = MultiAgentConverter().convert(trace)[0]
        turns = result.conversation
        assert turns[0]["agent_id"] == "user_proxy"
        assert turns[0]["addressee"] == "assistant"
        assert turns[1]["agent_id"] == "assistant"
        assert turns[1]["addressee"] == "user_proxy"
        roster = result.extra_fields["agents"]
        assert {a["id"] for a in roster} == {"user_proxy", "assistant"}
        # Speaker strings unchanged (display back-compat)
        assert turns[0]["speaker"] == "User (user_proxy)"

    def test_crewai_populates_agent_id_and_step_type(self):
        trace = {
            "id": "c1",
            "task": "report",
            "agents": [{"role": "Researcher", "goal": "find"},
                       {"role": "Writer", "goal": "write"}],
            "steps": [
                {"agent": "Researcher", "thought": "look", "action": "search()",
                 "result": "found"},
            ],
        }
        result = MultiAgentConverter().convert(trace)[0]
        turns = result.conversation
        assert turns[0]["agent_id"] == "Researcher" and turns[0]["step_type"] == "thought"
        assert turns[1]["agent_id"] == "Researcher" and turns[1]["step_type"] == "action"
        assert turns[2]["step_type"] == "observation" and "agent_id" not in turns[2]
        roster = result.extra_fields["agents"]
        assert [a["id"] for a in roster] == ["Researcher", "Writer"]
        assert roster[0]["goal"] == "find"

    def test_langgraph_populates_agent_id_and_tool(self):
        trace = {
            "id": "lg1",
            "task": "run",
            "events": [
                {"node": "agent", "type": "on_chain_start", "data": {"input": "go"}},
                {"node": "tools", "type": "on_tool_start", "data": {"tool": "search", "input": "q"}},
                {"node": "tools", "type": "on_tool_end", "data": {"output": "res"}},
            ],
        }
        result = MultiAgentConverter().convert(trace)[0]
        turns = result.conversation
        assert turns[0]["agent_id"] == "agent"
        assert turns[1]["agent_id"] == "tools"
        assert turns[1]["tool"] == "search"
        assert turns[1]["step_type"] == "action"
        assert {a["id"] for a in result.extra_fields["agents"]} == {"agent", "tools"}

    def test_to_dict_preserves_identity_keys(self):
        trace = {
            "id": "ag2", "task": "t",
            "messages": [{"sender": "a", "receiver": "b", "content": "hi"}],
        }
        d = MultiAgentConverter().convert(trace)[0].to_dict()
        assert d["conversation"][0]["addressee"] == "b"
        assert d["agents"][0]["id"] in ("a", "b")


DISCUSSION = [
    {"speaker": "moderator", "text": "begin", "agent_id": "moderator",
     "addressee": "planner", "turn_id": "t0"},
    {"speaker": "planner", "text": "I propose X", "agent_id": "planner",
     "addressee": "moderator", "turn_id": "t1"},
    {"speaker": "critic", "text": "I disagree", "agent_id": "critic",
     "addressee": "planner", "turn_id": "t2", "reply_to": "t1"},
    {"speaker": "Environment", "text": "tool output"},
]


class TestMultiAgentDiscussionDisplay:
    def _render(self, field_config=None, data=DISCUSSION):
        cfg = {"key": "conversation"}
        cfg.update(field_config or {})
        return MultiAgentDiscussionDisplay().render(cfg, data)

    def test_legend_renders_one_chip_per_agent(self):
        out = self._render()
        assert out.count("mad-legend-chip") >= 3
        assert 'data-agent-id="planner"' in out
        assert 'data-agent-id="critic"' in out

    def test_turns_carry_agent_identity(self):
        out = self._render()
        assert 'class="mad-turn" data-agent-id="planner"' in out.replace("  ", " ") or \
            'data-agent-id="planner"' in out

    def test_addressee_chips(self):
        out = self._render()
        assert "mad-addressee" in out
        assert "&rarr; planner" in out

    def test_reply_threading(self):
        out = self._render()
        assert "mad-reply" in out
        assert "mad-reply-connector" in out

    def test_addressees_can_be_disabled(self):
        out = self._render({"display_options": {"show_addressees": False}})
        assert "mad-addressee" not in out

    def test_span_target_contract(self):
        out = self._render({"span_target": True})
        assert 'class="text-content" id="text-content-conversation"' in out
        # Canonical-text approach: NO data-original-text on the wrapper
        wrapper = out.split('id="text-content-conversation"')[1].split(">")[0]
        assert "data-original-text" not in wrapper

    def test_turn_slots_render(self):
        scheme = {
            "annotation_type": "likert", "name": "contribution",
            "description": "contribution", "size": 5,
            "turn_level": True,
            "turn_binding": {"agents": ["planner", "critic"]},
        }
        out = self._render({"_turn_schemes": [scheme]})
        assert out.count("turn-anno-slot") == 2  # planner + critic turns only

    def test_agent_color_deterministic(self):
        assert agent_color("planner") == agent_color("planner")
        assert agent_color("planner") in AGENT_PALETTE

    def test_speaker_fallback_when_no_agent_id(self):
        out = self._render(data=[{"speaker": "alice", "text": "hi"},
                                 {"speaker": "bob", "text": "yo"}])
        assert 'data-agent-id="alice"' in out and 'data-agent-id="bob"' in out

    def test_html_escaping(self):
        out = self._render(data=[{"speaker": "<script>x</script>", "text": "<b>y</b>"}])
        assert "<script>" not in out and "<b>y</b>" not in out

    def test_registered_in_display_registry(self):
        from potato.server_utils.displays import display_registry
        assert "multi_agent_discussion" in display_registry.get_supported_types()
        assert display_registry.type_supports_span_target("multi_agent_discussion")


class TestConsensusTrackingSchema:
    SCHEME = {
        "annotation_type": "consensus_tracking",
        "name": "discussion_acts",
        "description": "Tag the discussion structure",
        "turns_key": "conversation",
    }

    def test_layout_generates(self):
        from potato.server_utils.schemas.consensus_tracking import (
            generate_consensus_tracking_layout)
        html, keybindings = generate_consensus_tracking_layout(dict(self.SCHEME))
        assert keybindings == []
        assert "consensus-tracking-container" in html
        # Persistence contract: hidden annotation-input with schema attrs +
        # IIFE that seeds from the restored value before wiring events
        assert 'class="annotation-input consensus-tracking-input"' in html
        assert "restore()" in html or "_tags = restore" in html.replace(" ", "")

    def test_registered_in_schema_registry(self):
        from potato.server_utils.schemas.registry import schema_registry
        assert "consensus_tracking" in schema_registry.get_supported_types()

    def test_config_validation_accepts(self):
        from potato.server_utils.config_module import validate_single_annotation_scheme
        validate_single_annotation_scheme(dict(self.SCHEME), "t")

    def test_custom_acts(self):
        from potato.server_utils.schemas.consensus_tracking import (
            generate_consensus_tracking_layout)
        scheme = dict(self.SCHEME)
        scheme["acts"] = ["offer", "counter", "accept"]
        scheme["linked_acts"] = ["counter", "accept"]
        html, _ = generate_consensus_tracking_layout(scheme)
        assert '"offer"' in html and '"counter"' in html
