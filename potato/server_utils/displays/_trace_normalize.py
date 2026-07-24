"""
Shared agent-trace normalization.

Both ``agent_trace`` (vertical step cards) and ``eval_trace`` (three-pane
reasoning | function calls | final answer) need to turn heterogeneous trace
data into a flat list of typed steps. This module is the single source of
truth for that parsing so the two displays never drift apart.

A normalized step is a dict with keys:
    type:       one of "thought" | "action" | "observation" | "system" | "error"
    speaker:    display label for the step (may be "")
    text:       the step's textual content
    timestamp:  optional timestamp string ("")
    screenshot: optional screenshot URL ("")

Optional identity keys are passed through from the source dict when present
(consumed by turn-level annotation bindings and multi-agent displays):
    turn_id / step_id:  stable id for the turn
    agent_id:           which agent produced the turn
    role:               the agent's role
    addressee:          which agent the turn is directed at
    tool:               tool name for tool-call steps
    run_id:             id of the run-tree node that produced the turn

Supported input formats (see ``normalize_steps``):
    - a single string                       -> one observation step
    - list of strings                       -> one step each (type inferred)
    - list of {speaker, text} dicts         -> dialogue-style turns
    - list of {thought, action, observation}-> one dict expands to 1-3 steps
    - list of {step_type, content} dicts    -> explicit typing
"""

import re
from typing import Any, Dict, List


# Default background colors for step types (consumed by displays' CSS builders).
DEFAULT_STEP_COLORS = {
    "thought": "#e8f4fd",
    "action": "#fff3e0",
    "observation": "#e8f5e9",
    "system": "#f3e5f5",
    "error": "#ffebee",
}

# Speaker/label substrings that map to a step type.
SPEAKER_TYPE_PATTERNS = {
    "thought": re.compile(r"(thought|reasoning|planning|think)", re.IGNORECASE),
    "action": re.compile(r"(action|tool|function|call|execute)", re.IGNORECASE),
    "observation": re.compile(r"(observation|environment|result|output|response)", re.IGNORECASE),
    "system": re.compile(r"(system|info|metadata)", re.IGNORECASE),
    "error": re.compile(r"(error|fail|exception)", re.IGNORECASE),
}


def infer_type_from_speaker(speaker: str) -> str:
    """Infer a step type from a speaker/label string."""
    if not speaker:
        return "observation"
    for type_name, pattern in SPEAKER_TYPE_PATTERNS.items():
        if pattern.search(speaker):
            return type_name
    return "observation"


def infer_type_from_text(text: str) -> str:
    """Infer a step type from free text content."""
    lower = text.lower()
    if lower.startswith(("i need to", "i should", "let me think", "my plan")):
        return "thought"
    if "(" in text and ")" in text and any(c.isalpha() for c in text.split("(")[0]):
        return "action"
    return "observation"


def format_action_text(action: Any) -> str:
    """Render an action value as ``tool(args)`` when it is a structured dict."""
    if isinstance(action, dict):
        tool = action.get("tool", action.get("name", ""))
        params = action.get("params", action.get("parameters", {}))
        if params:
            args = ", ".join(f"{k}={repr(v)}" for k, v in params.items())
            return f"{tool}({args})"
        return f"{tool}()"
    return str(action)


# Identity keys copied through from source dicts when present (turn-level
# annotation bindings + multi-agent displays consume these). run_id links a
# turn to its node in the trace's run tree (sub-agent hierarchy).
PASSTHROUGH_KEYS = ("turn_id", "step_id", "agent_id", "role", "addressee", "tool", "run_id")


def _passthrough(step: Dict[str, Any], item: Dict[str, Any], skip_ids: bool = False) -> Dict[str, Any]:
    """Copy optional identity keys from a source dict onto a normalized step.

    ``skip_ids=True`` omits turn_id/step_id — used when one source dict
    expands into multiple steps (thought/action/observation format), where a
    shared explicit id would collide across the expanded steps.
    """
    for key in PASSTHROUGH_KEYS:
        if skip_ids and key in ("turn_id", "step_id"):
            continue
        if key in item and item[key] not in (None, ""):
            step[key] = item[key]
    return step


def normalize_steps(
    data: Any,
    speaker_key: str = "speaker",
    text_key: str = "text",
) -> List[Dict[str, str]]:
    """Normalize heterogeneous trace data into a list of typed step dicts.

    See the module docstring for the accepted input formats and the shape of
    each returned step.
    """
    steps: List[Dict[str, str]] = []

    if isinstance(data, str):
        return [{"type": "observation", "speaker": "", "text": data}]

    if not isinstance(data, list):
        return steps

    for item in data:
        if isinstance(item, str):
            step_type = infer_type_from_text(item)
            steps.append({"type": step_type, "speaker": "", "text": item})
        elif isinstance(item, dict):
            # Format 1: speaker/text (same as dialogue)
            if speaker_key in item and text_key in item:
                speaker = item[speaker_key]
                text = item[text_key]
                step_type = item.get("step_type", infer_type_from_speaker(speaker))
                steps.append(_passthrough({
                    "type": step_type,
                    "speaker": speaker,
                    "text": text,
                    "timestamp": item.get("timestamp", ""),
                    "screenshot": item.get("screenshot", ""),
                }, item))
            # Format 2: thought/action/observation (one dict = up to 3 steps)
            elif any(k in item for k in ("thought", "action", "observation")):
                if item.get("thought"):
                    steps.append(_passthrough({
                        "type": "thought",
                        "speaker": "Agent (Thought)",
                        "text": str(item["thought"]),
                        "timestamp": item.get("timestamp", ""),
                    }, item, skip_ids=True))
                if item.get("action"):
                    steps.append(_passthrough({
                        "type": "action",
                        "speaker": "Agent (Action)",
                        "text": format_action_text(item["action"]),
                    }, item, skip_ids=True))
                if item.get("observation"):
                    steps.append(_passthrough({
                        "type": "observation",
                        "speaker": "Environment",
                        "text": str(item["observation"]),
                        "screenshot": item.get("screenshot", ""),
                    }, item, skip_ids=True))
            # Format 3: step_type/content
            elif "step_type" in item:
                steps.append(_passthrough({
                    "type": item["step_type"],
                    "speaker": item.get("speaker", item.get("step_type", "").capitalize()),
                    "text": item.get("content", item.get("text", "")),
                    "timestamp": item.get("timestamp", ""),
                    "screenshot": item.get("screenshot", ""),
                }, item))

    return steps
