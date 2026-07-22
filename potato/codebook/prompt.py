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
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from potato.codebook import store
from potato.codebook.codebook import Codebook

logger = logging.getLogger(__name__)


@dataclass
class RenderOptions:
    """Distill options for rendering a codebook into a prompt section.

    Mirrors ``potato.solo_mode.config.DistillConfig`` field-for-field, but
    lives here too so the (universal) codebook package doesn't have to
    import solo_mode just to render. Callers pass either one — see
    ``_as_options()``.
    """
    show_examples: bool = True
    max_examples: int = 5
    include_rationale: bool = True
    summarize_above_tokens: int = 400


def _as_options(options: Any) -> RenderOptions:
    if isinstance(options, RenderOptions):
        return options
    if options is None:
        return RenderOptions()
    # Duck-type: DistillConfig or a plain dict with the same field names.
    get = options.get if isinstance(options, dict) else (
        lambda k, d: getattr(options, k, d))
    defaults = RenderOptions()
    return RenderOptions(
        show_examples=get('show_examples', defaults.show_examples),
        max_examples=get('max_examples', defaults.max_examples),
        include_rationale=get('include_rationale', defaults.include_rationale),
        summarize_above_tokens=get(
            'summarize_above_tokens', defaults.summarize_above_tokens),
    )

# A short standing instruction that frames the codebook and directly
# counters the lexical-overlap failure mode the error analysis found.
_GUARD = (
    "Decide each label from its Definition, Include and Exclude rules "
    "below — NOT from surface wording. A keyword appearing in the text "
    "(e.g. a code's name) is not sufficient; the text must satisfy the "
    "code's definition. Pay special attention to the Exclude rules and "
    "the \"Do NOT apply when\" rules that separate similar codes."
)


def _render_code(
    detail: Dict[str, Any], options: RenderOptions,
    summarize: Optional[Any] = None,
) -> Optional[str]:
    """Render one code's block, or None if it has no structured content.

    ``summarize``, if given, is called as ``summarize(code_id, field,
    text)`` for each prose field and may return a shorter substitute (used
    when the field exceeds ``options.summarize_above_tokens``); the full
    text is always what's stored, only the rendered prompt is shortened.
    """
    lines: List[str] = []
    name = detail.get("name") or ""
    code_id = detail.get("id")

    def add(field: str, fmt: str) -> None:
        val = detail.get(field)
        if not val:
            return
        val = str(val)
        if summarize is not None and _tokens(val) > options.summarize_above_tokens:
            val = summarize(code_id, field, val) or val
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

    if options.show_examples:
        pos = [_example(ex) for ex in detail.get("positive_examples") or []]
        pos = [p for p in pos if p][:max(options.max_examples, 0)]
        for text, why in pos:
            suffix = f" — {why}" if (why and options.include_rationale) else ""
            lines.append(f'✓ Example: "{text}"' + suffix)

        neg = [_example(ex) for ex in detail.get("negative_examples") or []]
        neg = [n for n in neg if n][:max(options.max_examples, 0)]
        for text, why in neg:
            suffix = f" — {why}" if (why and options.include_rationale) else ""
            lines.append(f'✗ Looks like this code but is NOT: "{text}"' + suffix)

    rules = [str(r).strip() for r in (detail.get("exclusion_rules") or [])
             if str(r).strip()]
    if rules:
        lines.append("Do NOT apply when:")
        lines.extend(f"  • {r}" for r in rules)

    if not lines:
        return None
    return f"### {name}\n" + "\n".join(lines)


def _tokens(text: str) -> int:
    """Cheap token-count heuristic (whitespace split). Good enough for a
    render-time length threshold — not used for any billing/context math."""
    return len(text.split())


def render_from_codebook(
    cb: Codebook, options: Any = None, summarize: Optional[Any] = None,
) -> str:
    """Render the structured block from an already-loaded Codebook (no
    DB hit). Returns "" when no code carries any structured field.

    ``options`` accepts a ``RenderOptions``, a
    ``potato.solo_mode.config.DistillConfig``, a plain dict of the same
    fields, or None (defaults). ``summarize`` is an optional
    ``(code_id, field, text) -> str`` callback for length-k summarization
    of over-long prose fields (see ``summarizer.py``).
    """
    opts = _as_options(options)
    blocks: List[str] = []
    for detail in cb.details_in_order():
        block = _render_code(detail, opts, summarize=summarize)
        if block:
            blocks.append(block)
    if not blocks:
        return ""
    return "## Codebook\n\n" + _GUARD + "\n\n" + "\n\n".join(blocks)


def render_codebook_section(
    task_dir: str, project: str, options: Any = None,
    summarize: Optional[Any] = None,
) -> str:
    """Build the structured codebook block for a project, or "" if the
    codebook has no structured fields yet. Best-effort: never raises into
    the prompt path (a render failure must not break labeling)."""
    try:
        cb = Codebook.load(task_dir, project)
        return render_from_codebook(cb, options=options, summarize=summarize)
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
