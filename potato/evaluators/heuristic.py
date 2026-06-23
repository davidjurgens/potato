"""
Heuristic / code evaluators -- deterministic, dependency-light scorers for
output text.

These cover the common reference-based checks (exact match, contains, regex,
edit distance) plus structural checks (valid JSON, JSON-schema match). The
embedding-distance evaluator lazily imports ``sentence_transformers`` (or uses
an injected embed function) so importing this module never pulls the ML stack
-- see the boot-weight constraint in the project memory.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

from potato.evaluators.base import Evaluator, EvaluationResult


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        # Common output containers
        for k in ("output", "text", "content", "answer", "final_answer"):
            if k in value and isinstance(value[k], str):
                return value[k]
    return str(value)


class ExactMatch(Evaluator):
    def __init__(self, case_sensitive: bool = True, strip: bool = True, key: str = "exact_match"):
        self.case_sensitive = case_sensitive
        self.strip = strip
        self.key = key

    def _norm(self, s: str) -> str:
        if self.strip:
            s = s.strip()
        if not self.case_sensitive:
            s = s.lower()
        return s

    def evaluate(self, *, outputs=None, reference_outputs=None, inputs=None, **kwargs) -> EvaluationResult:
        out, ref = self._norm(_as_text(outputs)), self._norm(_as_text(reference_outputs))
        match = out == ref
        return EvaluationResult(key=self.key, score=1.0 if match else 0.0, value=match)


class Contains(Evaluator):
    def __init__(self, substring: Optional[str] = None, case_sensitive: bool = False, key: str = "contains"):
        self.substring = substring
        self.case_sensitive = case_sensitive
        self.key = key

    def evaluate(self, *, outputs=None, reference_outputs=None, inputs=None, **kwargs) -> EvaluationResult:
        needle = self.substring if self.substring is not None else _as_text(reference_outputs)
        hay = _as_text(outputs)
        if not self.case_sensitive:
            needle, hay = needle.lower(), hay.lower()
        found = needle in hay if needle else False
        return EvaluationResult(key=self.key, score=1.0 if found else 0.0, value=found)


class RegexMatch(Evaluator):
    def __init__(self, pattern: str, flags: int = 0, key: str = "regex_match"):
        self.pattern = re.compile(pattern, flags)
        self.key = key

    def evaluate(self, *, outputs=None, reference_outputs=None, inputs=None, **kwargs) -> EvaluationResult:
        found = bool(self.pattern.search(_as_text(outputs)))
        return EvaluationResult(key=self.key, score=1.0 if found else 0.0, value=found)


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


class EditDistance(Evaluator):
    """Normalized edit distance. ``score`` = 1 - dist/maxlen (1.0 = identical)."""

    def __init__(self, key: str = "edit_distance"):
        self.key = key

    def evaluate(self, *, outputs=None, reference_outputs=None, inputs=None, **kwargs) -> EvaluationResult:
        out, ref = _as_text(outputs), _as_text(reference_outputs)
        dist = _levenshtein(out, ref)
        maxlen = max(len(out), len(ref)) or 1
        score = 1.0 - dist / maxlen
        return EvaluationResult(
            key=self.key, score=score, value=dist,
            comment=f"edit distance {dist} over max length {maxlen}",
        )


class JSONValid(Evaluator):
    def __init__(self, key: str = "json_valid"):
        self.key = key

    def evaluate(self, *, outputs=None, reference_outputs=None, inputs=None, **kwargs) -> EvaluationResult:
        text = _as_text(outputs)
        try:
            json.loads(text)
            return EvaluationResult(key=self.key, score=1.0, value=True)
        except (json.JSONDecodeError, ValueError) as e:
            return EvaluationResult(key=self.key, score=0.0, value=False, comment=str(e))


class JSONSchemaMatch(Evaluator):
    """Validate output JSON against a JSON schema (lazy ``jsonschema`` import)."""

    def __init__(self, schema: Dict[str, Any], key: str = "json_schema_match"):
        self.schema = schema
        self.key = key

    def evaluate(self, *, outputs=None, reference_outputs=None, inputs=None, **kwargs) -> EvaluationResult:
        text = _as_text(outputs)
        try:
            data = json.loads(text) if isinstance(text, str) else text
        except (json.JSONDecodeError, ValueError) as e:
            return EvaluationResult(key=self.key, score=0.0, value=False, comment=f"invalid JSON: {e}")
        try:
            import jsonschema  # lazy, optional
        except ImportError:  # pragma: no cover
            raise ImportError("JSONSchemaMatch requires the 'jsonschema' package")
        try:
            jsonschema.validate(data, self.schema)
            return EvaluationResult(key=self.key, score=1.0, value=True)
        except jsonschema.ValidationError as e:
            return EvaluationResult(key=self.key, score=0.0, value=False, comment=e.message)


class EmbeddingDistance(Evaluator):
    """Cosine similarity between output and reference embeddings.

    ``embed_fn`` (str -> list[float]) may be injected (tests, custom endpoints).
    Otherwise ``sentence_transformers`` is imported lazily on first use.
    """

    def __init__(
        self,
        embed_fn: Optional[Callable[[str], List[float]]] = None,
        model_name: str = "all-MiniLM-L6-v2",
        key: str = "embedding_similarity",
    ):
        self._embed_fn = embed_fn
        self.model_name = model_name
        self.key = key
        self._model = None

    def _embed(self, text: str) -> List[float]:
        if self._embed_fn is not None:
            return self._embed_fn(text)
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # lazy
            self._model = SentenceTransformer(self.model_name)
        return self._model.encode(text).tolist()

    @staticmethod
    def _cosine(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(y * y for y in b) ** 0.5
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    def evaluate(self, *, outputs=None, reference_outputs=None, inputs=None, **kwargs) -> EvaluationResult:
        sim = self._cosine(self._embed(_as_text(outputs)), self._embed(_as_text(reference_outputs)))
        return EvaluationResult(key=self.key, score=sim, value=sim)
