"""
Step-Level Quality Control

Provides gold standard checks and attention checks at the individual
step level within agent traces. This enables fine-grained quality
assessment of annotators evaluating agent behavior.

Configuration:
    quality_control:
      step_level:
        enabled: true
        gold_standards_file: data/gold_steps.json
        attention_checks:
          enabled: true
          frequency: 5  # Insert attention check every N steps
"""

import json
import logging
import os
import random
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class StepGoldStandard:
    """A gold standard annotation for a specific step in a trace."""

    def __init__(
        self,
        instance_id: str,
        step_index: int,
        scheme_name: str,
        expected_label: str,
        tolerance: float = 0.0,
    ):
        self.instance_id = instance_id
        self.step_index = step_index
        self.scheme_name = scheme_name
        self.expected_label = expected_label
        self.tolerance = tolerance

    def check(self, annotator_label: str) -> bool:
        """Check if the annotator's label matches the gold standard."""
        if self.tolerance == 0:
            return annotator_label == self.expected_label
        # For numeric labels, allow tolerance
        try:
            expected = float(self.expected_label)
            actual = float(annotator_label)
            return abs(expected - actual) <= self.tolerance
        except (ValueError, TypeError):
            return annotator_label == self.expected_label

    def to_dict(self) -> Dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "step_index": self.step_index,
            "scheme_name": self.scheme_name,
            "expected_label": self.expected_label,
            "tolerance": self.tolerance,
        }


class StepAttentionCheck:
    """An attention check for a specific step type."""

    def __init__(
        self,
        question: str,
        expected_answer: str,
        action_type: Optional[str] = None,
    ):
        self.question = question
        self.expected_answer = expected_answer
        self.action_type = action_type  # Only show for specific action types

    def matches_step(self, step: Dict[str, Any]) -> bool:
        """Check if this attention check applies to the given step."""
        if self.action_type is None:
            return True
        return step.get("action_type") == self.action_type

    def check(self, answer: str) -> bool:
        """Check if the annotator's answer is correct."""
        return answer.strip().lower() == self.expected_answer.strip().lower()


class StepQualityControlManager:
    """
    Manages step-level quality control for agent trace annotations.

    Loads gold standards from file, tracks annotator performance,
    and injects attention checks.
    """

    def __init__(self, config: Dict[str, Any], base_dir: str = "."):
        self.config = config
        self.base_dir = base_dir
        self.enabled = config.get("enabled", False)

        # Gold standards
        self.gold_standards: List[StepGoldStandard] = []
        self._gold_by_instance: Dict[str, List[StepGoldStandard]] = {}

        # Attention checks
        self.attention_checks: List[StepAttentionCheck] = []
        self.attention_frequency = config.get("attention_checks", {}).get(
            "frequency", 5
        )
        self.attention_enabled = config.get("attention_checks", {}).get(
            "enabled", False
        )

        # Annotator performance tracking
        self._performance: Dict[str, Dict[str, Any]] = {}

        if self.enabled:
            self._load_gold_standards()
            self._load_attention_checks()

    def _load_gold_standards(self):
        """Load gold standard annotations from file."""
        gold_file = self.config.get("gold_standards_file", "")
        if not gold_file:
            return

        gold_path = os.path.join(self.base_dir, gold_file)
        if not os.path.isfile(gold_path):
            logger.warning(f"Gold standards file not found: {gold_path}")
            return

        try:
            with open(gold_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for item in data:
                gs = StepGoldStandard(
                    instance_id=item["instance_id"],
                    step_index=item["step_index"],
                    scheme_name=item["scheme_name"],
                    expected_label=item["expected_label"],
                    tolerance=item.get("tolerance", 0.0),
                )
                self.gold_standards.append(gs)

                if gs.instance_id not in self._gold_by_instance:
                    self._gold_by_instance[gs.instance_id] = []
                self._gold_by_instance[gs.instance_id].append(gs)

            logger.info(f"Loaded {len(self.gold_standards)} step gold standards")

        except Exception as e:
            logger.error(f"Failed to load gold standards: {e}")

    def _load_attention_checks(self):
        """Load attention check definitions."""
        checks_config = self.config.get("attention_checks", {})
        check_items = checks_config.get("items", [])

        if not check_items:
            # Default attention checks
            check_items = [
                {
                    "question": "What action type was just performed?",
                    "expected_answer": "",  # Dynamic
                    "action_type": None,
                },
            ]

        for item in check_items:
            self.attention_checks.append(
                StepAttentionCheck(
                    question=item.get("question", ""),
                    expected_answer=item.get("expected_answer", ""),
                    action_type=item.get("action_type"),
                )
            )

    def check_step_annotation(
        self,
        instance_id: str,
        step_index: int,
        scheme_name: str,
        annotator_id: str,
        label: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Check an annotator's step-level annotation against gold standards.

        Returns:
            Dict with check result or None if no gold standard exists
        """
        golds = self._gold_by_instance.get(instance_id, [])
        for gs in golds:
            if gs.step_index == step_index and gs.scheme_name == scheme_name:
                correct = gs.check(label)

                # Track performance
                self._track_performance(annotator_id, correct)

                return {
                    "is_gold": True,
                    "correct": correct,
                    "expected": gs.expected_label,
                    "given": label,
                    "step_index": step_index,
                    "scheme_name": scheme_name,
                }

        return None

    def should_inject_attention_check(
        self, annotator_id: str, steps_annotated: int
    ) -> bool:
        """Check if an attention check should be injected now."""
        if not self.attention_enabled:
            return False
        if self.attention_frequency <= 0:
            return False
        return steps_annotated > 0 and steps_annotated % self.attention_frequency == 0

    def get_attention_check(
        self, step: Optional[Dict[str, Any]] = None
    ) -> Optional[StepAttentionCheck]:
        """Get an appropriate attention check for the current step."""
        if not self.attention_checks:
            return None

        applicable = self.attention_checks
        if step:
            applicable = [c for c in self.attention_checks if c.matches_step(step)]

        if not applicable:
            applicable = self.attention_checks

        return random.choice(applicable)

    def _track_performance(self, annotator_id: str, correct: bool):
        """Track annotator performance on gold standards."""
        if annotator_id not in self._performance:
            self._performance[annotator_id] = {
                "total": 0,
                "correct": 0,
                "accuracy": 0.0,
            }

        perf = self._performance[annotator_id]
        perf["total"] += 1
        if correct:
            perf["correct"] += 1
        perf["accuracy"] = perf["correct"] / perf["total"] if perf["total"] > 0 else 0.0

    def get_annotator_performance(
        self, annotator_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get performance metrics for one or all annotators."""
        if annotator_id:
            return self._performance.get(annotator_id, {
                "total": 0, "correct": 0, "accuracy": 0.0
            })
        return dict(self._performance)

    def get_quality_summary(self) -> Dict[str, Any]:
        """Get overall quality control summary."""
        total_checks = sum(p["total"] for p in self._performance.values())
        total_correct = sum(p["correct"] for p in self._performance.values())

        return {
            "enabled": self.enabled,
            "gold_standards_count": len(self.gold_standards),
            "attention_checks_enabled": self.attention_enabled,
            "attention_frequency": self.attention_frequency,
            "total_checks_performed": total_checks,
            "total_correct": total_correct,
            "overall_accuracy": total_correct / total_checks if total_checks > 0 else None,
            "annotator_count": len(self._performance),
            "per_annotator": self._performance,
        }
