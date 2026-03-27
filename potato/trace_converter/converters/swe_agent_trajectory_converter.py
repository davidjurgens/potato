"""
SWE-Agent Trajectory Converter

Converts SWE-Agent's native trajectory format (thought/action/observation triples)
to Potato's canonical format with structured_turns for CodingTraceDisplay.

This handles the trajectory output files from SWE-Agent runs, which differ from
the SWE-bench benchmark format (handled by SWEBenchConverter).

Supported input formats:

1. SWE-Agent trajectory file:
{
    "trajectory": [
        [{"role": "assistant", "content": "...", "thought": "...", "action": "..."},
         {"role": "user", "content": "OBSERVATION:\n..."}]
    ],
    "info": {"instance_id": "...", "model": "...", "exit_status": "..."}
}

2. Simplified step format:
{
    "steps": [
        {"thought": "...", "action": "edit ...", "observation": "..."}
    ]
}
"""

import re
from typing import Any, Dict, List, Optional

from ..base import BaseTraceConverter, CanonicalTrace


# SWE-Agent action patterns
EDIT_ACTION = re.compile(r'^edit\s+(\S+)', re.IGNORECASE)
OPEN_ACTION = re.compile(r'^open\s+(\S+)', re.IGNORECASE)
FIND_ACTION = re.compile(r'^find_file\s+', re.IGNORECASE)
SEARCH_ACTION = re.compile(r'^search_(?:file|dir)\s+', re.IGNORECASE)
SUBMIT_ACTION = re.compile(r'^submit\s*$', re.IGNORECASE)


class SWEAgentTrajectoryConverter(BaseTraceConverter):
    """Converter for SWE-Agent trajectory output files."""

    format_name = "swe_agent_trajectory"
    description = "SWE-Agent trajectory files with thought/action/observation triples"
    file_extensions = [".json", ".jsonl"]

    def convert(self, data: Any, options: Optional[Dict] = None) -> List[CanonicalTrace]:
        items = data if isinstance(data, list) else [data]
        results = []
        for item in items:
            if not isinstance(item, dict):
                continue
            results.append(self._convert_item(item, len(results)))
        return results

    def _convert_item(self, item: dict, index: int) -> CanonicalTrace:
        """Convert a single SWE-Agent trajectory."""
        info = item.get("info", {})
        trace_id = info.get("instance_id", item.get("id", f"swe_agent_{index}"))
        model = info.get("model_name", info.get("model", item.get("model", "")))
        task = item.get("task_description", item.get("problem_statement", ""))

        # Extract trajectory
        if "trajectory" in item:
            turns = self._parse_trajectory(item["trajectory"])
        elif "steps" in item:
            turns = self._parse_steps(item["steps"])
        elif "history" in item:
            turns = self._parse_history(item["history"])
        else:
            turns = []

        # Extract task from first user message if not set
        if not task and turns:
            for t in turns:
                if t.get("role") == "user":
                    task = t.get("content", "")[:500]
                    break

        conversation = self._flatten_conversation(turns)

        metadata = []
        if model:
            metadata.append({"Property": "Model", "Value": str(model)})
        exit_status = info.get("exit_status", "")
        if exit_status:
            metadata.append({"Property": "Exit Status", "Value": str(exit_status)})

        return CanonicalTrace(
            id=str(trace_id),
            task_description=task,
            conversation=conversation,
            agent_name=model,
            metadata_table=metadata,
            extra_fields={"structured_turns": turns},
        )

    def _parse_trajectory(self, trajectory: list) -> List[Dict[str, Any]]:
        """Parse SWE-Agent trajectory format (list of message pairs)."""
        turns = []

        for pair in trajectory:
            if not isinstance(pair, (list, tuple)):
                continue

            for msg in pair:
                if not isinstance(msg, dict):
                    continue
                role = msg.get("role", "")
                content = msg.get("content", "")

                if role == "assistant":
                    thought = msg.get("thought", "")
                    action = msg.get("action", "")

                    # Parse thought/action from content if not separate
                    if not thought and not action and content:
                        thought, action = self._split_thought_action(content)

                    tool_calls = []
                    if action:
                        tool_calls = [self._action_to_tool_call(action)]

                    turns.append({
                        "role": "assistant",
                        "content": thought or content,
                        "tool_calls": tool_calls,
                    })

                elif role == "user" and "OBSERVATION:" in content:
                    # Observation goes as output of the last tool call
                    obs = content.replace("OBSERVATION:\n", "").strip()
                    if turns and turns[-1].get("tool_calls"):
                        turns[-1]["tool_calls"][-1]["output"] = obs
                    else:
                        turns.append({
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [{"tool": "Bash", "input": {"command": ""}, "output": obs}],
                        })

                elif role == "user":
                    turns.append({"role": "user", "content": content, "tool_calls": []})

        return turns

    def _parse_steps(self, steps: list) -> List[Dict[str, Any]]:
        """Parse simplified steps format."""
        turns = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            thought = step.get("thought", step.get("reasoning", ""))
            action = step.get("action", "")
            observation = step.get("observation", step.get("output", ""))

            tool_calls = []
            if action:
                tc = self._action_to_tool_call(str(action) if not isinstance(action, str) else action)
                tc["output"] = str(observation) if observation else ""
                tool_calls.append(tc)

            turns.append({
                "role": "assistant",
                "content": str(thought) if thought else "",
                "tool_calls": tool_calls,
            })
        return turns

    def _parse_history(self, history: list) -> List[Dict[str, Any]]:
        """Parse history format (list of role/content dicts)."""
        turns = []
        for msg in history:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role", "assistant")
            content = msg.get("content", "")

            if role == "user":
                turns.append({"role": "user", "content": content, "tool_calls": []})
            else:
                thought, action = self._split_thought_action(content)
                tool_calls = [self._action_to_tool_call(action)] if action else []
                turns.append({
                    "role": "assistant",
                    "content": thought,
                    "tool_calls": tool_calls,
                })
        return turns

    def _split_thought_action(self, content: str):
        """Split content into thought and action parts."""
        # SWE-Agent uses THOUGHT: and ACTION: markers
        thought = ""
        action = ""
        if "THOUGHT:" in content.upper():
            parts = re.split(r'(?:THOUGHT|DISCUSSION):\s*', content, flags=re.IGNORECASE)
            if len(parts) > 1:
                remaining = parts[-1]
                if "ACTION:" in remaining.upper():
                    thought_action = re.split(r'ACTION:\s*', remaining, flags=re.IGNORECASE)
                    thought = thought_action[0].strip()
                    action = thought_action[-1].strip() if len(thought_action) > 1 else ""
                else:
                    thought = remaining.strip()
        elif "ACTION:" in content.upper():
            parts = re.split(r'ACTION:\s*', content, flags=re.IGNORECASE)
            thought = parts[0].strip()
            action = parts[-1].strip() if len(parts) > 1 else ""
        else:
            thought = content
        return thought, action

    def _action_to_tool_call(self, action: str) -> Dict[str, Any]:
        """Convert an action string to a structured tool call."""
        action = action.strip()

        if EDIT_ACTION.match(action):
            m = EDIT_ACTION.match(action)
            return {
                "tool": "Edit",
                "input": {"file_path": m.group(1), "command": action},
                "output": "",
                "output_type": "diff",
            }
        elif OPEN_ACTION.match(action):
            m = OPEN_ACTION.match(action)
            return {
                "tool": "Read",
                "input": {"file_path": m.group(1)},
                "output": "",
                "output_type": "code",
            }
        elif FIND_ACTION.match(action) or SEARCH_ACTION.match(action):
            return {
                "tool": "Search",
                "input": {"command": action},
                "output": "",
                "output_type": "code",
            }
        elif SUBMIT_ACTION.match(action):
            return {
                "tool": "Bash",
                "input": {"command": "submit"},
                "output": "Submitted",
                "output_type": "terminal",
            }
        else:
            # Default: treat as bash command
            return {
                "tool": "Bash",
                "input": {"command": action},
                "output": "",
                "output_type": "terminal",
            }

    def _flatten_conversation(self, turns: list) -> List[Dict[str, str]]:
        """Flatten to speaker/text format."""
        conv = []
        for turn in turns:
            role = turn.get("role", "assistant")
            content = turn.get("content", "")
            if content:
                speaker = "User" if role == "user" else "Agent"
                conv.append({"speaker": speaker, "text": content})
            for tc in turn.get("tool_calls", []):
                tool = tc.get("tool", "Bash")
                inp = tc.get("input", {})
                cmd = inp.get("command", inp.get("file_path", ""))
                conv.append({"speaker": f"Agent ({tool})", "text": f"{tool}({cmd})"})
                output = tc.get("output", "")
                if output:
                    conv.append({"speaker": "Environment", "text": output})
        return conv

    def detect(self, data: Any) -> bool:
        items = data if isinstance(data, list) else [data]
        if not items:
            return False
        first = items[0]
        if not isinstance(first, dict):
            return False

        # SWE-Agent trajectory format
        if "trajectory" in first and isinstance(first.get("trajectory"), list):
            traj = first["trajectory"]
            if traj and isinstance(traj[0], (list, tuple)):
                return True

        # Check info block with SWE-Agent specific fields
        info = first.get("info", {})
        if isinstance(info, dict) and "exit_status" in info:
            return True

        return False
