"""
Unit tests for ModelCapabilities system.

Tests the capability declarations for AI endpoints and the supports_assistant() logic
that determines which AI assistants are available for different input types.
"""

import pytest
from potato.ai.ai_endpoint import ModelCapabilities


class TestModelCapabilitiesDataclass:
    """Tests for the ModelCapabilities dataclass."""

    def test_default_values(self):
        """Test that all capabilities default to False."""
        caps = ModelCapabilities()

        assert caps.text_generation is False
        assert caps.vision_input is False
        assert caps.bounding_box_output is False
        assert caps.text_classification is False
        assert caps.image_classification is False
        assert caps.rationale_generation is False
        assert caps.keyword_extraction is False

    def test_custom_values(self):
        """Test creating capabilities with custom values."""
        caps = ModelCapabilities(
            text_generation=True,
            vision_input=True,
            rationale_generation=True,
        )

        assert caps.text_generation is True
        assert caps.vision_input is True
        assert caps.rationale_generation is True
        assert caps.bounding_box_output is False  # Not set


class TestSupportsAssistantForText:
    """Tests for supports_assistant() with text input (has_image_input=False)."""

    def test_hint_requires_text_generation(self):
        """Hint assistant requires text_generation for text content."""
        caps_with = ModelCapabilities(text_generation=True)
        caps_without = ModelCapabilities(text_generation=False)

        assert caps_with.supports_assistant("hint", has_image_input=False) is True
        assert caps_without.supports_assistant("hint", has_image_input=False) is False

    def test_keyword_requires_keyword_extraction(self):
        """Keyword assistant requires keyword_extraction for text content."""
        caps_with = ModelCapabilities(keyword_extraction=True)
        caps_without = ModelCapabilities(keyword_extraction=False)

        assert caps_with.supports_assistant("keyword", has_image_input=False) is True
        assert caps_without.supports_assistant("keyword", has_image_input=False) is False

    def test_rationale_requires_rationale_generation(self):
        """Rationale assistant requires rationale_generation for text content."""
        caps_with = ModelCapabilities(rationale_generation=True)
        caps_without = ModelCapabilities(rationale_generation=False)

        assert caps_with.supports_assistant("rationale", has_image_input=False) is True
        assert caps_without.supports_assistant("rationale", has_image_input=False) is False

    def test_detection_requires_vision_and_bbox(self):
        """Detection assistant requires both vision_input and bounding_box_output."""
        # Even for text content, detection still requires vision
        caps_partial = ModelCapabilities(vision_input=True)
        caps_full = ModelCapabilities(vision_input=True, bounding_box_output=True)

        assert caps_partial.supports_assistant("detection", has_image_input=False) is False
        assert caps_full.supports_assistant("detection", has_image_input=False) is True

    def test_classification_requires_text_classification(self):
        """Classification assistant requires text_classification for text content."""
        caps_with = ModelCapabilities(text_classification=True)
        caps_without = ModelCapabilities(text_classification=False)

        assert caps_with.supports_assistant("classification", has_image_input=False) is True
        assert caps_without.supports_assistant("classification", has_image_input=False) is False


class TestSupportsAssistantForImages:
    """Tests for supports_assistant() with image input (has_image_input=True)."""

    def test_hint_requires_text_gen_and_vision(self):
        """Hint assistant requires both text_generation and vision_input for images."""
        caps_text_only = ModelCapabilities(text_generation=True)
        caps_vision_only = ModelCapabilities(vision_input=True)
        caps_both = ModelCapabilities(text_generation=True, vision_input=True)

        assert caps_text_only.supports_assistant("hint", has_image_input=True) is False
        assert caps_vision_only.supports_assistant("hint", has_image_input=True) is False
        assert caps_both.supports_assistant("hint", has_image_input=True) is True

    def test_keyword_disabled_for_images(self):
        """Keyword assistant should always be disabled for image content."""
        caps = ModelCapabilities(
            keyword_extraction=True,
            vision_input=True,
            text_generation=True,
        )

        # Even with all capabilities, keyword should not work for images
        assert caps.supports_assistant("keyword", has_image_input=True) is False

    def test_rationale_requires_rationale_gen_and_vision(self):
        """Rationale assistant requires both rationale_generation and vision_input for images."""
        caps_rationale_only = ModelCapabilities(rationale_generation=True)
        caps_vision_only = ModelCapabilities(vision_input=True)
        caps_both = ModelCapabilities(rationale_generation=True, vision_input=True)

        assert caps_rationale_only.supports_assistant("rationale", has_image_input=True) is False
        assert caps_vision_only.supports_assistant("rationale", has_image_input=True) is False
        assert caps_both.supports_assistant("rationale", has_image_input=True) is True

    def test_detection_requires_vision_and_bbox(self):
        """Detection assistant requires vision_input and bounding_box_output."""
        caps_bbox_only = ModelCapabilities(bounding_box_output=True)
        caps_vision_only = ModelCapabilities(vision_input=True)
        caps_both = ModelCapabilities(vision_input=True, bounding_box_output=True)

        assert caps_bbox_only.supports_assistant("detection", has_image_input=True) is False
        assert caps_vision_only.supports_assistant("detection", has_image_input=True) is False
        assert caps_both.supports_assistant("detection", has_image_input=True) is True

    def test_pre_annotate_same_as_detection(self):
        """Pre-annotate has same requirements as detection."""
        caps = ModelCapabilities(vision_input=True, bounding_box_output=True)

        assert caps.supports_assistant("pre_annotate", has_image_input=True) is True

    def test_classification_requires_image_classification_and_vision(self):
        """Classification assistant requires image_classification and vision_input for images."""
        caps_class_only = ModelCapabilities(image_classification=True)
        caps_vision_only = ModelCapabilities(vision_input=True)
        caps_both = ModelCapabilities(image_classification=True, vision_input=True)

        assert caps_class_only.supports_assistant("classification", has_image_input=True) is False
        assert caps_vision_only.supports_assistant("classification", has_image_input=True) is False
        assert caps_both.supports_assistant("classification", has_image_input=True) is True


class TestUnknownAssistantTypes:
    """Tests for unknown assistant type handling."""

    def test_unknown_assistant_returns_false(self):
        """Unknown assistant types should return False for safety."""
        caps = ModelCapabilities(
            text_generation=True,
            vision_input=True,
            bounding_box_output=True,
            text_classification=True,
            image_classification=True,
            rationale_generation=True,
            keyword_extraction=True,
        )

        assert caps.supports_assistant("unknown_type", has_image_input=False) is False
        assert caps.supports_assistant("", has_image_input=False) is False
        assert caps.supports_assistant("foo_bar", has_image_input=True) is False


class TestGetSupportedAssistants:
    """Tests for get_supported_assistants() method."""

    def test_text_model_supported_assistants(self):
        """Text-only model should support hint, keyword, rationale, classification."""
        caps = ModelCapabilities(
            text_generation=True,
            text_classification=True,
            rationale_generation=True,
            keyword_extraction=True,
        )

        supported = caps.get_supported_assistants(has_image_input=False)

        assert "hint" in supported
        assert "keyword" in supported
        assert "rationale" in supported
        assert "classification" in supported
        assert "detection" not in supported
        assert "pre_annotate" not in supported

    def test_vision_model_supported_assistants(self):
        """Vision model should support hint, rationale, classification for images."""
        caps = ModelCapabilities(
            text_generation=True,
            vision_input=True,
            image_classification=True,
            rationale_generation=True,
        )

        supported = caps.get_supported_assistants(has_image_input=True)

        assert "hint" in supported
        assert "rationale" in supported
        assert "classification" in supported
        assert "keyword" not in supported  # Never for images
        assert "detection" not in supported  # No bounding_box_output

    def test_yolo_model_supported_assistants(self):
        """YOLO model should only support detection-type assistants."""
        caps = ModelCapabilities(
            vision_input=True,
            bounding_box_output=True,
            image_classification=True,
        )

        supported = caps.get_supported_assistants(has_image_input=True)

        assert "detection" in supported
        assert "pre_annotate" in supported
        assert "hint" not in supported  # No text_generation
        assert "keyword" not in supported
        assert "rationale" not in supported


class TestEndpointCapabilities:
    """Tests for CAPABILITIES declarations on actual endpoint classes."""

    def test_ollama_endpoint_capabilities(self):
        """OllamaEndpoint should have text-only capabilities."""
        from potato.ai.ollama_endpoint import OllamaEndpoint

        caps = OllamaEndpoint.CAPABILITIES

        assert caps.text_generation is True
        assert caps.vision_input is False
        assert caps.bounding_box_output is False
        assert caps.keyword_extraction is True
        assert caps.rationale_generation is True

    def test_ollama_vision_endpoint_capabilities(self):
        """OllamaVisionEndpoint should have vision but no bbox capabilities."""
        from potato.ai.ollama_vision_endpoint import OllamaVisionEndpoint

        caps = OllamaVisionEndpoint.CAPABILITIES

        assert caps.text_generation is True
        assert caps.vision_input is True
        assert caps.bounding_box_output is False  # VLLMs don't do precise bbox
        assert caps.keyword_extraction is False  # Not for images
        assert caps.rationale_generation is True

    def test_yolo_endpoint_capabilities(self):
        """YOLOEndpoint should have bbox output but no text generation."""
        from potato.ai.yolo_endpoint import YOLOEndpoint

        caps = YOLOEndpoint.CAPABILITIES

        assert caps.text_generation is False
        assert caps.vision_input is True
        assert caps.bounding_box_output is True
        assert caps.keyword_extraction is False
        assert caps.rationale_generation is False

    def test_openai_endpoint_capabilities(self):
        """OpenAIEndpoint should have text-only capabilities."""
        from potato.ai.openai_endpoint import OpenAIEndpoint

        caps = OpenAIEndpoint.CAPABILITIES

        assert caps.text_generation is True
        assert caps.vision_input is False
        assert caps.keyword_extraction is True

    def test_openai_vision_endpoint_capabilities(self):
        """OpenAIVisionEndpoint should have vision but approximate bbox."""
        from potato.ai.openai_vision_endpoint import OpenAIVisionEndpoint

        caps = OpenAIVisionEndpoint.CAPABILITIES

        assert caps.text_generation is True
        assert caps.vision_input is True
        assert caps.bounding_box_output is False  # GPT-4V bbox is approximate
        assert caps.rationale_generation is True

    def test_anthropic_endpoint_capabilities(self):
        """AnthropicEndpoint should have text-only capabilities."""
        pytest.importorskip("anthropic")
        from potato.ai.anthropic_endpoint import AnthropicEndpoint

        caps = AnthropicEndpoint.CAPABILITIES

        assert caps.text_generation is True
        assert caps.vision_input is False
        assert caps.keyword_extraction is True

    def test_anthropic_vision_endpoint_capabilities(self):
        """AnthropicVisionEndpoint should have vision capabilities."""
        pytest.importorskip("anthropic")
        from potato.ai.anthropic_vision_endpoint import AnthropicVisionEndpoint

        caps = AnthropicVisionEndpoint.CAPABILITIES

        assert caps.text_generation is True
        assert caps.vision_input is True
        assert caps.bounding_box_output is False
        assert caps.rationale_generation is True


class TestCapabilityMatrix:
    """Tests that verify the complete capability matrix as documented."""

    @pytest.mark.parametrize("assistant_type,text_expected,image_vllm_expected,image_yolo_expected", [
        ("hint", True, True, False),
        ("keyword", True, False, False),
        ("rationale", True, True, False),
        ("detection", False, False, True),
        ("pre_annotate", False, False, True),
    ])
    def test_capability_matrix(
        self, assistant_type, text_expected, image_vllm_expected, image_yolo_expected
    ):
        """Test the full capability matrix from the plan."""
        # Text-only model (like OllamaEndpoint)
        text_caps = ModelCapabilities(
            text_generation=True,
            text_classification=True,
            rationale_generation=True,
            keyword_extraction=True,
        )

        # VLLM model (like OllamaVisionEndpoint)
        vllm_caps = ModelCapabilities(
            text_generation=True,
            vision_input=True,
            image_classification=True,
            rationale_generation=True,
        )

        # YOLO model
        yolo_caps = ModelCapabilities(
            vision_input=True,
            bounding_box_output=True,
            image_classification=True,
        )

        # Text input
        assert text_caps.supports_assistant(assistant_type, has_image_input=False) == text_expected, \
            f"{assistant_type} for text input"

        # Image input with VLLM
        assert vllm_caps.supports_assistant(assistant_type, has_image_input=True) == image_vllm_expected, \
            f"{assistant_type} for image with VLLM"

        # Image input with YOLO
        assert yolo_caps.supports_assistant(assistant_type, has_image_input=True) == image_yolo_expected, \
            f"{assistant_type} for image with YOLO"
