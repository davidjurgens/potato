"""
RAG triad + reference-free judge metrics.

The three most-adopted reference-free RAG metrics (TruLens/Ragas/Phoenix), as
Potato evaluators:

- **Context relevance** — is the retrieved context relevant to the question?
- **Groundedness / faithfulness** — is the answer supported by the context (no
  hallucination)? Computed by **claim decomposition**: the answer is split into
  atomic claims and each is checked against the context, so the score is
  ``supported / total`` and every claim verdict is recorded — a natural
  human-in-the-loop adjudication target (a span-style task Potato excels at).
- **Answer relevance** — does the answer actually address the question?

All three are reference-free (no gold answer needed). They reuse
``AIEndpointFactory`` exactly like ``potato/ai/judge.py`` and accept an injected
``endpoint`` for testing.

Inputs convention: the question comes from ``inputs`` (or ``inputs[question_key]``
when ``inputs`` is a dict), the answer from ``outputs``, and the retrieved context
from the ``context=`` kwarg (or ``inputs[context_key]``).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from potato.evaluators.base import Evaluator, EvaluationResult

logger = logging.getLogger(__name__)


class _JudgeBacked(Evaluator):
    """Shared judge-endpoint plumbing for the reference-free metrics."""

    def __init__(self, config: Optional[Dict[str, Any]] = None, endpoint: Any = None,
                 question_key: str = "question", context_key: str = "context",
                 key: Optional[str] = None):
        self.config = config or {}
        self._endpoint = endpoint
        self._endpoint_initialized = endpoint is not None
        self.question_key = question_key
        self.context_key = context_key
        if key:
            self.key = key

    def _get_endpoint(self):
        if not self._endpoint_initialized:
            self._endpoint_initialized = True
            try:
                from potato.ai.ai_endpoint import AIEndpointFactory
                ai_support = self.config.get("judge_alignment", {}).get("ai_support") \
                    or self.config.get("ai_support")
                if not ai_support:
                    logger.warning(f"{type(self).__name__}: no ai_support configured")
                    return None
                self._endpoint = AIEndpointFactory.create_endpoint({"ai_support": ai_support})
            except Exception as e:  # pragma: no cover - provider-dependent
                logger.error(f"{type(self).__name__}: failed to create endpoint: {e}")
                self._endpoint = None
        return self._endpoint

    def _resolve(self, outputs, inputs, kwargs):
        question = inputs
        context = kwargs.get("context")
        if isinstance(inputs, dict):
            question = inputs.get(self.question_key, inputs.get("text", ""))
            if context is None:
                context = inputs.get(self.context_key)
        return str(question or ""), str(outputs or ""), str(context or "")

    def _query_json(self, prompt: str, model) -> Optional[dict]:
        endpoint = self._get_endpoint()
        if endpoint is None:
            return None
        try:
            response = endpoint.query(prompt, model)
            if isinstance(response, str):
                # Robust parse: models often wrap JSON in ```json fences or prose;
                # the endpoint's parser strips those (and <think> blocks etc.).
                if hasattr(endpoint, "parseStringToJson"):
                    return endpoint.parseStringToJson(response)
                return json.loads(response)
            if hasattr(response, "model_dump"):
                return response.model_dump()
            if hasattr(response, "dict"):
                return response.dict()
            return response or {}
        except Exception as e:
            logger.error(f"{type(self).__name__}: query/parse failed: {e}")
            return None


class ContextRelevanceEvaluator(_JudgeBacked):
    key = "context_relevance"

    def evaluate(self, *, outputs=None, reference_outputs=None, inputs=None, **kwargs):
        question, _answer, context = self._resolve(outputs, inputs, kwargs)
        if not context:
            return EvaluationResult(key=self.key, score=None, comment="no context provided")
        prompt = (
            "Rate how RELEVANT the retrieved context is for answering the question.\n"
            "1.0 = fully relevant and sufficient; 0.0 = irrelevant.\n\n"
            f"Question:\n{question}\n\nRetrieved context:\n{context}\n\n"
            'Respond as JSON: {"score": <0.0-1.0>, "reasoning": "<one sentence>"}.'
        )
        return self._score_result(prompt)

    def _score_result(self, prompt):
        from pydantic import BaseModel

        class Verdict(BaseModel):
            score: float = 0.0
            reasoning: str = ""

        data = self._query_json(prompt, Verdict)
        if data is None:
            return EvaluationResult(key=self.key, score=None, comment="judge unavailable")
        try:
            score = min(1.0, max(0.0, float(data.get("score", 0.0))))
        except (TypeError, ValueError):
            score = None
        return EvaluationResult(key=self.key, score=score, value=score,
                                comment=str(data.get("reasoning", "")))


class AnswerRelevanceEvaluator(_JudgeBacked):
    key = "answer_relevance"

    def evaluate(self, *, outputs=None, reference_outputs=None, inputs=None, **kwargs):
        question, answer, _context = self._resolve(outputs, inputs, kwargs)
        prompt = (
            "Rate how well the ANSWER addresses the question (regardless of factual\n"
            "correctness). 1.0 = directly and completely answers; 0.0 = off-topic.\n\n"
            f"Question:\n{question}\n\nAnswer:\n{answer}\n\n"
            'Respond as JSON: {"score": <0.0-1.0>, "reasoning": "<one sentence>"}.'
        )
        return ContextRelevanceEvaluator._score_result(self, prompt)


class GroundednessEvaluator(_JudgeBacked):
    """Faithfulness via claim decomposition: split the answer into atomic claims,
    verify each against the context. Score = supported / total."""

    key = "groundedness"

    def evaluate(self, *, outputs=None, reference_outputs=None, inputs=None, **kwargs):
        _question, answer, context = self._resolve(outputs, inputs, kwargs)
        if not answer:
            return EvaluationResult(key=self.key, score=None, comment="empty answer")
        if not context:
            return EvaluationResult(key=self.key, score=None, comment="no context provided")

        prompt = (
            "Decompose the ANSWER into atomic factual claims, then judge whether each\n"
            "claim is SUPPORTED by the context (true only if the context entails it).\n\n"
            f"Context:\n{context}\n\nAnswer:\n{answer}\n\n"
            'Respond as JSON: {"claims": [{"claim": "<text>", "supported": <true|false>}], '
            '"reasoning": "<one sentence>"}.'
        )
        from pydantic import BaseModel

        class Claim(BaseModel):
            claim: str = ""
            supported: bool = False

        class Verdict(BaseModel):
            claims: List[Claim] = []
            reasoning: str = ""

        data = self._query_json(prompt, Verdict)
        if data is None:
            return EvaluationResult(key=self.key, score=None, comment="judge unavailable")
        claims = data.get("claims") or []
        if not claims:
            return EvaluationResult(key=self.key, score=None,
                                    comment="no claims extracted", metadata={"claims": []})
        supported = sum(1 for c in claims if (c.get("supported") if isinstance(c, dict) else getattr(c, "supported", False)))
        total = len(claims)
        score = supported / total if total else None
        return EvaluationResult(
            key=self.key, score=score, value=f"{supported}/{total} claims supported",
            comment=str(data.get("reasoning", "")),
            metadata={"claims": [c if isinstance(c, dict) else {"claim": c.claim, "supported": c.supported}
                                 for c in claims], "supported": supported, "total": total},
        )


def rag_triad(config: Dict[str, Any], endpoint: Any = None, **opts):
    """Convenience: the three RAG-triad evaluators as a dict, sharing one config."""
    return {
        "context_relevance": ContextRelevanceEvaluator(config, endpoint=endpoint, **opts),
        "groundedness": GroundednessEvaluator(config, endpoint=endpoint, **opts),
        "answer_relevance": AnswerRelevanceEvaluator(config, endpoint=endpoint, **opts),
    }
