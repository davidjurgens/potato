"""
Reference-free LLM-as-judge trajectory evaluator.

Scores the *quality* of an agent trajectory (was the path sensible, were tools
used appropriately, did it reach a good answer) without requiring a gold
reference -- addressing the reality that many valid agent paths exist. A
reference may optionally be supplied and is included in the prompt when present.

Reuses ``AIEndpointFactory`` exactly like ``potato/ai/judge.py`` so it honors the
same provider config (openai/anthropic/ollama/vllm/...). An ``endpoint`` may be
injected for testing.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from potato.evaluators.base import Evaluator, EvaluationResult
from potato.evaluators.trajectory import normalize_trajectory

logger = logging.getLogger(__name__)

DEFAULT_TRAJECTORY_PROMPT = (
    "You are an expert evaluator judging the quality of an AI agent's trajectory.\n"
    "Consider whether the agent took sensible steps, used tools appropriately,\n"
    "avoided unnecessary or erroneous actions, and reached a correct, complete\n"
    "final answer for the task.\n"
)


def _render_trajectory(obj: Any) -> str:
    lines = []
    for step in normalize_trajectory(obj):
        if step.tool_calls:
            for tc in step.tool_calls:
                lines.append(f"[{step.role}] TOOL {tc.name}({json.dumps(tc.args, ensure_ascii=False)})")
        if step.content:
            lines.append(f"[{step.role}] {step.content}")
    return "\n".join(lines)


class LLMTrajectoryJudge(Evaluator):
    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        prompt: str = DEFAULT_TRAJECTORY_PROMPT,
        continuous: bool = False,
        endpoint: Any = None,
        key: str = "trajectory_accuracy",
    ):
        """
        Args:
            config: task config dict carrying ``ai_support`` (or
                ``judge_alignment.ai_support``), as ``AIEndpointFactory`` expects.
            prompt: rubric / instructions prepended to the rendered trajectory.
            continuous: if True ask for a 0.0-1.0 score; else a pass/fail boolean.
            endpoint: pre-built endpoint (bypasses factory; used in tests).
        """
        self.config = config or {}
        self.prompt = prompt
        self.continuous = continuous
        self._endpoint = endpoint
        self._endpoint_initialized = endpoint is not None
        self.key = key

    def _get_endpoint(self):
        if not self._endpoint_initialized:
            self._endpoint_initialized = True
            try:
                from potato.ai.ai_endpoint import AIEndpointFactory
                ai_support = self.config.get("judge_alignment", {}).get("ai_support") \
                    or self.config.get("ai_support")
                if not ai_support:
                    logger.warning("LLMTrajectoryJudge: no ai_support configured")
                    return None
                self._endpoint = AIEndpointFactory.create_endpoint({"ai_support": ai_support})
            except Exception as e:  # pragma: no cover - depends on provider libs
                logger.error(f"LLMTrajectoryJudge: failed to create endpoint: {e}")
                self._endpoint = None
        return self._endpoint

    def _build_prompt(self, outputs: Any, reference_outputs: Any, inputs: Any) -> str:
        parts = [self.prompt, ""]
        if inputs:
            parts.append(f"Task / input:\n{inputs}\n")
        parts.append("Agent trajectory:\n" + _render_trajectory(outputs))
        if reference_outputs:
            parts.append("\nReference trajectory (for comparison):\n" + _render_trajectory(reference_outputs))
        if self.continuous:
            parts.append(
                '\nRespond as JSON: {"score": <0.0-1.0>, "reasoning": <one sentence>}.'
            )
        else:
            parts.append(
                '\nRespond as JSON: {"pass": <true|false>, "reasoning": <one sentence>}.'
            )
        return "\n".join(parts)

    def evaluate(
        self,
        *,
        outputs: Any = None,
        reference_outputs: Any = None,
        inputs: Any = None,
        **kwargs: Any,
    ) -> EvaluationResult:
        endpoint = self._get_endpoint()
        if endpoint is None:
            return EvaluationResult(key=self.key, score=None, comment="no judge endpoint configured")

        prompt = self._build_prompt(outputs, reference_outputs, inputs)
        try:
            from pydantic import BaseModel

            if self.continuous:
                class Verdict(BaseModel):
                    score: float = 0.0
                    reasoning: str = ""
            else:
                class Verdict(BaseModel):
                    pass_: bool = False
                    reasoning: str = ""

            response = endpoint.query(prompt, Verdict)
            if isinstance(response, str):
                data = json.loads(response)
            elif hasattr(response, "model_dump"):
                data = response.model_dump()
            elif hasattr(response, "dict"):
                data = response.dict()
            else:
                data = response or {}
        except Exception as e:
            logger.error(f"LLMTrajectoryJudge: query/parse failed: {e}")
            return EvaluationResult(key=self.key, score=None, comment=f"judge error: {e}")

        reasoning = str(data.get("reasoning", ""))
        if self.continuous:
            try:
                score = min(1.0, max(0.0, float(data.get("score", 0.0))))
            except (TypeError, ValueError):
                score = None
            return EvaluationResult(key=self.key, score=score, value=score, comment=reasoning)

        passed = bool(data.get("pass", data.get("pass_", False)))
        return EvaluationResult(
            key=self.key, score=1.0 if passed else 0.0, value=passed, comment=reasoning,
        )
