"""
Multi-Agent Converter (CrewAI / AutoGen / LangGraph)

Converts multi-agent orchestration traces to Potato's canonical format.
Auto-detects the sub-format based on structural markers.

Supported sub-formats:

1. CrewAI:
{
    "id": "crew_001",
    "task": "Research and write report",
    "agents": [
        {"role": "Researcher", "goal": "Find data"},
        {"role": "Writer", "goal": "Write report"}
    ],
    "steps": [
        {"agent": "Researcher", "thought": "...", "action": "...", "result": "..."},
        {"agent": "Writer", "thought": "...", "action": "...", "result": "..."}
    ]
}

2. AutoGen:
{
    "id": "autogen_001",
    "task": "Solve math problem",
    "messages": [
        {"sender": "user_proxy", "receiver": "assistant", "content": "..."},
        {"sender": "assistant", "receiver": "user_proxy", "content": "..."}
    ]
}

3. LangGraph:
{
    "id": "langgraph_001",
    "task": "Process request",
    "events": [
        {"node": "agent", "type": "on_chain_start", "data": {"input": "..."}},
        {"node": "tools", "type": "on_tool_start", "data": {"tool": "search"}},
        {"node": "tools", "type": "on_tool_end", "data": {"output": "..."}}
    ]
}
"""

from typing import Any, Dict, List, Optional

from ..base import BaseTraceConverter, CanonicalTrace


class MultiAgentConverter(BaseTraceConverter):
    """Converter for multi-agent traces (CrewAI, AutoGen, LangGraph)."""

    format_name = "multi_agent"
    description = "Multi-agent traces (CrewAI, AutoGen, LangGraph)"
    file_extensions = [".json", ".jsonl"]

    def convert(self, data: Any, options: Optional[Dict] = None) -> List[CanonicalTrace]:
        options = options or {}
        traces = data if isinstance(data, list) else [data]
        results = []

        for item in traces:
            sub_format = self._detect_sub_format(item)
            if sub_format == "crewai":
                results.append(self._convert_crewai(item, len(results)))
            elif sub_format == "autogen":
                results.append(self._convert_autogen(item, len(results)))
            elif sub_format == "langgraph":
                results.append(self._convert_langgraph(item, len(results)))
            else:
                # Fallback: try to convert generically
                results.append(self._convert_generic(item, len(results)))

        return results

    def _convert_crewai(self, item: dict, index: int) -> CanonicalTrace:
        """Convert a CrewAI trace."""
        trace_id = item.get("id", f"crewai_{index}")
        task = item.get("task", item.get("task_description", ""))
        agents = item.get("agents", [])
        steps = item.get("steps", [])

        conversation = []

        for step in steps:
            agent_name = step.get("agent", "Agent")
            thought = step.get("thought", "")
            action = step.get("action", "")
            result = step.get("result", step.get("observation", ""))

            if thought:
                conversation.append({
                    "speaker": f"{agent_name} (Thought)",
                    "text": thought
                })
            if action:
                conversation.append({
                    "speaker": f"{agent_name} (Action)",
                    "text": action
                })
            if result:
                conversation.append({
                    "speaker": "Environment",
                    "text": result
                })

        # Build metadata
        metadata_table = [
            {"Property": "Framework", "Value": "CrewAI"},
            {"Property": "Agents", "Value": str(len(agents))},
            {"Property": "Steps", "Value": str(len(steps))},
        ]
        for agent in agents:
            if isinstance(agent, dict):
                role = agent.get("role", "")
                goal = agent.get("goal", "")
                if role:
                    metadata_table.append({
                        "Property": f"Agent: {role}",
                        "Value": goal
                    })

        agent_names = ", ".join(
            a.get("role", "") for a in agents if isinstance(a, dict) and a.get("role")
        )

        return CanonicalTrace(
            id=trace_id,
            task_description=task,
            conversation=conversation,
            agent_name=agent_names or "CrewAI",
            metadata_table=metadata_table,
        )

    def _convert_autogen(self, item: dict, index: int) -> CanonicalTrace:
        """Convert an AutoGen trace."""
        trace_id = item.get("id", f"autogen_{index}")
        task = item.get("task", item.get("task_description", ""))
        messages = item.get("messages", [])

        conversation = []
        agents_seen = set()

        for msg in messages:
            sender = msg.get("sender", "Unknown")
            receiver = msg.get("receiver", "")
            content = msg.get("content", "")
            agents_seen.add(sender)
            if receiver:
                agents_seen.add(receiver)

            if not content:
                continue

            # Classify the speaker
            sender_lower = sender.lower()
            if "user" in sender_lower or "proxy" in sender_lower:
                speaker = f"User ({sender})"
            else:
                speaker = sender

            text = content if isinstance(content, str) else str(content)
            conversation.append({"speaker": speaker, "text": text})

            if not task and ("user" in sender_lower or "proxy" in sender_lower):
                task = text

        metadata_table = [
            {"Property": "Framework", "Value": "AutoGen"},
            {"Property": "Agents", "Value": str(len(agents_seen))},
            {"Property": "Messages", "Value": str(len(messages))},
        ]
        for agent in sorted(agents_seen):
            metadata_table.append({"Property": "Participant", "Value": agent})

        return CanonicalTrace(
            id=trace_id,
            task_description=task,
            conversation=conversation,
            agent_name=", ".join(sorted(agents_seen)),
            metadata_table=metadata_table,
        )

    def _convert_langgraph(self, item: dict, index: int) -> CanonicalTrace:
        """Convert a LangGraph trace."""
        trace_id = item.get("id", f"langgraph_{index}")
        task = item.get("task", item.get("task_description", ""))
        events = item.get("events", [])

        conversation = []
        nodes_seen = set()

        for event in events:
            node = event.get("node", "")
            event_type = event.get("type", "")
            event_data = event.get("data", {})

            if node:
                nodes_seen.add(node)

            if not isinstance(event_data, dict):
                continue

            if event_type in ("on_chain_start", "on_chain_end"):
                input_text = event_data.get("input", "")
                output_text = event_data.get("output", "")
                if input_text and event_type == "on_chain_start":
                    text = input_text if isinstance(input_text, str) else str(input_text)
                    if not task:
                        task = text
                    conversation.append({
                        "speaker": node or "Chain",
                        "text": text
                    })
                if output_text and event_type == "on_chain_end":
                    text = output_text if isinstance(output_text, str) else str(output_text)
                    conversation.append({
                        "speaker": node or "Chain",
                        "text": text
                    })

            elif event_type == "on_tool_start":
                tool = event_data.get("tool", event_data.get("name", ""))
                tool_input = event_data.get("input", "")
                text = f"{tool}({tool_input})" if tool else str(tool_input)
                conversation.append({
                    "speaker": f"{node} (Action)" if node else "Agent (Action)",
                    "text": text
                })

            elif event_type == "on_tool_end":
                output = event_data.get("output", "")
                if output:
                    conversation.append({
                        "speaker": "Environment",
                        "text": str(output)
                    })

            elif event_type in ("on_llm_start", "on_llm_end"):
                if event_type == "on_llm_end":
                    output = event_data.get("output", event_data.get("text", ""))
                    if output:
                        conversation.append({
                            "speaker": node or "Agent",
                            "text": str(output)
                        })

        metadata_table = [
            {"Property": "Framework", "Value": "LangGraph"},
            {"Property": "Nodes", "Value": str(len(nodes_seen))},
            {"Property": "Events", "Value": str(len(events))},
        ]
        for node_name in sorted(nodes_seen):
            metadata_table.append({"Property": "Node", "Value": node_name})

        return CanonicalTrace(
            id=trace_id,
            task_description=task,
            conversation=conversation,
            agent_name="LangGraph",
            metadata_table=metadata_table,
        )

    def _convert_generic(self, item: dict, index: int) -> CanonicalTrace:
        """Fallback generic conversion for unrecognized multi-agent sub-format."""
        trace_id = item.get("id", f"multi_agent_{index}")
        task = item.get("task", item.get("task_description", ""))

        return CanonicalTrace(
            id=trace_id,
            task_description=task or "Multi-agent trace",
            conversation=[],
            metadata_table=[{"Property": "Format", "Value": "unknown multi-agent"}],
        )

    def _detect_sub_format(self, item: dict) -> str:
        """Detect which multi-agent sub-format this item uses."""
        if not isinstance(item, dict):
            return ""

        # CrewAI: has agents list + steps with agent field
        if "agents" in item and isinstance(item.get("agents"), list):
            steps = item.get("steps", [])
            if isinstance(steps, list) and steps:
                if isinstance(steps[0], dict) and "agent" in steps[0]:
                    return "crewai"

        # AutoGen: messages with sender/receiver
        messages = item.get("messages", [])
        if isinstance(messages, list) and messages:
            first_msg = messages[0]
            if isinstance(first_msg, dict) and "sender" in first_msg:
                return "autogen"

        # LangGraph: events with node field
        events = item.get("events", [])
        if isinstance(events, list) and events:
            first_event = events[0]
            if isinstance(first_event, dict) and "node" in first_event:
                return "langgraph"

        return ""

    def detect(self, data: Any) -> bool:
        items = data if isinstance(data, list) else [data]
        if not items:
            return False
        first = items[0]
        if not isinstance(first, dict):
            return False

        sub_format = self._detect_sub_format(first)
        return sub_format != ""
