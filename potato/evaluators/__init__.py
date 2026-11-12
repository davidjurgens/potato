"""
Potato evaluators library.

Flask-free, dependency-light evaluators for agent trajectories and text outputs.
Used by the experiment runner (datasets/experiments), the automation engine, and
the pytest CI plugin -- and importable standalone.

    from potato.evaluators import TrajectoryMatchEvaluator
    ev = TrajectoryMatchEvaluator(mode="unordered")
    result = ev.evaluate(outputs=agent_trace, reference_outputs=gold_trace)
    print(result.score)  # 1.0 / 0.0
"""

from potato.evaluators.base import Evaluator, EvaluationResult
from potato.evaluators.trajectory import (
    Step,
    ToolCall,
    normalize_trajectory,
    extract_tool_calls,
)
from potato.evaluators.trajectory_match import TrajectoryMatchEvaluator
from potato.evaluators.tool_use import ToolUseEvaluator, ToolCallAccuracyEvaluator
from potato.evaluators.llm_judge import LLMTrajectoryJudge
from potato.evaluators.heuristic import (
    ExactMatch,
    Contains,
    RegexMatch,
    EditDistance,
    JSONValid,
    JSONSchemaMatch,
    EmbeddingDistance,
)
from potato.evaluators.rubric_dag import (
    RubricDagEvaluator,
    make_rubric_dag,
    RUBRIC_PRESETS,
)
from potato.evaluators.rag_triad import (
    ContextRelevanceEvaluator,
    GroundednessEvaluator,
    AnswerRelevanceEvaluator,
    rag_triad,
)
from potato.evaluators.agent_as_judge import AgentAsJudgeEvaluator
from potato.evaluators.registry import (
    build_evaluator,
    register_evaluator,
    list_evaluators,
    get_supported_evaluators,
)

__all__ = [
    "Evaluator",
    "EvaluationResult",
    "Step",
    "ToolCall",
    "normalize_trajectory",
    "extract_tool_calls",
    "TrajectoryMatchEvaluator",
    "ToolUseEvaluator",
    "ToolCallAccuracyEvaluator",
    "LLMTrajectoryJudge",
    "ExactMatch",
    "Contains",
    "RegexMatch",
    "EditDistance",
    "JSONValid",
    "JSONSchemaMatch",
    "EmbeddingDistance",
    "RubricDagEvaluator",
    "make_rubric_dag",
    "RUBRIC_PRESETS",
    "ContextRelevanceEvaluator",
    "GroundednessEvaluator",
    "AnswerRelevanceEvaluator",
    "rag_triad",
    "AgentAsJudgeEvaluator",
    "build_evaluator",
    "register_evaluator",
    "list_evaluators",
    "get_supported_evaluators",
]
