"""
Integration tests for Solo Mode workflow.

Tests the complete Solo Mode workflow including:
- Manager initialization and configuration
- Phase state machine transitions
- Prompt management
- Instance selection
- LLM labeling (mocked)
- Agreement tracking
- Validation workflow
"""

import json
import os
import pytest
import time
from unittest.mock import patch, MagicMock

from potato.solo_mode import (
    SoloModeManager,
    SoloModeConfig,
    SoloPhase,
    SoloPhaseController,
    InstanceSelector,
    SelectionWeights,
    ValidationTracker,
    DisagreementDetector,
    DisagreementResolver,
    parse_solo_mode_config,
    init_solo_mode_manager,
    get_solo_mode_manager,
    clear_solo_mode_manager,
)


class TestSoloModeManagerIntegration:
    """Integration tests for SoloModeManager."""

    @pytest.fixture(autouse=True)
    def setup_manager(self, tmp_path):
        """Set up and tear down manager for each test."""
        clear_solo_mode_manager()
        # Store tmp_path for test config
        self._state_dir = str(tmp_path / "solo_state")
        yield
        clear_solo_mode_manager()

    def create_test_config(self):
        """Create test configuration."""
        return {
            'solo_mode': {
                'enabled': True,
                'labeling_models': [
                    {'endpoint_type': 'mock', 'model': 'mock-model'}
                ],
                'revision_models': [
                    {'endpoint_type': 'mock', 'model': 'mock-model'}
                ],
                'uncertainty': {'strategy': 'direct_confidence'},
                'thresholds': {
                    'end_human_annotation_agreement': 0.90,
                    'minimum_validation_sample': 10,
                    'confidence_low': 0.5,
                    'confidence_high': 0.8,
                    'periodic_review_interval': 50,
                },
                'instance_selection': {
                    'low_confidence_weight': 0.4,
                    'diversity_weight': 0.3,
                    'random_weight': 0.2,
                    'disagreement_weight': 0.1,
                },
                'batches': {
                    'llm_labeling_batch': 10,
                    'max_parallel_labels': 50,
                },
                'state_dir': getattr(self, '_state_dir', '/tmp/solo_test_state'),
            },
            'annotation_schemes': [
                {
                    'name': 'sentiment',
                    'annotation_type': 'radio',
                    'labels': [
                        {'name': 'positive'},
                        {'name': 'negative'},
                        {'name': 'neutral'},
                    ]
                }
            ],
        }

    def test_manager_initialization(self):
        """Test that manager initializes correctly."""
        config = self.create_test_config()
        manager = init_solo_mode_manager(config)

        assert manager is not None
        assert manager.config.enabled is True

    def test_manager_singleton(self):
        """Test that manager is a singleton."""
        config = self.create_test_config()

        manager1 = init_solo_mode_manager(config)
        manager2 = get_solo_mode_manager()

        assert manager1 is manager2

    def test_manager_initial_phase(self):
        """Test that manager starts in setup phase."""
        config = self.create_test_config()
        manager = init_solo_mode_manager(config)

        phase = manager.get_current_phase()
        assert phase == SoloPhase.SETUP

    def test_manager_phase_transition(self):
        """Test phase transitions work correctly."""
        config = self.create_test_config()
        manager = init_solo_mode_manager(config)

        # Initial phase
        assert manager.get_current_phase() == SoloPhase.SETUP

        # Transition to prompt review
        success = manager.advance_to_phase(SoloPhase.PROMPT_REVIEW)
        assert success is True
        assert manager.get_current_phase() == SoloPhase.PROMPT_REVIEW

    def test_manager_create_prompt_version(self):
        """Test creating prompt versions."""
        config = self.create_test_config()
        manager = init_solo_mode_manager(config)

        # Create initial prompt
        prompt = manager.create_prompt_version(
            "Test prompt for sentiment analysis",
            created_by='test',
            source_description='Test source'
        )

        assert prompt is not None
        assert prompt.version == 1
        assert prompt.created_by == 'test'

    def test_manager_get_current_prompt(self):
        """Test getting current prompt."""
        config = self.create_test_config()
        manager = init_solo_mode_manager(config)

        # No prompt initially
        assert manager.get_current_prompt() is None

        # Create prompt
        manager.create_prompt_version("Test prompt", created_by='test')

        # Now should have prompt
        prompt = manager.get_current_prompt()
        assert prompt is not None
        assert "Test prompt" in prompt.prompt_text

    def test_manager_update_prompt(self):
        """Test updating prompt creates new version."""
        config = self.create_test_config()
        manager = init_solo_mode_manager(config)

        # Create initial prompt
        manager.create_prompt_version("Version 1", created_by='test')

        # Update prompt
        manager.update_prompt("Version 2", source='test')

        # Should have two versions
        versions = manager.get_all_prompt_versions()
        assert len(versions) == 2

        # Current should be version 2
        current = manager.get_current_prompt()
        assert "Version 2" in current.prompt_text

    def test_manager_set_task_description(self):
        """Test setting task description."""
        config = self.create_test_config()
        manager = init_solo_mode_manager(config)

        description = "Classify product reviews by sentiment"
        manager.set_task_description(description)

        assert manager.get_task_description() == description

    def test_manager_get_available_labels(self):
        """Test getting available labels from config."""
        config = self.create_test_config()
        manager = init_solo_mode_manager(config)

        labels = manager.get_available_labels()

        assert 'positive' in labels
        assert 'negative' in labels
        assert 'neutral' in labels

    def test_manager_get_annotation_stats(self):
        """Test getting annotation statistics."""
        config = self.create_test_config()
        manager = init_solo_mode_manager(config)

        stats = manager.get_annotation_stats()

        assert 'human_labeled' in stats
        assert 'llm_labeled' in stats
        assert 'agreement_rate' in stats

    def test_manager_get_status(self):
        """Test getting comprehensive status."""
        config = self.create_test_config()
        manager = init_solo_mode_manager(config)

        status = manager.get_status()

        assert 'enabled' in status
        assert 'phase' in status
        assert 'labeling' in status
        assert 'agreement' in status

    def test_manager_agreement_metrics(self):
        """Test agreement metrics tracking."""
        config = self.create_test_config()
        manager = init_solo_mode_manager(config)

        metrics = manager.get_agreement_metrics()

        assert metrics.total_compared == 0
        assert metrics.agreements == 0
        assert metrics.disagreements == 0

    def test_manager_should_end_human_annotation(self):
        """Test end human annotation check."""
        config = self.create_test_config()
        manager = init_solo_mode_manager(config)

        # Initially should not end
        assert manager.should_end_human_annotation() is False


class TestPhaseControllerIntegration:
    """Integration tests for SoloPhaseController."""

    def test_phase_controller_initialization(self):
        """Test phase controller initializes correctly."""
        controller = SoloPhaseController()

        assert controller.get_current_phase() == SoloPhase.SETUP

    def test_phase_controller_valid_transitions(self):
        """Test valid phase transitions."""
        controller = SoloPhaseController()

        # SETUP -> PROMPT_REVIEW
        assert controller.transition_to(SoloPhase.PROMPT_REVIEW)
        assert controller.get_current_phase() == SoloPhase.PROMPT_REVIEW

        # PROMPT_REVIEW -> EDGE_CASE_SYNTHESIS
        assert controller.transition_to(SoloPhase.EDGE_CASE_SYNTHESIS)
        assert controller.get_current_phase() == SoloPhase.EDGE_CASE_SYNTHESIS

    def test_phase_controller_invalid_transition(self):
        """Test invalid phase transition is rejected."""
        controller = SoloPhaseController()

        # Can't go directly from SETUP to COMPLETED - should raise ValueError
        with pytest.raises(ValueError):
            controller.transition_to(SoloPhase.COMPLETED)

        # Should still be in SETUP
        assert controller.get_current_phase() == SoloPhase.SETUP

    def test_phase_controller_force_transition(self):
        """Test forced phase transition."""
        controller = SoloPhaseController()

        # Force transition should work even if invalid
        result = controller.transition_to(SoloPhase.COMPLETED, force=True)
        assert result is True
        assert controller.get_current_phase() == SoloPhase.COMPLETED

    def test_phase_controller_history(self):
        """Test phase transition history."""
        controller = SoloPhaseController()

        controller.transition_to(SoloPhase.PROMPT_REVIEW)
        controller.transition_to(SoloPhase.EDGE_CASE_SYNTHESIS)

        history = controller.get_transition_history()
        assert len(history) >= 2

    def test_phase_controller_status(self):
        """Test phase controller status."""
        controller = SoloPhaseController()

        status = controller.get_status()

        assert 'current_phase' in status
        assert 'allowed_transitions' in status


class TestInstanceSelectorIntegration:
    """Integration tests for InstanceSelector."""

    def test_selector_initialization(self):
        """Test instance selector initializes correctly."""
        selector = InstanceSelector()

        assert selector.weights is not None
        assert selector.weights.low_confidence > 0

    def test_selector_weight_normalization(self):
        """Test that weights are normalized to sum to 1.0."""
        weights = SelectionWeights(
            low_confidence=0.5,
            diverse=0.5,
            random=0.5,
            disagreement=0.5,
        )
        weights.validate()

        total = (
            weights.low_confidence +
            weights.diverse +
            weights.random +
            weights.disagreement
        )
        assert abs(total - 1.0) < 0.001

    def test_selector_select_next(self):
        """Test selecting next instance."""
        selector = InstanceSelector()

        available = {'inst_1', 'inst_2', 'inst_3'}
        selector.refresh_pools(available)

        selected = selector.select_next(available)

        assert selected in available

    def test_selector_select_batch(self):
        """Test selecting batch of instances."""
        selector = InstanceSelector()

        available = {'inst_1', 'inst_2', 'inst_3', 'inst_4', 'inst_5'}
        selector.refresh_pools(available)

        batch = selector.select_batch(available, batch_size=3)

        assert len(batch) == 3
        assert all(inst in available for inst in batch)
        assert len(set(batch)) == 3  # No duplicates

    def test_selector_exclude_ids(self):
        """Test excluding specific IDs from selection."""
        selector = InstanceSelector()

        available = {'inst_1', 'inst_2', 'inst_3'}
        exclude = {'inst_1', 'inst_2'}
        selector.refresh_pools(available)

        selected = selector.select_next(available, exclude_ids=exclude)

        assert selected == 'inst_3'

    def test_selector_selection_stats(self):
        """Test getting selection statistics."""
        selector = InstanceSelector()

        available = {'inst_1', 'inst_2', 'inst_3'}
        selector.refresh_pools(available)
        selector.select_next(available)

        stats = selector.get_selection_stats()

        assert 'total_selections' in stats
        assert 'by_pool' in stats
        assert stats['total_selections'] == 1


class TestValidationTrackerIntegration:
    """Integration tests for ValidationTracker."""

    def test_tracker_initialization(self):
        """Test validation tracker initializes correctly."""
        tracker = ValidationTracker()

        assert tracker.end_human_threshold == 0.90
        assert tracker.minimum_validation_sample == 50

    def test_tracker_record_comparisons(self):
        """Test recording comparisons updates metrics."""
        tracker = ValidationTracker()

        # Record some comparisons
        tracker.record_comparison('inst_1', 'positive', 'positive', 'sentiment', True)
        tracker.record_comparison('inst_2', 'negative', 'positive', 'sentiment', False)

        metrics = tracker.get_metrics()

        assert metrics.total_compared == 2
        assert metrics.agreements == 1
        assert metrics.disagreements == 1

    def test_tracker_agreement_rate(self):
        """Test agreement rate calculation."""
        tracker = ValidationTracker()

        # Record 80% agreement
        for i in range(8):
            tracker.record_comparison(f'inst_{i}', 'pos', 'pos', 'test', True)
        for i in range(2):
            tracker.record_comparison(f'inst_{8+i}', 'neg', 'pos', 'test', False)

        metrics = tracker.get_metrics()

        assert abs(metrics.agreement_rate - 0.8) < 0.01

    def test_tracker_select_validation_sample(self):
        """Test selecting validation sample."""
        tracker = ValidationTracker()

        instances = {
            f'inst_{i}': {'label': 'pos', 'confidence': 0.5 + i * 0.05}
            for i in range(20)
        }

        selected = tracker.select_validation_sample(instances, sample_size=10)

        assert len(selected) == 10

    def test_tracker_record_validation_result(self):
        """Test recording validation results."""
        tracker = ValidationTracker()

        # Select a sample
        instances = {
            'inst_1': {'label': 'pos', 'confidence': 0.8},
            'inst_2': {'label': 'neg', 'confidence': 0.7},
        }
        tracker.select_validation_sample(instances, sample_size=2)

        # Record validation
        result = tracker.record_validation_result('inst_1', 'pos')
        assert result is True

        progress = tracker.get_validation_progress()
        assert progress['validated'] == 1

    def test_tracker_validation_progress(self):
        """Test validation progress tracking."""
        tracker = ValidationTracker()

        instances = {
            f'inst_{i}': {'label': 'pos', 'confidence': 0.8}
            for i in range(5)
        }
        tracker.select_validation_sample(instances, sample_size=5)

        # Validate half
        for i in range(2):
            tracker.record_validation_result(f'inst_{i}', 'pos')

        progress = tracker.get_validation_progress()

        assert progress['total_samples'] == 5
        assert progress['validated'] == 2
        assert progress['remaining'] == 3


class TestDisagreementResolverIntegration:
    """Integration tests for DisagreementResolver."""

    def test_detector_radio_agreement(self):
        """Test disagreement detection for radio buttons."""
        thresholds = {
            'likert_tolerance': 1,
            'multiselect_jaccard_threshold': 0.5,
            'span_overlap_threshold': 0.5,
        }
        detector = DisagreementDetector(thresholds)

        # Exact match = agreement (returns tuple: is_disagreement, type)
        is_disagreement, _ = detector.detect('radio', 'positive', 'positive')
        assert not is_disagreement

        # Different = disagreement
        is_disagreement, _ = detector.detect('radio', 'positive', 'negative')
        assert is_disagreement

    def test_detector_likert_agreement(self):
        """Test disagreement detection for likert scales."""
        thresholds = {
            'likert_tolerance': 1,
            'multiselect_jaccard_threshold': 0.5,
            'span_overlap_threshold': 0.5,
        }
        detector = DisagreementDetector(thresholds)

        # Within tolerance = agreement
        is_disagreement, _ = detector.detect('likert', 3, 4)
        assert not is_disagreement

        # Beyond tolerance = disagreement
        is_disagreement, _ = detector.detect('likert', 1, 5)
        assert is_disagreement

    def test_detector_multiselect_agreement(self):
        """Test disagreement detection for multiselect."""
        thresholds = {
            'likert_tolerance': 1,
            'multiselect_jaccard_threshold': 0.5,
            'span_overlap_threshold': 0.5,
        }
        detector = DisagreementDetector(thresholds)

        # High overlap = agreement
        is_disagreement, _ = detector.detect('multiselect', ['a', 'b'], ['a', 'b', 'c'])
        assert not is_disagreement

        # Low overlap = disagreement
        is_disagreement, _ = detector.detect('multiselect', ['a', 'b'], ['c', 'd'])
        assert is_disagreement

    def test_resolver_record_disagreement(self):
        """Test recording disagreements."""
        config = {
            'annotation_schemes': [{
                'name': 'test',
                'annotation_type': 'radio',
                'labels': [{'name': 'a'}, {'name': 'b'}]
            }]
        }

        # Create a proper mock solo_config with nested thresholds
        solo_config = MagicMock()
        solo_config.thresholds.likert_tolerance = 1
        solo_config.thresholds.multiselect_jaccard_threshold = 0.5
        solo_config.thresholds.span_overlap_threshold = 0.5

        resolver = DisagreementResolver(config, solo_config)

        # Use check_and_record method
        result = resolver.check_and_record(
            instance_id='inst_1',
            schema_name='test',
            human_label='a',
            llm_label='b',
            llm_confidence=0.8,
        )

        # Should record a disagreement (returns Disagreement or None)
        assert result is not None

        pending = resolver.get_pending_disagreements()
        assert len(pending) == 1

    def test_resolver_resolve_disagreement(self):
        """Test resolving disagreements."""
        config = {
            'annotation_schemes': [{
                'name': 'test',
                'annotation_type': 'radio',
                'labels': [{'name': 'a'}, {'name': 'b'}]
            }]
        }

        # Create a proper mock solo_config with nested thresholds
        solo_config = MagicMock()
        solo_config.thresholds.likert_tolerance = 1
        solo_config.thresholds.multiselect_jaccard_threshold = 0.5
        solo_config.thresholds.span_overlap_threshold = 0.5

        resolver = DisagreementResolver(config, solo_config)

        # Record disagreement
        disagreement = resolver.check_and_record(
            instance_id='inst_1',
            schema_name='test',
            human_label='a',
            llm_label='b',
            llm_confidence=0.8,
        )

        # Resolve it using disagreement id
        result = resolver.resolve(disagreement.id, 'a', 'human_wins')
        assert result is True

        # Should be resolved now
        pending = resolver.get_pending_disagreements()
        assert len(pending) == 0


class TestSoloModeConfigIntegration:
    """Integration tests for Solo Mode configuration."""

    def test_config_parsing(self):
        """Test configuration parsing."""
        config_data = {
            'solo_mode': {
                'enabled': True,
                'labeling_models': [
                    {'endpoint_type': 'anthropic', 'model': 'claude-3-sonnet'}
                ],
                'thresholds': {
                    'end_human_annotation_agreement': 0.85,
                },
            }
        }

        config = parse_solo_mode_config(config_data)

        assert config.enabled is True
        assert config.thresholds.end_human_annotation_agreement == 0.85

    def test_config_defaults(self):
        """Test configuration defaults are applied."""
        config_data = {
            'solo_mode': {
                'enabled': True,
            }
        }

        config = parse_solo_mode_config(config_data)

        # Should have default thresholds
        assert config.thresholds.end_human_annotation_agreement == 0.90
        assert config.thresholds.minimum_validation_sample == 50

    def test_config_disabled(self):
        """Test disabled configuration."""
        config_data = {
            'solo_mode': {
                'enabled': False,
            }
        }

        config = parse_solo_mode_config(config_data)

        assert config.enabled is False

    def test_config_validation(self):
        """Test configuration validation."""
        config_data = {
            'solo_mode': {
                'enabled': True,
                'thresholds': {
                    'end_human_annotation_agreement': 1.5,  # Invalid
                },
            }
        }

        config = parse_solo_mode_config(config_data)
        errors = config.validate()

        # Should have validation errors
        assert len(errors) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
