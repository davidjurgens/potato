"""
Score a codebook variant with Laya (a local, non-generative decision
model) instead of an LLM, for multi-label tasks.

Each label becomes one yes/no (``noul``) question whose text is that
label's block from the real ``potato.codebook.prompt`` renderer. Laya
answers every question independently with P(yes), and a label is
predicted when P(yes) >= threshold. Because labels never see each
other's definitions, swapping one label's fields in a hybrid changes
only that label's predictions, which keeps the per-label comparison
clean.

Laya runs in its own venv behind a loopback sidecar (see
examples/advanced/codebook-lab-naacl-frames/laya_server.py); this module
only talks HTTP.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Dict, List, Tuple

from .models import CodebookVariant, ExamplePrediction, PlatinumExample, VariantScore

logger = logging.getLogger(__name__)

# The sidecar's /predict_batch caps a request at 64 states x 64 questions.
_STATES_PER_REQUEST = 32


def label_questions(
    variant: CodebookVariant, task_description: str = "",
) -> Dict[str, Dict[str, str]]:
    from potato.codebook.prompt import RenderOptions, _render_code

    opts = RenderOptions()
    questions = {}
    for i, code in enumerate(variant.codes):
        block = _render_code(code.to_codebook_row(i), opts) or f"### {code.name}"
        ask = f'Does this tweet use the "{code.name}" frame, as defined below?'
        if task_description:
            ask = task_description.strip() + " " + ask
        questions[f"q{i}"] = {"type": "noul", "instructions": ask + "\n" + block}
    return questions


def _post(base_url: str, path: str, payload: dict, timeout: int = 600) -> dict:
    req = urllib.request.Request(
        base_url.rstrip("/") + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def predict_probs(
    base_url: str, variant: CodebookVariant, examples: List[PlatinumExample],
    task_description: str = "", head_max_len: int = 400,
) -> Dict[str, Dict[str, float]]:
    """{example_id: {label: P(yes)}}"""
    questions = label_questions(variant, task_description)
    names = {f"q{i}": c.name for i, c in enumerate(variant.codes)}
    out: Dict[str, Dict[str, float]] = {}
    for start in range(0, len(examples), _STATES_PER_REQUEST):
        chunk = examples[start:start + _STATES_PER_REQUEST]
        data = _post(base_url, "/predict_batch", {
            "states": [ex.text for ex in chunk], "questions": questions,
            "head_max_len": head_max_len, "batch_size": 8})
        if "error" in data:
            raise RuntimeError(f"Laya sidecar: {data['error']}")
        for ex, res in zip(chunk, data["results"]):
            out[ex.example_id] = {
                names[qid]: float(a["noul"]) for qid, a in res["answers"].items()}
    return out


def score_from_probs(
    variant: CodebookVariant, examples: List[PlatinumExample],
    probs: Dict[str, Dict[str, float]], threshold: float = 0.5,
) -> VariantScore:
    labels = variant.label_names()
    preds = []
    for ex in examples:
        p = probs[ex.example_id]
        predicted = [l for l in labels if p[l] >= threshold]
        preds.append(ExamplePrediction(
            example_id=ex.example_id, true_label=ex.label,
            predicted_label=predicted[0] if predicted else None,
            correct=set(predicted) == set(ex.labels),
            confidence=max(p.values()) if p else 0.0,
            true_labels=list(ex.labels), predicted_labels=predicted))
    return VariantScore(variant.variant_id, preds, multi_label=True)


def score_variant_laya(
    base_url: str, variant: CodebookVariant, examples: List[PlatinumExample],
    task_description: str = "", head_max_len: int = 400, threshold: float = 0.5,
) -> Tuple[VariantScore, Dict[str, Dict[str, float]]]:
    probs = predict_probs(base_url, variant, examples, task_description, head_max_len)
    score = score_from_probs(variant, examples, probs, threshold)
    logger.info("Scored %s: %.1f%% macro-F1 (%d/%d exact)",
                variant.variant_id, score.overall_score * 100,
                sum(p.correct for p in score.predictions), len(examples))
    return score, probs
