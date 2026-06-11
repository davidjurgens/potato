"""
LLM-as-Judge service for human-alignment.

Produces a judge verdict (label + confidence + reasoning) for an annotation
instance, given the schema (labels + description + an editable rubric) and,
optionally, few-shot examples drawn from high-agreement human labels. The
verdicts are compared against human labels elsewhere
(``potato/server_utils/judge_alignment.py``) to measure and calibrate
human↔judge agreement (Cohen's κ).

This deliberately does NOT reuse ``ICLLabeler`` as the judge — ICL auto-labels
from inter-annotator agreement, which would leak the gold labels we are trying
to measure the judge against. We only borrow ICLLabeler's *example selection*
for few-shot calibration, and we always exclude the instance being judged from
its own example set.

The judge call goes through the same ``AIEndpointFactory`` / ``BaseAIEndpoint``
machinery as every other AI feature (mirrors ``icl_labeler.label_instance``),
so it works with any configured provider.
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class JudgePrediction:
    """A single LLM-judge verdict for one instance + schema."""

    instance_id: str
    schema_name: str
    predicted_label: str
    confidence: float  # 0.0–1.0
    reasoning: str = ""
    model_name: str = ""
    prompt_version: str = ""
    examples_used: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "schema_name": self.schema_name,
            "predicted_label": self.predicted_label,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "model_name": self.model_name,
            "prompt_version": self.prompt_version,
            "examples_used": self.examples_used,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JudgePrediction":
        return cls(
            instance_id=data["instance_id"],
            schema_name=data["schema_name"],
            predicted_label=data.get("predicted_label", ""),
            confidence=float(data.get("confidence", 0.0)),
            reasoning=data.get("reasoning", ""),
            model_name=data.get("model_name", ""),
            prompt_version=data.get("prompt_version", ""),
            examples_used=data.get("examples_used", []),
        )


def extract_labels(schema_info: Dict[str, Any]) -> List[str]:
    """Return the allowed label names for a categorical schema.

    Supports ``radio``/``select``/``multiselect`` (``labels`` list of
    str|dict) and ``likert`` (1..size). Returns ``[]`` for unsupported types.
    """
    atype = schema_info.get("annotation_type", "")
    if atype == "likert":
        size = int(schema_info.get("size", 5))
        return [str(i) for i in range(1, size + 1)]
    labels = schema_info.get("labels", [])
    out = []
    for lab in labels:
        if isinstance(lab, dict):
            out.append(str(lab.get("name", "")))
        else:
            out.append(str(lab))
    return [x for x in out if x]


def compute_prompt_version(rubric: str, schema_name: str, few_shot: bool) -> str:
    """Stable short hash identifying this judge configuration.

    Editing the rubric (or toggling few-shot) yields a new version so the admin
    report can track κ across prompt versions.
    """
    basis = f"{schema_name}␟{int(bool(few_shot))}␟{rubric or ''}"
    return "v_" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:10]


class JudgeService:
    """Builds judge prompts and queries the configured AI endpoint."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config or {}
        self.judge_config = self.config.get("judge_alignment", {}) or {}
        self._endpoint = None
        self._endpoint_initialized = False

    # ----- endpoint -------------------------------------------------------

    def _get_endpoint(self):
        if not self._endpoint_initialized:
            self._endpoint_initialized = True
            try:
                from potato.ai.ai_endpoint import AIEndpointFactory
                # The judge endpoint config lives under judge_alignment, but
                # fall back to the task's ai_support so a single endpoint can
                # serve both. Shape mirrors what AIEndpointFactory expects.
                ai_support = self.judge_config.get("ai_support") or self.config.get("ai_support")
                if not ai_support:
                    logger.warning("Judge: no ai_support / judge_alignment.ai_support configured")
                    return None
                self._endpoint = AIEndpointFactory.create_endpoint({"ai_support": ai_support})
            except Exception as e:
                logger.error(f"Judge: failed to create endpoint: {e}")
                self._endpoint = None
        return self._endpoint

    # ----- prompt ---------------------------------------------------------

    def _schema_judge_config(self, schema_name: str) -> Dict[str, Any]:
        per_schema = self.judge_config.get("schemas", {}) or {}
        return per_schema.get(schema_name, {}) or {}

    def get_rubric(self, schema_info: Dict[str, Any]) -> str:
        """Editable rubric for a schema; falls back to its description."""
        sc = self._schema_judge_config(schema_info.get("name", ""))
        return sc.get("rubric") or schema_info.get("description", "") or ""

    def build_prompt(
        self,
        schema_info: Dict[str, Any],
        instance_text: str,
        few_shot_examples: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """Compose the judge prompt.

        few_shot_examples: list of {"text": ..., "label": ...} gold exemplars
        (already excluding the target instance).
        """
        labels = extract_labels(schema_info)
        rubric = self.get_rubric(schema_info)
        parts = [
            "You are an expert evaluator acting as an impartial judge.",
            "Assign exactly one label to the item below, following the rubric.",
            "",
            f"Task: {schema_info.get('description', '')}".rstrip(),
            f"Rubric: {rubric}".rstrip(),
            "Allowed labels: " + ", ".join(labels) if labels else "",
        ]
        if few_shot_examples:
            parts.append("\nExamples (item → correct label):")
            for ex in few_shot_examples:
                parts.append(f"- {_truncate(ex.get('text', ''))} → {ex.get('label', '')}")
        parts.append("\nItem to judge:")
        parts.append(_truncate(instance_text, 4000))
        parts.append(
            '\nRespond as JSON: {"label": <one of the allowed labels>, '
            '"confidence": <0.0-1.0>, "reasoning": <one sentence>}.'
        )
        return "\n".join(p for p in parts if p != "")

    # ----- judging --------------------------------------------------------

    def judge_instance(
        self,
        instance_id: str,
        schema_info: Dict[str, Any],
        instance_text: str,
        few_shot_examples: Optional[List[Dict[str, str]]] = None,
        prompt_version: Optional[str] = None,
    ) -> Optional[JudgePrediction]:
        """Query the judge for one instance. Returns None on failure."""
        endpoint = self._get_endpoint()
        if endpoint is None:
            return None

        schema_name = schema_info.get("name", "")
        valid_labels = extract_labels(schema_info)
        rubric = self.get_rubric(schema_info)
        if prompt_version is None:
            prompt_version = compute_prompt_version(
                rubric, schema_name, bool(few_shot_examples)
            )

        prompt = self.build_prompt(schema_info, instance_text, few_shot_examples)

        try:
            from pydantic import BaseModel

            class JudgeVerdict(BaseModel):
                label: str
                confidence: float = 0.5
                reasoning: str = ""

            response = endpoint.query(prompt, JudgeVerdict)
            if isinstance(response, str):
                data = json.loads(response)
            elif hasattr(response, "model_dump"):
                data = response.model_dump()
            elif hasattr(response, "dict"):
                data = response.dict()
            else:
                data = response or {}
        except Exception as e:
            logger.error(f"Judge: query/parse failed for {instance_id}/{schema_name}: {e}")
            return None

        predicted = str(data.get("label", "")).strip()
        try:
            confidence = float(data.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = min(1.0, max(0.0, confidence))
        reasoning = str(data.get("reasoning", ""))

        if valid_labels and predicted not in valid_labels:
            matched = _fuzzy_match_label(predicted, valid_labels)
            if matched is None:
                logger.warning(
                    f"Judge: invalid label '{predicted}' for {instance_id}/{schema_name}"
                )
                return None
            predicted = matched

        return JudgePrediction(
            instance_id=instance_id,
            schema_name=schema_name,
            predicted_label=predicted,
            confidence=confidence,
            reasoning=reasoning,
            model_name=getattr(endpoint, "model", ""),
            prompt_version=prompt_version,
            examples_used=[e.get("id", "") for e in (few_shot_examples or []) if e.get("id")],
        )


def _truncate(text: str, limit: int = 300) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[:limit] + "…"


def _fuzzy_match_label(predicted: str, valid_labels: List[str]) -> Optional[str]:
    """Case-insensitive / prefix match a model label to an allowed label."""
    if not predicted:
        return None
    low = predicted.lower().strip()
    for lab in valid_labels:
        if lab.lower() == low:
            return lab
    for lab in valid_labels:
        ll = lab.lower()
        if ll in low or low in ll:
            return lab
    return None
