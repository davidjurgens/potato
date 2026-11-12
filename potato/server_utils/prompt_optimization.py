"""
Eval→improve loop: export to GEPA/DSPy + a reflective prompt proposal a human approves.

Every other Potato eval feature *measures*; this closes the loop to *act* — but
stays human-in-the-loop. Two pieces:

1. **Export for optimization** — turn a human-curated eval dataset + the current
   prompt into a trainset GEPA/DSPy/TextGrad can optimize against (the eval set is
   the objective). Keeps the heavy optimizer external; Potato supplies the
   human-grounded objective.
2. **Reflective proposal** — a GEPA-style single-step rewrite: given failing
   examples, an LLM proposes an improved prompt with a rationale. The result is a
   ``PromptDiff`` a human **approves or rejects** before anything ships — the
   optimizer never silently changes the prompt.

Export is pure stdlib; the reflective step takes an ``llm`` (injectable for tests).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def export_for_optimization(examples: List[Dict[str, Any]], prompt: str = "",
                            fmt: str = "dspy") -> Dict[str, Any]:
    """Build an optimizer-ready export from eval examples + the seed prompt.

    ``examples``: ``[{inputs, reference_outputs?}, ...]`` (the dataset shape).
    ``fmt``: ``dspy`` (trainset of input/output dicts + a signature) or ``gepa``
    (seed prompt + scored examples as the optimization objective). The export is
    JSON; the user feeds it to the external optimizer.
    """
    trainset = []
    for ex in examples:
        inp = ex.get("inputs")
        out = ex.get("reference_outputs")
        trainset.append({"inputs": inp, "expected": out})
    if fmt == "gepa":
        return {"format": "gepa", "seed_prompt": prompt,
                "objective": "maximize mean eval score on the trainset",
                "trainset": trainset, "n": len(trainset)}
    if fmt == "dspy":
        return {"format": "dspy", "signature_instructions": prompt,
                "trainset": trainset, "n": len(trainset)}
    raise ValueError(f"unknown export format '{fmt}' (use 'dspy' or 'gepa')")


@dataclass
class PromptDiff:
    original_prompt: str
    proposed_prompt: str
    rationale: str = ""
    based_on_failures: int = 0
    approved: Optional[bool] = None     # None = pending human review
    notes: str = ""

    def approve(self, notes: str = "") -> "PromptDiff":
        self.approved = True
        self.notes = notes
        return self

    def reject(self, notes: str = "") -> "PromptDiff":
        self.approved = False
        self.notes = notes
        return self

    @property
    def changed(self) -> bool:
        return self.proposed_prompt.strip() != self.original_prompt.strip()

    def to_dict(self) -> Dict[str, Any]:
        return {"original_prompt": self.original_prompt, "proposed_prompt": self.proposed_prompt,
                "rationale": self.rationale, "based_on_failures": self.based_on_failures,
                "approved": self.approved, "changed": self.changed, "notes": self.notes}


def reflective_proposal(prompt: str, failures: List[Dict[str, Any]], llm: Any,
                        max_failures: int = 8) -> Optional[PromptDiff]:
    """GEPA-style reflective rewrite: from failing examples, ask the LLM to propose an
    improved prompt + rationale. Returns a ``PromptDiff`` *pending human approval*
    (``approved=None``); the caller decides whether to ship it.

    ``failures``: ``[{inputs, expected?, got?, reason?}, ...]``.
    """
    if not prompt or not failures:
        return None
    shown = failures[:max_failures]
    lines = []
    for i, f in enumerate(shown):
        lines.append(f"Failure {i+1}: input={f.get('inputs')!r} expected={f.get('expected')!r} "
                     f"got={f.get('got')!r} reason={f.get('reason','')!r}")
    block = "\n".join(lines)
    ask = (
        "You are improving an LLM prompt by reflecting on its failures. Propose a "
        "revised prompt that would fix these failures without overfitting, and explain "
        "briefly why.\n\n"
        f"Current prompt:\n{prompt}\n\nFailures:\n{block}\n\n"
        'Respond as JSON: {"proposed_prompt": "<full revised prompt>", '
        '"rationale": "<one-two sentences>"}.'
    )
    try:
        from pydantic import BaseModel

        class Proposal(BaseModel):
            proposed_prompt: str = ""
            rationale: str = ""

        resp = llm.query(ask, Proposal)
        if isinstance(resp, str):
            data = (llm.parseStringToJson(resp) if hasattr(llm, "parseStringToJson")
                    else __import__("json").loads(resp))
        elif hasattr(resp, "model_dump"):
            data = resp.model_dump()
        else:
            data = resp or {}
        if not isinstance(data, dict) or not str(data.get("proposed_prompt", "")).strip():
            return None
        return PromptDiff(original_prompt=prompt,
                          proposed_prompt=str(data["proposed_prompt"]).strip(),
                          rationale=str(data.get("rationale", "")).strip(),
                          based_on_failures=len(shown))
    except Exception as e:
        logger.error(f"prompt_optimization: reflective proposal failed: {e}")
        return None
