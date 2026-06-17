"""
Codebook -> LLM prompt renderer.

Turns a project's structured codebook (each code's definition,
inclusion/exclusion clarifications, and a positive/negative worked
example) into a Markdown "## Codebook" block that is injected into the
prompt the model actually sees.

This is the load-bearing integration: the annotator/researcher writes
their prompt as usual, and we transparently *augment* it with the
codebook block before it reaches the model — we never ask them to
restructure their prompt by hand. Dropping the definition is known to
tank agreement (the codebook-prompting ablation), and explicit negative
clarifications / negative examples are what stop the model from
collapsing semantically adjacent codes via lexical-overlap heuristics
(predicting "rally" just because the word "rally" appears).

Backward compatible: if no code carries any structured field, the
renderer returns "" and callers fall back to their existing flat label
list.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from potato.codebook import store
from potato.codebook.codebook import Codebook

logger = logging.getLogger(__name__)

# A short standing instruction that frames the codebook and directly
# counters the lexical-overlap failure mode the error analysis found.
_GUARD = (
    "Decide each label from its Definition, Include and Exclude rules "
    "below — NOT from surface wording. A keyword appearing in the text "
    "(e.g. a code's name) is not sufficient; the text must satisfy the "
    "code's definition. Pay special attention to the Exclude rules and "
    "the \"Do NOT apply when\" rules that separate similar codes."
)


def _render_code(detail: Dict[str, Any]) -> Optional[str]:
    """Render one code's block, or None if it has no structured content."""
    lines: List[str] = []
    name = detail.get("name") or ""

    def add(field: str, fmt: str) -> None:
        val = detail.get(field)
        if val:
            lines.append(fmt.format(val=val))

    add("definition", "Definition: {val}")
    add("clarification", "Include: {val}")
    add("negative_clarification", "Exclude: {val}")

    def _example(ex: Any) -> Optional[tuple]:
        """(text, why) for a worked example, or None if it has no text."""
        if not isinstance(ex, dict):
            return None
        text = (ex.get("text") or "").strip()
        if not text:
            return None
        return text, (ex.get("why") or "").strip()

    for ex in detail.get("positive_examples") or []:
        parsed = _example(ex)
        if parsed:
            text, why = parsed
            lines.append(f'✓ Example: "{text}"' + (f" — {why}" if why else ""))

    for ex in detail.get("negative_examples") or []:
        parsed = _example(ex)
        if parsed:
            text, why = parsed
            lines.append(
                f'✗ Looks like this code but is NOT: "{text}"'
                + (f" — {why}" if why else ""))

    rules = [str(r).strip() for r in (detail.get("exclusion_rules") or [])
             if str(r).strip()]
    if rules:
        lines.append("Do NOT apply when:")
        lines.extend(f"  • {r}" for r in rules)

    if not lines:
        return None
    return f"### {name}\n" + "\n".join(lines)


def render_from_codebook(cb: Codebook) -> str:
    """Render the structured block from an already-loaded Codebook (no
    DB hit). Returns "" when no code carries any structured field."""
    blocks: List[str] = []
    for detail in cb.details_in_order():
        block = _render_code(detail)
        if block:
            blocks.append(block)
    if not blocks:
        return ""
    return "## Codebook\n\n" + _GUARD + "\n\n" + "\n\n".join(blocks)


def render_codebook_section(task_dir: str, project: str) -> str:
    """Build the structured codebook block for a project, or "" if the
    codebook has no structured fields yet. Best-effort: never raises into
    the prompt path (a render failure must not break labeling)."""
    try:
        cb = Codebook.load(task_dir, project)
        return render_from_codebook(cb)
    except Exception:  # pragma: no cover - defensive
        logger.exception("codebook prompt render failed; falling back")
        return ""


def has_rich_detail(task_dir: str, project: str) -> bool:
    """True if at least one code carries a structured field."""
    try:
        cb = Codebook.load(task_dir, project)
        return any(
            any(d.get(f) for f in store.RICH_FIELDS)
            for d in cb.details_in_order())
    except Exception:  # pragma: no cover - defensive
        return False
