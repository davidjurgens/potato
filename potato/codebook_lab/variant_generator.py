"""
Generate N codebook variants from a seed codebook via an LLM, each guided
by a "directive" that pushes the variant in a different, deliberate
direction — some should read as clear improvements, some as regressions,
some as lateral rewrites — so scoring later actually has a spread to work
with instead of N near-identical paraphrases.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from .endpoints import query_json
from .models import Code, CodebookVariant

logger = logging.getLogger(__name__)

# Cycled across the N variants (index % len(DIRECTIVES)) so a run with
# enough variants covers every direction at least once, rather than
# leaving the mix to per-call sampling luck.
DIRECTIVES: List[Dict[str, str]] = [
    {
        "key": "improve_clarity",
        "instruction": (
            "Improve this codebook overall: tighten every definition, add "
            "or sharpen exclusion rules that resolve real ambiguity "
            "between adjacent labels, and make worked examples more "
            "concrete. The result should be a clear improvement on every "
            "label, not just one."
        ),
    },
    {
        "key": "specialize_one_label",
        "instruction": (
            "Pick ONE label at random and make it excellent: a precise "
            "definition, sharp include/exclude rules, and strong worked "
            "examples for it specifically. Leave the other labels mostly "
            "as-is, or even slightly vaguer, so this variant ends up "
            "noticeably better on that one label than on the rest."
        ),
    },
    {
        "key": "introduce_regression",
        "instruction": (
            "Weaken this codebook: remove or vague-up one or two "
            "exclusion rules that currently resolve confusion between "
            "similar labels, so the boundary between them gets blurrier. "
            "Keep everything else close to the original — this should "
            "read as a plausible but worse edit, not an obvious sabotage."
        ),
    },
    {
        "key": "shorten_all",
        "instruction": (
            "Drastically shorten every definition, clarification, and "
            "example across all labels — aim for roughly half the "
            "original length everywhere. Preserve the core meaning but "
            "drop supporting detail and nuance."
        ),
    },
    {
        "key": "faithful_paraphrase",
        "instruction": (
            "Reword this codebook's language throughout (different "
            "phrasing, same structure and level of detail) without "
            "meaningfully changing what it means or how strict its rules "
            "are. This variant should score close to the original."
        ),
    },
    {
        "key": "expand_scope_overlap",
        "instruction": (
            "Pick one label and broaden its 'include' language so it "
            "starts to overlap with a neighboring label's territory — "
            "e.g. loosen a boundary condition. This should make that "
            "label and its neighbor harder to tell apart than in the "
            "original."
        ),
    },
]


class _GeneratedCode(BaseModel):
    name: str
    definition: str = ""
    clarification: str = ""
    negative_clarification: str = ""
    positive_examples: List[Dict[str, str]] = []
    negative_examples: List[Dict[str, str]] = []
    exclusion_rules: List[str] = []


class _GeneratedCodebook(BaseModel):
    codes: List[_GeneratedCode]
    summary: str = ""  # brief note on what actually changed, for notes


_PROMPT_TEMPLATE = """You are helping design experiments on annotation codebook quality.

Here is a seed codebook (one label per section, JSON below):
{seed_json}

Task: {directive}

Requirements:
- Keep exactly the same set of label names, in the same order: {label_names}
- Every label must still have a definition (don't leave any blank).
- Return the FULL codebook (all labels), not just the ones you changed.
- "summary" should be one sentence describing what you actually did.

Respond with JSON matching this shape:
{{
  "codes": [
    {{
      "name": "<label name, unchanged>",
      "definition": "<...>",
      "clarification": "<include rules, or empty string>",
      "negative_clarification": "<exclude rules, or empty string>",
      "positive_examples": [{{"text": "<...>", "why": "<...>"}}],
      "negative_examples": [{{"text": "<...>", "why": "<...>"}}],
      "exclusion_rules": ["<...>"]
    }}
  ],
  "summary": "<one sentence>"
}}
"""


def _seed_json(seed: List[Code]) -> str:
    import json
    return json.dumps([c.to_dict() for c in seed], indent=2, ensure_ascii=False)


def generate_variant(
    endpoint: Any, seed: List[Code], variant_id: str, directive: Dict[str, str],
) -> CodebookVariant:
    """One LLM call: produce one variant of ``seed`` under ``directive``.
    Raises on a malformed/incomplete response rather than silently
    falling back to the seed — a silently-unchanged "variant" would
    corrupt the accuracy comparison downstream."""
    label_names = [c.name for c in seed]
    prompt = _PROMPT_TEMPLATE.format(
        seed_json=_seed_json(seed),
        directive=directive["instruction"],
        label_names=", ".join(label_names),
    )
    data = query_json(endpoint, prompt, _GeneratedCodebook)
    codes = [Code.from_dict(c) for c in data.get("codes", [])]
    got_names = {c.name for c in codes}
    missing = set(label_names) - got_names
    if missing:
        raise ValueError(
            f"Variant {variant_id} ({directive['key']}) dropped label(s) "
            f"{missing} — discarding this variant rather than scoring an "
            f"incomplete codebook")
    # Reorder to match the seed's label order regardless of what order
    # the model returned them in, and drop any label it hallucinated
    # that wasn't in the seed.
    by_name = {c.name: c for c in codes}
    ordered = [by_name[name] for name in label_names]
    return CodebookVariant(
        variant_id=variant_id,
        codes=ordered,
        origin=f"llm:{directive['key']}",
        notes=data.get("summary", ""),
    )


def generate_variants(
    endpoint: Any, seed: List[Code], n: int,
) -> List[CodebookVariant]:
    """Generate N variants, cycling through DIRECTIVES for a controlled
    spread of improved/worsened/lateral changes. A variant whose
    generation call fails (bad JSON, dropped label) is logged and
    skipped rather than aborting the whole batch — a partial batch is
    still useful; run again with a larger N to make up the shortfall."""
    variants: List[CodebookVariant] = []
    for i in range(n):
        directive = DIRECTIVES[i % len(DIRECTIVES)]
        variant_id = f"v{i + 1:02d}_{directive['key']}"
        try:
            variants.append(generate_variant(endpoint, seed, variant_id, directive))
            logger.info("Generated %s", variant_id)
        except Exception:
            logger.exception("Failed to generate variant %s — skipping", variant_id)
    return variants
