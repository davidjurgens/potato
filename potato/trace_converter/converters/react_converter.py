"""
ReAct JSON Converter

Converts generic ReAct-format traces (thought/action/observation steps)
to Potato's canonical format.

Expected input format:
{
    "id": "trace_001",
    "task": "Book a flight...",
    "steps": [
        {"thought": "I need to...", "action": "search(...)", "observation": "Found..."},
        ...
    ],
    "metadata": {"agent": "GPT-4", "tokens": 2340}
}
"""

from typing import Any, Dict, List, Optional

from ..base import BaseTraceConverter, CanonicalTrace


class ReActConverter(BaseTraceConverter):
    """Converter for generic ReAct JSON traces."""

    format_name = "react"
    description = "Generic ReAct JSON format (thought/action/observation steps)"
    file_extensions = [".json", ".jsonl"]

    def convert(self, data: Any, options: Optional[Dict] = None) -> List[CanonicalTrace]:
        options = options or {}
        traces = data if isinstance(data, list) else [data]
        results = []

        for item in traces:
            trace_id = item.get("id", f"trace_{len(results)}")
            task = item.get("task", item.get("task_description", ""))
            agent_name = item.get("agent", item.get("agent_name", ""))
            steps = item.get("steps", [])
            metadata = item.get("metadata", {})

            # Build conversation turns
            conversation = []
            for step in steps:
                if "thought" in step and step["thought"]:
                    conversation.append({
                        "speaker": "Agent (Thought)",
                        "text": step["thought"]
                    })
                if "action" in step and step["action"]:
                    conversation.append({
                        "speaker": "Agent (Action)",
                        "text": step["action"]
                    })
                if "observation" in step and step["observation"]:
                    conversation.append({
                        "speaker": "Environment",
                        "text": step["observation"]
                    })

            # Build metadata table
            metadata_table = []
            metadata_table.append({"Property": "Steps", "Value": str(len(steps))})
            for key, value in metadata.items():
                metadata_table.append({"Property": key, "Value": str(value)})

            trace = CanonicalTrace(
                id=trace_id,
                task_description=task,
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
        # ReAct format has "steps" with thought/action/observation
        if "steps" not in first:
            return False
        steps = first["steps"]
        if not isinstance(steps, list) or not steps:
            return False
        step = steps[0]
        return isinstance(step, dict) and any(
            k in step for k in ("thought", "action", "observation")
        )
