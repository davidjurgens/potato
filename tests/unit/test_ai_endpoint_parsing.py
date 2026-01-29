"""
Unit tests for AI endpoint JSON parsing and error handling.

Tests the parseStringToJson method and get_ai error handling.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json


class TestParseStringToJson:
    """Test the parseStringToJson method of BaseAIEndpoint."""

    def setup_method(self):
        """Create a mock endpoint for testing."""
        # Import here to avoid import-time issues
        from potato.ai.ai_endpoint import BaseAIEndpoint

        class TestEndpoint(BaseAIEndpoint):
            def _initialize_client(self):
                pass

            def _get_default_model(self):
                return "test-model"

            def query(self, prompt, output_format=None):
                return '{"test": "response"}'

        self.endpoint = TestEndpoint({
            "description": "test",
            "annotation_type": "radio",
            "ai_config": {}
        })

    def test_parse_valid_json_string(self):
        """Valid JSON string should parse correctly."""
        json_str = '{"hint": "Look for positive words", "suggestive_choice": "positive"}'

        result = self.endpoint.parseStringToJson(json_str)

        assert isinstance(result, dict)
        assert result["hint"] == "Look for positive words"
        assert result["suggestive_choice"] == "positive"

    def test_parse_empty_string_raises(self):
        """Empty string should raise ValueError."""
        with pytest.raises(ValueError, match="Empty response"):
            self.endpoint.parseStringToJson("")

    def test_parse_none_raises(self):
        """None should raise ValueError."""
        with pytest.raises(ValueError, match="Empty response"):
            self.endpoint.parseStringToJson(None)

    def test_parse_whitespace_only_raises(self):
        """Whitespace-only string should raise ValueError."""
        with pytest.raises(ValueError, match="Empty response"):
            self.endpoint.parseStringToJson("   ")

    def test_parse_dict_passthrough(self):
        """Dict input should be returned unchanged."""
        input_dict = {"hint": "test", "suggestive_choice": "positive"}

        result = self.endpoint.parseStringToJson(input_dict)

        assert result == input_dict
        assert result is input_dict  # Should be same object

    def test_parse_json_in_markdown_code_block(self):
        """JSON wrapped in markdown code block should be extracted."""
        markdown_json = '''```json
{"hint": "extracted", "suggestive_choice": "neutral"}
```'''

        result = self.endpoint.parseStringToJson(markdown_json)

        assert isinstance(result, dict)
        assert result["hint"] == "extracted"

    def test_parse_json_in_plain_code_block(self):
        """JSON wrapped in plain code block should be extracted."""
        code_block = '''```
{"hint": "from plain block", "suggestive_choice": "negative"}
```'''

        result = self.endpoint.parseStringToJson(code_block)

        assert isinstance(result, dict)
        assert result["hint"] == "from plain block"

    def test_parse_invalid_json_raises(self):
        """Invalid JSON should raise ValueError with details."""
        invalid_json = '{"hint": "unclosed string'

        with pytest.raises(ValueError, match="Failed to parse JSON"):
            self.endpoint.parseStringToJson(invalid_json)

    def test_parse_array_json(self):
        """JSON array should parse correctly."""
        json_array = '["keyword1", "keyword2", "keyword3"]'

        result = self.endpoint.parseStringToJson(json_array)

        assert isinstance(result, list)
        assert len(result) == 3
        assert "keyword1" in result

    def test_parse_nested_json(self):
        """Nested JSON should parse correctly."""
        nested_json = '{"keywords": [{"word": "good", "score": 0.9}]}'

        result = self.endpoint.parseStringToJson(nested_json)

        assert isinstance(result, dict)
        assert "keywords" in result
        assert len(result["keywords"]) == 1
        assert result["keywords"][0]["word"] == "good"


class TestGetAIErrorHandling:
    """Test the get_ai method error handling."""

    def setup_method(self):
        """Create a mock endpoint for testing."""
        from potato.ai.ai_endpoint import BaseAIEndpoint, AnnotationInput

        class TestEndpoint(BaseAIEndpoint):
            def _initialize_client(self):
                pass

            def _get_default_model(self):
                return "test-model"

            def query(self, prompt, output_format=None):
                return '{"hint": "test response"}'

        # Patch the ai_prompt to return test prompts
        self.mock_prompts = {
            "radio": {
                "hint": {
                    "prompt": "Test prompt for $text",
                    "output_format": "default_hint"
                }
            }
        }

        self.endpoint = TestEndpoint({
            "description": "test",
            "annotation_type": "radio",
            "ai_config": {}
        })
        self.endpoint.prompts = self.mock_prompts

    def test_invalid_annotation_type_returns_error_string(self):
        """Invalid annotation type should return error string, not raise."""
        from potato.ai.ai_endpoint import AnnotationInput

        data = AnnotationInput(
            ai_assistant="hint",
            annotation_type="invalid_type",  # Not a valid type
            text="test text",
            description="test description"
        )

        with patch('potato.ai.ai_endpoint.get_ai_prompt', return_value=self.mock_prompts):
            result = self.endpoint.get_ai(data, Mock())

        assert isinstance(result, str)
        assert "Unable to generate" in result

    def test_missing_ai_assistant_returns_error_string(self):
        """Missing AI assistant config should return error string."""
        from potato.ai.ai_endpoint import AnnotationInput

        data = AnnotationInput(
            ai_assistant="nonexistent_assistant",  # Not configured
            annotation_type="radio",
            text="test text",
            description="test description"
        )

        # Prompts don't have "nonexistent_assistant"
        with patch('potato.ai.ai_endpoint.get_ai_prompt', return_value=self.mock_prompts):
            result = self.endpoint.get_ai(data, Mock())

        assert isinstance(result, str)
        assert "Unable to generate" in result

    def test_query_exception_returns_unable_to_generate(self):
        """Exception during query should return 'Unable to generate' string."""
        from potato.ai.ai_endpoint import AnnotationInput

        # Make query raise an exception
        self.endpoint.query = Mock(side_effect=Exception("Network error"))

        data = AnnotationInput(
            ai_assistant="hint",
            annotation_type="radio",
            text="test text",
            description="test description"
        )

        with patch('potato.ai.ai_endpoint.get_ai_prompt', return_value=self.mock_prompts):
            result = self.endpoint.get_ai(data, Mock())

        assert isinstance(result, str)
        assert "Unable to generate hint at this time" in result


class TestAnnotationTypeValidation:
    """Test annotation type enum validation."""

    def test_valid_annotation_types(self):
        """Test all valid annotation types are recognized."""
        from potato.ai.ai_endpoint import Annotation_Type

        valid_types = ["radio", "likert", "number", "text", "multiselect", "span", "select", "slider"]

        for type_name in valid_types:
            # Should not raise
            enum_value = Annotation_Type(type_name)
            assert enum_value.value == type_name

    def test_invalid_annotation_type_raises(self):
        """Invalid annotation type should raise ValueError."""
        from potato.ai.ai_endpoint import Annotation_Type

        with pytest.raises(ValueError):
            Annotation_Type("invalid_type")


class TestAnnotationInput:
    """Test AnnotationInput dataclass."""

    def test_annotation_input_creation(self):
        """Test creating an AnnotationInput."""
        from potato.ai.ai_endpoint import AnnotationInput

        data = AnnotationInput(
            ai_assistant="hint",
            annotation_type="radio",
            text="Sample review text",
            description="Rate the sentiment",
            labels=[{"name": "positive"}, {"name": "negative"}]
        )

        assert data.ai_assistant == "hint"
        assert data.annotation_type == "radio"
        assert data.text == "Sample review text"
        assert len(data.labels) == 2

    def test_annotation_input_defaults(self):
        """Test AnnotationInput default values."""
        from potato.ai.ai_endpoint import AnnotationInput

        data = AnnotationInput(
            ai_assistant="hint",
            annotation_type="radio",
            text="text",
            description="desc"
        )

        assert data.min_label == ""
        assert data.max_label == ""
        assert data.size == -1
        assert data.labels is None
        assert data.min_value == -1
        assert data.max_value == -1
        assert data.step == -1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
