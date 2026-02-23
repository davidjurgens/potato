"""
LangChain/LangSmith Converter

Converts LangChain run traces (as exported from LangSmith) to Potato's
canonical format.

Expected input format (LangSmith export):
{
    "id": "run-uuid",
    "name": "AgentExecutor",
    "run_type": "chain",
    "inputs": {"input": "Book a flight..."},
    "outputs": {"output": "I booked flight BA117..."},
    "child_runs": [
        {
            "name": "ChatOpenAI",
            "run_type": "llm",
            "inputs": {...},
            "outputs": {"generations": [{"text": "I need to search..."}]}
        },
        {
            "name": "search_flights",
            "run_type": "tool",
            "inputs": {"query": "JFK to LHR"},
            "outputs": {"output": "Found 5 flights..."}
        }
    ]
}
"""

from typing import Any, Dict, List, Optional

from ..base import BaseTraceConverter, CanonicalTrace


class LangChainConverter(BaseTraceConverter):
    """Converter for LangChain/LangSmith trace exports."""

    format_name = "langchain"
    description = "LangChain/LangSmith run trace export format"
    file_extensions = [".json", ".jsonl"]

    def convert(self, data: Any, options: Optional[Dict] = None) -> List[CanonicalTrace]:
        options = options or {}
        traces = data if isinstance(data, list) else [data]
        results = []

        for item in traces:
            trace_id = item.get("id", f"trace_{len(results)}")
            name = item.get("name", "")
            inputs = item.get("inputs") or {}
            outputs = item.get("outputs") or {}
            child_runs = item.get("child_runs") or []

            # Extract task description from inputs
            task = inputs.get("input", inputs.get("question", inputs.get("query", "")))
            if isinstance(task, dict):
                task = str(task)

            # Build conversation from child runs
            conversation = []
            for run in child_runs:
                run_type = run.get("run_type", "")
                run_name = run.get("name", "")
                run_inputs = run.get("inputs") or {}
                run_outputs = run.get("outputs") or {}

                if run_type == "llm":
                    # LLM call - extract generated text as thought
                    text = self._extract_llm_output(run_outputs)
                    if text:
                        conversation.append({
                            "speaker": "Agent (Thought)",
                            "text": text
                        })
                elif run_type == "tool":
                    # Tool call - show as action + observation
                    action_text = self._format_tool_call(run_name, run_inputs)
                    conversation.append({
                        "speaker": "Agent (Action)",
                        "text": action_text
                    })
                    obs_text = self._extract_tool_output(run_outputs)
                    if obs_text:
                        conversation.append({
                            "speaker": "Environment",
                            "text": obs_text
                        })
                elif run_type == "chain":
                    # Nested chain - recurse into child_runs if present
                    nested_runs = run.get("child_runs", [])
                    for nested in nested_runs:
                        self._process_run(nested, conversation)

            # If no child runs, try to create a simple trace from inputs/outputs
            if not conversation:
                if task:
                    conversation.append({"speaker": "User", "text": task})
                final_output = self._extract_output(outputs)
                if final_output:
                    conversation.append({"speaker": "Agent", "text": final_output})

            # Build metadata
            metadata_table = [
                {"Property": "Steps", "Value": str(len(child_runs))},
            ]
            if name:
                metadata_table.append({"Property": "Chain", "Value": name})
            # Extract timing if available
            if "start_time" in item and "end_time" in item:
                metadata_table.append({
                    "Property": "Start",
                    "Value": str(item["start_time"])
                })
            if "total_tokens" in item.get("extra", {}):
                metadata_table.append({
                    "Property": "Tokens",
                    "Value": str(item["extra"]["total_tokens"])
                })

            trace = CanonicalTrace(
                id=trace_id,
                task_description=task,
                conversation=conversation,
                agent_name=name,
                metadata_table=metadata_table,
            )
            results.append(trace)

        return results

    def _process_run(self, run: Dict, conversation: List[Dict[str, str]]) -> None:
        """Recursively process a run and its children."""
        run_type = run.get("run_type", "")
        run_name = run.get("name", "")
        run_inputs = run.get("inputs", {}) or {}
        run_outputs = run.get("outputs", {}) or {}

        if run_type == "llm":
            text = self._extract_llm_output(run_outputs)
            if text:
                conversation.append({"speaker": "Agent (Thought)", "text": text})
        elif run_type == "tool":
            action_text = self._format_tool_call(run_name, run_inputs)
            conversation.append({"speaker": "Agent (Action)", "text": action_text})
            obs_text = self._extract_tool_output(run_outputs)
            if obs_text:
                conversation.append({"speaker": "Environment", "text": obs_text})
        elif run_type == "chain":
            # Recurse into nested chain's child runs
            for nested in run.get("child_runs", []):
                self._process_run(nested, conversation)

    def _extract_llm_output(self, outputs: Dict) -> str:
        """Extract text from LLM run outputs."""
        if "generations" in outputs:
            gens = outputs["generations"]
            if isinstance(gens, list) and gens:
                first_gen = gens[0]
                if isinstance(first_gen, list) and first_gen:
                    return first_gen[0].get("text", "")
                if isinstance(first_gen, dict):
                    return first_gen.get("text", "")
        if "output" in outputs:
            return str(outputs["output"])
        return ""

    def _format_tool_call(self, name: str, inputs: Dict) -> str:
        """Format a tool call as a readable string."""
        if not inputs:
            return f"{name}()"
        args = ", ".join(f"{k}={repr(v)}" for k, v in inputs.items()
                         if k not in ("callbacks", "run_manager"))
        return f"{name}({args})"

    def _extract_tool_output(self, outputs: Dict) -> str:
        """Extract text from tool run outputs."""
        if "output" in outputs:
            return str(outputs["output"])
        if "result" in outputs:
            return str(outputs["result"])
        return ""

    def _extract_output(self, outputs: Dict) -> str:
        """Extract final output from chain outputs."""
        if "output" in outputs:
            return str(outputs["output"])
        if "answer" in outputs:
            return str(outputs["answer"])
        if "result" in outputs:
            return str(outputs["result"])
        return ""

    def detect(self, data: Any) -> bool:
        items = data if isinstance(data, list) else [data]
        if not items:
            return False
        first = items[0]
        if not isinstance(first, dict):
            return False
        # LangChain traces have run_type and typically child_runs
        return "run_type" in first and "child_runs" in first
