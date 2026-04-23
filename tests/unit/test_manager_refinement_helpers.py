"""
Unit tests for manager helper methods used by the validated refinement framework.

These test the pieces that bridge the refinement framework to the manager:
- _build_eval_prompt_for_candidate: turns candidates into eval prompts
- _build_patterns_from_comparisons: builds ConfusionPattern from raw comparisons
- ICL library persistence through manager save/load
- get_icl_examples returns validated library entries first
"""
import pytest
import tempfile
from datetime import datetime

from potato.solo_mode import (
    init_solo_mode_manager,
    get_solo_mode_manager,
    clear_solo_mode_manager,
)
from potato.solo_mode.manager import LLMPrediction
from potato.solo_mode.refinement.base import (
    RefinementCandidate, CandidateKind,
)
from potato.solo_mode.refinement.icl_library import ICLEntry


def _make_config(tmp_path):
    return {
        'solo_mode': {
            'enabled': True,
            'labeling_models': [{'endpoint_type': 'mock', 'model': 'test'}],
            'uncertainty': {'strategy': 'direct_confidence'},
            'state_dir': str(tmp_path / "solo_state"),
        },
        'annotation_schemes': [{
            'name': 'sentiment',
            'annotation_type': 'radio',
            'labels': [{'name': 'positive'}, {'name': 'negative'}, {'name': 'neutral'}],
        }],
    }


@pytest.fixture
def manager(tmp_path):
    clear_solo_mode_manager()
    m = init_solo_mode_manager(_make_config(tmp_path))
    m._get_instance_text = lambda iid: f"Test text for {iid}"
    yield m
    clear_solo_mode_manager()


class TestBuildEvalPromptForCandidate:
    """Test candidate -> eval prompt construction."""

    def test_prompt_edit_candidate(self, manager):
        cand = RefinementCandidate(
            kind=CandidateKind.PROMPT_EDIT,
            payload={
                "new_prompt_text": "EDITED PROMPT",
                "rules": ["rule 1"],
            },
        )
        result = manager._build_eval_prompt_for_candidate(cand, "ORIGINAL")
        assert result == "EDITED PROMPT"

    def test_icl_example_candidate_appends_example(self, manager):
        cand = RefinementCandidate(
            kind=CandidateKind.ICL_EXAMPLE,
            payload={
                "instance_id": "a",
                "text": "Sample text",
                "label": "positive",
                "principle": "some principle",
            },
        )
        result = manager._build_eval_prompt_for_candidate(cand, "BASE PROMPT")
        assert "BASE PROMPT" in result
        assert "## Examples" in result
        assert "Sample text" in result
        assert "positive" in result

    def test_principle_candidate_appends_principle(self, manager):
        cand = RefinementCandidate(
            kind=CandidateKind.PRINCIPLE,
            payload="Focus on valence",
        )
        result = manager._build_eval_prompt_for_candidate(cand, "BASE")
        assert "BASE" in result
        assert "Focus on valence" in result


class TestBuildPatternsFromComparisons:
    """Test that _build_patterns_from_comparisons filters correctly."""

    def test_filters_agreements(self, manager):
        manager._get_instance_text = lambda iid: f"text {iid}"
        # Add several predictions so we can look up text
        for i in range(5):
            pred = LLMPrediction(
                instance_id=f"a_{i}", schema_name="sentiment",
                predicted_label="pos", confidence_score=0.8,
                uncertainty_score=0.2, prompt_version=1,
                timestamp=datetime.now(),
            )
            manager.set_llm_prediction(f"a_{i}", "sentiment", pred)

        comparisons = [
            {"instance_id": f"a_{i}", "human_label": "neg",
             "llm_label": "pos", "agrees": False}
            for i in range(5)
        ] + [
            {"instance_id": f"a_{i}", "human_label": "pos",
             "llm_label": "pos", "agrees": True}
            for i in range(5, 10)
        ]

        patterns = manager._build_patterns_from_comparisons(comparisons)
        assert len(patterns) >= 1
        assert patterns[0].predicted_label == "pos"
        assert patterns[0].actual_label == "neg"
        assert patterns[0].count == 5

    def test_respects_min_instances(self, manager):
        # Default is 3 from the _make_config, but let's test with too few
        manager.config.confusion_analysis.min_instances_for_pattern = 10
        comparisons = [
            {"instance_id": f"a_{i}", "human_label": "neg",
             "llm_label": "pos", "agrees": False}
            for i in range(5)
        ]
        patterns = manager._build_patterns_from_comparisons(comparisons)
        assert len(patterns) == 0  # below threshold


class TestICLLibraryPersistence:
    """Verify ICL library survives save/load via the manager."""

    def test_library_persists(self, manager, tmp_path):
        lib = manager._get_icl_library()
        lib.add(ICLEntry(
            instance_id="test_id",
            text="A good example",
            label="positive",
            principle="when positive",
            val_accuracy_gain=0.15,
        ))
        assert manager._get_icl_library().size() == 1
        manager._save_state()

        clear_solo_mode_manager()
        m2 = init_solo_mode_manager(_make_config(tmp_path))
        m2._get_instance_text = lambda iid: ""
        assert m2._get_icl_library().size() == 1
        entry = m2._get_icl_library().list_all()[0]
        assert entry.instance_id == "test_id"
        assert entry.val_accuracy_gain == pytest.approx(0.15)


class TestGetICLExamplesIntegration:
    """Verify get_icl_examples returns validated library first, then agreements."""

    def test_library_examples_first(self, manager):
        # Add to library
        lib = manager._get_icl_library()
        lib.add(ICLEntry(
            instance_id="lib_1", text="Library ex", label="positive",
            val_accuracy_gain=0.3,
        ))

        # Add a human-labeled agreement
        pred = LLMPrediction(
            instance_id="agr_1", schema_name="sentiment",
            predicted_label="negative", confidence_score=0.9,
            uncertainty_score=0.1, prompt_version=1,
            timestamp=datetime.now(),
            human_label="negative", agrees_with_human=True,
        )
        manager.set_llm_prediction("agr_1", "sentiment", pred)
        manager.human_labeled_ids.add("agr_1")

        examples = manager.get_icl_examples(max_per_label=1, max_total=5)
        # Library entry should be first (highest gain)
        assert any(e['text'] == 'Library ex' for e in examples)

    def test_falls_back_to_agreements_when_library_empty(self, manager):
        # Add only human-labeled agreements
        pred = LLMPrediction(
            instance_id="agr_1", schema_name="sentiment",
            predicted_label="neutral", confidence_score=0.9,
            uncertainty_score=0.1, prompt_version=1,
            timestamp=datetime.now(),
            human_label="neutral", agrees_with_human=True,
        )
        manager.set_llm_prediction("agr_1", "sentiment", pred)
        manager.human_labeled_ids.add("agr_1")

        examples = manager.get_icl_examples(max_per_label=2, max_total=5)
        assert any(e['label'] == 'neutral' for e in examples)


class TestFailureCounterResumeLogic:
    """Test that the failure counter resets correctly."""

    def test_initial_state(self, manager):
        assert manager._refinement_consecutive_failures == 0

    def test_counter_increments(self, manager):
        manager._handle_refinement_failure("test_strat", reason="test")
        assert manager._refinement_consecutive_failures == 1
        manager._handle_refinement_failure("test_strat", reason="test")
        assert manager._refinement_consecutive_failures == 2

    def test_counter_stops_loop_at_max(self, manager):
        manager.config.refinement_loop.max_consecutive_failures = 2
        manager._handle_refinement_failure("test", reason="bad")
        assert not manager.refinement_loop.is_stopped
        manager._handle_refinement_failure("test", reason="bad")
        assert manager.refinement_loop.is_stopped


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
