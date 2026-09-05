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


#: Openers that mean the step is the agent reasoning rather than reporting.
_THOUGHT_OPENERS = (
    "i need to", "i should", "i will", "i'll", "i am going to", "i'm going to",
    "let me", "let's", "my plan", "first", "next", "then", "finally",
    "so ", "because", "the plan", "we need to", "we should", "now i",
    "to do this", "in order to", "this means", "therefore", "it looks like",
)

#: A leading list or step marker: "1. ", "2) ", "- ", "* ", "Step 3: ".
_LIST_MARKER = re.compile(r"^\s*(?:step\s*\d+\s*[:.\-]|\d+[.)]|[-*\u2022])\s*",
                          re.IGNORECASE)


def infer_type_from_text(text: str, default: str = "observation") -> str:
    """Infer a step type from free text content.

    The list marker is stripped before the opener test, because a segmented
    chain of thought numbers its steps: "1. First I need to reproduce the
    failure" begins with "1." and so matched no opener, and every step of every
    segmented CoT was typed -- and badged in the display -- "Observation".

    `default` is what an unrecognized step becomes. A trace display leaves it
    at "observation", which is what an unlabelled line in a trace usually is;
    `cot_segmentation` passes "thought", because a chain of thought is
    reasoning by construction.
    """
    stripped = _LIST_MARKER.sub("", text or "", count=1)
    lower = stripped.lower()
    if lower.startswith(_THOUGHT_OPENERS):
        return "thought"
    head = stripped.split("(")[0]
    if "(" in stripped and ")" in stripped and head and any(c.isalpha() for c in head):
        # A call looks like `tool(args)`, not like a sentence with a
        # parenthetical aside in it.
        if len(head.split()) <= 3:
            return "action"
    return default


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
