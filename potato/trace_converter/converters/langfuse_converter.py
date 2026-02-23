"""
Langfuse Converter

Converts Langfuse observation/trace exports to Potato's canonical format.

Expected input format (Langfuse export):
{
    "id": "trace-uuid",
    "name": "agent-run",
    "input": {"query": "Book a flight..."},
    "output": {"result": "Booked BA117..."},
    "observations": [
        {
            "id": "obs-1",
            "type": "GENERATION",
            "name": "gpt-4",
            "input": [...],
            "output": {"content": "I need to search..."},
            "model": "gpt-4"
        },
        {
            "id": "obs-2",
            "type": "SPAN",
            "name": "search_flights",
            "input": {"origin": "JFK"},
            "output": {"result": "Found 5 flights..."}
        }
    ],
    "metadata": {"userId": "user-1", "tags": ["production"]}
}
"""

from typing import Any, Dict, List, Optional

from ..base import BaseTraceConverter, CanonicalTrace


class LangfuseConverter(BaseTraceConverter):
    """Converter for Langfuse trace exports."""

    format_name = "langfuse"
    description = "Langfuse observation/trace export format"
    file_extensions = [".json", ".jsonl"]

    def convert(self, data: Any, options: Optional[Dict] = None) -> List[CanonicalTrace]:
        options = options or {}
        traces = data if isinstance(data, list) else [data]
        results = []

        for item in traces:
            trace_id = item.get("id", f"trace_{len(results)}")
            name = item.get("name", "")
            trace_input = item.get("input", {})
            observations = item.get("observations", [])
            metadata = item.get("metadata", {})

            # Extract task description
            task = ""
            if isinstance(trace_input, dict):
                task = trace_input.get("query", trace_input.get("input", trace_input.get("question", "")))
            elif isinstance(trace_input, str):
                task = trace_input

            # Build conversation from observations
            conversation = []
            for obs in observations:
                obs_type = obs.get("type", "").upper()
                obs_name = obs.get("name", "")
                obs_input = obs.get("input", {})
                obs_output = obs.get("output", {})

                if obs_type == "GENERATION":
                    # LLM generation - treat as thought
                    text = self._extract_generation_output(obs_output)
                    if text:
                        conversation.append({
                            "speaker": "Agent (Thought)",
                            "text": text
                        })
                elif obs_type == "SPAN":
                    # Tool/function call - treat as action + observation
                    action_text = self._format_span_action(obs_name, obs_input)
                    conversation.append({
                        "speaker": "Agent (Action)",
                        "text": action_text
                    })
                    result_text = self._extract_span_output(obs_output)
                    if result_text:
                        conversation.append({
                            "speaker": "Environment",
                            "text": result_text
                        })
                elif obs_type == "EVENT":
                    # Events - include as system messages
                    event_text = obs.get("output", obs.get("input", ""))
                    if isinstance(event_text, dict):
                        event_text = str(event_text)
                    if event_text:
                        conversation.append({
                            "speaker": f"System ({obs_name})",
                            "text": str(event_text)
                        })

            # Build metadata table
            metadata_table = [
                {"Property": "Steps", "Value": str(len(observations))},
            ]
            if name:
                metadata_table.append({"Property": "Trace", "Value": name})
            # Extract model info
            models = set()
            total_tokens = 0
            for obs in observations:
                if obs.get("model"):
                    models.add(obs["model"])
                usage = obs.get("usage") or {}
                if isinstance(usage, dict):
                    token_count = usage.get("totalTokens", usage.get("total_tokens", 0))
                    total_tokens += token_count or 0
            if models:
                metadata_table.append({"Property": "Models", "Value": ", ".join(models)})
            if total_tokens:
                metadata_table.append({"Property": "Tokens", "Value": str(total_tokens)})

            trace = CanonicalTrace(
                id=trace_id,
                task_description=task,
                conversation=conversation,
                agent_name=name,
                metadata_table=metadata_table,
            )
            results.append(trace)

        return results

    def _extract_generation_output(self, output: Any) -> str:
        """Extract text from a generation observation output."""
        if isinstance(output, str):
            return output
        if isinstance(output, dict):
            if "content" in output:
                return str(output["content"])
            if "text" in output:
                return str(output["text"])
            if "completion" in output:
                return str(output["completion"])
        return ""

    def _format_span_action(self, name: str, inputs: Any) -> str:
        """Format a span/tool call."""
        if not inputs:
            return f"{name}()"
        if isinstance(inputs, dict):
            args = ", ".join(f"{k}={repr(v)}" for k, v in inputs.items())
            return f"{name}({args})"
        return f"{name}({inputs})"

    def _extract_span_output(self, output: Any) -> str:
        """Extract text from a span observation output."""
        if isinstance(output, str):
            return output
        if isinstance(output, dict):
            if "result" in output:
                return str(output["result"])
            if "output" in output:
                return str(output["output"])
            return str(output)
        return ""

    def detect(self, data: Any) -> bool:
        items = data if isinstance(data, list) else [data]
        if not items:
            return False
        first = items[0]
        if not isinstance(first, dict):
            return False
        # Langfuse traces have "observations" with type field
        if "observations" not in first:
            return False
        obs = first["observations"]
        if not isinstance(obs, list) or not obs:
            return False
        return isinstance(obs[0], dict) and "type" in obs[0]
