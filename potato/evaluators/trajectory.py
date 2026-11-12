"""
Trajectory normalization.

Agent trajectories reach the evaluators in several shapes:

1. OpenAI-style message lists -- ``[{"role": "assistant", "tool_calls": [...]}, ...]``
   (the native ``agentevals`` shape; also what the tracing SDK in Phase 7 emits).
2. Potato's canonical ``conversation`` turns -- ``[{"speaker": ..., "text": ...}]``,
   produced by every ``trace_converter`` importer. Tool calls are flattened into
   ``{"speaker": "Agent (Action)", "text": "tool_name({\\"arg\\": 1})"}`` turns.
3. A ``CanonicalTrace`` object or its ``.to_dict()`` (which carries ``conversation``).
4. A bare string (single assistant message).

Evaluators operate on the normalized ``list[Step]`` produced here, so they never
care which importer or runtime produced the trace.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Matches a flattened action turn like ``get_weather({"location": "NYC"})`` or
# ``search(query="cats")`` -- name followed by a parenthesized argument blob.
_ACTION_RE = re.compile(r"^\s*([A-Za-z_][\w.\-]*)\s*\((.*)\)\s*$", re.DOTALL)


@dataclass
class ToolCall:
    """A single tool/function invocation."""

    name: str
    args: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "args": self.args}


@dataclass
class Step:
    """One normalized trajectory step."""

    role: str  # "user" | "assistant" | "tool" | "system"
    content: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)


def _coerce_args(raw: Any) -> Dict[str, Any]:
    """Coerce a tool-call argument blob into a dict.

    Accepts dicts as-is, parses JSON strings, and wraps any non-dict scalar
    under ``_value`` so downstream dict-based matching always has a mapping.
    """
    if isinstance(raw, dict):
        return raw
    if raw is None or raw == "":
        return {}
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return {"_raw": raw}
        if isinstance(parsed, dict):
            return parsed
        return {"_value": parsed}
    return {"_value": raw}


def _parse_action_text(text: str) -> Optional[ToolCall]:
    """Parse a flattened ``name(args)`` action turn into a ToolCall."""
    if not text:
        return None
    m = _ACTION_RE.match(text)
    if not m:
        # No parens -- treat the whole thing as a bare tool name.
        name = text.strip()
        return ToolCall(name=name, args={}) if name else None
    name, arg_blob = m.group(1), m.group(2).strip()
    return ToolCall(name=name, args=_coerce_args(arg_blob))


def _speaker_to_role(speaker: str) -> str:
    s = (speaker or "").lower()
    if s.startswith("user"):
        return "user"
    if s.startswith("system"):
        return "system"
    if s.startswith("environment") or s.startswith("tool") or "observation" in s:
        return "tool"
    return "assistant"


def _step_from_openai_message(msg: Dict[str, Any]) -> Step:
    role = msg.get("role", "assistant")
    content = msg.get("content", "")
    if isinstance(content, list):  # content blocks -> flatten text
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text", block.get("content", ""))))
            else:
                parts.append(str(block))
        content = " ".join(p for p in parts if p)
    content = content if isinstance(content, str) else str(content)

    tool_calls: List[ToolCall] = []
    for tc in msg.get("tool_calls", []) or []:
        func = tc.get("function", tc) if isinstance(tc, dict) else {}
        name = func.get("name", "unknown")
        tool_calls.append(ToolCall(name=name, args=_coerce_args(func.get("arguments"))))
    # Legacy single function_call
    fc = msg.get("function_call")
    if isinstance(fc, dict) and fc.get("name"):
        tool_calls.append(ToolCall(name=fc["name"], args=_coerce_args(fc.get("arguments"))))

    return Step(role=role, content=content, tool_calls=tool_calls)


def _step_from_canonical_turn(turn: Dict[str, Any]) -> Step:
    speaker = turn.get("speaker", "")
    text = turn.get("text", "")
    text = text if isinstance(text, str) else str(text)
    role = _speaker_to_role(speaker)
    tool_calls: List[ToolCall] = []
    if "(action)" in (speaker or "").lower():
        tc = _parse_action_text(text)
        if tc is not None:
            tool_calls.append(tc)
            # Keep the original text as content too; matching uses tool_calls.
    return Step(role=role, content=text, tool_calls=tool_calls)


def normalize_trajectory(obj: Any) -> List[Step]:
    """Normalize any supported trajectory representation into ``list[Step]``."""
    if obj is None:
        return []

    # CanonicalTrace object (duck-typed: has a `conversation` attribute)
    if hasattr(obj, "conversation") and not isinstance(obj, dict):
        return [_step_from_canonical_turn(t) for t in (obj.conversation or [])]

    # Bare string -> a single assistant step
    if isinstance(obj, str):
        return [Step(role="assistant", content=obj)]

    # Dict carrying a conversation (CanonicalTrace.to_dict / loaded trace)
    if isinstance(obj, dict):
        if "conversation" in obj:
            return [_step_from_canonical_turn(t) for t in (obj.get("conversation") or [])]
        if "messages" in obj:
            return [_step_from_openai_message(m) for m in (obj.get("messages") or [])]
        # A single message dict
        if "role" in obj:
            return [_step_from_openai_message(obj)]
        if "speaker" in obj:
            return [_step_from_canonical_turn(obj)]
        return []

    # List of turns/messages
    if isinstance(obj, (list, tuple)):
        steps: List[Step] = []
        for item in obj:
            if isinstance(item, str):
                steps.append(Step(role="assistant", content=item))
            elif isinstance(item, dict) and "role" in item:
                steps.append(_step_from_openai_message(item))
            elif isinstance(item, dict) and "speaker" in item:
                steps.append(_step_from_canonical_turn(item))
            elif isinstance(item, Step):
                steps.append(item)
        return steps

    return []


def extract_tool_calls(obj: Any) -> List[ToolCall]:
    """Flatten a trajectory into its ordered sequence of tool calls."""
    calls: List[ToolCall] = []
    for step in normalize_trajectory(obj):
        calls.extend(step.tool_calls)
    return calls
