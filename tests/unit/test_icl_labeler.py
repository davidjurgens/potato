"""
Unit tests for ICL Labeler.

This module tests the core ICL labeling functionality including
high-confidence example collection, prediction management, verification
workflow, and accuracy tracking.
"""

import unittest
import json
import os
import tempfile
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

from potato.ai.icl_labeler import (
    ICLLabeler, ICLPrediction, HighConfidenceExample,
    init_icl_labeler, get_icl_labeler, clear_icl_labeler
)


class TestHighConfidenceExample(unittest.TestCase):
    """Test cases for HighConfidenceExample dataclass."""

    def test_creation(self):
        """Test creating a HighConfidenceExample."""
        example = HighConfidenceExample(
            instance_id='test_001',
            text='Sample text for testing',
            schema_name='sentiment',
            label='positive',
            agreement_score=0.9,
            annotator_count=5
        )

        self.assertEqual(example.instance_id, 'test_001')
        self.assertEqual(example.text, 'Sample text for testing')
        self.assertEqual(example.schema_name, 'sentiment')
        self.assertEqual(example.label, 'positive')
        self.assertAlmostEqual(example.agreement_score, 0.9, places=2)
        self.assertEqual(example.annotator_count, 5)

    def test_to_dict(self):
        """Test serialization to dictionary."""
        timestamp = datetime.now()
        example = HighConfidenceExample(
            instance_id='test_001',
            text='Sample text',
            schema_name='sentiment',
            label='positive',
            agreement_score=0.85,
            annotator_count=3,
            timestamp=timestamp
        )

        data = example.to_dict()

        self.assertEqual(data['instance_id'], 'test_001')
        self.assertEqual(data['label'], 'positive')
        self.assertEqual(data['agreement_score'], 0.85)
        self.assertEqual(data['timestamp'], timestamp.isoformat())

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            'instance_id': 'test_002',
            'text': 'Another sample',
            'schema_name': 'category',
            'label': 'A',
            'agreement_score': 0.95,
            'annotator_count': 4,
            'timestamp': '2024-01-15T10:30:00'
        }

        example = HighConfidenceExample.from_dict(data)

        self.assertEqual(example.instance_id, 'test_002')
        self.assertEqual(example.label, 'A')
        self.assertEqual(example.annotator_count, 4)
        self.assertIsInstance(example.timestamp, datetime)


class TestICLPrediction(unittest.TestCase):
    """Test cases for ICLPrediction dataclass."""

    def test_creation(self):
        """Test creating an ICLPrediction."""
        prediction = ICLPrediction(
            instance_id='pred_001',
            schema_name='sentiment',
            predicted_label='positive',
            confidence_score=0.85
        )

        self.assertEqual(prediction.instance_id, 'pred_001')
        self.assertEqual(prediction.predicted_label, 'positive')
        self.assertAlmostEqual(prediction.confidence_score, 0.85, places=2)
        self.assertEqual(prediction.verification_status, 'pending')
        self.assertIsNone(prediction.verified_by)
        self.assertIsNone(prediction.human_label)

    def test_to_dict_and_from_dict(self):
        """Test round-trip serialization."""
        original = ICLPrediction(
            instance_id='pred_002',
            schema_name='category',
            predicted_label='B',
            confidence_score=0.72,
            example_instance_ids=['ex1', 'ex2'],
            verification_status='verified_correct',
            verified_by='user1',
            human_label='B',
            model_name='gpt-4',
            reasoning='Based on keywords...'
        )

        data = original.to_dict()
        restored = ICLPrediction.from_dict(data)

        self.assertEqual(restored.instance_id, original.instance_id)
        self.assertEqual(restored.predicted_label, original.predicted_label)
        self.assertEqual(restored.confidence_score, original.confidence_score)
        self.assertEqual(restored.verification_status, original.verification_status)
        self.assertEqual(restored.verified_by, original.verified_by)
        self.assertEqual(restored.example_instance_ids, original.example_instance_ids)

    def test_verification_status_values(self):
        """Test valid verification status values."""
        prediction = ICLPrediction(
            instance_id='test',
            schema_name='test',
            predicted_label='A',
            confidence_score=0.5
        )

        # Default is pending
        self.assertEqual(prediction.verification_status, 'pending')

        # Can set to verified_correct
        prediction.verification_status = 'verified_correct'
        self.assertEqual(prediction.verification_status, 'verified_correct')

        # Can set to verified_incorrect
        prediction.verification_status = 'verified_incorrect'
        self.assertEqual(prediction.verification_status, 'verified_incorrect')


class TestICLLabelerInit(unittest.TestCase):
    """Test cases for ICLLabeler initialization."""

    def setUp(self):
        """Clear singleton before each test."""
        clear_icl_labeler()

    def tearDown(self):
        """Clear singleton after each test."""
        clear_icl_labeler()

    def test_singleton_pattern(self):
        """Test that ICLLabeler follows singleton pattern."""
        config = {'icl_labeling': {'enabled': True}}

        labeler1 = ICLLabeler(config)
        labeler2 = ICLLabeler(config)

        self.assertIs(labeler1, labeler2)

    def test_default_config(self):
        """Test default configuration values."""
        config = {'icl_labeling': {'enabled': True}}
        labeler = ICLLabeler(config)

        self.assertEqual(labeler.min_agreement_threshold, 0.8)
        self.assertEqual(labeler.min_annotators_per_instance, 2)
        self.assertEqual(labeler.max_examples_per_schema, 10)
        self.assertEqual(labeler.batch_size, 20)
        self.assertEqual(labeler.confidence_threshold, 0.7)

    def test_custom_config(self):
        """Test custom configuration values."""
        config = {
            'icl_labeling': {
                'enabled': True,
                'example_selection': {
                    'min_agreement_threshold': 0.9,
                    'min_annotators_per_instance': 3,
                    'max_examples_per_schema': 5
                },
                'llm_labeling': {
                    'batch_size': 10,
                    'confidence_threshold': 0.8,
                    'max_total_labels': 100,
                    'max_unlabeled_ratio': 0.3
                },
                'verification': {
                    'enabled': True,
                    'sample_rate': 0.3,
                    'selection_strategy': 'random'
                }
            }
        }

        labeler = ICLLabeler(config)

        self.assertEqual(labeler.min_agreement_threshold, 0.9)
        self.assertEqual(labeler.min_annotators_per_instance, 3)
        self.assertEqual(labeler.max_examples_per_schema, 5)
        self.assertEqual(labeler.batch_size, 10)
        self.assertEqual(labeler.confidence_threshold, 0.8)
        self.assertEqual(labeler.max_total_labels, 100)
        self.assertEqual(labeler.max_unlabeled_ratio, 0.3)
        self.assertEqual(labeler.verification_sample_rate, 0.3)
        self.assertEqual(labeler.verification_strategy, 'random')


class TestICLLabelerModuleFunctions(unittest.TestCase):
    """Test module-level functions."""

    def setUp(self):
        """Clear singleton before each test."""
        clear_icl_labeler()

    def tearDown(self):
        """Clear singleton after each test."""
        clear_icl_labeler()

    def test_init_icl_labeler(self):
        """Test init_icl_labeler function."""
        config = {'icl_labeling': {'enabled': True}}

        labeler = init_icl_labeler(config)

        self.assertIsNotNone(labeler)
        self.assertIsInstance(labeler, ICLLabeler)

    def test_get_icl_labeler_after_init(self):
        """Test get_icl_labeler after initialization."""
        config = {'icl_labeling': {'enabled': True}}
        init_icl_labeler(config)

        labeler = get_icl_labeler()

        self.assertIsNotNone(labeler)

    def test_get_icl_labeler_before_init(self):
        """Test get_icl_labeler before initialization."""
        labeler = get_icl_labeler()
        self.assertIsNone(labeler)

    def test_clear_icl_labeler(self):
        """Test clear_icl_labeler function."""
        config = {'icl_labeling': {'enabled': True}}
        init_icl_labeler(config)

        clear_icl_labeler()

        self.assertIsNone(get_icl_labeler())


class TestICLLabelerExamples(unittest.TestCase):
    """Test high-confidence example management."""

    def setUp(self):
        """Set up test fixtures."""
        clear_icl_labeler()
        self.config = {'icl_labeling': {'enabled': True}}
        self.labeler = init_icl_labeler(self.config)

    def tearDown(self):
        """Clean up."""
        clear_icl_labeler()

    def test_get_examples_for_schema_empty(self):
        """Test getting examples when none exist."""
        examples = self.labeler.get_examples_for_schema('sentiment')
        self.assertEqual(examples, [])

    def test_has_enough_examples_false(self):
        """Test has_enough_examples when insufficient."""
        self.assertFalse(self.labeler.has_enough_examples('sentiment'))

    def test_has_enough_examples_true(self):
        """Test has_enough_examples when sufficient."""
        # Manually add examples
        self.labeler.schema_to_examples['sentiment'] = [
            HighConfidenceExample(f'ex{i}', f'text{i}', 'sentiment', 'pos', 0.9, 3)
            for i in range(10)
        ]

        self.assertTrue(self.labeler.has_enough_examples('sentiment'))


class TestICLLabelerPredictions(unittest.TestCase):
    """Test prediction storage and retrieval."""

    def setUp(self):
        """Set up test fixtures."""
        clear_icl_labeler()
        self.config = {'icl_labeling': {'enabled': True}}
        self.labeler = init_icl_labeler(self.config)

    def tearDown(self):
        """Clean up."""
        clear_icl_labeler()

    def test_store_prediction(self):
        """Test storing a prediction."""
        prediction = ICLPrediction(
            instance_id='test_001',
            schema_name='sentiment',
            predicted_label='positive',
            confidence_score=0.85
        )

        # Manually store prediction
        self.labeler.predictions['test_001'] = {'sentiment': prediction}
        self.labeler.labeled_instance_ids.add('test_001')

        self.assertIn('test_001', self.labeler.predictions)
        self.assertIn('test_001', self.labeler.labeled_instance_ids)


class TestICLLabelerVerification(unittest.TestCase):
    """Test verification workflow."""

    def setUp(self):
        """Set up test fixtures."""
        clear_icl_labeler()
        self.config = {
            'icl_labeling': {
                'enabled': True,
                'verification': {
                    'enabled': True,
                    'sample_rate': 1.0,  # Always sample for testing
                    'selection_strategy': 'low_confidence'
                }
            }
        }
        self.labeler = init_icl_labeler(self.config)

    def tearDown(self):
        """Clean up."""
        clear_icl_labeler()

    def test_get_pending_verifications_empty(self):
        """Test getting verifications when queue is empty."""
        pending = self.labeler.get_pending_verifications(count=5)
        self.assertEqual(pending, [])

    def test_get_pending_verifications_with_predictions(self):
        """Test getting verifications with predictions in queue."""
        # Add predictions to queue
        for i in range(5):
            pred = ICLPrediction(
                instance_id=f'pred_{i}',
                schema_name='sentiment',
                predicted_label='positive',
                confidence_score=0.5 + i * 0.1  # 0.5, 0.6, 0.7, 0.8, 0.9
            )
            self.labeler.predictions[f'pred_{i}'] = {'sentiment': pred}
            self.labeler.verification_queue.append((f'pred_{i}', 'sentiment'))

        # Get pending verifications (low_confidence strategy)
        pending = self.labeler.get_pending_verifications(count=3)

        self.assertEqual(len(pending), 3)
        # Should be sorted by confidence ascending (low confidence first)
        self.assertEqual(pending[0][0], 'pred_0')  # Lowest confidence

    def test_record_verification_correct(self):
        """Test recording a correct verification."""
        pred = ICLPrediction(
            instance_id='test_001',
            schema_name='sentiment',
            predicted_label='positive',
            confidence_score=0.8
        )
        self.labeler.predictions['test_001'] = {'sentiment': pred}
        self.labeler.verification_queue.append(('test_001', 'sentiment'))

        success = self.labeler.record_verification(
            instance_id='test_001',
            schema_name='sentiment',
            human_label='positive',
            verified_by='user1'
        )

        self.assertTrue(success)
        self.assertEqual(pred.verification_status, 'verified_correct')
        self.assertEqual(pred.human_label, 'positive')
        self.assertEqual(pred.verified_by, 'user1')
        self.assertNotIn(('test_001', 'sentiment'), self.labeler.verification_queue)

    def test_record_verification_incorrect(self):
        """Test recording an incorrect verification."""
        pred = ICLPrediction(
            instance_id='test_002',
            schema_name='sentiment',
            predicted_label='positive',
            confidence_score=0.7
        )
        self.labeler.predictions['test_002'] = {'sentiment': pred}
        self.labeler.verification_queue.append(('test_002', 'sentiment'))

        success = self.labeler.record_verification(
            instance_id='test_002',
            schema_name='sentiment',
            human_label='negative',  # Different from predicted
            verified_by='user2'
        )

        self.assertTrue(success)
        self.assertEqual(pred.verification_status, 'verified_incorrect')
        self.assertEqual(pred.human_label, 'negative')

    def test_record_verification_not_found(self):
        """Test recording verification for non-existent prediction."""
        success = self.labeler.record_verification(
            instance_id='nonexistent',
            schema_name='sentiment',
            human_label='positive',
            verified_by='user1'
        )

        self.assertFalse(success)


class TestICLLabelerAccuracyMetrics(unittest.TestCase):
    """Test accuracy calculation."""

    def setUp(self):
        """Set up test fixtures."""
        clear_icl_labeler()
        self.config = {'icl_labeling': {'enabled': True}}
        self.labeler = init_icl_labeler(self.config)

    def tearDown(self):
        """Clean up."""
        clear_icl_labeler()

    def test_get_accuracy_metrics_empty(self):
        """Test accuracy metrics with no predictions."""
        metrics = self.labeler.get_accuracy_metrics()

        self.assertEqual(metrics['total_predictions'], 0)
        self.assertEqual(metrics['total_verified'], 0)
        self.assertIsNone(metrics['accuracy'])

    def test_get_accuracy_metrics_with_verifications(self):
        """Test accuracy metrics with verified predictions."""
        # Add verified predictions
        for i in range(10):
            pred = ICLPrediction(
                instance_id=f'test_{i}',
                schema_name='sentiment',
                predicted_label='positive',
                confidence_score=0.8,
                verification_status='verified_correct' if i < 8 else 'verified_incorrect',
                human_label='positive' if i < 8 else 'negative'
            )
            self.labeler.predictions[f'test_{i}'] = {'sentiment': pred}

        metrics = self.labeler.get_accuracy_metrics()

        self.assertEqual(metrics['total_predictions'], 10)
        self.assertEqual(metrics['verified_correct'], 8)
        self.assertEqual(metrics['verified_incorrect'], 2)
        self.assertEqual(metrics['total_verified'], 10)
        self.assertAlmostEqual(metrics['accuracy'], 0.8, places=2)

    def test_get_accuracy_metrics_by_schema(self):
        """Test accuracy metrics filtered by schema."""
        # Add predictions for multiple schemas
        for schema in ['sentiment', 'category']:
            for i in range(5):
                pred = ICLPrediction(
                    instance_id=f'{schema}_{i}',
                    schema_name=schema,
                    predicted_label='A',
                    confidence_score=0.8,
                    verification_status='verified_correct'
                )
                self.labeler.predictions[f'{schema}_{i}'] = {schema: pred}

        sentiment_metrics = self.labeler.get_accuracy_metrics(schema_name='sentiment')
        category_metrics = self.labeler.get_accuracy_metrics(schema_name='category')

        self.assertEqual(sentiment_metrics['total_predictions'], 5)
        self.assertEqual(category_metrics['total_predictions'], 5)


class TestICLLabelerLimits(unittest.TestCase):
    """Test labeling limits functionality."""

    def setUp(self):
        """Set up test fixtures."""
        clear_icl_labeler()
        self.config = {
            'icl_labeling': {
                'enabled': True,
                'llm_labeling': {
                    'max_total_labels': 10,
                    'max_unlabeled_ratio': 0.5,
                    'pause_on_low_accuracy': True,
                    'min_accuracy_threshold': 0.7
                }
            }
        }
        self.labeler = init_icl_labeler(self.config)

    def tearDown(self):
        """Clean up."""
        clear_icl_labeler()

    def test_should_pause_labeling_not_reached_limit(self):
        """Test should_pause_labeling when limit not reached."""
        should_pause, reason = self.labeler.should_pause_labeling()
        self.assertFalse(should_pause)
        self.assertEqual(reason, '')

    def test_should_pause_labeling_reached_limit(self):
        """Test should_pause_labeling when limit reached."""
        # Simulate reaching the limit
        for i in range(10):
            self.labeler.labeled_instance_ids.add(f'test_{i}')

        should_pause, reason = self.labeler.should_pause_labeling()
        self.assertTrue(should_pause)
        self.assertIn('max_total_labels', reason)

    def test_should_pause_labeling_low_accuracy(self):
        """Test should_pause_labeling with low accuracy."""
        # Add enough verifications with low accuracy
        for i in range(15):
            pred = ICLPrediction(
                instance_id=f'test_{i}',
                schema_name='sentiment',
                predicted_label='positive',
                confidence_score=0.8,
                verification_status='verified_incorrect',  # All incorrect
                human_label='negative'
            )
            self.labeler.predictions[f'test_{i}'] = {'sentiment': pred}

        should_pause, reason = self.labeler.should_pause_labeling()
        self.assertTrue(should_pause)
        self.assertIn('Accuracy', reason)


class TestICLLabelerStatus(unittest.TestCase):
    """Test status reporting."""

    def setUp(self):
        """Set up test fixtures."""
        clear_icl_labeler()
        self.config = {'icl_labeling': {'enabled': True}}
        self.labeler = init_icl_labeler(self.config)

    def tearDown(self):
        """Clean up."""
        clear_icl_labeler()

    @patch('potato.flask_server.get_item_state_manager')
    def test_get_status(self, mock_get_ism):
        """Test get_status returns expected fields."""
        # Mock the ItemStateManager to avoid initialization error
        mock_ism = MagicMock()
        mock_ism.get_all_instance_ids.return_value = ['test_001', 'test_002']
        mock_get_ism.return_value = mock_ism

        status = self.labeler.get_status()

        self.assertIn('enabled', status)
        self.assertIn('total_examples', status)
        self.assertIn('examples_by_schema', status)
        self.assertIn('total_predictions', status)
        self.assertIn('labeled_instances', status)
        self.assertIn('verification_queue_size', status)
        self.assertIn('worker_running', status)
        self.assertIn('accuracy_metrics', status)
        self.assertIn('labeling_paused', status)


class TestICLLabelerPersistence(unittest.TestCase):
    """Test state persistence."""

    def setUp(self):
        """Set up test fixtures."""
        clear_icl_labeler()
        self.temp_dir = tempfile.mkdtemp()
        self.config = {
            'icl_labeling': {
                'enabled': True,
                'persistence': {
                    'predictions_file': 'icl_predictions.json'
                }
            },
            'output_annotation_dir': self.temp_dir
        }
        self.labeler = init_icl_labeler(self.config)

    def tearDown(self):
        """Clean up."""
        clear_icl_labeler()
        # Clean up temp files
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_save_state(self):
        """Test saving state to disk."""
        # Add some data
        self.labeler.schema_to_examples['sentiment'] = [
            HighConfidenceExample('ex1', 'text', 'sentiment', 'pos', 0.9, 3)
        ]
        self.labeler.predictions['pred1'] = {
            'sentiment': ICLPrediction('pred1', 'sentiment', 'pos', 0.8)
        }
        self.labeler.labeled_instance_ids.add('pred1')

        # Save state
        self.labeler.save_state()

        # Check file exists
        filepath = os.path.join(self.temp_dir, 'icl_predictions.json')
        self.assertTrue(os.path.exists(filepath))

        # Check content
        with open(filepath, 'r') as f:
            state = json.load(f)

        self.assertIn('predictions', state)
        self.assertIn('examples', state)
        self.assertIn('labeled_instance_ids', state)

    def test_load_state(self):
        """Test loading state from disk."""
        # Create state file
        state = {
            'predictions': {
                'pred1': {
                    'sentiment': {
                        'instance_id': 'pred1',
                        'schema_name': 'sentiment',
                        'predicted_label': 'positive',
                        'confidence_score': 0.85,
                        'timestamp': datetime.now().isoformat(),
                        'example_instance_ids': [],
                        'verification_status': 'pending',
                        'verified_by': None,
                        'verified_at': None,
                        'human_label': None,
                        'model_name': '',
                        'reasoning': ''
                    }
                }
            },
            'examples': {
                'sentiment': [
                    {
                        'instance_id': 'ex1',
                        'text': 'Sample',
                        'schema_name': 'sentiment',
                        'label': 'positive',
                        'agreement_score': 0.9,
                        'annotator_count': 3,
                        'timestamp': datetime.now().isoformat()
                    }
                ]
            },
            'verification_queue': [['pred1', 'sentiment']],
            'labeled_instance_ids': ['pred1']
        }

        filepath = os.path.join(self.temp_dir, 'icl_predictions.json')
        with open(filepath, 'w') as f:
            json.dump(state, f)

        # Load state
        self.labeler.load_state()

        # Verify loaded data
        self.assertIn('pred1', self.labeler.predictions)
        self.assertIn('sentiment', self.labeler.schema_to_examples)
        self.assertIn('pred1', self.labeler.labeled_instance_ids)


class TestICLLabelerVerificationStrategies(unittest.TestCase):
    """Test different verification selection strategies."""

    def setUp(self):
        """Set up test fixtures."""
        clear_icl_labeler()

    def tearDown(self):
        """Clean up."""
        clear_icl_labeler()

    def test_low_confidence_strategy(self):
        """Test low_confidence verification strategy."""
        config = {
            'icl_labeling': {
                'enabled': True,
                'verification': {
                    'selection_strategy': 'low_confidence'
                }
            }
        }
        labeler = init_icl_labeler(config)

        # Add predictions with varying confidence
        confidences = [0.9, 0.5, 0.7, 0.3, 0.8]
        for i, conf in enumerate(confidences):
            pred = ICLPrediction(f'pred_{i}', 'test', 'A', conf)
            labeler.predictions[f'pred_{i}'] = {'test': pred}
            labeler.verification_queue.append((f'pred_{i}', 'test'))

        # Get verifications
        pending = labeler.get_pending_verifications(count=3)

        # Should be sorted by confidence ascending
        self.assertEqual(pending[0][0], 'pred_3')  # 0.3
        self.assertEqual(pending[1][0], 'pred_1')  # 0.5
        self.assertEqual(pending[2][0], 'pred_2')  # 0.7

    def test_random_strategy(self):
        """Test random verification strategy."""
        config = {
            'icl_labeling': {
                'enabled': True,
                'verification': {
                    'selection_strategy': 'random'
                }
            }
        }
        labeler = init_icl_labeler(config)

        # Add predictions
        for i in range(10):
            pred = ICLPrediction(f'pred_{i}', 'test', 'A', 0.8)
            labeler.predictions[f'pred_{i}'] = {'test': pred}
            labeler.verification_queue.append((f'pred_{i}', 'test'))

        # Get verifications - should return some items
        pending = labeler.get_pending_verifications(count=5)

        self.assertEqual(len(pending), 5)

    def test_mixed_strategy(self):
        """Test mixed verification strategy."""
        clear_icl_labeler()
        config = {
            'icl_labeling': {
                'enabled': True,
                'verification': {
                    'selection_strategy': 'mixed'
                }
            }
        }
        labeler = init_icl_labeler(config)

        # Add predictions with varying confidence
        for i in range(10):
            pred = ICLPrediction(f'pred_{i}', 'test', 'A', i * 0.1)
            labeler.predictions[f'pred_{i}'] = {'test': pred}
            labeler.verification_queue.append((f'pred_{i}', 'test'))

        # Get verifications - should return mix of low confidence and random
        pending = labeler.get_pending_verifications(count=4)

        self.assertEqual(len(pending), 4)
        # First half should be low confidence
        self.assertEqual(pending[0][0], 'pred_0')  # Lowest confidence


if __name__ == '__main__':
    unittest.main()
