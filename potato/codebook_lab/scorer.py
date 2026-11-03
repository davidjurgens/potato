"""
Score one codebook variant against a fixed platinum example set.

Renders the variant through the *real* potato.codebook.prompt pipeline
(the same renderer Solo Mode uses at labeling time) so the accuracy
numbers reflect exactly what the model would see in production, not an
approximation of it.
"""

from __future__ import annotations

import logging
from typing import Any, List, Tuple

from pydantic import BaseModel

from .endpoints import query_json
from .models import CodebookVariant, ExamplePrediction, PlatinumExample, VariantScore

logger = logging.getLogger(__name__)


class _ScoreResponse(BaseModel):
    label: str
    confidence: float = 50.0
    reasoning: str = ""


class _MultiScoreResponse(BaseModel):
    labels: List[str]
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

_MULTI_PROMPT_TEMPLATE = """{task_description}

{codebook_section}Text to label:
{text}

Available labels: {labels}

Select every label that applies (one or more), using only the label names
listed above.

Respond with JSON:
{{
    "labels": ["<label>", ...],
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
    multi_label: bool = False,
) -> ExamplePrediction:
    if multi_label:
        return _score_example_multi(
            endpoint, variant, codebook_section, task_description, example)
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


def _canonicalize(
    raw_labels: Any, labels: List[str],
) -> Tuple[List[str], List[str]]:
    """Map the model's raw label strings onto codebook names. Returns
    (valid, invalid): valid is de-duplicated in codebook order; invalid
    keeps whatever the model made up, so over-/hallucinated labeling is
    visible in the score file rather than silently dropped."""
    if isinstance(raw_labels, str):
        raw_labels = [raw_labels]
    by_norm = {_normalize(l): l for l in labels}
    found, invalid = set(), []
    for raw in raw_labels or []:
        canon = by_norm.get(_normalize(str(raw)))
        if canon:
            found.add(canon)
        elif str(raw).strip():
            invalid.append(str(raw))
    return [l for l in labels if l in found], invalid


def _score_example_multi(
    endpoint: Any, variant: CodebookVariant, codebook_section: str,
    task_description: str, example: PlatinumExample,
) -> ExamplePrediction:
    labels = variant.label_names()
    prompt = _MULTI_PROMPT_TEMPLATE.format(
        task_description=task_description,
        codebook_section=codebook_section,
        text=example.text,
        labels=", ".join(labels),
    )
    try:
        data = query_json(endpoint, prompt, _MultiScoreResponse)
    except Exception as e:
        logger.warning(
            "Scoring call failed for variant=%s example=%s: %s",
            variant.variant_id, example.example_id, e)
        return ExamplePrediction(
            example_id=example.example_id, true_label=example.label,
            predicted_label=None, correct=False, error=str(e),
            true_labels=list(example.labels))

    predicted, invalid = _canonicalize(data.get("labels"), labels)
    correct = set(predicted) == set(example.labels) and not invalid

    return ExamplePrediction(
        example_id=example.example_id, true_label=example.label,
        predicted_label=predicted[0] if predicted else None,
        correct=correct,
        confidence=float(data.get("confidence", 0.0)) / 100.0,
        reasoning=str(data.get("reasoning", "")),
        true_labels=list(example.labels),
        predicted_labels=predicted,
        invalid_labels=invalid,
    )


def score_variant(
    endpoint: Any, variant: CodebookVariant, task_description: str,
    examples: List[PlatinumExample], multi_label: bool = False,
) -> VariantScore:
    codebook_section = _render_codebook_section(variant)
    predictions = [
        score_example(endpoint, variant, codebook_section, task_description,
                      ex, multi_label=multi_label)
        for ex in examples
    ]
    score = VariantScore(
        variant_id=variant.variant_id, predictions=predictions,
        multi_label=multi_label)
    logger.info(
        "Scored %s: %.1f%% %s (%d/%d exact)",
        variant.variant_id, score.overall_score * 100,
        "macro-F1" if multi_label else "overall",
        sum(p.correct for p in predictions), len(predictions))
    return score
