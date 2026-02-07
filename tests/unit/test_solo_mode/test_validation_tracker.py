"""
Unit tests for ValidationTracker.

Tests agreement metrics, threshold checking, and validation sampling.
"""

import pytest
from datetime import datetime
from potato.solo_mode.validation_tracker import (
    ValidationTracker,
    AgreementMetrics,
    ValidationSample,
)


class TestAgreementMetrics:
    """Tests for AgreementMetrics dataclass."""

    def test_default_values(self):
        """Test that metrics have sensible defaults."""
        metrics = AgreementMetrics()
        assert metrics.total_compared == 0
        assert metrics.agreements == 0
        assert metrics.disagreements == 0
        assert metrics.agreement_rate == 0.0
        assert metrics.trend == "stable"

    def test_to_dict(self):
        """Test serialization to dictionary."""
        metrics = AgreementMetrics(
            total_compared=100,
            agreements=85,
            disagreements=15,
            agreement_rate=0.85,
            label_agreements={'positive': 40, 'negative': 45},
            label_disagreements={'positive': 5, 'negative': 10},
            confusion_matrix={('positive', 'negative'): 5},
            recent_agreement_rate=0.90,
            trend='improving',
        )

        data = metrics.to_dict()

        assert data['total_compared'] == 100
        assert data['agreements'] == 85
        assert data['agreement_rate'] == 0.85
        assert data['label_agreements']['positive'] == 40
        assert 'positive|negative' in data['confusion_matrix']


class TestValidationSample:
    """Tests for ValidationSample dataclass."""

    def test_creation(self):
        """Test creating a validation sample."""
        sample = ValidationSample(
            instance_id='inst_001',
            llm_label='positive',
            llm_confidence=0.85,
        )

        assert sample.instance_id == 'inst_001'
        assert sample.llm_label == 'positive'
        assert sample.llm_confidence == 0.85
        assert sample.human_label is None
        assert sample.validated_at is None
        assert sample.agrees is None

    def test_to_dict(self):
        """Test serialization."""
        sample = ValidationSample(
            instance_id='inst_001',
            llm_label='positive',
            llm_confidence=0.85,
        )
        sample.human_label = 'positive'
        sample.validated_at = datetime.now()
        sample.agrees = True

        data = sample.to_dict()

        assert data['instance_id'] == 'inst_001'
        assert data['agrees'] is True
        assert data['validated_at'] is not None


class TestValidationTracker:
    """Tests for ValidationTracker class."""

    @pytest.fixture
    def tracker(self):
        """Create a tracker with default config."""
        config = {
            'solo_mode': {
                'thresholds': {
                    'end_human_annotation_agreement': 0.90,
                    'minimum_validation_sample': 50,
                    'periodic_review_interval': 100,
                }
            }
        }
        return ValidationTracker(config)

    @pytest.fixture
    def populated_tracker(self, tracker):
        """Create a tracker with recorded comparisons."""
        for i in range(100):
            agrees = i < 85  # 85% agreement
            tracker.record_comparison(
                instance_id=f'inst_{i:03d}',
                human_label='positive' if i % 2 == 0 else 'negative',
                llm_label='positive' if i % 2 == 0 else 'negative' if agrees else 'positive',
                schema_name='sentiment',
                agrees=agrees,
            )
        return tracker

    def test_initialization(self, tracker):
        """Test tracker initializes with correct thresholds."""
        assert tracker.end_human_threshold == 0.90
        assert tracker.minimum_validation_sample == 50
        assert tracker.periodic_review_interval == 100

    def test_record_comparison_agreement(self, tracker):
        """Test recording an agreeing comparison."""
        tracker.record_comparison(
            instance_id='inst_001',
            human_label='positive',
            llm_label='positive',
            schema_name='sentiment',
            agrees=True,
        )

        metrics = tracker.get_metrics()
        assert metrics.total_compared == 1
        assert metrics.agreements == 1
        assert metrics.disagreements == 0
        assert metrics.agreement_rate == 1.0

    def test_record_comparison_disagreement(self, tracker):
        """Test recording a disagreeing comparison."""
        tracker.record_comparison(
            instance_id='inst_001',
            human_label='positive',
            llm_label='negative',
            schema_name='sentiment',
            agrees=False,
        )

        metrics = tracker.get_metrics()
        assert metrics.total_compared == 1
        assert metrics.agreements == 0
        assert metrics.disagreements == 1
        assert metrics.agreement_rate == 0.0

    def test_confusion_matrix_tracking(self, tracker):
        """Test that confusion is tracked correctly."""
        # LLM says positive, human corrects to negative
        tracker.record_comparison(
            instance_id='inst_001',
            human_label='negative',
            llm_label='positive',
            schema_name='sentiment',
            agrees=False,
        )
        tracker.record_comparison(
            instance_id='inst_002',
            human_label='negative',
            llm_label='positive',
            schema_name='sentiment',
            agrees=False,
        )

        metrics = tracker.get_metrics()
        assert metrics.confusion_matrix[('positive', 'negative')] == 2

    def test_should_end_human_annotation_below_threshold(self, tracker):
        """Test that annotation continues when below threshold."""
        # 80% agreement with 60 samples
        for i in range(60):
            tracker.record_comparison(
                instance_id=f'inst_{i:03d}',
                human_label='positive',
                llm_label='positive' if i < 48 else 'negative',
                schema_name='test',
                agrees=(i < 48),
            )

        assert not tracker.should_end_human_annotation()

    def test_should_end_human_annotation_above_threshold(self, tracker):
        """Test that annotation can end when threshold is met."""
        # 92% agreement with 50 samples
        for i in range(50):
            tracker.record_comparison(
                instance_id=f'inst_{i:03d}',
                human_label='positive',
                llm_label='positive' if i < 46 else 'negative',
                schema_name='test',
                agrees=(i < 46),
            )

        assert tracker.should_end_human_annotation()

    def test_should_end_human_annotation_insufficient_samples(self, tracker):
        """Test that annotation continues with insufficient samples."""
        # Perfect agreement but only 10 samples
        for i in range(10):
            tracker.record_comparison(
                instance_id=f'inst_{i:03d}',
                human_label='positive',
                llm_label='positive',
                schema_name='test',
                agrees=True,
            )

        assert not tracker.should_end_human_annotation()

    def test_periodic_review_trigger(self, tracker):
        """Test periodic review is triggered after interval."""
        assert not tracker.should_trigger_periodic_review()

        for i in range(100):
            tracker.record_llm_label(f'inst_{i:03d}')

        assert tracker.should_trigger_periodic_review()

    def test_periodic_review_reset(self, tracker):
        """Test periodic review counter can be reset."""
        for i in range(100):
            tracker.record_llm_label(f'inst_{i:03d}')

        assert tracker.should_trigger_periodic_review()

        tracker.reset_periodic_review_counter()

        assert not tracker.should_trigger_periodic_review()

    def test_select_validation_sample(self, tracker):
        """Test validation sample selection."""
        instances = {
            f'inst_{i:03d}': {
                'label': 'positive',
                'confidence': 0.3 + (i * 0.007),  # 0.3 to 1.0
            }
            for i in range(100)
        }

        selected = tracker.select_validation_sample(instances, sample_size=20)

        assert len(selected) == 20
        assert all(sid in instances for sid in selected)

    def test_stratified_sample_oversamples_low_confidence(self, tracker):
        """Test that stratified sampling oversamples low confidence."""
        # Create instances with different confidence levels
        instances = {}
        for i in range(30):
            instances[f'low_{i}'] = {'label': 'a', 'confidence': 0.3}
        for i in range(30):
            instances[f'mid_{i}'] = {'label': 'a', 'confidence': 0.65}
        for i in range(30):
            instances[f'high_{i}'] = {'label': 'a', 'confidence': 0.9}

        selected = tracker.select_validation_sample(instances, sample_size=30)

        low_selected = sum(1 for s in selected if s.startswith('low_'))
        mid_selected = sum(1 for s in selected if s.startswith('mid_'))
        high_selected = sum(1 for s in selected if s.startswith('high_'))

        # Low confidence should be oversampled
        assert low_selected >= high_selected

    def test_record_validation_result(self, tracker):
        """Test recording validation results."""
        instances = {
            'inst_001': {'label': 'positive', 'confidence': 0.8},
            'inst_002': {'label': 'negative', 'confidence': 0.7},
        }
        tracker.select_validation_sample(instances, sample_size=2)

        # Record validation
        result = tracker.record_validation_result(
            'inst_001',
            human_label='positive',
            notes='Clear positive case',
        )

        assert result is True

        progress = tracker.get_validation_progress()
        assert progress['validated'] == 1
        assert progress['remaining'] == 1
        assert progress['agreements'] == 1

    def test_record_validation_result_unknown_sample(self, tracker):
        """Test recording result for unknown sample."""
        result = tracker.record_validation_result('unknown_id', 'positive')
        assert result is False

    def test_get_validation_progress(self, tracker):
        """Test getting validation progress."""
        instances = {
            f'inst_{i}': {'label': 'positive', 'confidence': 0.8}
            for i in range(10)
        }
        tracker.select_validation_sample(instances, sample_size=10)

        # Validate half
        for i in range(5):
            tracker.record_validation_result(f'inst_{i}', 'positive')

        progress = tracker.get_validation_progress()

        assert progress['total_samples'] == 10
        assert progress['validated'] == 5
        assert progress['remaining'] == 5
        assert progress['percent_complete'] == 50.0

    def test_get_confusion_analysis(self, populated_tracker):
        """Test confusion pattern analysis."""
        analysis = populated_tracker.get_confusion_analysis()

        assert 'patterns' in analysis
        assert 'most_confused' in analysis
        assert 'total_disagreements' in analysis

    def test_get_label_accuracy(self, populated_tracker):
        """Test per-label accuracy calculation."""
        accuracy = populated_tracker.get_label_accuracy()

        assert 'positive' in accuracy or 'negative' in accuracy
        for label, rate in accuracy.items():
            assert 0.0 <= rate <= 1.0

    def test_get_status(self, populated_tracker):
        """Test comprehensive status retrieval."""
        status = populated_tracker.get_status()

        assert 'metrics' in status
        assert 'thresholds' in status
        assert 'should_end_human_annotation' in status
        assert 'validation_progress' in status
        assert 'label_accuracy' in status

    def test_serialization_roundtrip(self, populated_tracker):
        """Test serialization and deserialization."""
        # Add validation samples
        instances = {
            f'inst_{i}': {'label': 'positive', 'confidence': 0.8}
            for i in range(10)
        }
        selected = populated_tracker.select_validation_sample(instances, sample_size=5)
        # Use a sample that was actually selected
        if selected:
            populated_tracker.record_validation_result(selected[0], 'positive')

        # Serialize
        data = populated_tracker.to_dict()

        # Create new tracker and deserialize
        new_tracker = ValidationTracker()
        new_tracker.from_dict(data)

        # Verify metrics preserved
        assert new_tracker.get_metrics().total_compared == 100
        assert new_tracker.get_metrics().agreements == 85

        # Verify validation samples preserved
        progress = new_tracker.get_validation_progress()
        assert progress['total_samples'] == 5
        assert progress['validated'] == 1

    def test_trend_detection_improving(self, tracker):
        """Test that improving trend is detected."""
        # First 50: 60% agreement
        for i in range(50):
            tracker.record_comparison(
                instance_id=f'inst_{i:03d}',
                human_label='positive',
                llm_label='positive' if i < 30 else 'negative',
                schema_name='test',
                agrees=(i < 30),
            )

        # Next 50: 90% agreement (improving)
        for i in range(50, 100):
            tracker.record_comparison(
                instance_id=f'inst_{i:03d}',
                human_label='positive',
                llm_label='positive' if i < 95 else 'negative',
                schema_name='test',
                agrees=(i < 95),
            )

        metrics = tracker.get_metrics()
        assert metrics.trend == "improving"

    def test_trend_detection_declining(self, tracker):
        """Test that declining trend is detected."""
        # First 50: 90% agreement
        for i in range(50):
            tracker.record_comparison(
                instance_id=f'inst_{i:03d}',
                human_label='positive',
                llm_label='positive' if i < 45 else 'negative',
                schema_name='test',
                agrees=(i < 45),
            )

        # Next 50: 60% agreement (declining)
        for i in range(50, 100):
            tracker.record_comparison(
                instance_id=f'inst_{i:03d}',
                human_label='positive',
                llm_label='positive' if i < 80 else 'negative',
                schema_name='test',
                agrees=(i < 80),
            )

        metrics = tracker.get_metrics()
        assert metrics.trend == "declining"

    def test_unvalidated_samples(self, tracker):
        """Test getting unvalidated samples."""
        instances = {
            f'inst_{i}': {'label': 'positive', 'confidence': 0.8}
            for i in range(5)
        }
        tracker.select_validation_sample(instances, sample_size=5)

        # Validate some
        tracker.record_validation_result('inst_0', 'positive')
        tracker.record_validation_result('inst_1', 'positive')

        unvalidated = tracker.get_unvalidated_samples()
        assert len(unvalidated) == 3

    def test_all_validation_samples(self, tracker):
        """Test getting all validation samples."""
        instances = {
            f'inst_{i}': {'label': 'positive', 'confidence': 0.8}
            for i in range(5)
        }
        tracker.select_validation_sample(instances, sample_size=5)

        all_samples = tracker.get_validation_samples()
        assert len(all_samples) == 5


class TestValidationTrackerEdgeCases:
    """Edge case tests for ValidationTracker."""

    def test_empty_tracker(self):
        """Test operations on empty tracker."""
        tracker = ValidationTracker()

        assert not tracker.should_end_human_annotation()
        assert not tracker.should_trigger_periodic_review()
        assert tracker.get_metrics().total_compared == 0

    def test_default_config(self):
        """Test tracker with no config uses defaults."""
        tracker = ValidationTracker()

        assert tracker.end_human_threshold == 0.90
        assert tracker.minimum_validation_sample == 50

    def test_sample_larger_than_population(self):
        """Test sampling when sample size exceeds population."""
        tracker = ValidationTracker()

        instances = {
            'inst_0': {'label': 'a', 'confidence': 0.8},
            'inst_1': {'label': 'b', 'confidence': 0.7},
        }

        selected = tracker.select_validation_sample(instances, sample_size=10)

        # Should return all available instances
        assert len(selected) == 2
