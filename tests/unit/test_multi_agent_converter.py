"""Tests for the Multi-Agent trace converter (CrewAI, AutoGen, LangGraph)."""

import pytest

from potato.trace_converter.converters.multi_agent_converter import MultiAgentConverter


class TestMultiAgentConverterDetect:
    """Detection tests for multi-agent formats."""

    def test_detect_crewai(self):
        converter = MultiAgentConverter()
        data = [{
            "id": "crew_001",
            "task": "Research and report",
            "agents": [{"role": "Researcher", "goal": "Find data"}],
            "steps": [{"agent": "Researcher", "thought": "...", "action": "search"}]
        }]
        assert converter.detect(data) is True

    def test_detect_autogen(self):
        converter = MultiAgentConverter()
        data = [{
            "id": "ag_001",
            "task": "Solve problem",
            "messages": [
                {"sender": "user_proxy", "receiver": "assistant", "content": "Hello"}
            ]
        }]
        assert converter.detect(data) is True

    def test_detect_langgraph(self):
        converter = MultiAgentConverter()
        data = [{
            "id": "lg_001",
            "events": [
                {"node": "agent", "type": "on_chain_start", "data": {"input": "test"}}
            ]
        }]
        assert converter.detect(data) is True

    def test_reject_openai_messages(self):
        """Messages with role (not sender) are not multi-agent."""
        converter = MultiAgentConverter()
        data = [{
            "messages": [
                {"role": "user", "content": "Hello"}
            ]
        }]
        assert converter.detect(data) is False

    def test_reject_react_steps(self):
        """Steps without agent field are not multi-agent (they're ReAct)."""
        converter = MultiAgentConverter()
        data = [{
            "steps": [{"thought": "...", "action": "...", "observation": "..."}]
        }]
        assert converter.detect(data) is False

    def test_reject_empty(self):
        converter = MultiAgentConverter()
        assert converter.detect([]) is False


class TestCrewAIConvert:
    """Conversion tests for CrewAI format."""

    def get_sample_crewai(self):
        return [{
            "id": "crew_001",
            "task": "Research and write a report on AI safety",
            "agents": [
                {"role": "Researcher", "goal": "Find relevant papers"},
                {"role": "Writer", "goal": "Write the report"}
            ],
            "steps": [
                {"agent": "Researcher", "thought": "I need to find papers on AI safety",
                 "action": "search_papers(query='AI safety')", "result": "Found 15 papers"},
                {"agent": "Researcher", "thought": "Let me summarize the top ones",
                 "action": "summarize(papers=top_5)", "result": "Summary ready"},
                {"agent": "Writer", "thought": "I have the summaries, let me write",
                 "action": "write_report(outline=True)", "result": "Draft completed"}
            ]
        }]

    def test_convert_crewai(self):
        converter = MultiAgentConverter()
        traces = converter.convert(self.get_sample_crewai())
        assert len(traces) == 1
        trace = traces[0]
        assert trace.id == "crew_001"
        assert "AI safety" in trace.task_description

    def test_crewai_speaker_names(self):
        converter = MultiAgentConverter()
        traces = converter.convert(self.get_sample_crewai())
        conv = traces[0].conversation
        # Speakers should include agent role names
        assert any("Researcher" in t["speaker"] for t in conv)
        assert any("Writer" in t["speaker"] for t in conv)

    def test_crewai_metadata(self):
        converter = MultiAgentConverter()
        traces = converter.convert(self.get_sample_crewai())
        meta = traces[0].metadata_table
        assert any(m["Property"] == "Framework" and m["Value"] == "CrewAI" for m in meta)
        assert any(m["Property"] == "Agents" and m["Value"] == "2" for m in meta)
        assert any(m["Property"] == "Steps" and m["Value"] == "3" for m in meta)


class TestAutoGenConvert:
    """Conversion tests for AutoGen format."""

    def get_sample_autogen(self):
        return [{
            "id": "autogen_001",
            "task": "Solve the equation x^2 + 5x + 6 = 0",
            "messages": [
                {"sender": "user_proxy", "receiver": "math_assistant",
                 "content": "Solve x^2 + 5x + 6 = 0"},
                {"sender": "math_assistant", "receiver": "user_proxy",
                 "content": "Using the quadratic formula: x = -2 or x = -3"},
                {"sender": "user_proxy", "receiver": "math_assistant",
                 "content": "Verify the answer"},
                {"sender": "math_assistant", "receiver": "user_proxy",
                 "content": "(-2)^2 + 5(-2) + 6 = 4 - 10 + 6 = 0. Verified."}
            ]
        }]

    def test_convert_autogen(self):
        converter = MultiAgentConverter()
        traces = converter.convert(self.get_sample_autogen())
        assert len(traces) == 1
        trace = traces[0]
        assert trace.id == "autogen_001"

    def test_autogen_speaker_identification(self):
        converter = MultiAgentConverter()
        traces = converter.convert(self.get_sample_autogen())
        conv = traces[0].conversation
        # user_proxy messages should have User prefix
        assert any("User" in t["speaker"] for t in conv)
        # math_assistant messages should use the agent name
        assert any("math_assistant" in t["speaker"] for t in conv)

    def test_autogen_metadata(self):
        converter = MultiAgentConverter()
        traces = converter.convert(self.get_sample_autogen())
        meta = traces[0].metadata_table
        assert any(m["Property"] == "Framework" and m["Value"] == "AutoGen" for m in meta)
        assert any(m["Property"] == "Messages" and m["Value"] == "4" for m in meta)


class TestLangGraphConvert:
    """Conversion tests for LangGraph format."""

    def get_sample_langgraph(self):
        return [{
            "id": "lg_001",
            "task": "Process user request",
            "events": [
                {"node": "agent", "type": "on_chain_start", "data": {"input": "Find me a restaurant"}},
                {"node": "tools", "type": "on_tool_start", "data": {"tool": "search_restaurants", "input": "near me"}},
                {"node": "tools", "type": "on_tool_end", "data": {"output": "Found 3 restaurants"}},
                {"node": "agent", "type": "on_llm_end", "data": {"output": "I found 3 restaurants nearby."}},
                {"node": "agent", "type": "on_chain_end", "data": {"output": "Here are your options..."}}
            ]
        }]

    def test_convert_langgraph(self):
        converter = MultiAgentConverter()
        traces = converter.convert(self.get_sample_langgraph())
        assert len(traces) == 1
        trace = traces[0]
        assert trace.id == "lg_001"

    def test_langgraph_conversation(self):
        converter = MultiAgentConverter()
        traces = converter.convert(self.get_sample_langgraph())
        conv = traces[0].conversation
        # Should have tool action, tool result, and agent output
        action_turns = [t for t in conv if "Action" in t["speaker"]]
        env_turns = [t for t in conv if t["speaker"] == "Environment"]
        assert len(action_turns) >= 1
        assert len(env_turns) >= 1

    def test_langgraph_metadata(self):
        converter = MultiAgentConverter()
        traces = converter.convert(self.get_sample_langgraph())
        meta = traces[0].metadata_table
        assert any(m["Property"] == "Framework" and m["Value"] == "LangGraph" for m in meta)
        assert any(m["Property"] == "Events" and m["Value"] == "5" for m in meta)

    def test_to_dict(self):
        converter = MultiAgentConverter()
        traces = converter.convert(self.get_sample_langgraph())
        d = traces[0].to_dict()
        assert "id" in d
        assert "conversation" in d
