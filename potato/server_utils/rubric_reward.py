"""
Rubrics-as-Rewards (RaR) export: turn rubric / agent-as-judge evaluations into
criterion-level reward-model training data.

Potato already exports preferences (DPO) and SFT data. The 2025–26 post-training
frontier (OpenRubrics, Rubrics-as-Rewards, ICLR 2026) wants **criterion-level reward
signals** for non-verifiable domains: each rubric criterion is scored, and a weighted
combination becomes the scalar reward. This module converts two evaluation sources
Potato already produces into that format:

- **Rubric DAG** ([[rubric_dag]]) — the traversed path's nodes/choices become
  criteria; the authored leaf score is the reward.
- **Agent-as-judge** — each per-requirement verdict (satisfied/not) is a criterion.

Output rows are JSONL-ready: ``{prompt, response, reward, criteria:[{name, satisfied,
weight, points}], source}``. Pure stdlib.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _weighted_reward(criteria: List[Dict[str, Any]]) -> float:
    """Weighted mean of per-criterion points (points in [0,1]); equal weights if
    none given. Returns 0..1."""
    if not criteria:
        return 0.0
    total_w = sum(float(c.get("weight", 1.0)) for c in criteria) or 1.0
    return round(sum(float(c.get("points", 0.0)) * float(c.get("weight", 1.0))
                     for c in criteria) / total_w, 6)


def reward_row_from_agent_judge(result: Dict[str, Any], prompt: str = "",
                                response: str = "", weights: Optional[Dict[str, float]] = None
                                ) -> Optional[Dict[str, Any]]:
    """Build a RaR row from an agent-as-judge result dict (``metadata.verdicts``)."""
    verdicts = (result.get("metadata", {}) or {}).get("verdicts") or []
    if not verdicts:
        return None
    weights = weights or {}
    criteria = [{"name": v.get("requirement", ""),
                 "satisfied": bool(v.get("satisfied")),
                 "weight": float(weights.get(v.get("requirement", ""), 1.0)),
                 "points": 1.0 if v.get("satisfied") else 0.0,
                 "evidence": v.get("evidence", "")}
                for v in verdicts]
    return {"prompt": prompt, "response": response,
            "reward": _weighted_reward(criteria), "criteria": criteria,
            "source": "agent_as_judge"}


def reward_row_from_dag(result: Dict[str, Any], prompt: str = "", response: str = ""
                        ) -> Optional[Dict[str, Any]]:
    """Build a RaR row from a rubric-DAG result dict (``metadata.path`` + ``score``).

    Each traversed node becomes a criterion (its choice recorded); the authored leaf
    score is the reward (already a deterministic, human-authored value)."""
    md = result.get("metadata", {}) or {}
    path = md.get("path") or []
    if result.get("score") is None and not path:
        return None
    criteria = [{"name": step.get("node", ""), "choice": step.get("choice", ""),
                 "weight": 1.0,
                 "reasoning": step.get("reasoning", "")} for step in path]
    return {"prompt": prompt, "response": response,
            "reward": round(float(result["score"]), 6) if result.get("score") is not None else None,
            "criteria": criteria, "leaf": md.get("leaf"), "source": "rubric_dag"}


def build_reward_dataset(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert a list of ``{result, prompt?, response?, source?, weights?}`` into
    RaR rows. ``source`` is auto-detected from the result's ``key``/metadata when
    omitted. Rows that yield no criteria are skipped.
    """
    rows: List[Dict[str, Any]] = []
    for rec in records:
        result = rec.get("result") or {}
        prompt = rec.get("prompt", "")
        response = rec.get("response", "")
        source = rec.get("source") or _detect_source(result)
        if source == "agent_as_judge":
            row = reward_row_from_agent_judge(result, prompt, response, rec.get("weights"))
        elif source == "rubric_dag":
            row = reward_row_from_dag(result, prompt, response)
        else:
            row = None
        if row:
            rows.append(row)
    return rows


def _detect_source(result: Dict[str, Any]) -> Optional[str]:
    key = result.get("key", "")
    md = result.get("metadata", {}) or {}
    if key == "agent_as_judge" or "verdicts" in md:
        return "agent_as_judge"
    if key == "rubric_dag" or "path" in md:
        return "rubric_dag"
    return None
