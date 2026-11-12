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

            # Build conversation from child runs, preserving the run
            # hierarchy as a run tree (sub-agent view). Each turn is tagged
            # with the run_id of the run that produced it.
            conversation = []
            root_id = str(trace_id)
            root_node = {
                "id": root_id,
                "parent_id": None,
                "name": name or "root",
                "run_type": item.get("run_type", "chain"),
                "status": item.get("status"),
                "turn_range": None,
            }
            run_tree = [root_node]
            counter = {"n": 0}
            for run in child_runs:
                self._process_run(run, conversation,
                                  run_tree=run_tree, parent_id=root_id,
                                  counter=counter)
            if conversation:
                root_node["turn_range"] = [0, len(conversation) - 1]

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

            # Only carry the run tree when there is real hierarchy
            # (more than just the synthetic root node).
            extra_fields = {}
            if len(run_tree) > 1:
                extra_fields["run_tree"] = run_tree

            trace = CanonicalTrace(
                id=trace_id,
                task_description=task,
                conversation=conversation,
                agent_name=name,
                metadata_table=metadata_table,
                extra_fields=extra_fields,
            )
            results.append(trace)

        return results

    def _process_run(self, run: Dict, conversation: List[Dict[str, str]],
                     run_tree: Optional[List[Dict]] = None,
                     parent_id: Optional[str] = None,
                     counter: Optional[Dict[str, int]] = None) -> None:
        """Recursively process a run and its children.

        When ``run_tree`` is provided, each run appends a node
        ``{id, parent_id, name, run_type, status, turn_range}`` and tags
        the conversation turns it produces with ``run_id``.
        """
        run_type = run.get("run_type", "")
        run_name = run.get("name", "")
        run_inputs = run.get("inputs", {}) or {}
        run_outputs = run.get("outputs", {}) or {}

        run_id = None
        node = None
        if run_tree is not None:
            counter = counter if counter is not None else {"n": 0}
            run_id = str(run.get("id") or f"run-{counter['n']}")
            counter["n"] += 1
            node = {
                "id": run_id,
                "parent_id": parent_id,
                "name": run_name or run_type or "run",
                "run_type": run_type or "chain",
                "status": run.get("status"),
                "turn_range": None,
            }
            run_tree.append(node)
        start = len(conversation)

        def _turn(turn: Dict) -> Dict:
            if run_id is not None:
                turn["run_id"] = run_id
            return turn

        if run_type == "llm":
            text = self._extract_llm_output(run_outputs)
            if text:
                conversation.append(_turn(
                    {"speaker": "Agent (Thought)", "text": text}))
        elif run_type == "tool":
            action_text = self._format_tool_call(run_name, run_inputs)
            conversation.append(_turn(
                {"speaker": "Agent (Action)", "text": action_text}))
            obs_text = self._extract_tool_output(run_outputs)
            if obs_text:
                conversation.append(_turn(
                    {"speaker": "Environment", "text": obs_text}))
        elif run_type == "chain":
            # Recurse into nested chain's child runs
            for nested in run.get("child_runs", []):
                self._process_run(nested, conversation, run_tree=run_tree,
                                  parent_id=run_id or parent_id,
                                  counter=counter)

        if node is not None and len(conversation) > start:
            node["turn_range"] = [start, len(conversation) - 1]

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
