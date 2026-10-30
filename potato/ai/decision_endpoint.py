"""
Decision-model ("System One") endpoints.

A decision model is a non-generative classifier: it reads a ``state`` (the
item text) plus typed questions and returns a probability distribution over
each question's options in one forward pass. It never produces text, so it
can answer "which label?" but cannot write a hint, a rationale, or a revised
prompt.

Three backends speak the same wire format as of 2026-10:

* Jev (TypeSafe AI), hosted: ``POST https://api.typesafe.ai/v1/systemone``,
  bearer API key, model alias ``jev-latest`` (-> ``jev-1.13.0``), up to 255
  options per choice question.
* OpenJev (``openjev/openjev`` on HF, Qwen 3.5 27B): vLLM plus a shim serving
  ``/v1/systemone`` (default port 3000). 52 options per question in one pass;
  more are split into multiple passes by the shim.
* Laya (Convai Innovations, Apache-2.0, ``pip install laya``): in-process via
  ``laya.load(...).predict(state, questions)`` or ``laya.Router().predict``,
  and ``laya-serve`` serves the Jev protocol over HTTP (default port 8000).

Wire format, as confirmed (not guessed):

Request (spice.ai/learn/typesafe-jev; HF openjev/openjev model card; laya
0.4.7 ``serve.py`` and ``agent.Agent.system_one`` docstring)::

    {"model": "jev-latest",
     "state": {"message": "..."}          # a string, object or list
     "questions": {
        "team":    {"type": "choice", "instructions": "...",
                    "criteria": {"billing": "Payments...", "technical": null}},
        "urgency": {"type": "score", "instructions": "...",
                    "criteria": ["Can wait", "Reply this week", "Reply today"]},
        "refund":  {"type": "noul", "instructions": "..."}}}

``criteria`` values of ``null`` mean "no description": the OpenJev card's
example uses them, and laya's ``common.render_options`` renders such an
option as its bare key. Whether hosted Jev accepts ``null`` is not documented
anywhere we could read.

Response (spice.ai example; laya ``serve._project_jev_strict``)::

    {"model": "jev-1.13.0",
     "answers": {
        "team":    {"type": "choice", "choice": "billing",
                    "probabilities": {"billing": 0.97, ...}, "confidence": 0.95},
        "urgency": {"type": "score", "score": 1.9,
                    "legend": {"0": "Can wait", ...},
                    "probabilities": {"0": 0.0, "1": 0.1, "2": 0.9},
                    "confidence": 0.85},
        "refund":  {"type": "noul", "noul": 0.91}},
     "usage": {"input_tokens": 312, "output_tokens": 30}}

Two things in that response are easy to misread, so this module does not use
them directly:

* ``confidence`` on choice/score is laya's normalised entropy
  (``1 - H(p)/log k``, ``laya.common.confidence_from_probs``), not the
  probability of the chosen option. ``DecisionAnswer.confidence`` is always
  ``probabilities[value]``.
* ``score`` is the *expected* level index (a float), and score probabilities
  are keyed by level index ``"0".."k-1"``, not by label. The answer's value is
  the argmax level, mapped back to the question's option label.

Normalisation (``normalize_distribution``): a distribution whose values are
all in [0, 1] and sum to 1 +/- 0.02 is treated as probabilities and divided
by its sum (the backends round to 4 places). Anything else -- a negative
value, a value above 1, or a sum outside that band -- is treated as logits
and softmaxed. A noul value outside [0, 1] is treated as a logit and passed
through a sigmoid. Every backend we confirmed returns probabilities, so the
logit path exists for compatible servers that do not.
"""

import logging
import math
from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel

from .ai_endpoint import BaseAIEndpoint, AIEndpointRequestError

logger = logging.getLogger(__name__)

QUESTION_KINDS = ("choice", "score", "noul")

# A slider with more positions than this is a continuous scale, and asking a
# classifier to pick one of 101 integers wastes its probability mass on
# near-duplicates. 21 covers 0-20 and -10..10.
MAX_SLIDER_STEPS = 21

NOT_GENERATIVE_MESSAGE = (
    "{name} is a decision model: it returns probabilities over a question's "
    "options and cannot generate text. Use a generative model (openai, "
    "anthropic, vllm, ollama, ...) for hints, rationales, revision_models and "
    "prompt work."
)


class UnsupportedSchemeError(ValueError):
    """An annotation scheme a decision model cannot answer."""
    pass


@dataclass
class DecisionQuestion:
    """One typed question for a decision model.

    ``options`` holds the option labels for ``choice`` and the ordered scale
    labels (low to high) for ``score``; ``noul`` ignores it. ``descriptions``
    is optional per-option text shown to the model beside the label.
    """
    id: str
    kind: str            # 'choice' | 'score' | 'noul'
    text: str            # the question / instructions
    options: List[str] = field(default_factory=list)
    descriptions: Dict[str, str] = field(default_factory=dict)


@dataclass
class DecisionAnswer:
    """A decision model's answer to one question.

    ``value`` is the chosen option label (choice), the chosen scale label
    (score) or a bool (noul). ``confidence`` is the probability of ``value``.
    ``probabilities`` maps every option to its probability; for noul it is
    ``{'yes': p, 'no': 1 - p}``.
    """
    id: str
    value: Any
    confidence: float
    probabilities: Dict[str, float]
    raw: Any = None


# ---------------------------------------------------------------------------
# Scheme mapping
# ---------------------------------------------------------------------------

def _label_name(label: Any) -> str:
    if isinstance(label, dict):
        if "name" not in label:
            raise UnsupportedSchemeError(f"label {label!r} has no 'name' key")
        return str(label["name"])
    return str(label)


def _label_description(label: Any) -> Optional[str]:
    if isinstance(label, dict):
        for key in ("description", "tooltip"):
            value = label.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _question_text(scheme: dict, instructions: str) -> str:
    parts = [p.strip() for p in (instructions or "", str(scheme.get("description") or ""))
             if p and p.strip()]
    return "\n\n".join(parts) or str(scheme.get("name", ""))


def _format_step(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def questions_for_scheme(scheme: dict, instructions: str) -> List[DecisionQuestion]:
    """Map a Potato annotation scheme to decision-model questions.

    radio/select -> one choice over the labels; likert -> a score over
    "1".."size"; slider -> a score over its steps (at most MAX_SLIDER_STEPS).
    Every other type raises UnsupportedSchemeError: decision models answer
    one-of-N questions only.
    """
    atype = scheme.get("annotation_type")
    name = scheme.get("name")
    if not name:
        raise UnsupportedSchemeError("annotation scheme has no 'name'")
    text = _question_text(scheme, instructions)

    if atype in ("radio", "select"):
        labels = scheme.get("labels") or []
        options = [_label_name(l) for l in labels]
        if len(options) < 2:
            raise UnsupportedSchemeError(
                f"{atype} scheme '{name}' needs at least two labels, has {len(options)}")
        if len(set(options)) != len(options):
            raise UnsupportedSchemeError(f"{atype} scheme '{name}' has duplicate labels")
        descriptions = {n: d for n, d in ((_label_name(l), _label_description(l)) for l in labels) if d}
        return [DecisionQuestion(id=name, kind="choice", text=text,
                                 options=options, descriptions=descriptions)]

    if atype == "likert":
        size = scheme.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size < 2:
            raise UnsupportedSchemeError(
                f"likert scheme '{name}' needs an integer size >= 2, got {size!r}")
        options = [str(i) for i in range(1, size + 1)]
        descriptions = {}
        if scheme.get("min_label"):
            descriptions["1"] = f"1 ({scheme['min_label']})"
        if scheme.get("max_label"):
            descriptions[str(size)] = f"{size} ({scheme['max_label']})"
        return [DecisionQuestion(id=name, kind="score", text=text,
                                 options=options, descriptions=descriptions)]

    if atype == "slider":
        try:
            lo = float(scheme["min_value"])
            hi = float(scheme["max_value"])
            step = float(scheme.get("step", 1) or 1)
        except (KeyError, TypeError, ValueError):
            raise UnsupportedSchemeError(
                f"slider scheme '{name}' needs numeric min_value and max_value")
        if step <= 0 or hi <= lo:
            raise UnsupportedSchemeError(
                f"slider scheme '{name}' needs min_value < max_value and step > 0")
        count = int(math.floor((hi - lo) / step + 1e-9)) + 1
        if count > MAX_SLIDER_STEPS:
            raise UnsupportedSchemeError(
                f"slider scheme '{name}' has {count} steps; decision models answer "
                f"scales of at most {MAX_SLIDER_STEPS} points. Use a coarser step or a likert scheme.")
        options = [_format_step(lo + i * step) for i in range(count)]
        descriptions = {}
        if scheme.get("min_label"):
            descriptions[options[0]] = f"{options[0]} ({scheme['min_label']})"
        if scheme.get("max_label"):
            descriptions[options[-1]] = f"{options[-1]} ({scheme['max_label']})"
        return [DecisionQuestion(id=name, kind="score", text=text,
                                 options=options, descriptions=descriptions)]

    raise UnsupportedSchemeError(
        f"annotation_type '{atype}' (scheme '{name}') is not supported by decision models: "
        f"they answer one-of-N questions only (radio, select, likert, slider).")


# ---------------------------------------------------------------------------
# Wire format
# ---------------------------------------------------------------------------

def normalize_distribution(values: Dict[str, Any]) -> Dict[str, float]:
    """Return a probability distribution over the same keys.

    Probabilities (all in [0, 1], summing to 1 +/- 0.02) are renormalised;
    anything else is treated as logits and softmaxed.
    """
    if not values:
        return {}
    try:
        nums = {k: float(v) for k, v in values.items()}
    except (TypeError, ValueError):
        raise AIEndpointRequestError(f"non-numeric probabilities in decision response: {values!r}")
    if any(not math.isfinite(v) for v in nums.values()):
        raise AIEndpointRequestError(f"non-finite probabilities in decision response: {values!r}")
    total = sum(nums.values())
    if all(0.0 <= v <= 1.0 for v in nums.values()) and abs(total - 1.0) <= 0.02 and total > 0:
        return {k: v / total for k, v in nums.items()}
    top = max(nums.values())
    exps = {k: math.exp(v - top) for k, v in nums.items()}
    z = sum(exps.values())
    return {k: v / z for k, v in exps.items()}


def _noul_probability(value: Any) -> float:
    try:
        p = float(value)
    except (TypeError, ValueError):
        raise AIEndpointRequestError(f"non-numeric noul value in decision response: {value!r}")
    if not math.isfinite(p):
        raise AIEndpointRequestError(f"non-finite noul value in decision response: {value!r}")
    if 0.0 <= p <= 1.0:
        return p
    return 1.0 / (1.0 + math.exp(-p))  # a logit


def build_systemone_questions(questions: List[DecisionQuestion]) -> Dict[str, Dict[str, Any]]:
    """The ``questions`` object of a /v1/systemone request (and laya predict)."""
    out: Dict[str, Dict[str, Any]] = {}
    for q in questions:
        body: Dict[str, Any] = {"type": q.kind, "instructions": q.text}
        if q.kind == "choice":
            body["criteria"] = {opt: q.descriptions.get(opt) for opt in q.options}
        elif q.kind == "score":
            body["criteria"] = [q.descriptions.get(opt) or opt for opt in q.options]
        out[q.id] = body
    return out


def parse_systemone_answers(response: Dict[str, Any],
                            questions: List[DecisionQuestion]) -> List[DecisionAnswer]:
    """Turn a /v1/systemone response into DecisionAnswers, in question order."""
    if not isinstance(response, dict) or not isinstance(response.get("answers"), dict):
        raise AIEndpointRequestError(
            f"decision response has no 'answers' object: {str(response)[:300]}")
    answers = response["answers"]
    out: List[DecisionAnswer] = []
    for q in questions:
        ans = answers.get(q.id)
        if not isinstance(ans, dict):
            raise AIEndpointRequestError(f"decision response has no answer for question '{q.id}'")

        if q.kind == "noul":
            p = _noul_probability(ans.get("noul"))
            out.append(DecisionAnswer(id=q.id, value=p >= 0.5, confidence=max(p, 1.0 - p),
                                      probabilities={"yes": p, "no": 1.0 - p}, raw=ans))
            continue

        raw_probs = ans.get("probabilities")
        if not isinstance(raw_probs, dict) or not raw_probs:
            raise AIEndpointRequestError(
                f"decision answer for '{q.id}' has no probabilities: {str(ans)[:300]}")

        if q.kind == "choice":
            unknown = set(raw_probs) - set(q.options)
            if unknown:
                raise AIEndpointRequestError(
                    f"decision answer for '{q.id}' names options that were not asked: {sorted(unknown)}")
            probs = normalize_distribution({opt: raw_probs.get(opt, 0.0) for opt in q.options})
            value = ans.get("choice")
            if value not in probs:
                value = max(probs, key=probs.get)
        else:  # score: probabilities are keyed by level index "0".."k-1"
            by_index = {}
            for i, opt in enumerate(q.options):
                v = raw_probs.get(str(i), raw_probs.get(opt, 0.0))
                by_index[opt] = v
            probs = normalize_distribution(by_index)
            value = max(probs, key=probs.get)

        out.append(DecisionAnswer(id=q.id, value=value, confidence=probs[value],
                                  probabilities=probs, raw=ans))
    return out


# ---------------------------------------------------------------------------
# Base endpoint
# ---------------------------------------------------------------------------

class DecisionModelEndpoint(BaseAIEndpoint):
    """Base class for decision ("System One") models.

    Subclasses implement ``_decide_raw`` returning a /v1/systemone-shaped
    response dict; validation, option limits and parsing live here.
    """

    is_decision_model = True
    #: Most options a single question may carry for this backend.
    max_options: int = 255

    def _check_questions(self, questions: List[DecisionQuestion]) -> None:
        if not questions:
            raise ValueError("decide() needs at least one question")
        seen = set()
        for q in questions:
            if q.kind not in QUESTION_KINDS:
                raise ValueError(f"question '{q.id}' has kind '{q.kind}'; expected one of {QUESTION_KINDS}")
            if q.id in seen:
                raise ValueError(f"duplicate question id '{q.id}'")
            seen.add(q.id)
            if q.kind == "noul":
                continue
            if len(q.options) < 2:
                raise ValueError(f"{q.kind} question '{q.id}' needs at least two options")
            if len(set(q.options)) != len(q.options):
                raise ValueError(f"{q.kind} question '{q.id}' has duplicate options")
            if len(q.options) > self.max_options:
                raise ValueError(
                    f"question '{q.id}' has {len(q.options)} options; "
                    f"{self.__class__.__name__} accepts at most {self.max_options}")

    def decide(self, state: str, questions: List[DecisionQuestion]) -> List[DecisionAnswer]:
        """Answer every question about ``state`` in one request."""
        self._check_questions(questions)
        response = self._decide_raw(state, questions)
        return self._calibrated(parse_systemone_answers(response, questions))

    def _calibrated(self, answers: List[DecisionAnswer]) -> List[DecisionAnswer]:
        """Apply ``ai_config.calibration`` (a file a ``decision-calibrate``
        training run wrote) to parsed answers; unchanged without one."""
        path = (getattr(self, "ai_config", None) or {}).get("calibration")
        if not path:
            return answers
        if getattr(self, "_calibration_path", None) != path:
            from potato.ai.decision_calibration import load_calibration
            try:
                self._calibration = load_calibration(str(path))
            except (OSError, ValueError) as e:
                raise AIEndpointRequestError(
                    f"Could not read the decision-model calibration {path}: {e}")
            self._calibration_path = path
        from potato.ai.decision_calibration import apply_calibration
        return apply_calibration(answers, self._calibration)

    def decide_batch(self, states: List[str],
                     questions: List[DecisionQuestion]) -> List[List[DecisionAnswer]]:
        """Answer the same questions for many states. Subclasses may batch."""
        return [self.decide(s, questions) for s in states]

    @abstractmethod
    def _decide_raw(self, state: str, questions: List[DecisionQuestion]) -> Dict[str, Any]:
        """Return the backend's /v1/systemone-shaped response."""

    # -- generation is not available ---------------------------------------

    def _refuse(self):
        raise AIEndpointRequestError(NOT_GENERATIVE_MESSAGE.format(name=self.__class__.__name__))

    def query(self, prompt: str, output_format: Optional[Type[BaseModel]] = None):
        self._refuse()

    def chat_query(self, messages: List[Dict[str, str]]) -> str:
        self._refuse()

    def chat_query_with_image(self, messages, images=None) -> str:
        self._refuse()

    def health_check(self) -> bool:  # pragma: no cover - overridden
        return False
