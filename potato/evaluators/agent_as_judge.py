"""
Agent-as-a-Judge: per-requirement trajectory evaluation with a human spot-check loop.

Where a flat LLM judge emits one holistic score for a final answer, an
**agent-as-judge** inspects the *intermediate steps* and judges the trajectory
against each acceptance **requirement** separately, citing evidence. This aligns
far better with human judgment on complex agent tasks (Zhuge et al. 2024,
"Agent-as-a-Judge": ~90% human alignment per-requirement vs ~70% for a flat judge).

Every per-requirement verdict is a discrete, evidence-backed claim — the natural
unit for a **human spot-check**: an annotator confirms or overrides each verdict,
and those corrections feed the judge↔human alignment corpus (see
``potato/server_utils/judge_alignment.py``).

Reuses the shared judge-endpoint plumbing and the trajectory renderer.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from potato.evaluators.base import EvaluationResult
from potato.evaluators.rag_triad import _JudgeBacked
from potato.evaluators.llm_judge import _render_trajectory

logger = logging.getLogger(__name__)


class AgentAsJudgeEvaluator(_JudgeBacked):
    """Judge an agent trajectory against a checklist of requirements.

    Requirements come from the ``requirements`` param, or from
    ``inputs[requirements_key]`` when inputs is a dict. The task/goal comes from
    ``inputs`` (or ``inputs[question_key]``); the trajectory from ``outputs``.
    Score = fraction of requirements satisfied.
    """

    key = "agent_as_judge"

    def __init__(self, config=None, endpoint=None, requirements: Optional[List[str]] = None,
                 requirements_key: str = "requirements", **kw):
        super().__init__(config=config, endpoint=endpoint, **kw)
        self.requirements = requirements
        self.requirements_key = requirements_key

    def _resolve_requirements(self, inputs, kwargs) -> List[str]:
        reqs = kwargs.get("requirements") or self.requirements
        if not reqs and isinstance(inputs, dict):
            reqs = inputs.get(self.requirements_key)
        if isinstance(reqs, str):
            reqs = [reqs]
        return [str(r) for r in (reqs or []) if str(r).strip()]

    def evaluate(self, *, outputs=None, reference_outputs=None, inputs=None, **kwargs):
        requirements = self._resolve_requirements(inputs, kwargs)
        if not requirements:
            return EvaluationResult(key=self.key, score=None,
                                    comment="no requirements provided")
        task = inputs.get(self.question_key, inputs.get("text", "")) if isinstance(inputs, dict) else inputs
        trajectory = _render_trajectory(outputs)
        numbered = "\n".join(f"{i+1}. {r}" for i, r in enumerate(requirements))
        prompt = (
            "You are an expert evaluator acting as an AGENT-AS-JUDGE. Inspect the "
            "agent's full trajectory (its intermediate steps, tool calls, and final "
            "answer) and judge whether it satisfies EACH requirement below. Cite the "
            "evidence (which step) for each verdict.\n\n"
            f"Task / goal:\n{task}\n\n"
            f"Agent trajectory:\n{trajectory}\n\n"
            f"Requirements:\n{numbered}\n\n"
            'Respond as JSON: {"verdicts": [{"requirement": "<text>", '
            '"satisfied": <true|false>, "evidence": "<step / why>"}], '
            '"reasoning": "<one sentence overall>"}.'
        )
        from pydantic import BaseModel

        class Verdict(BaseModel):
            requirement: str = ""
            satisfied: bool = False
            evidence: str = ""

        class Report(BaseModel):
            verdicts: List[Verdict] = []
            reasoning: str = ""

        data = self._query_json(prompt, Report)
        if data is None:
            return EvaluationResult(key=self.key, score=None, comment="judge unavailable")
        verdicts = data.get("verdicts") or []
        if not verdicts:
            return EvaluationResult(key=self.key, score=None,
                                    comment="judge returned no verdicts",
                                    metadata={"requirements": requirements})

        norm = []
        for v in verdicts:
            if isinstance(v, dict):
                norm.append({"requirement": v.get("requirement", ""),
                             "satisfied": bool(v.get("satisfied", False)),
                             "evidence": v.get("evidence", "")})
            else:
                norm.append({"requirement": v.requirement, "satisfied": bool(v.satisfied),
                             "evidence": v.evidence})
        satisfied = sum(1 for v in norm if v["satisfied"])
        total = len(norm)
        score = satisfied / total if total else None
        return EvaluationResult(
            key=self.key, score=score,
            value=f"{satisfied}/{total} requirements satisfied",
            comment=str(data.get("reasoning", "")),
            metadata={"verdicts": norm, "satisfied": satisfied, "total": total,
                      # each verdict is a discrete human spot-check unit
                      "spot_check_units": total},
        )
