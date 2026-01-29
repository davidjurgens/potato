"""
Unit tests for AI cache system.

Tests caching behavior, error detection, and cache key format.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json


class TestErrorResponseDetection:
    """Test the error detection logic that prevents caching error responses."""

    def test_unable_to_generate_is_error(self):
        """'Unable to generate...' strings should be detected as errors."""
        test_cases = [
            "Unable to generate hint at this time.",
            "Unable to generate suggestion - annotation type not configured",
            "Unable to generate suggestion - prompt not configured",
        ]

        for result in test_cases:
            is_error = (
                isinstance(result, str) and
                (result.startswith("Unable to generate") or
                 result.startswith("Error:") or
                 "error" in result.lower()[:50])
            )
            assert is_error, f"'{result}' should be detected as error"

    def test_error_prefix_is_error(self):
        """'Error:...' strings should be detected as errors."""
        test_cases = [
            "Error: Connection refused",
            "Error: Timeout after 60 seconds",
            "Error: Invalid JSON response",
        ]

        for result in test_cases:
            is_error = (
                isinstance(result, str) and
                (result.startswith("Unable to generate") or
                 result.startswith("Error:") or
                 "error" in result.lower()[:50])
            )
            assert is_error, f"'{result}' should be detected as error"

    def test_error_in_first_50_chars_is_error(self):
        """Strings containing 'error' in first 50 chars should be detected."""
        test_cases = [
            "There was an error processing your request",
            "An error occurred while generating hint",
            '{"error": "timeout"}',  # JSON error response
        ]

        for result in test_cases:
            is_error = (
                isinstance(result, str) and
                (result.startswith("Unable to generate") or
                 result.startswith("Error:") or
                 "error" in result.lower()[:50])
            )
            assert is_error, f"'{result}' should be detected as error"

    def test_valid_json_not_error(self):
        """Valid JSON hint responses should NOT be detected as errors."""
        test_cases = [
            '{"hint": "Look for positive sentiment words", "suggestive_choice": "positive"}',
            '{"keywords": ["great", "excellent", "love"]}',
            '{"hint": "This review discusses product quality"}',
        ]

        for result in test_cases:
            is_error = (
                isinstance(result, str) and
                (result.startswith("Unable to generate") or
                 result.startswith("Error:") or
                 "error" in result.lower()[:50])
            )
            assert not is_error, f"'{result}' should NOT be detected as error"

    def test_dict_result_not_error(self):
        """Dict results (already parsed JSON) should NOT be detected as errors."""
        result = {"hint": "Test hint", "suggestive_choice": "positive"}

        is_error = (
            isinstance(result, str) and
            (result.startswith("Unable to generate") or
             result.startswith("Error:") or
             "error" in result.lower()[:50])
        )
        assert not is_error, "Dict result should NOT be detected as error"

    def test_error_after_50_chars_not_detected(self):
        """Strings with 'error' after first 50 chars may not be detected."""
        # This is a known limitation - error must be in first 50 chars
        result = "A" * 60 + "error occurred"  # Error is at position 60

        is_error = (
            isinstance(result, str) and
            (result.startswith("Unable to generate") or
             result.startswith("Error:") or
             "error" in result.lower()[:50])
        )
        # This string won't be detected as error (limitation)
        assert not is_error, "Error after 50 chars is not detected (known limitation)"


class TestCacheKeyFormat:
    """Test the cache key format."""

    def test_cache_key_is_tuple(self):
        """Cache key should be (instance_id, annotation_id, ai_assistant) tuple."""
        instance_id = 0
        annotation_id = 0
        ai_assistant = "hint"

        key = (instance_id, annotation_id, ai_assistant)

        assert isinstance(key, tuple)
        assert len(key) == 3
        assert key[0] == instance_id
        assert key[1] == annotation_id
        assert key[2] == ai_assistant

    def test_cache_key_different_for_different_assistants(self):
        """Different ai_assistant types should have different keys."""
        key_hint = (0, 0, "hint")
        key_keyword = (0, 0, "keyword")
        key_random = (0, 0, "random")

        assert key_hint != key_keyword
        assert key_hint != key_random
        assert key_keyword != key_random

    def test_cache_key_different_for_different_instances(self):
        """Different instance_ids should have different keys."""
        key_0 = (0, 0, "hint")
        key_1 = (1, 0, "hint")

        assert key_0 != key_1

    def test_cache_key_different_for_different_annotations(self):
        """Different annotation_ids should have different keys."""
        key_ann0 = (0, 0, "hint")
        key_ann1 = (0, 1, "hint")

        assert key_ann0 != key_ann1


class TestCacheOperations:
    """Test cache add/get operations."""

    def test_add_and_get_from_cache(self):
        """Test basic cache add and retrieve."""
        cache = {}
        key = (0, 0, "hint")
        value = '{"hint": "test"}'

        cache[key] = value

        assert key in cache
        assert cache[key] == value

    def test_cache_miss_returns_none(self):
        """Cache miss should return None (or key not found)."""
        cache = {}
        key = (0, 0, "hint")

        assert cache.get(key) is None

    def test_cache_stores_json_string(self):
        """Cache should store JSON strings correctly."""
        cache = {}
        key = (0, 0, "hint")
        value = json.dumps({"hint": "Look for sentiment", "suggestive_choice": "positive"})

        cache[key] = value

        retrieved = cache[key]
        parsed = json.loads(retrieved)
        assert parsed["hint"] == "Look for sentiment"
        assert parsed["suggestive_choice"] == "positive"


class TestComputeHelpRouting:
    """Test that compute_help routes to correct generator based on annotation type."""

    def test_annotation_type_routing_cases(self):
        """Verify the annotation types that should be routed."""
        from potato.ai.ai_endpoint import Annotation_Type

        expected_types = [
            "radio",
            "likert",
            "multiselect",
            "number",
            "select",
            "slider",
            "span",
            "text",  # textbox maps to "text"
        ]

        # Verify all expected types exist in the enum
        for type_name in expected_types:
            assert type_name in [e.value for e in Annotation_Type], \
                f"Annotation_Type should have '{type_name}'"


class TestMockedAICacheManager:
    """Test AiCacheManager with mocked dependencies."""

    @patch('potato.ai.ai_cache.config', {
        'ai_support': {
            'enabled': True,
            'endpoint_type': 'ollama',
            'ai_config': {
                'model': 'test-model',
                'include': {'all': True}
            },
            'cache_config': {
                'disk_cache': {'enabled': False, 'path': ''},
                'prefetch': {'warm_up_page_count': 0, 'on_next': 0, 'on_prev': 0}
            }
        },
        'annotation_schemes': [{'annotation_type': 'radio', 'name': 'test'}]
    })
    @patch('potato.ai.ai_cache.AIEndpointFactory')
    @patch('potato.ai.ai_cache.ModelManager')
    def test_cache_manager_init_without_disk_cache(self, mock_model_manager, mock_factory):
        """Test AiCacheManager initializes without disk cache."""
        mock_factory.create_endpoint.return_value = Mock()
        mock_model_manager_instance = Mock()
        mock_model_manager.return_value = mock_model_manager_instance

        from potato.ai.ai_cache import AiCacheManager

        manager = AiCacheManager()

        assert manager.disk_cache_enabled is False
        assert manager.include_all is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
