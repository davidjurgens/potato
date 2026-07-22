"""
"Get Feedback": an LLM critiques the current annotation prompt.

Purely advisory — this module only asks a model for targeted feedback
(ambiguities, missing exclusions, overlapping categories) on the exact
prompt the labeling thread builds. It never edits the prompt or the
codebook itself; the human reads the feedback and decides what, if
anything, to change (by hand, or via the codebook tray / prompt editor).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """You are reviewing an annotation prompt that instructs \
another LLM how to label text. Give specific, actionable feedback — not \
generic advice.

The full prompt as given to the labeling model:
---
{full_prompt}
---
{examples_section}
Look for: ambiguous or underspecified categories, missing exclusion rules, \
categories that overlap or could be conflated, and instructions the \
low-confidence examples above suggest the model is struggling with (if any \
were given). Only report specific, concrete issues — do not pad with \
generic advice.

Respond with JSON: {{"feedback": [{{"issue": "<what's wrong>", \
"suggestion": "<a concrete fix>", "severity": "<low|medium|high>"}}, ...]}} \
(empty list if the prompt has no notable issues).
"""

_MAX_EXAMPLES = 5


def _format_examples(examples: Optional[List[Dict[str, Any]]]) -> str:
    if not examples:
        return ""
    lines = ["\nInstances the labeling model was least confident on:"]
    for ex in examples[:_MAX_EXAMPLES]:
        text = (ex.get("text") or "").strip().replace("\n", " ")
        if len(text) > 200:
            text = text[:200] + "…"
        lines.append(
            f'- "{text}" -> labeled "{ex.get("llm_label")}" '
            f'(confidence {ex.get("confidence")}): {ex.get("reasoning") or ""}'
        )
    return "\n".join(lines) + "\n"


def _parse_feedback(response: Any) -> List[Dict[str, Any]]:
    if isinstance(response, dict):
        data = response
    elif hasattr(response, "model_dump"):
        data = response.model_dump()
    else:
        content = str(response).strip()
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
        if match:
            content = match.group(1).strip()
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return []
    items = data.get("feedback") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    return [
        {
            "issue": str(it.get("issue", "")).strip(),
            "suggestion": str(it.get("suggestion", "")).strip(),
            "severity": str(it.get("severity", "medium")).strip().lower(),
        }
        for it in items if isinstance(it, dict) and it.get("issue")
    ]


def get_prompt_feedback(
    full_prompt: str, endpoint: Any,
    examples: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Ask ``endpoint`` for targeted feedback on ``full_prompt``. Returns
    ``[{issue, suggestion, severity}]``, possibly empty; never raises."""
    if not full_prompt or not full_prompt.strip():
        return []
    try:
        prompt = _PROMPT_TEMPLATE.format(
            full_prompt=full_prompt,
            examples_section=_format_examples(examples))
        response = endpoint.query(prompt)
        return _parse_feedback(response)
    except Exception:
        logger.warning("prompt feedback generation failed", exc_info=True)
        return []
