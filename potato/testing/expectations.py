"""
Fluent ``expect(...)`` assertions for Potato eval tests (LangSmith-style).

    from potato.testing import expect

    expect(output).to_contain("answer")
    expect.edit_distance(output, reference).to_be_less_than(0.3)
    expect.embedding_distance(output, reference).to_be_less_than(0.2)
    expect(score).to_be_greater_than(0.8)

Each matcher raises ``AssertionError`` on failure (so pytest reports it) with a
clear message that names the metric and the actual value.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from potato.evaluators.heuristic import _levenshtein, EmbeddingDistance


def _as_text(v: Any) -> str:
    return v if isinstance(v, str) else str(v)


def normalized_edit_distance(a: Any, b: Any) -> float:
    """0.0 = identical, 1.0 = maximally different."""
    a, b = _as_text(a), _as_text(b)
    maxlen = max(len(a), len(b)) or 1
    return _levenshtein(a, b) / maxlen


class Matcher:
    """Wraps a value (often a computed metric) with fluent assertions."""

    def __init__(self, value: Any, label: str = "value"):
        self.value = value
        self.label = label

    def _fail(self, expectation: str):
        raise AssertionError(f"expected {self.label} ({self.value!r}) {expectation}")

    def to_equal(self, other: Any) -> "Matcher":
        if self.value != other:
            self._fail(f"to equal {other!r}")
        return self

    def to_contain(self, sub: Any) -> "Matcher":
        if sub not in self.value:
            self._fail(f"to contain {sub!r}")
        return self

    def to_be_less_than(self, n: float) -> "Matcher":
        if not (self.value < n):
            self._fail(f"to be less than {n}")
        return self

    def to_be_greater_than(self, n: float) -> "Matcher":
        if not (self.value > n):
            self._fail(f"to be greater than {n}")
        return self

    def to_be_between(self, lo: float, hi: float) -> "Matcher":
        if not (lo <= self.value <= hi):
            self._fail(f"to be between {lo} and {hi}")
        return self

    def to_be_close_to(self, target: float, tolerance: float = 1e-6) -> "Matcher":
        if abs(self.value - target) > tolerance:
            self._fail(f"to be close to {target} (±{tolerance})")
        return self


class _Expect:
    """Callable that also exposes metric constructors."""

    def __call__(self, value: Any, label: str = "value") -> Matcher:
        return Matcher(value, label)

    def edit_distance(self, a: Any, b: Any) -> Matcher:
        return Matcher(normalized_edit_distance(a, b), "edit_distance")

    def embedding_distance(self, a: Any, b: Any,
                           embed_fn: Optional[Callable[[str], list]] = None) -> Matcher:
        ev = EmbeddingDistance(embed_fn=embed_fn)
        sim = ev.evaluate(outputs=a, reference_outputs=b).score or 0.0
        return Matcher(1.0 - sim, "embedding_distance")  # distance = 1 - cosine sim


expect = _Expect()
