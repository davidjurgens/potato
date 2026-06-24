"""
Agent-metric induction from open-ended human feedback (AutoLibra-style).

Fixed rubrics are top-down. This is **bottom-up**: mine the free-text comments
annotators already write about agent behavior, extract the implicit evaluation
*aspect* of each, group recurring aspects, and propose **candidate metrics**
(name + definition + supporting comments) for a human to confirm — which then feed
the rubric DAG ([[rubric_dag]]). Captures implicit, context-specific preferences a
fixed benchmark misses (Zhu et al., AutoLibra, 2505.02820).

LLM-assisted (extraction); an ``llm`` may be injected for testing. Grouping is by
normalized aspect label (no embedding dependency).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CandidateMetric:
    name: str
    definition: str = ""
    support: int = 0
    polarity_counts: Dict[str, int] = field(default_factory=dict)  # +/-/neutral
    examples: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "definition": self.definition, "support": self.support,
                "polarity_counts": self.polarity_counts, "examples": self.examples[:5]}


def _extract_aspect(llm, comment: str) -> Optional[Dict[str, str]]:
    """LLM extracts the evaluation aspect a comment implies."""
    prompt = (
        "A human wrote this feedback about an AI agent's behavior. Identify the single "
        "evaluation ASPECT it is really about (a short reusable metric name like "
        "'conciseness' or 'tool selection'), a one-line definition, and whether the "
        "feedback is positive, negative, or neutral about it.\n\n"
        f"Feedback: {comment}\n\n"
        'Respond as JSON: {"aspect": "<2-4 word metric name>", "definition": '
        '"<one sentence>", "polarity": "positive|negative|neutral"}.'
    )
    try:
        from pydantic import BaseModel

        class Aspect(BaseModel):
            aspect: str = ""
            definition: str = ""
            polarity: str = "neutral"

        resp = llm.query(prompt, Aspect)
        if isinstance(resp, str):
            data = (llm.parseStringToJson(resp) if hasattr(llm, "parseStringToJson")
                    else __import__("json").loads(resp))
        elif hasattr(resp, "model_dump"):
            data = resp.model_dump()
        else:
            data = resp or {}
        if not isinstance(data, dict) or not str(data.get("aspect", "")).strip():
            return None
        return {"aspect": str(data["aspect"]).strip(),
                "definition": str(data.get("definition", "")).strip(),
                "polarity": str(data.get("polarity", "neutral")).strip().lower()}
    except Exception as e:
        logger.error(f"metric_induction: aspect extraction failed: {e}")
        return None


def induce_metrics(comments: List[str], llm: Any, min_support: int = 2
                   ) -> List[CandidateMetric]:
    """Extract aspects from free-text comments and group recurring ones into
    candidate metrics (support ≥ ``min_support``), sorted by support desc."""
    groups: Dict[str, CandidateMetric] = {}
    for comment in comments:
        if not comment or not str(comment).strip():
            continue
        asp = _extract_aspect(llm, comment)
        if not asp:
            continue
        key = asp["aspect"].lower()
        m = groups.get(key)
        if m is None:
            m = CandidateMetric(name=asp["aspect"], definition=asp["definition"])
            groups[key] = m
        m.support += 1
        m.polarity_counts[asp["polarity"]] = m.polarity_counts.get(asp["polarity"], 0) + 1
        if comment not in m.examples:
            m.examples.append(comment)
        # keep the longest definition seen (usually the most informative)
        if len(asp["definition"]) > len(m.definition):
            m.definition = asp["definition"]
    candidates = [m for m in groups.values() if m.support >= min_support]
    candidates.sort(key=lambda m: m.support, reverse=True)
    return candidates
