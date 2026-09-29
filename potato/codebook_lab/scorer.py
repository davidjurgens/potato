"""
Score one codebook variant against a fixed platinum example set.

Renders the variant through the *real* potato.codebook.prompt pipeline
(the same renderer Solo Mode uses at labeling time) so the accuracy
numbers reflect exactly what the model would see in production, not an
approximation of it.
"""

from __future__ import annotations

import logging
from typing import Any, List

from pydantic import BaseModel

from .endpoints import query_json
from .models import CodebookVariant, ExamplePrediction, PlatinumExample, VariantScore

logger = logging.getLogger(__name__)


class _ScoreResponse(BaseModel):
    label: str
    confidence: float = 50.0
    reasoning: str = ""


_PROMPT_TEMPLATE = """{task_description}

{codebook_section}Text to label:
{text}

Available labels: {labels}

Respond with JSON:
{{
    "label": "<your label>",
    "confidence": <0-100>,
    "reasoning": "<brief explanation>"
}}
"""


def _render_codebook_section(variant: CodebookVariant) -> str:
    from potato.codebook.codebook import Codebook
    from potato.codebook.prompt import render_from_codebook

    cb = Codebook("codebook_lab", variant.codebook_rows())
    section = render_from_codebook(cb)
    return (section + "\n\n") if section else ""


def _normalize(label: str) -> str:
    return " ".join(label.strip().lower().split())


def score_example(
    endpoint: Any, variant: CodebookVariant, codebook_section: str,
    task_description: str, example: PlatinumExample,
) -> ExamplePrediction:
    labels = variant.label_names()
    prompt = _PROMPT_TEMPLATE.format(
        task_description=task_description,
        codebook_section=codebook_section,
        text=example.text,
        labels=", ".join(labels),
    )
    try:
        data = query_json(endpoint, prompt, _ScoreResponse)
    except Exception as e:
        logger.warning(
            "Scoring call failed for variant=%s example=%s: %s",
            variant.variant_id, example.example_id, e)
        return ExamplePrediction(
            example_id=example.example_id, true_label=example.label,
            predicted_label=None, correct=False, error=str(e))

    raw_label = str(data.get("label", ""))
    by_norm = {_normalize(l): l for l in labels}
    predicted = by_norm.get(_normalize(raw_label), raw_label)
    correct = _normalize(predicted) == _normalize(example.label)

    return ExamplePrediction(
        example_id=example.example_id, true_label=example.label,
        predicted_label=predicted, correct=correct,
        confidence=float(data.get("confidence", 0.0)) / 100.0,
        reasoning=str(data.get("reasoning", "")),
    )


def score_variant(
    endpoint: Any, variant: CodebookVariant, task_description: str,
    examples: List[PlatinumExample],
) -> VariantScore:
    codebook_section = _render_codebook_section(variant)
    predictions = [
        score_example(endpoint, variant, codebook_section, task_description, ex)
        for ex in examples
    ]
    score = VariantScore(variant_id=variant.variant_id, predictions=predictions)
    logger.info(
        "Scored %s: %.1f%% overall (%d/%d)",
        variant.variant_id, score.overall_accuracy * 100,
        sum(p.correct for p in predictions), len(predictions))
    return score
