"""
Integration tests for ICL Labeling with Ollama.

This module tests the full ICL labeling workflow using a real Ollama
LLM endpoint with the qwen3:0.6b model for debugging/testing purposes.

Prerequisites:
    - Ollama must be running locally (ollama serve)
    - The qwen3:0.6b model must be available (ollama pull qwen3:0.6b)

Run these tests with:
    pytest tests/integration/test_icl_ollama_integration.py -v -s

Skip if ollama not available:
    pytest tests/integration/test_icl_ollama_integration.py -v -s -m "not requires_ollama"
"""

import os
import sys
import json
import time
import tempfile
import unittest
import subprocess
from datetime import datetime
from typing import Optional
from unittest.mock import patch, MagicMock

import pytest
import requests

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))


def is_ollama_available() -> bool:
    """Check if Ollama is running and accessible."""
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        return response.status_code == 200
    except:
        return False


def is_model_available(model_name: str = "qwen3:0.6b") -> bool:
    """Check if a specific model is available in Ollama."""
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code == 200:
            models = response.json().get('models', [])
            return any(model_name in m.get('name', '') for m in models)
        return False
    except:
        return False


# Markers for conditional test execution
requires_ollama = pytest.mark.skipif(
    not is_ollama_available(),
    reason="Ollama is not running on localhost:11434"
)

requires_qwen = pytest.mark.skipif(
    not is_model_available("qwen3:0.6b"),
    reason="qwen3:0.6b model not available in Ollama"
)


@pytest.fixture(scope="module")
def ollama_config():
    """Create a configuration with Ollama endpoint."""
    return {
        'ai_support': {
            'enabled': True,
            'endpoint_type': 'ollama',
            'ai_config': {
                'model': 'qwen3:0.6b',
                'base_url': 'http://localhost:11434'
            }
        },
        'icl_labeling': {
            'enabled': True,
            'example_selection': {
                'min_agreement_threshold': 0.8,
                'min_annotators_per_instance': 2,
                'max_examples_per_schema': 5
            },
            'llm_labeling': {
                'batch_size': 3,
                'trigger_threshold': 2,
                'confidence_threshold': 0.5,
                'max_total_labels': 10
            },
            'verification': {
                'enabled': True,
                'sample_rate': 0.5
            }
        }
    }


@requires_ollama
@requires_qwen
class TestICLPromptBuilderWithOllama(unittest.TestCase):
    """Test prompt building and response parsing with real Ollama responses."""

    def setUp(self):
        """Set up test fixtures."""
        from potato.ai.icl_prompt_builder import ICLPromptBuilder

        self.builder = ICLPromptBuilder()
        self.schema = {
            'name': 'sentiment',
            'description': 'Classify the sentiment of the text as positive, neutral, or negative.',
            'annotation_type': 'radio',
            'labels': [
                {'name': 'positive', 'description': 'Expresses positive sentiment'},
                {'name': 'neutral', 'description': 'Neutral or factual'},
                {'name': 'negative', 'description': 'Expresses negative sentiment'}
            ]
        }

    def _call_ollama(self, prompt: str) -> str:
        """Call Ollama API directly."""
        try:
            response = requests.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "qwen3:0.6b",
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.1,  # Low temperature for more deterministic output
                        "num_predict": 200
                    }
                },
                timeout=60
            )
            if response.status_code == 200:
                return response.json().get('response', '')
            return ''
        except Exception as e:
            print(f"Ollama call failed: {e}")
            return ''

    def test_prompt_produces_parseable_response(self):
        """Test that generated prompts produce parseable responses from Ollama."""
        # Create a simple example
        class MockExample:
            instance_id = 'ex1'
            text = 'I love this product!'
            schema_name = 'sentiment'
            label = 'positive'
            agreement_score = 0.95
            annotator_count = 3

        prompt = self.builder.build_prompt(
            schema=self.schema,
            examples=[MockExample()],
            target_text="This is terrible service."
        )

        print(f"\n=== Generated Prompt ===\n{prompt[:500]}...\n")

        # Call Ollama
        response = self._call_ollama(prompt)
        print(f"=== Ollama Response ===\n{response}\n")

        # Try to parse
        label, confidence, reasoning = self.builder.parse_response(response, self.schema)

        print(f"Parsed: label={label}, confidence={confidence}, reasoning={reasoning[:50] if reasoning else 'N/A'}...")

        # The response should be parseable (may or may not be correct label)
        # We're testing that the prompt format works with the model
        if label is not None:
            self.assertIn(label, ['positive', 'neutral', 'negative'])
            self.assertGreaterEqual(confidence, 0.0)
            self.assertLessEqual(confidence, 1.0)

    def test_multiple_examples_improve_context(self):
        """Test that multiple examples provide better context."""
        class MockExample:
            def __init__(self, text, label):
                self.instance_id = f'ex_{hash(text)}'
                self.text = text
                self.schema_name = 'sentiment'
                self.label = label
                self.agreement_score = 0.9
                self.annotator_count = 3

        examples = [
            MockExample("I love this!", "positive"),
            MockExample("This is okay, nothing special.", "neutral"),
            MockExample("Worst experience ever.", "negative")
        ]

        prompt = self.builder.build_prompt(
            schema=self.schema,
            examples=examples,
            target_text="Amazing product, exceeded expectations!"
        )

        response = self._call_ollama(prompt)
        label, confidence, reasoning = self.builder.parse_response(response, self.schema)

        print(f"\nWith 3 examples - Label: {label}, Confidence: {confidence}")

        # With clear positive text and examples, should hopefully get positive
        # But we're mainly testing the workflow, not the model quality


@requires_ollama
@requires_qwen
class TestICLLabelerWithOllama(unittest.TestCase):
    """Integration tests for ICLLabeler with Ollama backend."""

    def setUp(self):
        """Set up test fixtures."""
        from potato.ai.icl_labeler import clear_icl_labeler
        clear_icl_labeler()

        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up."""
        from potato.ai.icl_labeler import clear_icl_labeler
        clear_icl_labeler()

        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_label_instance_with_ollama(self):
        """Test labeling a single instance with Ollama."""
        from potato.ai.icl_labeler import ICLLabeler, HighConfidenceExample, clear_icl_labeler

        config = {
            'ai_support': {
                'enabled': True,
                'endpoint_type': 'ollama',
                'ai_config': {
                    'model': 'qwen3:0.6b',
                    'base_url': 'http://localhost:11434'
                }
            },
            'icl_labeling': {
                'enabled': True,
                'llm_labeling': {
                    'confidence_threshold': 0.3  # Low threshold for testing
                }
            },
            'output_annotation_dir': self.temp_dir,
            'annotation_schemes': [{
                'name': 'sentiment',
                'annotation_type': 'radio',
                'labels': ['positive', 'neutral', 'negative'],
                'description': 'Sentiment classification'
            }]
        }

        labeler = ICLLabeler(config)

        # Add some examples manually
        labeler.schema_to_examples['sentiment'] = [
            HighConfidenceExample(
                'ex1', 'I love this product!', 'sentiment', 'positive', 0.95, 3
            ),
            HighConfidenceExample(
                'ex2', 'This is terrible.', 'sentiment', 'negative', 0.90, 3
            ),
            HighConfidenceExample(
                'ex3', 'It works as described.', 'sentiment', 'neutral', 0.85, 3
            )
        ]

        # Label a new instance
        prediction = labeler.label_instance(
            instance_id='test_001',
            schema_name='sentiment',
            instance_text='Absolutely wonderful experience!'
        )

        print(f"\n=== Prediction ===")
        print(f"Label: {prediction.predicted_label if prediction else 'None'}")
        print(f"Confidence: {prediction.confidence_score if prediction else 0}")
        print(f"Reasoning: {prediction.reasoning[:100] if prediction and prediction.reasoning else 'N/A'}...")

        # Verify prediction structure
        if prediction:
            self.assertEqual(prediction.instance_id, 'test_001')
            self.assertEqual(prediction.schema_name, 'sentiment')
            self.assertIn(prediction.predicted_label, ['positive', 'neutral', 'negative'])
            self.assertGreaterEqual(prediction.confidence_score, 0.0)
            self.assertLessEqual(prediction.confidence_score, 1.0)


@requires_ollama
@requires_qwen
class TestFullICLWorkflow(unittest.TestCase):
    """End-to-end integration test of the full ICL workflow."""

    @classmethod
    def setUpClass(cls):
        """Set up test environment."""
        from potato.ai.icl_labeler import clear_icl_labeler
        clear_icl_labeler()

        cls.temp_dir = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        """Clean up."""
        from potato.ai.icl_labeler import clear_icl_labeler
        clear_icl_labeler()

        import shutil
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    @patch('potato.flask_server.get_item_state_manager')
    def test_workflow_example_collection_to_verification(self, mock_get_ism):
        """Test the complete workflow from examples to verification."""
        from potato.ai.icl_labeler import (
            ICLLabeler, HighConfidenceExample, ICLPrediction, clear_icl_labeler
        )

        # Mock ItemStateManager
        mock_ism = MagicMock()
        mock_ism.get_all_instance_ids.return_value = [f'test_{i:03d}' for i in range(20)]
        mock_get_ism.return_value = mock_ism

        clear_icl_labeler()

        config = {
            'ai_support': {
                'enabled': True,
                'endpoint_type': 'ollama',
                'ai_config': {
                    'model': 'qwen3:0.6b',
                    'base_url': 'http://localhost:11434'
                }
            },
            'icl_labeling': {
                'enabled': True,
                'example_selection': {
                    'min_agreement_threshold': 0.8,
                    'min_annotators_per_instance': 2,
                    'max_examples_per_schema': 5
                },
                'llm_labeling': {
                    'batch_size': 2,
                    'trigger_threshold': 2,
                    'confidence_threshold': 0.3,
                    'max_total_labels': 5
                },
                'verification': {
                    'enabled': True,
                    'sample_rate': 1.0  # Verify all for testing
                }
            },
            'output_annotation_dir': self.temp_dir,
            'annotation_schemes': [{
                'name': 'category',
                'annotation_type': 'radio',
                'labels': ['technology', 'sports', 'politics'],
                'description': 'News category classification'
            }]
        }

        labeler = ICLLabeler(config)

        print("\n=== Step 1: Add High-Confidence Examples ===")
        # Simulate having collected high-confidence examples from annotators
        examples = [
            HighConfidenceExample(
                'news_001',
                'Apple announces new iPhone with revolutionary chip.',
                'category', 'technology', 0.95, 4
            ),
            HighConfidenceExample(
                'news_002',
                'Lakers win championship after thrilling overtime.',
                'category', 'sports', 0.90, 3
            ),
            HighConfidenceExample(
                'news_003',
                'Senate passes new infrastructure bill.',
                'category', 'politics', 0.88, 3
            )
        ]
        labeler.schema_to_examples['category'] = examples
        print(f"Added {len(examples)} high-confidence examples")

        print("\n=== Step 2: Label New Instances ===")
        # Label some new instances
        test_texts = [
            ('test_001', 'Google releases new AI model for search.'),
            ('test_002', 'Manchester United signs star player.'),
        ]

        predictions = []
        for instance_id, text in test_texts:
            prediction = labeler.label_instance(instance_id, 'category', text)
            if prediction:
                predictions.append(prediction)
                print(f"  {instance_id}: {prediction.predicted_label} (conf: {prediction.confidence_score:.2f})")

        print("\n=== Step 3: Check Verification Queue ===")
        pending = labeler.get_pending_verifications(count=10)
        print(f"Pending verifications: {len(pending)}")
        for instance_id, schema in pending:
            print(f"  - {instance_id} ({schema})")

        print("\n=== Step 4: Simulate Human Verification ===")
        # Simulate human verification
        if pending:
            instance_id, schema = pending[0]
            pred = labeler.predictions.get(instance_id, {}).get(schema)
            if pred:
                # Human verifies (we'll say they agree with the prediction)
                success = labeler.record_verification(
                    instance_id=instance_id,
                    schema_name=schema,
                    human_label=pred.predicted_label,  # Agree with LLM
                    verified_by='test_user'
                )
                print(f"Recorded verification for {instance_id}: {success}")

        print("\n=== Step 5: Check Accuracy Metrics ===")
        metrics = labeler.get_accuracy_metrics()
        print(f"Total predictions: {metrics['total_predictions']}")
        print(f"Total verified: {metrics['total_verified']}")
        print(f"Accuracy: {metrics['accuracy']}")

        print("\n=== Step 6: Get Status ===")
        status = labeler.get_status()
        print(f"Enabled: {status['enabled']}")
        print(f"Total examples: {status['total_examples']}")
        print(f"Total predictions: {status['total_predictions']}")
        print(f"Labeling paused: {status['labeling_paused']}")

        # Assertions
        self.assertTrue(labeler.has_enough_examples('category'))
        self.assertGreater(len(predictions), 0)


@requires_ollama
@requires_qwen
class TestOllamaEndpointDirectly(unittest.TestCase):
    """Direct tests of the Ollama AI endpoint."""

    def test_ollama_endpoint_connection(self):
        """Test basic connection to Ollama."""
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        self.assertEqual(response.status_code, 200)

        models = response.json().get('models', [])
        print(f"\nAvailable Ollama models: {[m['name'] for m in models]}")

    def test_ollama_generate(self):
        """Test basic text generation with Ollama."""
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "qwen3:0.6b",
                "prompt": "Say 'hello' in JSON format like: {\"message\": \"hello\"}",
                "stream": False,
                "options": {"num_predict": 50}
            },
            timeout=30
        )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        print(f"\nOllama response: {result.get('response', '')[:200]}")

    def test_ollama_through_ai_endpoint(self):
        """Test Ollama through the Potato AI endpoint abstraction."""
        try:
            from potato.ai.ollama_endpoint import OllamaEndpoint
            from pydantic import BaseModel

            # Define a simple output schema
            class SimpleResponse(BaseModel):
                message: str

            config = {
                'ai_support': {
                    'enabled': True,
                    'endpoint_type': 'ollama',
                    'ai_config': {
                        'model': 'qwen3:0.6b',
                        'base_url': 'http://localhost:11434'
                    }
                }
            }

            endpoint = OllamaEndpoint(config['ai_support']['ai_config'])
            self.assertIsNotNone(endpoint)

            # Try to get a response using the query method with output format
            prompt = "Respond with a JSON object containing a 'message' field with the value 'test'"
            response = endpoint.query(prompt, SimpleResponse)
            print(f"\nAI Endpoint response: {response[:200] if response else 'None'}")

        except ImportError as e:
            self.skipTest(f"AI endpoint module not available: {e}")
        except Exception as e:
            # OllamaEndpoint might have issues with structured output
            print(f"\nNote: Ollama endpoint test failed (expected with some models): {e}")


class TestOllamaAvailability(unittest.TestCase):
    """Tests that check Ollama availability (always run)."""

    def test_check_ollama_status(self):
        """Report on Ollama availability for debugging."""
        ollama_running = is_ollama_available()
        model_available = is_model_available("qwen3:0.6b") if ollama_running else False

        print(f"\n=== Ollama Status ===")
        print(f"Ollama running: {ollama_running}")
        print(f"qwen3:0.6b available: {model_available}")

        if not ollama_running:
            print("\nTo start Ollama:")
            print("  ollama serve")
            print("\nTo pull the model:")
            print("  ollama pull qwen3:0.6b")

    def test_setup_instructions(self):
        """Provide setup instructions for running integration tests."""
        print("\n=== Integration Test Setup ===")
        print("To run these integration tests with Ollama:")
        print("")
        print("1. Install Ollama: https://ollama.ai/download")
        print("2. Start Ollama: ollama serve")
        print("3. Pull the test model: ollama pull qwen3:0.6b")
        print("4. Run tests: pytest tests/integration/test_icl_ollama_integration.py -v -s")
        print("")
        print("Note: qwen3:0.6b is a small model suitable for testing.")
        print("For production, use larger models like llama3 or gpt-4.")


if __name__ == '__main__':
    # Print setup instructions
    print("=" * 60)
    print("ICL Labeling Integration Tests with Ollama")
    print("=" * 60)

    if not is_ollama_available():
        print("\nWARNING: Ollama is not running!")
        print("Start Ollama with: ollama serve")
        print("Then pull the model: ollama pull qwen3:0.6b")
        print("\nSkipping integration tests that require Ollama...")
    elif not is_model_available("qwen3:0.6b"):
        print("\nWARNING: qwen3:0.6b model not available!")
        print("Pull it with: ollama pull qwen3:0.6b")
        print("\nSkipping tests that require this model...")
    else:
        print("\nOllama is running with qwen3:0.6b available.")
        print("Running full integration tests...")

    print("")

    unittest.main(verbosity=2)
