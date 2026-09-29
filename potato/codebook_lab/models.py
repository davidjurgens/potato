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
    """One must-get-right instance: text plus its known-correct label."""
    example_id: str
    text: str
    label: str

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.example_id, "text": self.text, "label": self.label}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlatinumExample":
        return cls(
            example_id=str(data.get("id") or data.get("example_id")),
            text=str(data["text"]),
            label=str(data["label"]),
        )


@dataclass
class ExamplePrediction:
    """One scored example: what the variant predicted vs. the truth."""
    example_id: str
    true_label: str
    predicted_label: Optional[str]
    correct: bool
    confidence: float = 0.0
    reasoning: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "example_id": self.example_id,
            "true_label": self.true_label,
            "predicted_label": self.predicted_label,
            "correct": self.correct,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "error": self.error,
        }


@dataclass
class VariantScore:
    """Result of scoring one variant against the whole platinum set."""
    variant_id: str
    predictions: List[ExamplePrediction] = field(default_factory=list)

    @property
    def overall_accuracy(self) -> float:
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "overall_accuracy": self.overall_accuracy,
            "per_label_accuracy": self.per_label_accuracy(),
            "predictions": [p.to_dict() for p in self.predictions],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VariantScore":
        return cls(
            variant_id=str(data["variant_id"]),
            predictions=[
                ExamplePrediction(
                    example_id=str(p["example_id"]),
                    true_label=str(p["true_label"]),
                    predicted_label=p.get("predicted_label"),
                    correct=bool(p["correct"]),
                    confidence=float(p.get("confidence", 0.0)),
                    reasoning=p.get("reasoning", ""),
                    error=p.get("error"),
                )
                for p in data.get("predictions", [])
            ],
        )
