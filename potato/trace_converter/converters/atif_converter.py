"""
ATIF (Agent Trace Interchange Format) Converter

Converts traces in the academic ATIF standard format to Potato's
canonical format.

Expected input format:
{
    "trace_id": "trace_001",
    "task": {"description": "Book a flight...", "domain": "travel"},
    "agent": {"name": "ReAct-GPT4", "model": "gpt-4"},
    "steps": [
        {
            "step_id": 1,
            "thought": "I need to search for flights...",
            "action": {"tool": "search_flights", "params": {"origin": "JFK"}},
            "observation": "Found 5 flights...",
            "timestamp": "2024-01-01T00:00:00Z"
        }
    ],
    "outcome": {"success": true, "reward": 1.0},
    "metrics": {"total_steps": 7, "total_tokens": 2340}
}
"""

from typing import Any, Dict, List, Optional

from ..base import BaseTraceConverter, CanonicalTrace


class ATIFConverter(BaseTraceConverter):
    """Converter for ATIF (Agent Trace Interchange Format) traces."""

    format_name = "atif"
    description = "Agent Trace Interchange Format (academic standard)"
    file_extensions = [".json", ".jsonl"]

    def convert(self, data: Any, options: Optional[Dict] = None) -> List[CanonicalTrace]:
        options = options or {}
        traces = data if isinstance(data, list) else [data]
        results = []

        for item in traces:
            trace_id = item.get("trace_id", item.get("id", f"trace_{len(results)}"))
            task = item.get("task") or {}
            agent = item.get("agent") or {}
            steps = item.get("steps") or []
            outcome = item.get("outcome") or {}
            metrics = item.get("metrics") or {}

            task_desc = task.get("description", "") if isinstance(task, dict) else str(task)
            agent_name = agent.get("name", "") if isinstance(agent, dict) else str(agent)

            # Build conversation
            conversation = []
            for step in steps:
                if "thought" in step and step["thought"]:
                    conversation.append({
                        "speaker": "Agent (Thought)",
                        "text": step["thought"]
                    })
                if "action" in step:
                    action = step["action"]
                    if isinstance(action, dict):
                        tool = action.get("tool", action.get("name", ""))
                        params = action.get("params", action.get("parameters", {}))
                        if params:
                            args = ", ".join(f"{k}={repr(v)}" for k, v in params.items())
                            action_text = f"{tool}({args})"
                        else:
                            action_text = f"{tool}()"
                    else:
                        action_text = str(action)
                    conversation.append({
                        "speaker": "Agent (Action)",
                        "text": action_text
                    })
                if "observation" in step and step["observation"]:
                    conversation.append({
                        "speaker": "Environment",
                        "text": str(step["observation"])
                    })

            # Build metadata table
            metadata_table = [
                {"Property": "Steps", "Value": str(len(steps))},
            ]
            if isinstance(agent, dict) and "model" in agent:
                metadata_table.append({"Property": "Model", "Value": agent["model"]})
            if isinstance(task, dict) and "domain" in task:
                metadata_table.append({"Property": "Domain", "Value": task["domain"]})
            if outcome:
                if "success" in outcome:
                    metadata_table.append({
                        "Property": "Success",
                        "Value": str(outcome["success"])
                    })
                if "reward" in outcome:
                    metadata_table.append({
                        "Property": "Reward",
                        "Value": str(outcome["reward"])
                    })
            for key, value in metrics.items():
                metadata_table.append({"Property": key, "Value": str(value)})

            trace = CanonicalTrace(
                id=trace_id,
                task_description=task_desc,
                conversation=conversation,
                agent_name=agent_name,
                metadata_table=metadata_table,
            )
            results.append(trace)

        return results

    def detect(self, data: Any) -> bool:
        items = data if isinstance(data, list) else [data]
        if not items:
            return False
        first = items[0]
        if not isinstance(first, dict):
            return False
        # ATIF has "trace_id" and structured "task" and "agent" fields
        has_trace_id = "trace_id" in first
        has_structured_task = isinstance(first.get("task"), dict)
        has_structured_agent = isinstance(first.get("agent"), dict)
        has_steps = isinstance(first.get("steps"), list)
        return has_trace_id and has_steps and (has_structured_task or has_structured_agent)
