"""
Integration tests for the validated refinement framework.

Each test targets one pipeline step. LLM endpoints are mocked so tests
are fast and deterministic. Tests verify:

1. Validation split triggers when enough disagreements exist
2. Candidate evaluation correctly scores against baseline
3. Winner application creates a new prompt version or adds to ICL library
4. Failure counter increments when no candidate beats baseline
5. Failure counter stops the loop after max_consecutive_failures
6. Dry run mode logs but doesn't apply
7. Require approval mode queues for admin review
8. ICL library entries persist across save/load
9. Full end-to-end cycle with mocked strategy producing a winning candidate
"""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from potato.solo_mode import (
    init_solo_mode_manager,
    get_solo_mode_manager,
    clear_solo_mode_manager,
)
from potato.solo_mode.manager import LLMPrediction
from potato.solo_mode.refinement import (
    RefinementStrategy,
    RefinementCandidate,
    CandidateKind,
    register_strategy,
)


def _make_config(strategy='validated_focused_edit', dry_run=False, require_approval=False,
                 max_failures=2, min_val=3, num_candidates=3, tmp_path=None):
    state_dir = str(tmp_path / "solo_state") if tmp_path else "/tmp/solo_test"
    return {
        'solo_mode': {
            'enabled': True,
            'labeling_models': [{'endpoint_type': 'mock', 'model': 'test'}],
            'revision_models': [{'endpoint_type': 'mock', 'model': 'test'}],
            'uncertainty': {'strategy': 'direct_confidence'},
            'thresholds': {
                'end_human_annotation_agreement': 0.90,
                'minimum_validation_sample': 10,
                'confidence_low': 0.5,
                'confidence_high': 0.8,
            },
            'instance_selection': {
                'low_confidence_weight': 0.4,
                'diversity_weight': 0.3,
                'random_weight': 0.2,
                'disagreement_weight': 0.1,
            },
            'batches': {'llm_labeling_batch': 10, 'max_parallel_labels': 50},
            'state_dir': state_dir,
            'confusion_analysis': {'min_instances_for_pattern': 2},
            'refinement_loop': {
                'enabled': True,
                'trigger_interval': 10,
                'auto_apply_suggestions': True,
                'refinement_strategy': strategy,
                'validation_split_ratio': 0.3,
                'eval_sample_size': 5,
                'num_candidates': num_candidates,
                'min_val_size': min_val,
                'max_consecutive_failures': max_failures,
                'dry_run': dry_run,
                'require_approval': require_approval,
            },
        },
        'annotation_schemes': [{
            'name': 'sentiment',
            'annotation_type': 'radio',
            'labels': [{'name': 'positive'}, {'name': 'negative'}, {'name': 'neutral'}],
        }],
    }


def _inject_prediction_and_comparison(manager, iid, llm_label, human_label, prompt_version=1, confidence=0.8):
    """Helper: add an LLM prediction and record a human comparison."""
    pred = LLMPrediction(
        instance_id=iid,
        schema_name='sentiment',
        predicted_label=llm_label,
        confidence_score=confidence,
        uncertainty_score=1.0 - confidence,
        prompt_version=prompt_version,
        timestamp=datetime.now(),
    )
    manager.set_llm_prediction(iid, 'sentiment', pred)
    manager.record_human_label(iid, 'sentiment', human_label, 'test_user')


class MockWinningStrategy(RefinementStrategy):
    """Test strategy that proposes one winning candidate (always improves)."""
    NAME = "mock_winning"
    RECOMMENDED_OPTIMIZER_TIER = "small"
    BEST_FOR = ["testing"]
    DESCRIPTION = "Test strategy that always wins"

    def propose_candidates(self, patterns, current_prompt, train_comparisons):
        new_prompt = current_prompt + "\n\n## Annotation Guidelines\n\n- Pay attention to sarcasm.\n"
        return [RefinementCandidate(
            kind=CandidateKind.PROMPT_EDIT,
            payload={"new_prompt_text": new_prompt, "rules": ["Pay attention to sarcasm."]},
            proposed_by=self.NAME,
            rationale="test winning candidate",
        )]


class MockLosingStrategy(RefinementStrategy):
    """Test strategy that always loses validation."""
    NAME = "mock_losing"
    RECOMMENDED_OPTIMIZER_TIER = "small"
    BEST_FOR = ["testing"]
    DESCRIPTION = "Test strategy that always loses"

    def propose_candidates(self, patterns, current_prompt, train_comparisons):
        new_prompt = current_prompt + "\n\n## Annotation Guidelines\n\n- Bad rule.\n"
        return [RefinementCandidate(
            kind=CandidateKind.PROMPT_EDIT,
            payload={"new_prompt_text": new_prompt, "rules": ["Bad rule."]},
            proposed_by=self.NAME,
            rationale="test losing candidate",
        )]


class MockICLStrategy(RefinementStrategy):
    """Test strategy that proposes ICL examples."""
    NAME = "mock_icl"
    RECOMMENDED_OPTIMIZER_TIER = "small"
    BEST_FOR = ["testing"]
    DESCRIPTION = "Test ICL strategy"

    def propose_candidates(self, patterns, current_prompt, train_comparisons):
        if not patterns:
            return []
        # Use first pattern's first example
        ex = patterns[0].examples[0]
        return [RefinementCandidate(
            kind=CandidateKind.ICL_EXAMPLE,
            payload={
                "instance_id": ex.instance_id,
                "text": ex.text,
                "label": patterns[0].actual_label,
                "principle": "test principle",
            },
            proposed_by=self.NAME,
            rationale="test ICL candidate",
        )]


# Register test strategies
register_strategy(MockWinningStrategy)
register_strategy(MockLosingStrategy)
register_strategy(MockICLStrategy)


class TestValidatedRefinementIntegration:
    """Integration tests for the full validated refinement pipeline."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        clear_solo_mode_manager()
        self.tmp_path = tmp_path

        # Mock _label_with_candidate so we control accuracy per candidate
        self._candidate_accuracies = {}  # maps candidate prompt text -> accuracy dict
        yield
        clear_solo_mode_manager()

    def _setup_manager(self, strategy, **kwargs):
        """Create a manager with mocked labeling."""
        config = _make_config(strategy=strategy, tmp_path=self.tmp_path, **kwargs)
        manager = init_solo_mode_manager(config)

        # Mock get_instance_text to return predictable text
        manager._get_instance_text = lambda iid: f"Test text for {iid}"

        # Mock the labeling thread endpoint (needed by _label_with_candidate)
        mock_endpoint = MagicMock()
        manager.llm_labeling_thread._get_endpoint = lambda: mock_endpoint

        # Default: label_with_candidate returns wrong for baseline, right for winners
        def mock_label(iid, text, prompt):
            # Matches our test data: d_N are disagreements, label 'negative' is wrong
            # Winning indicators:
            # - "sarcasm" (winning prompt edit)
            # - "Pay attention" (winning prompt edit)
            # - "## Examples" (ICL candidate — contains an example)
            if ("sarcasm" in prompt or "Pay attention" in prompt
                    or "## Examples" in prompt):
                # Winning candidate: predict the human label
                return self._human_label_for.get(iid, 'positive')
            # Baseline or losing: predict something wrong
            return 'negative'
        manager._label_with_candidate = mock_label
        self._human_label_for = {}

        return manager

    def _add_disagreements(self, manager, count, winner_can_fix=True):
        """Add `count` disagreement comparisons so refinement can fire."""
        for i in range(count):
            iid = f"d_{i}"
            # LLM said 'negative', human said 'positive' — systematic disagreement
            _inject_prediction_and_comparison(
                manager, iid, llm_label='negative', human_label='positive',
                confidence=0.8, prompt_version=1,
            )
            if winner_can_fix:
                self._human_label_for[iid] = 'positive'

    # -----------------------------------------------------------------
    # Test 1: Skip cycle if not enough disagreements
    # -----------------------------------------------------------------
    def test_skips_cycle_when_insufficient_disagreements(self):
        manager = self._setup_manager('mock_winning', min_val=10)
        self._add_disagreements(manager, count=3)  # only 3, need 10+

        result = manager.trigger_refinement_cycle()
        assert result.get('success') is True
        assert 'Not enough disagreements' in result.get('message', '')

    # -----------------------------------------------------------------
    # Test 2: Winning candidate is applied
    # -----------------------------------------------------------------
    def test_winning_candidate_applied(self):
        manager = self._setup_manager('mock_winning', min_val=3)
        manager.create_prompt_version("Base prompt", created_by='test')
        self._add_disagreements(manager, count=15, winner_can_fix=True)

        initial_version = manager.current_prompt_version
        result = manager.trigger_refinement_cycle()

        assert result.get('success') is True
        assert manager.current_prompt_version > initial_version, \
            "Expected new prompt version after winning candidate applied"
        assert manager._refinement_consecutive_failures == 0

    # -----------------------------------------------------------------
    # Test 3: Losing candidate is rejected, failure counter increments
    # -----------------------------------------------------------------
    def test_losing_candidate_increments_failure_counter(self):
        manager = self._setup_manager('mock_losing', min_val=3)
        manager.create_prompt_version("Base prompt", created_by='test')
        self._add_disagreements(manager, count=15, winner_can_fix=False)

        initial_version = manager.current_prompt_version
        result = manager.trigger_refinement_cycle()

        assert manager._refinement_consecutive_failures == 1
        # No new prompt version
        assert manager.current_prompt_version == initial_version
        assert 'baseline' in result.get('message', '').lower() or \
               result.get('failure_reason') == 'no_candidate_beat_baseline'

    # -----------------------------------------------------------------
    # Test 4: Max consecutive failures stops the loop
    # -----------------------------------------------------------------
    def test_max_failures_stops_loop(self):
        manager = self._setup_manager('mock_losing', min_val=3, max_failures=2)
        manager.create_prompt_version("Base prompt", created_by='test')
        self._add_disagreements(manager, count=15, winner_can_fix=False)

        # Run cycle twice to hit max_consecutive_failures
        manager.trigger_refinement_cycle()
        manager.trigger_refinement_cycle()

        assert manager._refinement_consecutive_failures >= 2
        assert manager.refinement_loop.is_stopped

    # -----------------------------------------------------------------
    # Test 5: Dry run mode logs but doesn't apply
    # -----------------------------------------------------------------
    def test_dry_run_does_not_apply(self):
        manager = self._setup_manager('mock_winning', min_val=3, dry_run=True)
        manager.create_prompt_version("Base prompt", created_by='test')
        self._add_disagreements(manager, count=15, winner_can_fix=True)

        initial_version = manager.current_prompt_version
        result = manager.trigger_refinement_cycle()

        # Candidate wins, but dry run prevents apply
        assert result.get('dry_run') is True
        assert manager.current_prompt_version == initial_version, \
            "Dry run should not create a new prompt version"
        # But the log should contain it
        log = manager.get_refinement_log()
        assert len(log) >= 1
        assert log[-1].get('success') is True

    # -----------------------------------------------------------------
    # Test 6: Require approval mode queues for admin
    # -----------------------------------------------------------------
    def test_require_approval_queues_candidate(self):
        manager = self._setup_manager('mock_winning', min_val=3, require_approval=True)
        manager.create_prompt_version("Base prompt", created_by='test')
        self._add_disagreements(manager, count=15, winner_can_fix=True)

        initial_version = manager.current_prompt_version
        result = manager.trigger_refinement_cycle()

        assert result.get('status') == 'queued_for_approval'
        assert manager.current_prompt_version == initial_version, \
            "Should not apply until admin approves"
        pending = manager.get_pending_refinements()
        assert len(pending) == 1

    # -----------------------------------------------------------------
    # Test 7: Approval mechanism applies pending candidate
    # -----------------------------------------------------------------
    def test_approve_pending_applies_candidate(self):
        manager = self._setup_manager('mock_winning', min_val=3, require_approval=True)
        manager.create_prompt_version("Base prompt", created_by='test')
        self._add_disagreements(manager, count=15, winner_can_fix=True)
        manager.trigger_refinement_cycle()

        initial_version = manager.current_prompt_version
        assert len(manager.get_pending_refinements()) == 1

        result = manager.approve_pending_refinement(0)
        assert result.get('success') is True
        assert manager.current_prompt_version > initial_version, \
            "Approving should apply the candidate"
        assert len(manager.get_pending_refinements()) == 0

    # -----------------------------------------------------------------
    # Test 8: Reject pending discards candidate
    # -----------------------------------------------------------------
    def test_reject_pending_discards_candidate(self):
        manager = self._setup_manager('mock_winning', min_val=3, require_approval=True)
        manager.create_prompt_version("Base prompt", created_by='test')
        self._add_disagreements(manager, count=15, winner_can_fix=True)
        manager.trigger_refinement_cycle()

        initial_version = manager.current_prompt_version
        result = manager.reject_pending_refinement(0)
        assert result.get('success') is True
        assert manager.current_prompt_version == initial_version
        assert len(manager.get_pending_refinements()) == 0

    # -----------------------------------------------------------------
    # Test 9: ICL strategy adds to library on success
    # -----------------------------------------------------------------
    def test_icl_strategy_adds_to_library(self):
        manager = self._setup_manager('mock_icl', min_val=3)
        manager.create_prompt_version("Base prompt", created_by='test')
        self._add_disagreements(manager, count=15, winner_can_fix=True)

        result = manager.trigger_refinement_cycle()

        lib = manager._get_icl_library()
        assert lib.size() >= 1
        entries = lib.list_all()
        assert entries[0].label == 'positive'

    # -----------------------------------------------------------------
    # Test 10: ICL library examples show up in get_icl_examples()
    # -----------------------------------------------------------------
    def test_icl_library_examples_returned(self):
        manager = self._setup_manager('mock_icl', min_val=3)
        manager.create_prompt_version("Base prompt", created_by='test')
        self._add_disagreements(manager, count=15, winner_can_fix=True)
        manager.trigger_refinement_cycle()

        examples = manager.get_icl_examples(max_per_label=3, max_total=5)
        assert len(examples) >= 1
        # At least one example should be from the ICL library (label='positive')
        positive_examples = [e for e in examples if e['label'] == 'positive']
        assert len(positive_examples) >= 1

    # -----------------------------------------------------------------
    # Test 11: Full state persistence (save + load) preserves refinement state
    # -----------------------------------------------------------------
    def test_state_persistence(self):
        manager = self._setup_manager('mock_winning', min_val=3)
        manager.create_prompt_version("Base prompt", created_by='test')
        self._add_disagreements(manager, count=15, winner_can_fix=True)
        manager.trigger_refinement_cycle()

        # Capture state
        orig_version = manager.current_prompt_version
        orig_failures = manager._refinement_consecutive_failures
        orig_log_len = len(manager.get_refinement_log())

        manager._save_state()

        # Reinit
        clear_solo_mode_manager()
        manager2 = self._setup_manager('mock_winning', min_val=3)

        assert manager2.current_prompt_version == orig_version
        assert manager2._refinement_consecutive_failures == orig_failures
        assert len(manager2.get_refinement_log()) == orig_log_len

    # -----------------------------------------------------------------
    # Test 12: Refinement log records all cycles (success and failure)
    # -----------------------------------------------------------------
    def test_refinement_log_records_cycles(self):
        manager = self._setup_manager('mock_losing', min_val=3)
        manager.create_prompt_version("Base prompt", created_by='test')
        self._add_disagreements(manager, count=15, winner_can_fix=False)

        assert len(manager.get_refinement_log()) == 0
        manager.trigger_refinement_cycle()
        log = manager.get_refinement_log()
        assert len(log) == 1
        assert log[0].get('failure_reason') == 'no_candidate_beat_baseline'


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
