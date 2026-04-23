"""
Unit tests for the refinement framework foundation.

Tests each component in isolation with mocks:
- ValidationSplit: deterministic train/val split
- CandidateEvaluator: scoring candidates on val set
- ICLLibrary: persistent example storage
- Strategy registry: lookup and registration
"""
import pytest

from potato.solo_mode.refinement.validation import (
    ValidationSplit, CandidateEvaluator, SplitResult, EvalResult,
)
from potato.solo_mode.refinement.icl_library import ICLLibrary, ICLEntry
from potato.solo_mode.refinement.registry import (
    get_strategy, list_strategies, register_strategy,
)
from potato.solo_mode.refinement.base import (
    RefinementStrategy, RefinementCandidate, RefinementResult, CandidateKind,
)


# ===========================================================================
# ValidationSplit tests
# ===========================================================================

class TestValidationSplit:
    """Test the train/val split logic."""

    def _make_comparisons(self, n_disagree, n_agree):
        disagreements = [
            {"instance_id": f"d_{i}", "human_label": "pos", "llm_label": "neg", "agrees": False}
            for i in range(n_disagree)
        ]
        agreements = [
            {"instance_id": f"a_{i}", "human_label": "pos", "llm_label": "pos", "agrees": True}
            for i in range(n_agree)
        ]
        return disagreements + agreements

    def test_split_with_enough_data(self):
        split = ValidationSplit(val_ratio=0.3, min_val=3, min_train=3)
        comparisons = self._make_comparisons(20, 5)
        result = split.split(comparisons, prompt_version=1)
        assert len(result.val) >= 3
        assert len(result.train) > 0
        # Val should only contain disagreements
        for v in result.val:
            assert not v["agrees"]
        # Train includes both disagreements and agreements
        train_agrees = [c for c in result.train if c["agrees"]]
        assert len(train_agrees) == 5

    def test_split_insufficient_data(self):
        split = ValidationSplit(val_ratio=0.3, min_val=5, min_train=5)
        comparisons = self._make_comparisons(5, 2)  # only 5 disagreements, need 10+
        result = split.split(comparisons, prompt_version=1)
        assert result.train == []
        assert result.val == []

    def test_split_deterministic_per_version(self):
        split = ValidationSplit(val_ratio=0.3, min_val=3, min_train=3)
        comparisons = self._make_comparisons(20, 0)
        r1 = split.split(comparisons, prompt_version=1)
        r2 = split.split(comparisons, prompt_version=1)
        r3 = split.split(comparisons, prompt_version=2)
        # Same version = same split
        assert [c["instance_id"] for c in r1.val] == [c["instance_id"] for c in r2.val]
        # Different version = different split
        assert set(c["instance_id"] for c in r1.val) != set(c["instance_id"] for c in r3.val) or len(r1.val) != len(r3.val)

    def test_no_overlap_between_train_and_val(self):
        split = ValidationSplit(val_ratio=0.3, min_val=3, min_train=3)
        comparisons = self._make_comparisons(20, 0)
        result = split.split(comparisons, prompt_version=1)
        train_ids = {c["instance_id"] for c in result.train}
        val_ids = {c["instance_id"] for c in result.val}
        assert train_ids.isdisjoint(val_ids)


# ===========================================================================
# CandidateEvaluator tests
# ===========================================================================

class TestCandidateEvaluator:
    """Test candidate evaluation against validation set."""

    def test_evaluates_correctly_labeled(self):
        # Label fn: always returns the expected human label (perfect)
        def label_fn(iid, text, prompt):
            return "pos"

        def text_fn(iid):
            return f"text for {iid}"

        evaluator = CandidateEvaluator(label_fn=label_fn, get_text_fn=text_fn)
        val = [
            {"instance_id": "a", "human_label": "pos"},
            {"instance_id": "b", "human_label": "pos"},
            {"instance_id": "c", "human_label": "pos"},
        ]
        result = evaluator.evaluate("dummy prompt", val)
        assert result.accuracy == 1.0
        assert result.correct_count == 3

    def test_evaluates_incorrectly_labeled(self):
        def label_fn(iid, text, prompt):
            return "pos"  # always pos

        def text_fn(iid):
            return f"text for {iid}"

        evaluator = CandidateEvaluator(label_fn=label_fn, get_text_fn=text_fn)
        val = [
            {"instance_id": "a", "human_label": "neg"},
            {"instance_id": "b", "human_label": "neg"},
            {"instance_id": "c", "human_label": "pos"},
        ]
        result = evaluator.evaluate("dummy prompt", val)
        assert result.accuracy == pytest.approx(1.0 / 3.0)
        assert result.correct_count == 1

    def test_evaluator_handles_label_fn_failures(self):
        def label_fn(iid, text, prompt):
            if iid == "a":
                raise ValueError("boom")
            return "pos"

        def text_fn(iid):
            return f"text for {iid}"

        evaluator = CandidateEvaluator(label_fn=label_fn, get_text_fn=text_fn)
        val = [
            {"instance_id": "a", "human_label": "pos"},
            {"instance_id": "b", "human_label": "pos"},
        ]
        result = evaluator.evaluate("dummy prompt", val)
        # 'a' failed (predicted=None, not correct); 'b' correct
        assert result.correct_count == 1
        assert result.accuracy == 0.5

    def test_evaluator_skips_instances_without_human_label(self):
        def label_fn(iid, text, prompt):
            return "pos"

        def text_fn(iid):
            return f"text for {iid}"

        evaluator = CandidateEvaluator(label_fn=label_fn, get_text_fn=text_fn)
        val = [
            {"instance_id": "a", "human_label": "pos"},
            {"instance_id": "b", "human_label": None},
            {"instance_id": "c"},  # no human_label key
        ]
        result = evaluator.evaluate("dummy prompt", val)
        assert result.total == 1  # only 'a' scored
        assert result.correct_count == 1


# ===========================================================================
# ICLLibrary tests
# ===========================================================================

class TestICLLibrary:
    """Test the persistent ICL example library."""

    def test_add_and_get(self):
        lib = ICLLibrary(max_size=5)
        lib.add(ICLEntry(
            instance_id="a", text="Great!", label="pos",
            val_accuracy_gain=0.2,
        ))
        examples = lib.get_examples()
        assert len(examples) == 1
        assert examples[0]["text"] == "Great!"
        assert examples[0]["label"] == "pos"

    def test_dedupe_by_instance_id(self):
        lib = ICLLibrary()
        lib.add(ICLEntry(instance_id="a", text="Great!", label="pos", val_accuracy_gain=0.1))
        lib.add(ICLEntry(instance_id="a", text="Different text", label="pos", val_accuracy_gain=0.5))
        assert lib.size() == 1
        # Original kept
        entries = lib.list_all()
        assert entries[0].text == "Great!"

    def test_get_examples_sorts_by_gain(self):
        lib = ICLLibrary()
        lib.add(ICLEntry(instance_id="a", text="A", label="pos", val_accuracy_gain=0.1))
        lib.add(ICLEntry(instance_id="b", text="B", label="neg", val_accuracy_gain=0.5))
        lib.add(ICLEntry(instance_id="c", text="C", label="pos", val_accuracy_gain=0.3))
        examples = lib.get_examples(max_per_label=2, max_total=5)
        # Sorted by gain desc: B, C, A
        texts = [e["text"] for e in examples]
        assert texts[0] == "B"

    def test_max_per_label(self):
        lib = ICLLibrary()
        lib.add(ICLEntry(instance_id="a", text="A", label="pos", val_accuracy_gain=0.5))
        lib.add(ICLEntry(instance_id="b", text="B", label="pos", val_accuracy_gain=0.4))
        lib.add(ICLEntry(instance_id="c", text="C", label="pos", val_accuracy_gain=0.3))
        examples = lib.get_examples(max_per_label=1, max_total=5)
        assert len(examples) == 1

    def test_max_total(self):
        lib = ICLLibrary()
        for i, label in enumerate(["pos", "neg", "neutral", "other"]):
            lib.add(ICLEntry(
                instance_id=f"i{i}", text=f"T{i}", label=label,
                val_accuracy_gain=0.1 * i,
            ))
        examples = lib.get_examples(max_per_label=1, max_total=2)
        assert len(examples) == 2

    def test_remove(self):
        lib = ICLLibrary()
        lib.add(ICLEntry(instance_id="a", text="A", label="pos", val_accuracy_gain=0.1))
        assert lib.remove("a") is True
        assert lib.size() == 0
        assert lib.remove("nonexistent") is False

    def test_serialization_roundtrip(self):
        lib = ICLLibrary(max_size=7)
        lib.add(ICLEntry(instance_id="a", text="Hello", label="pos", val_accuracy_gain=0.2))
        lib.add(ICLEntry(instance_id="b", text="World", label="neg", val_accuracy_gain=0.3))
        data = lib.to_dict()
        restored = ICLLibrary.from_dict(data)
        assert restored.size() == 2
        assert restored.max_size == 7
        assert restored.list_all()[0].instance_id == "a"


# ===========================================================================
# Strategy registry tests
# ===========================================================================

class TestStrategyRegistry:
    """Test strategy lookup and registration."""

    def test_builtin_strategies_registered(self):
        strategies = list_strategies()
        names = {s["name"] for s in strategies}
        assert "validated_focused_edit" in names
        assert "principle_icl" in names
        assert "hybrid_dual_track" in names
        assert "legacy_append" in names

    def test_get_strategy_returns_class(self):
        cls = get_strategy("validated_focused_edit")
        assert issubclass(cls, RefinementStrategy)
        assert cls.NAME == "validated_focused_edit"

    def test_unknown_strategy_raises(self):
        with pytest.raises(KeyError, match="Unknown refinement strategy"):
            get_strategy("nonexistent_strategy")

    def test_strategy_metadata(self):
        strategies = list_strategies()
        for s in strategies:
            assert s["tier"] in ("small", "medium", "large")
            assert s["description"]


# ===========================================================================
# Candidate / Result dataclass tests
# ===========================================================================

class TestRefinementDataclasses:
    """Test the core data structures."""

    def test_candidate_kinds(self):
        assert CandidateKind.PROMPT_EDIT.value == "prompt_edit"
        assert CandidateKind.ICL_EXAMPLE.value == "icl_example"
        assert CandidateKind.PRINCIPLE.value == "principle"

    def test_result_to_dict(self):
        cand = RefinementCandidate(
            kind=CandidateKind.PROMPT_EDIT,
            payload={"new_prompt_text": "foo", "rules": ["r1"]},
            proposed_by="test",
        )
        result = RefinementResult(
            success=True,
            strategy="test_strategy",
            applied_candidate=cand,
            all_candidates=[cand],
            val_baseline_accuracy=0.5,
            val_candidate_accuracies={0: 0.7},
            val_sample_size=10,
            train_sample_size=20,
        )
        d = result.to_dict()
        assert d["success"] is True
        assert d["strategy"] == "test_strategy"
        assert d["applied_candidate"]["kind"] == "prompt_edit"
        assert d["val_candidate_accuracies"]["0"] == 0.7


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
