"""
Data structures shared across the codebook_lab pipeline.

A ``Code`` is one label's structured fields — the same shape as a row
from ``potato.codebook.store`` (``RICH_FIELDS``) plus ``name`` — so a list
of them can be wrapped directly in a ``potato.codebook.codebook.Codebook``
and rendered through the real ``potato.codebook.prompt`` pipeline with no
DB involved. That's what makes a "codebook variant" here just a plain
Python value: no project, no revision counter, no persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Mirrors potato.codebook.store.RICH_FIELDS — duplicated (not imported)
# so this package has zero dependency on the live codebook DB layer.
RICH_FIELDS = (
    "definition",
    "clarification",
    "negative_clarification",
    "positive_examples",
    "negative_examples",
    "exclusion_rules",
)


@dataclass
class Code:
    """One label's structured fields — a flat (non-nested) codebook entry."""
    name: str
    definition: str = ""
    clarification: str = ""
    negative_clarification: str = ""
    positive_examples: List[Dict[str, str]] = field(default_factory=list)
    negative_examples: List[Dict[str, str]] = field(default_factory=list)
    exclusion_rules: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, **{f: getattr(self, f) for f in RICH_FIELDS}}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Code":
        return cls(
            name=str(data["name"]),
            definition=data.get("definition", "") or "",
            clarification=data.get("clarification", "") or "",
            negative_clarification=data.get("negative_clarification", "") or "",
            positive_examples=list(data.get("positive_examples") or []),
            negative_examples=list(data.get("negative_examples") or []),
            exclusion_rules=list(data.get("exclusion_rules") or []),
        )

    def to_codebook_row(self, index: int) -> Dict[str, Any]:
        """Shape expected by potato.codebook.codebook.Codebook: id/name/
        parent_id/sort_order plus the rich fields. Flat (top-level-only)
        codebooks are all this package supports — id is just the name,
        which is fine for an in-memory, DB-free tree."""
        row: Dict[str, Any] = {
            "id": self.name,
            "name": self.name,
            "parent_id": "",  # potato.codebook.store.ROOT sentinel
            "sort_order": index,
        }
        row.update({f: getattr(self, f) for f in RICH_FIELDS})
        return row


@dataclass
class CodebookVariant:
    """One candidate codebook: a named, flat list of Codes."""
    variant_id: str
    codes: List[Code]
    # How this variant came to exist — "seed", "llm:<directive>", or
    # "hybrid:<label>=<source_variant_id>,...".
    origin: str = ""
    notes: str = ""

    def label_names(self) -> List[str]:
        return [c.name for c in self.codes]

    def code(self, name: str) -> Optional[Code]:
        return next((c for c in self.codes if c.name == name), None)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "origin": self.origin,
            "notes": self.notes,
            "codes": [c.to_dict() for c in self.codes],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CodebookVariant":
        return cls(
            variant_id=str(data["variant_id"]),
            origin=data.get("origin", ""),
            notes=data.get("notes", ""),
            codes=[Code.from_dict(c) for c in data.get("codes", [])],
        )

    def codebook_rows(self) -> List[Dict[str, Any]]:
        return [c.to_codebook_row(i) for i, c in enumerate(self.codes)]


@dataclass
class PlatinumExample:
    """One must-get-right instance: text plus its known-correct label(s).

    Single-label tasks have exactly one entry in ``labels``; multi-label
    tasks (e.g. GoEmotions) may have several. Files accept either
    ``label: "x"`` or ``labels: ["x", "y"]``."""
    example_id: str
    text: str
    labels: List[str]

    @property
    def label(self) -> str:
        """The single gold label — only meaningful for single-label tasks."""
        return self.labels[0]

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"id": self.example_id, "text": self.text}
        if len(self.labels) == 1:
            out["label"] = self.labels[0]
        else:
            out["labels"] = list(self.labels)
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlatinumExample":
        if data.get("labels") is not None:
            labels = [str(l) for l in data["labels"]]
        else:
            labels = [str(data["label"])]
        if not labels:
            raise ValueError(f"Platinum example {data!r} has no labels")
        return cls(
            example_id=str(data.get("id") or data.get("example_id")),
            text=str(data["text"]),
            labels=labels,
        )


@dataclass
class ExamplePrediction:
    """One scored example: what the variant predicted vs. the truth.

    ``true_labels``/``predicted_labels`` hold the full sets for
    multi-label tasks; ``true_label``/``predicted_label`` stay as the
    single-label view (first label) so single-label score files keep
    their shape."""
    example_id: str
    true_label: str
    predicted_label: Optional[str]
    correct: bool
    confidence: float = 0.0
    reasoning: str = ""
    error: Optional[str] = None
    true_labels: List[str] = field(default_factory=list)
    predicted_labels: List[str] = field(default_factory=list)
    # Labels the model returned that aren't in the codebook at all.
    invalid_labels: List[str] = field(default_factory=list)

    def gold_set(self) -> List[str]:
        return self.true_labels or [self.true_label]

    def predicted_set(self) -> List[str]:
        if self.predicted_labels:
            return self.predicted_labels
        return [self.predicted_label] if self.predicted_label else []

    def to_dict(self) -> Dict[str, Any]:
        out = {
            "example_id": self.example_id,
            "true_label": self.true_label,
            "predicted_label": self.predicted_label,
            "correct": self.correct,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "error": self.error,
        }
        if self.true_labels or self.predicted_labels or self.invalid_labels:
            out["true_labels"] = list(self.true_labels)
            out["predicted_labels"] = list(self.predicted_labels)
            out["invalid_labels"] = list(self.invalid_labels)
        return out

    @classmethod
    def from_dict(cls, p: Dict[str, Any]) -> "ExamplePrediction":
        return cls(
            example_id=str(p["example_id"]),
            true_label=str(p["true_label"]),
            predicted_label=p.get("predicted_label"),
            correct=bool(p["correct"]),
            confidence=float(p.get("confidence", 0.0)),
            reasoning=p.get("reasoning", ""),
            error=p.get("error"),
            true_labels=list(p.get("true_labels") or []),
            predicted_labels=list(p.get("predicted_labels") or []),
            invalid_labels=list(p.get("invalid_labels") or []),
        )


@dataclass
class VariantScore:
    """Result of scoring one variant against the whole platinum set.

    Single-label runs are scored by accuracy (per true label, and
    overall). Multi-label runs are scored by F1: per-label F1 over all
    examples, and macro-F1 overall — so a variant that over-applies a
    label pays for the false positives, not just the misses."""
    variant_id: str
    predictions: List[ExamplePrediction] = field(default_factory=list)
    multi_label: bool = False

    @property
    def metric_name(self) -> str:
        return "F1" if self.multi_label else "accuracy"

    @property
    def overall_accuracy(self) -> float:
        """Exact-match rate (for multi-label: predicted set == gold set)."""
        if not self.predictions:
            return 0.0
        return sum(p.correct for p in self.predictions) / len(self.predictions)

    def per_label_accuracy(self) -> Dict[str, float]:
        """Accuracy computed within each *true* label's examples — "how
        good is this variant specifically at the 'wait times' label"."""
        buckets: Dict[str, List[bool]] = {}
        for p in self.predictions:
            buckets.setdefault(p.true_label, []).append(p.correct)
        return {
            label: (sum(hits) / len(hits)) if hits else 0.0
            for label, hits in buckets.items()
        }

    def per_label_counts(self) -> Dict[str, Dict[str, int]]:
        """{label: {tp, fp, fn}} over every label seen in gold or
        predictions. Failed calls count as predicting nothing."""
        counts: Dict[str, Dict[str, int]] = {}

        def bump(label: str, key: str) -> None:
            counts.setdefault(label, {"tp": 0, "fp": 0, "fn": 0})[key] += 1

        for p in self.predictions:
            gold, pred = set(p.gold_set()), set(p.predicted_set())
            for l in gold & pred:
                bump(l, "tp")
            for l in pred - gold:
                bump(l, "fp")
            for l in gold - pred:
                bump(l, "fn")
        return counts

    def per_label_f1(self) -> Dict[str, float]:
        """F1 for every label that appears in the gold set. A label with
        no gold examples isn't scored (its F1 would be undefined) — but
        its false positives still drag down other labels' exact-match."""
        gold_labels = {l for p in self.predictions for l in p.gold_set()}
        out: Dict[str, float] = {}
        for label, c in self.per_label_counts().items():
            if label not in gold_labels:
                continue
            denom = 2 * c["tp"] + c["fp"] + c["fn"]
            out[label] = (2 * c["tp"] / denom) if denom else 0.0
        return out

    def per_label_score(self) -> Dict[str, float]:
        """The per-label metric the hybridizer and leaderboard rank by."""
        return self.per_label_f1() if self.multi_label else self.per_label_accuracy()

    @property
    def overall_score(self) -> float:
        """Accuracy for single-label runs, macro-F1 for multi-label."""
        if not self.multi_label:
            return self.overall_accuracy
        f1 = self.per_label_f1()
        return sum(f1.values()) / len(f1) if f1 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "variant_id": self.variant_id,
            "overall_accuracy": self.overall_accuracy,
            "per_label_accuracy": self.per_label_accuracy(),
        }
        if self.multi_label:
            out["multi_label"] = True
            out["macro_f1"] = self.overall_score
            out["per_label_f1"] = self.per_label_f1()
            out["per_label_counts"] = self.per_label_counts()
        out["predictions"] = [p.to_dict() for p in self.predictions]
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VariantScore":
        return cls(
            variant_id=str(data["variant_id"]),
            multi_label=bool(data.get("multi_label", False)),
            predictions=[
                ExamplePrediction.from_dict(p)
                for p in data.get("predictions", [])
            ],
        )
