"""
Unit tests for Instance class serialization.

These tests verify that Instance objects can be properly serialized to dictionaries
for JSON responses, which is critical for the /admin/user_state/<user_id> endpoint.
"""

import pytest
from potato.instance_state_management import Instance


class TestInstanceSerialization:
    """Test Instance class serialization methods."""

    def test_instance_to_dict_basic(self):
        """Test basic to_dict() functionality."""
        instance_data = {
            "id": "test_item_1",
            "text": "This is a test item for serialization.",
            "metadata": {"source": "test"}
        }

        instance = Instance(
            instance_id="test_item_1",
            instance_data=instance_data
        )
        # Add metadata separately
        instance.add_metadata("source", "test")

        result = instance.to_dict()

        assert isinstance(result, dict)
        assert result["id"] == "test_item_1"
        assert result["text"] == "This is a test item for serialization."
        assert result["data"] == instance_data
        assert result["metadata"] == {"source": "test"}
        assert "displayed_text" in result

    def test_instance_to_dict_with_displayed_text(self):
        """Test to_dict() with custom displayed text."""
        instance_data = {
            "id": "test_item_2",
            "text": "Original text",
            "displayed_text": "Modified displayed text"
        }

        instance = Instance(
            instance_id="test_item_2",
            instance_data=instance_data
        )

        result = instance.to_dict()

        assert result["text"] == "Original text"
        # Note: get_displayed_text() currently returns get_text(), so displayed_text will be the same
        assert result["displayed_text"] == "Original text"

    def test_instance_to_dict_empty_metadata(self):
        """Test to_dict() with empty metadata."""
        instance_data = {"id": "test_item_3", "text": "Simple text"}

        instance = Instance(
            instance_id="test_item_3",
            instance_data=instance_data
        )

        result = instance.to_dict()

        assert result["metadata"] == {}
        assert result["id"] == "test_item_3"

    def test_instance_to_dict_complex_metadata(self):
        """Test to_dict() with complex metadata."""
        complex_metadata = {
            "source": "test",
            "timestamp": "2023-01-01"
        }

        instance_data = {"id": "test_item_4", "text": "Complex metadata test"}

        instance = Instance(
            instance_id="test_item_4",
            instance_data=instance_data
        )
        # Add metadata separately (add_metadata only accepts strings)
        for key, value in complex_metadata.items():
            instance.add_metadata(key, str(value))

        result = instance.to_dict()

        # Check that metadata was added correctly
        assert result["metadata"]["source"] == "test"
        assert result["metadata"]["timestamp"] == "2023-01-01"

    def test_instance_to_dict_json_serializable(self):
        """Test that to_dict() result is JSON serializable."""
        import json

        instance_data = {
            "id": "test_item_5",
            "text": "JSON serialization test",
            "metadata": {"source": "test"}
        }

        instance = Instance(
            instance_id="test_item_5",
            instance_data=instance_data
        )
        # Add metadata separately
        instance.add_metadata("source", "test")

        result = instance.to_dict()

        # Should not raise any exceptions
        json_str = json.dumps(result)
        assert isinstance(json_str, str)

        # Should be able to deserialize back
        deserialized = json.loads(json_str)
        assert deserialized["id"] == "test_item_5"

    def test_instance_to_dict_method_exists(self):
        """Test that to_dict() method exists on Instance class."""
        instance_data = {"id": "test_item_6", "text": "Method existence test"}

        instance = Instance(
            instance_id="test_item_6",
            instance_data=instance_data
        )

        # Should not raise AttributeError
        assert hasattr(instance, 'to_dict')
        assert callable(instance.to_dict)

        result = instance.to_dict()
        assert isinstance(result, dict)