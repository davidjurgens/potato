"""
DAG (decision-tree) rubric evaluator.

A config-defined decision tree the LLM judge traverses node by node. At each node
the judge answers a discrete question; the chosen branch leads either to another
node or to a leaf carrying a *fixed* score. This makes scoring **deterministic and
auditable** (the leaf scores are authored, not invented by the model) and
**human-in-the-loop friendly**: the full traversed path is recorded, so an
annotator can correct a single branch decision instead of re-grading the whole
output.

Inspired by DeepEval's DAGMetric. Reuses ``AIEndpointFactory`` like the other
LLM evaluators, so it honors the same provider config and accepts an injected
``endpoint`` for testing.

Config shape::

    rubric_dag:
      key: answer_quality          # metric name (optional)
      root: has_answer
      nodes:
        has_answer:
          question: "Does the response directly answer the question?"
          choices: [yes, no]
          branches:
            yes: cites_sources                 # -> another node
            no:  {score: 0.0, label: "no answer"}   # -> leaf
        cites_sources:
          question: "Does it cite supporting sources?"
          choices: [yes, no]
          branches:
            yes: {score: 1.0, label: "complete"}
            no:  {score: 0.6, label: "unsourced"}
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from potato.evaluators.base import Evaluator, EvaluationResult

logger = logging.getLogger(__name__)

MAX_DEPTH = 25  # guard against a misconfigured cyclic tree


class RubricDagEvaluator(Evaluator):
    def __init__(
        self,
        dag: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
        endpoint: Any = None,
        key: Optional[str] = None,
    ):
        self.dag = dag or {}
        self.config = config or {}
        self._endpoint = endpoint
        self._endpoint_initialized = endpoint is not None
        self.key = key or self.dag.get("key", "rubric_dag")
        self.root = self.dag.get("root")
        self.nodes = self.dag.get("nodes", {}) or {}

    # ----- endpoint (mirrors potato/ai/judge.py + llm_judge.py) -----
    def _get_endpoint(self):
        if not self._endpoint_initialized:
            self._endpoint_initialized = True
            try:
                from potato.ai.ai_endpoint import AIEndpointFactory
                ai_support = self.config.get("judge_alignment", {}).get("ai_support") \
                    or self.config.get("ai_support")
                if not ai_support:
                    logger.warning("RubricDagEvaluator: no ai_support configured")
                    return None
                self._endpoint = AIEndpointFactory.create_endpoint({"ai_support": ai_support})
            except Exception as e:  # pragma: no cover - provider-dependent
                logger.error(f"RubricDagEvaluator: failed to create endpoint: {e}")
                self._endpoint = None
        return self._endpoint

    @staticmethod
    def _is_leaf(branch: Any) -> bool:
        return isinstance(branch, dict) and "score" in branch

    def _ask(self, endpoint, node: Dict[str, Any], context: str) -> Optional[str]:
        """Ask the judge the node's question, constrained to its choices."""
        choices: List[str] = [str(c) for c in node.get("choices", [])]
        if not choices:
            return None
        prompt = (
            "You are evaluating an AI output against a rubric. Answer the single "
            "question below by choosing EXACTLY ONE of the allowed options.\n\n"
            f"{context}\n\n"
            f"Question: {node.get('question', '')}\n"
            f"Allowed options: {', '.join(choices)}\n\n"
            'Respond as JSON: {"choice": "<one of the allowed options>", '
            '"reasoning": "<one sentence>"}.'
        )
        raw = ""
        data: Dict[str, Any] = {}
        try:
            from pydantic import BaseModel

            class NodeVerdict(BaseModel):
                choice: str = ""
                reasoning: str = ""

            response = endpoint.query(prompt, NodeVerdict)
            if isinstance(response, str):
                raw = response
                try:
                    # Robust parse (strips ```json fences, <think> blocks, prose).
                    if hasattr(endpoint, "parseStringToJson"):
                        data = endpoint.parseStringToJson(response)
                    else:
                        data = json.loads(response)
                    if not isinstance(data, dict):
                        data = {}
                except (ValueError, TypeError):
                    data = {}
            elif hasattr(response, "model_dump"):
                data = response.model_dump()
            elif hasattr(response, "dict"):
                data = response.dict()
            else:
                data = response or {}
        except Exception as e:
            logger.error(f"RubricDagEvaluator: node query failed: {e}")
            return (None, "")

        choice = str(data.get("choice", "")).strip()
        reasoning = str(data.get("reasoning", ""))
        resolved = self._match_choice(choice, choices)
        # Recover the choice from raw text ONLY when structured parsing produced
        # nothing usable (a model that ignored JSON response_format). If the model
        # DID return structured data with an empty/invalid choice, respect that as
        # "no valid choice" rather than scanning the reasoning for a stray token.
        if resolved is None and not data and raw:
            resolved = self._match_choice(raw, choices)
        return (resolved, reasoning)

    @staticmethod
    def _match_choice(text: str, choices: List[str]) -> Optional[str]:
        """Resolve free text to one of the allowed choices (exact, case-insensitive,
        then substring), preferring the longest matching option."""
        if not text:
            return None
        text = text.strip()
        if text in choices:
            return text
        lower = {c.lower(): c for c in choices}
        if text.lower() in lower:
            return lower[text.lower()]
        hits = [c for c in choices if c.lower() in text.lower()]
        return max(hits, key=len) if hits else None

    def _context(self, outputs: Any, reference_outputs: Any, inputs: Any) -> str:
        parts = []
        if inputs:
            parts.append(f"Task / input:\n{inputs}")
        parts.append(f"Output to evaluate:\n{outputs}")
        if reference_outputs:
            parts.append(f"Reference / expected:\n{reference_outputs}")
        return "\n\n".join(parts)

    def evaluate(self, *, outputs: Any = None, reference_outputs: Any = None,
                 inputs: Any = None, **kwargs: Any) -> EvaluationResult:
        if not self.root or self.root not in self.nodes:
            return EvaluationResult(key=self.key, score=None,
                                    comment="rubric_dag misconfigured: missing/invalid root")
        endpoint = self._get_endpoint()
        if endpoint is None:
            return EvaluationResult(key=self.key, score=None,
                                    comment="no judge endpoint configured")

        context = self._context(outputs, reference_outputs, inputs)
        path: List[Dict[str, Any]] = []
        node_name = self.root
        for _ in range(MAX_DEPTH):
            node = self.nodes.get(node_name)
            if not node:
                return EvaluationResult(key=self.key, score=None,
                                        comment=f"unknown node '{node_name}'", metadata={"path": path})
            choice, reasoning = self._ask(endpoint, node, context)
            if choice is None:
                return EvaluationResult(key=self.key, score=None,
                                        comment=f"judge gave no valid choice at '{node_name}'",
                                        metadata={"path": path})
            path.append({"node": node_name, "question": node.get("question", ""),
                         "choice": choice, "reasoning": reasoning})
            branch = (node.get("branches") or {}).get(choice)
            if branch is None:
                return EvaluationResult(key=self.key, score=None,
                                        comment=f"no branch for choice '{choice}' at '{node_name}'",
                                        metadata={"path": path})
            if self._is_leaf(branch):
                score = float(branch["score"])
                label = branch.get("label", "")
                return EvaluationResult(
                    key=self.key, score=score, value=label,
                    comment=label or f"score={score}",
                    metadata={"path": path, "leaf": {"score": score, "label": label}},
                )
            node_name = str(branch)  # traverse to the next node
        return EvaluationResult(key=self.key, score=None,
                                comment="max depth exceeded (cyclic rubric_dag?)",
                                metadata={"path": path})


# ----- reusable rubric library -----------------------------------------------
# Small, named DAGs projects can use out of the box or copy as a starting point.
RUBRIC_PRESETS: Dict[str, Dict[str, Any]] = {
    "answer_quality": {
        "key": "answer_quality",
        "root": "answers",
        "nodes": {
            "answers": {
                "question": "Does the response directly and correctly answer the question?",
                "choices": ["yes", "partially", "no"],
                "branches": {
                    "yes": "grounded",
                    "partially": {"score": 0.5, "label": "partial answer"},
                    "no": {"score": 0.0, "label": "does not answer"},
                },
            },
            "grounded": {
                "question": "Is the answer well-supported (no unsupported or fabricated claims)?",
                "choices": ["yes", "no"],
                "branches": {
                    "yes": {"score": 1.0, "label": "correct & grounded"},
                    "no": {"score": 0.7, "label": "correct but unsupported"},
                },
            },
        },
    },
}


def make_rubric_dag(config: Dict[str, Any], dag: Optional[Dict[str, Any]] = None,
                    preset: Optional[str] = None, endpoint: Any = None) -> RubricDagEvaluator:
    """Factory: build from an explicit ``dag``, or a named ``preset`` from the
    rubric library. An explicit dag wins over a preset."""
    if dag is None and preset:
        if preset not in RUBRIC_PRESETS:
            raise KeyError(f"Unknown rubric preset '{preset}'. "
                           f"Available: {', '.join(sorted(RUBRIC_PRESETS))}")
        dag = RUBRIC_PRESETS[preset]
    return RubricDagEvaluator(dag=dag or {}, config=config, endpoint=endpoint)
