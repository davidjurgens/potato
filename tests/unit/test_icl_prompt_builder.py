"""
Unit tests for ICL Prompt Builder.

This module tests the prompt construction and response parsing functionality
for the In-Context Learning labeling system.
"""

import unittest
import json
from datetime import datetime
from unittest.mock import Mock, patch

from potato.ai.icl_prompt_builder import ICLPromptBuilder, MultiSelectPromptBuilder


class MockHighConfidenceExample:
    """Mock HighConfidenceExample for testing."""

    def __init__(self, instance_id, text, schema_name, label, agreement_score, annotator_count):
        self.instance_id = instance_id
        self.text = text
        self.schema_name = schema_name
        self.label = label
        self.agreement_score = agreement_score
        self.annotator_count = annotator_count


class TestICLPromptBuilder(unittest.TestCase):
    """Test cases for ICLPromptBuilder class."""

    def setUp(self):
        """Set up test fixtures."""
        self.builder = ICLPromptBuilder(max_example_length=500, max_target_length=1000)

        self.sample_schema = {
            'name': 'sentiment',
            'description': 'Classify the sentiment of the text.',
            'annotation_type': 'radio',
            'labels': [
                {'name': 'positive', 'description': 'Positive sentiment'},
                {'name': 'neutral', 'description': 'Neutral sentiment'},
                {'name': 'negative', 'description': 'Negative sentiment'}
            ]
        }

        self.sample_examples = [
            MockHighConfidenceExample(
                instance_id='ex1',
                text='I love this product! It is amazing.',
                schema_name='sentiment',
                label='positive',
                agreement_score=0.95,
                annotator_count=3
            ),
            MockHighConfidenceExample(
                instance_id='ex2',
                text='This is terrible. I want a refund.',
                schema_name='sentiment',
                label='negative',
                agreement_score=0.90,
                annotator_count=3
            )
        ]

    def test_build_prompt_basic(self):
        """Test building a basic prompt with examples."""
        target_text = "The product works as expected."

        prompt = self.builder.build_prompt(
            schema=self.sample_schema,
            examples=self.sample_examples,
            target_text=target_text
        )

        # Check that prompt contains key sections
        self.assertIn('sentiment', prompt)
        self.assertIn('Classify the sentiment', prompt)
        self.assertIn('positive', prompt)
        self.assertIn('neutral', prompt)
        self.assertIn('negative', prompt)
        self.assertIn('I love this product', prompt)
        self.assertIn('This is terrible', prompt)
        self.assertIn('The product works as expected', prompt)
        self.assertIn('JSON', prompt)

    def test_build_prompt_no_examples(self):
        """Test building a prompt without examples."""
        target_text = "Test text."

        prompt = self.builder.build_prompt(
            schema=self.sample_schema,
            examples=[],
            target_text=target_text
        )

        # Should still have schema info and target text
        self.assertIn('sentiment', prompt)
        self.assertIn('Test text', prompt)
        # Should NOT have examples section
        self.assertNotIn('Example 1', prompt)

    def test_build_prompt_with_string_labels(self):
        """Test building prompt with string-only labels."""
        schema = {
            'name': 'category',
            'description': 'Categorize the text.',
            'labels': ['A', 'B', 'C']
        }

        prompt = self.builder.build_prompt(
            schema=schema,
            examples=[],
            target_text="Test"
        )

        self.assertIn('A, B, C', prompt)

    def test_build_system_prompt_radio(self):
        """Test system prompt for radio annotation type."""
        prompt = self.builder._build_system_prompt(self.sample_schema)

        self.assertIn('Single-choice classification', prompt)
        self.assertIn('exactly ONE label', prompt)

    def test_build_system_prompt_multiselect(self):
        """Test system prompt for multiselect annotation type."""
        schema = dict(self.sample_schema)
        schema['annotation_type'] = 'multiselect'

        prompt = self.builder._build_system_prompt(schema)

        self.assertIn('Multi-label classification', prompt)
        self.assertIn('ALL applicable', prompt)

    def test_build_system_prompt_likert(self):
        """Test system prompt for likert annotation type."""
        schema = dict(self.sample_schema)
        schema['annotation_type'] = 'likert'

        prompt = self.builder._build_system_prompt(schema)

        self.assertIn('Rating scale', prompt)

    def test_format_example(self):
        """Test formatting a single example."""
        example = self.sample_examples[0]
        formatted = self.builder._format_example(example, 1)

        self.assertIn('Example 1', formatted)
        self.assertIn('I love this product', formatted)
        self.assertIn('positive', formatted)
        self.assertIn('95%', formatted)
        self.assertIn('3 annotators', formatted)

    def test_truncate_text_short(self):
        """Test truncation with short text."""
        text = "Short text."
        result = self.builder._truncate_text(text, 100)
        self.assertEqual(result, text)

    def test_truncate_text_long(self):
        """Test truncation with long text."""
        text = "This is a very long text " * 50
        result = self.builder._truncate_text(text, 100)

        self.assertTrue(len(result) <= 103)  # 100 + "..."
        self.assertTrue(result.endswith('...'))

    def test_truncate_text_word_boundary(self):
        """Test truncation preserves word boundaries."""
        text = "word1 word2 word3 word4 word5 word6"
        result = self.builder._truncate_text(text, 20)

        # Should break at a word boundary
        self.assertFalse(result.rstrip('.').endswith('word'))
        self.assertTrue(result.endswith('...'))

    def test_get_labels_from_schema_dict_format(self):
        """Test extracting labels from dict format."""
        labels = self.builder._get_labels_from_schema(self.sample_schema)
        self.assertEqual(labels, ['positive', 'neutral', 'negative'])

    def test_get_labels_from_schema_string_format(self):
        """Test extracting labels from string format."""
        schema = {'labels': ['A', 'B', 'C']}
        labels = self.builder._get_labels_from_schema(schema)
        self.assertEqual(labels, ['A', 'B', 'C'])

    def test_get_labels_from_schema_empty(self):
        """Test extracting labels from empty schema."""
        schema = {}
        labels = self.builder._get_labels_from_schema(schema)
        self.assertEqual(labels, [])


class TestICLPromptBuilderResponseParsing(unittest.TestCase):
    """Test cases for response parsing functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.builder = ICLPromptBuilder()
        self.schema = {
            'name': 'sentiment',
            'labels': ['positive', 'neutral', 'negative']
        }

    def test_parse_response_valid_json(self):
        """Test parsing a valid JSON response."""
        response = '{"label": "positive", "confidence": 0.85, "reasoning": "The text is happy."}'

        label, confidence, reasoning = self.builder.parse_response(response, self.schema)

        self.assertEqual(label, 'positive')
        self.assertAlmostEqual(confidence, 0.85, places=2)
        self.assertEqual(reasoning, 'The text is happy.')

    def test_parse_response_json_in_code_block(self):
        """Test parsing JSON wrapped in markdown code block."""
        response = '''Here is my analysis:
```json
{"label": "negative", "confidence": 0.75, "reasoning": "Contains complaints."}
```'''

        label, confidence, reasoning = self.builder.parse_response(response, self.schema)

        self.assertEqual(label, 'negative')
        self.assertAlmostEqual(confidence, 0.75, places=2)

    def test_parse_response_json_in_generic_code_block(self):
        """Test parsing JSON in generic code block."""
        response = '''```
{"label": "neutral", "confidence": 0.6, "reasoning": "Factual statement."}
```'''

        label, confidence, reasoning = self.builder.parse_response(response, self.schema)

        self.assertEqual(label, 'neutral')

    def test_parse_response_case_insensitive_label(self):
        """Test fuzzy matching for case differences."""
        response = '{"label": "POSITIVE", "confidence": 0.8, "reasoning": "..."}'

        label, confidence, reasoning = self.builder.parse_response(response, self.schema)

        self.assertEqual(label, 'positive')

    def test_parse_response_whitespace_in_label(self):
        """Test fuzzy matching handles whitespace."""
        response = '{"label": " positive ", "confidence": 0.8, "reasoning": "..."}'

        label, confidence, reasoning = self.builder.parse_response(response, self.schema)

        self.assertEqual(label, 'positive')

    def test_parse_response_invalid_label(self):
        """Test handling of invalid label."""
        response = '{"label": "unknown", "confidence": 0.9, "reasoning": "..."}'

        label, confidence, reasoning = self.builder.parse_response(response, self.schema)

        # Should return None for invalid label
        self.assertIsNone(label)

    def test_parse_response_confidence_clamping_high(self):
        """Test confidence is clamped to 1.0 max."""
        response = '{"label": "positive", "confidence": 1.5, "reasoning": "..."}'

        label, confidence, reasoning = self.builder.parse_response(response, self.schema)

        self.assertEqual(confidence, 1.0)

    def test_parse_response_confidence_clamping_low(self):
        """Test confidence is clamped to 0.0 min."""
        response = '{"label": "positive", "confidence": -0.5, "reasoning": "..."}'

        label, confidence, reasoning = self.builder.parse_response(response, self.schema)

        self.assertEqual(confidence, 0.0)

    def test_parse_response_missing_confidence(self):
        """Test default confidence when missing."""
        response = '{"label": "positive", "reasoning": "..."}'

        label, confidence, reasoning = self.builder.parse_response(response, self.schema)

        self.assertEqual(confidence, 0.5)  # Default

    def test_parse_response_fallback_text_extraction(self):
        """Test fallback extraction from plain text."""
        response = "I think this is positive because it contains happy words."

        label, confidence, reasoning = self.builder.parse_response(response, self.schema)

        self.assertEqual(label, 'positive')
        self.assertEqual(confidence, 0.5)  # Low confidence for fallback

    def test_parse_response_invalid_json(self):
        """Test handling of completely invalid response."""
        response = "This is not JSON at all and mentions no labels."

        label, confidence, reasoning = self.builder.parse_response(response, self.schema)

        self.assertIsNone(label)
        self.assertEqual(confidence, 0.0)

    def test_extract_json_direct(self):
        """Test direct JSON parsing."""
        text = '{"label": "test"}'
        result = self.builder._extract_json(text)
        self.assertEqual(result, {'label': 'test'})

    def test_extract_json_from_code_block(self):
        """Test JSON extraction from code block."""
        text = '''Some text
```json
{"key": "value"}
```
More text'''
        result = self.builder._extract_json(text)
        self.assertEqual(result, {'key': 'value'})

    def test_extract_json_inline(self):
        """Test inline JSON extraction."""
        text = 'The result is {"label": "test", "confidence": 0.8} which means...'
        result = self.builder._extract_json(text)
        self.assertIsNotNone(result)
        self.assertEqual(result['label'], 'test')

    def test_fuzzy_match_label_exact(self):
        """Test fuzzy matching with exact match."""
        result = self.builder._fuzzy_match_label('positive', ['positive', 'neutral', 'negative'])
        self.assertEqual(result, 'positive')

    def test_fuzzy_match_label_case(self):
        """Test fuzzy matching with case difference."""
        result = self.builder._fuzzy_match_label('POSITIVE', ['positive', 'neutral', 'negative'])
        self.assertEqual(result, 'positive')

    def test_fuzzy_match_label_no_match(self):
        """Test fuzzy matching with no match."""
        result = self.builder._fuzzy_match_label('unknown', ['positive', 'neutral', 'negative'])
        self.assertIsNone(result)


class TestMultiSelectPromptBuilder(unittest.TestCase):
    """Test cases for MultiSelectPromptBuilder class."""

    def setUp(self):
        """Set up test fixtures."""
        self.builder = MultiSelectPromptBuilder()
        self.schema = {
            'name': 'topics',
            'description': 'Select all applicable topics.',
            'labels': ['politics', 'sports', 'technology', 'entertainment']
        }

    def test_build_output_instructions(self):
        """Test multiselect output instructions."""
        instructions = self.builder._build_output_instructions(self.schema)

        self.assertIn('labels', instructions)
        self.assertIn('Array', instructions)
        self.assertIn('["label1", "label2"]', instructions)

    def test_parse_response_valid(self):
        """Test parsing valid multiselect response."""
        response = '{"labels": ["politics", "technology"], "confidence": 0.8, "reasoning": "..."}'

        labels, confidence, reasoning = self.builder.parse_response(response, self.schema)

        self.assertEqual(labels, ['politics', 'technology'])
        self.assertAlmostEqual(confidence, 0.8, places=2)

    def test_parse_response_filters_invalid_labels(self):
        """Test that invalid labels are filtered out."""
        response = '{"labels": ["politics", "invalid", "sports"], "confidence": 0.7, "reasoning": "..."}'

        labels, confidence, reasoning = self.builder.parse_response(response, self.schema)

        self.assertEqual(labels, ['politics', 'sports'])

    def test_parse_response_all_invalid(self):
        """Test response with all invalid labels."""
        response = '{"labels": ["invalid1", "invalid2"], "confidence": 0.9, "reasoning": "..."}'

        labels, confidence, reasoning = self.builder.parse_response(response, self.schema)

        self.assertIsNone(labels)

    def test_parse_response_empty_labels(self):
        """Test response with empty labels array."""
        response = '{"labels": [], "confidence": 0.5, "reasoning": "..."}'

        labels, confidence, reasoning = self.builder.parse_response(response, self.schema)

        self.assertIsNone(labels)


class TestPromptBuilderEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def setUp(self):
        """Set up test fixtures."""
        self.builder = ICLPromptBuilder()

    def test_schema_without_name(self):
        """Test handling schema without name."""
        schema = {'labels': ['a', 'b']}
        prompt = self.builder._build_system_prompt(schema)
        self.assertIn('unknown', prompt)

    def test_schema_without_description(self):
        """Test handling schema without description."""
        schema = {'name': 'test', 'labels': ['a', 'b']}
        prompt = self.builder._build_system_prompt(schema)
        self.assertIn('Label the text according to the schema', prompt)

    def test_build_prompt_with_special_characters(self):
        """Test handling text with special characters."""
        schema = {'name': 'test', 'labels': ['yes', 'no']}
        examples = [
            MockHighConfidenceExample(
                instance_id='ex1',
                text='Text with "quotes" and {braces} and [brackets]',
                schema_name='test',
                label='yes',
                agreement_score=0.9,
                annotator_count=2
            )
        ]

        prompt = self.builder.build_prompt(schema, examples, 'Target with <html> tags')

        # Should handle without errors
        self.assertIsNotNone(prompt)
        self.assertIn('quotes', prompt)

    def test_parse_response_with_exception(self):
        """Test graceful handling of parsing exceptions."""
        # Malformed JSON that might cause issues
        response = '{"label": "test", confidence: invalid}'

        label, confidence, reasoning = self.builder.parse_response(response, {'labels': ['test']})

        # Should fallback to text extraction or return None gracefully
        # The key is it doesn't raise an exception


if __name__ == '__main__':
    unittest.main()
