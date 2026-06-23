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


def compute_prompt_version(rubric: str, schema_name: str, few_shot: bool,
                           extra: str = "") -> str:
    """Stable short hash identifying this judge configuration.

    Editing the rubric (or toggling few-shot) yields a new version so the admin
    report can track κ across prompt versions. ``extra`` is an optional salt
    (e.g. a correction-set fingerprint) so auto-calibrated versions are tracked
    distinctly from manual rubric edits.
    """
    basis = f"{schema_name}␟{int(bool(few_shot))}␟{rubric or ''}␟{extra or ''}"
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

    # ----- span judging --------------------------------------------------

    def judge_spans(self, instance_id: str, schema_info: Dict[str, Any],
                    instance_text: str) -> Optional[Dict[str, Any]]:
        """Ask the judge to extract labeled spans; return located spans + reasoning.

        Returns ``{instance_id, schema_name, spans:[{start,end,text,label}],
        reasoning, model_name}`` or None on failure.
        """
        endpoint = self._get_endpoint()
        if endpoint is None:
            return None
        labels = extract_labels(schema_info)
        rubric = self.get_rubric(schema_info)
        parts = [
            "You are an expert annotator. Extract every span of text matching the",
            "task below. Return each span's exact substring and its label.",
            f"Task: {schema_info.get('description', '')}".rstrip(),
            f"Rubric: {rubric}".rstrip(),
            ("Allowed labels: " + ", ".join(labels)) if labels else "",
            "\nText:", _truncate(instance_text, 4000),
            '\nRespond as JSON: {"spans": [{"text": <exact substring>, '
            '"label": <one allowed label>}], "reasoning": <one sentence>}.',
        ]
        prompt = "\n".join(p for p in parts if p != "")
        try:
            from pydantic import BaseModel

            class SpanItem(BaseModel):
                text: str = ""
                label: str = ""

            class SpanVerdict(BaseModel):
                spans: List[SpanItem] = []
                reasoning: str = ""

            response = endpoint.query(prompt, SpanVerdict)
            data = _response_to_dict(response)
        except Exception as e:
            logger.error(f"Judge spans: query/parse failed for {instance_id}: {e}")
            return None

        raw = data.get("spans", []) or []
        raw = [r if isinstance(r, dict) else {"text": str(r)} for r in raw]
        spans = _locate_spans(instance_text or "", raw, labels)
        return {
            "instance_id": instance_id,
            "schema_name": schema_info.get("name", ""),
            "spans": spans,
            "reasoning": str(data.get("reasoning", "")),
            "model_name": getattr(endpoint, "model", ""),
        }

    # ----- free-text judging --------------------------------------------

    def judge_freetext(self, instance_id: str, schema_info: Dict[str, Any],
                       instance_text: str,
                       dimensions: Optional[List[Dict[str, Any]]] = None
                       ) -> Optional[Dict[str, Any]]:
        """Rubric-score a free-text output along one or more feedback dimensions.

        ``dimensions``: list of ``{"key", "type": continuous|boolean|categorical,
        "labels"?}``. Defaults to a single continuous ``quality`` score.
        Returns ``{instance_id, schema_name, scores:{key:val}, reasoning, ...}``.
        """
        endpoint = self._get_endpoint()
        if endpoint is None:
            return None
        dims = dimensions or [{"key": "quality", "type": "continuous"}]
        rubric = self.get_rubric(schema_info)
        spec_lines = []
        for d in dims:
            t = d.get("type", "continuous")
            if t == "continuous":
                spec_lines.append(f'  "{d["key"]}": <0.0-1.0>')
            elif t == "boolean":
                spec_lines.append(f'  "{d["key"]}": <true|false>')
            else:
                opts = "|".join(d.get("labels", []))
                spec_lines.append(f'  "{d["key"]}": <{opts or "label"}>')
        parts = [
            "You are an impartial judge scoring a free-text response.",
            f"Task: {schema_info.get('description', '')}".rstrip(),
            f"Rubric: {rubric}".rstrip(),
            "\nResponse to evaluate:", _truncate(instance_text, 4000),
            '\nRespond as JSON: {"scores": {\n' + ",\n".join(spec_lines)
            + '\n}, "reasoning": <one sentence>}.',
        ]
        prompt = "\n".join(p for p in parts if p != "")
        try:
            response = endpoint.query(prompt, None)
            data = _response_to_dict(response)
        except Exception as e:
            logger.error(f"Judge freetext: query/parse failed for {instance_id}: {e}")
            return None

        raw_scores = data.get("scores", {}) or {}
        scores = {}
        for d in dims:
            scores[d["key"]] = _coerce_feedback(
                raw_scores.get(d["key"]), d.get("type", "continuous"), d.get("labels"))
        return {
            "instance_id": instance_id,
            "schema_name": schema_info.get("name", ""),
            "scores": scores,
            "reasoning": str(data.get("reasoning", "")),
            "model_name": getattr(endpoint, "model", ""),
        }


def _response_to_dict(response: Any) -> Dict[str, Any]:
    """Normalize an endpoint response (str/JSON, pydantic, or dict) to a dict."""
    if isinstance(response, str):
        return json.loads(response)
    if hasattr(response, "model_dump"):
        return response.model_dump()
    if hasattr(response, "dict"):
        return response.dict()
    return response or {}


_SPAN_TYPES = {"span", "error_span", "coreference"}
_FREETEXT_TYPES = {"textbox", "text", "text_edit"}


def judge_mode(schema_info: Dict[str, Any]) -> str:
    """Which judging strategy fits a schema: 'categorical' | 'span' | 'freetext'."""
    atype = schema_info.get("annotation_type", "")
    if atype in _SPAN_TYPES:
        return "span"
    if atype in _FREETEXT_TYPES:
        return "freetext"
    return "categorical"


def _locate_spans(text: str, raw_spans: List[Dict[str, Any]],
                  valid_labels: List[str]) -> List[Dict[str, Any]]:
    """Map LLM-proposed ``{text,label}`` spans to character offsets in ``text``.

    Repeated span texts advance a search cursor so each occurrence maps to a
    distinct offset. Labels are validated against the schema (fuzzy-matched);
    unlocatable or invalid-label spans are dropped.
    """
    out = []
    cursor = 0
    for s in raw_spans:
        frag = str(s.get("text", "")).strip()
        if not frag:
            continue
        label = str(s.get("label", "")).strip()
        if valid_labels:
            matched = _fuzzy_match_label(label, valid_labels)
            if matched is None:
                continue
            label = matched
        idx = text.find(frag, cursor)
        if idx < 0:
            idx = text.find(frag)  # fall back to first occurrence
        if idx < 0:
            continue
        start, end = idx, idx + len(frag)
        cursor = end
        out.append({"start": start, "end": end, "text": frag, "label": label})
    return out


def score_spans(predicted: List[Dict[str, Any]], gold: List[Dict[str, Any]],
                iou_threshold: float = 0.5) -> Dict[str, Any]:
    """IoU-matched span agreement (precision/recall/F1) of judge vs human spans.

    Reuses the calibration span matcher so the judge path shares one definition.
    """
    from potato.judge_calibration.metrics import _match_spans, _prf
    tp, fp, fn, matched_ious, _ = _match_spans(predicted, gold, iou_threshold)
    out = _prf(tp, fp, fn)
    out.update({
        "tp": tp, "fp": fp, "fn": fn,
        "mean_iou": round(sum(matched_ious) / len(matched_ious), 4) if matched_ious else 0.0,
    })
    return out


def _coerce_feedback(value: Any, dim_type: str, labels: Optional[List[str]]):
    """Coerce a free-text judge feedback value to its declared type."""
    if dim_type == "boolean":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "yes", "1", "pass")
    if dim_type == "categorical":
        v = str(value).strip()
        if labels:
            return _fuzzy_match_label(v, labels) or v
        return v
    # continuous (default): clamp to [0, 1]
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return None


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
