"""
Unit tests for visual AI endpoints.

Tests the visual endpoint implementations and output format parsing.
"""

import pytest
import json
from unittest.mock import MagicMock, patch, PropertyMock
import base64


class TestImageData:
    """Tests for the ImageData dataclass."""

    def test_create_url_image_data(self):
        """Test creating ImageData from URL."""
        from potato.ai.ai_endpoint import ImageData

        img_data = ImageData(
            source="url",
            data="https://example.com/image.jpg"
        )

        assert img_data.source == "url"
        assert img_data.data == "https://example.com/image.jpg"
        assert img_data.width is None
        assert img_data.height is None

    def test_create_base64_image_data(self):
        """Test creating ImageData from base64."""
        from potato.ai.ai_endpoint import ImageData

        img_data = ImageData(
            source="base64",
            data="SGVsbG8gV29ybGQ=",
            width=100,
            height=200,
            mime_type="image/jpeg"
        )

        assert img_data.source == "base64"
        assert img_data.width == 100
        assert img_data.height == 200
        assert img_data.mime_type == "image/jpeg"


class TestVisualAnnotationInput:
    """Tests for VisualAnnotationInput dataclass."""

    def test_create_visual_annotation_input(self):
        """Test creating VisualAnnotationInput."""
        from potato.ai.ai_endpoint import ImageData, VisualAnnotationInput

        img_data = ImageData(source="url", data="https://example.com/image.jpg")

        input_data = VisualAnnotationInput(
            ai_assistant="detection",
            annotation_type="image_annotation",
            task_type="detection",
            image_data=img_data,
            description="Detect objects",
            labels=["person", "car"],
            confidence_threshold=0.5
        )

        assert input_data.ai_assistant == "detection"
        assert input_data.annotation_type == "image_annotation"
        assert input_data.labels == ["person", "car"]
        assert input_data.confidence_threshold == 0.5

    def test_create_video_annotation_input(self):
        """Test creating VisualAnnotationInput for video."""
        from potato.ai.ai_endpoint import ImageData, VisualAnnotationInput

        frames = [
            ImageData(source="base64", data="frame1"),
            ImageData(source="base64", data="frame2"),
        ]

        input_data = VisualAnnotationInput(
            ai_assistant="scene_detection",
            annotation_type="video_annotation",
            task_type="scene_detection",
            image_data=frames,
            description="Detect scenes",
            labels=["intro", "action"],
            video_metadata={"fps": 30, "duration": 60}
        )

        assert len(input_data.image_data) == 2
        assert input_data.video_metadata["fps"] == 30
        assert input_data.video_metadata["duration"] == 60


class TestVisualOutputFormats:
    """Tests for visual output format Pydantic models."""

    def test_bounding_box_model(self):
        """Test BoundingBox model."""
        from potato.ai.prompt.models_module import BoundingBox

        bbox = BoundingBox(x=0.1, y=0.2, width=0.3, height=0.4)
        assert bbox.x == 0.1
        assert bbox.y == 0.2
        assert bbox.width == 0.3
        assert bbox.height == 0.4

    def test_detection_model(self):
        """Test Detection model."""
        from potato.ai.prompt.models_module import Detection, BoundingBox

        detection = Detection(
            label="person",
            bbox=BoundingBox(x=0.1, y=0.2, width=0.3, height=0.4),
            confidence=0.95
        )

        assert detection.label == "person"
        assert detection.confidence == 0.95
        assert detection.bbox.x == 0.1

    def test_visual_detection_format(self):
        """Test VisualDetectionFormat model."""
        from potato.ai.prompt.models_module import VisualDetectionFormat, Detection, BoundingBox

        result = VisualDetectionFormat(
            detections=[
                Detection(
                    label="car",
                    bbox=BoundingBox(x=0.1, y=0.2, width=0.3, height=0.2),
                    confidence=0.92
                ),
                Detection(
                    label="person",
                    bbox=BoundingBox(x=0.5, y=0.3, width=0.1, height=0.4),
                    confidence=0.87
                )
            ]
        )

        assert len(result.detections) == 2
        assert result.detections[0].label == "car"
        assert result.detections[1].label == "person"

    def test_visual_detection_from_json(self):
        """Test parsing VisualDetectionFormat from JSON."""
        from potato.ai.prompt.models_module import VisualDetectionFormat

        json_data = {
            "detections": [
                {
                    "label": "dog",
                    "bbox": {"x": 0.2, "y": 0.3, "width": 0.4, "height": 0.5},
                    "confidence": 0.88
                }
            ]
        }

        result = VisualDetectionFormat(**json_data)
        assert result.detections[0].label == "dog"
        assert result.detections[0].bbox.x == 0.2

    def test_video_segment_model(self):
        """Test VideoSegment model."""
        from potato.ai.prompt.models_module import VideoSegment

        segment = VideoSegment(
            start_time=0.0,
            end_time=5.5,
            suggested_label="intro",
            confidence=0.9,
            description="Opening scene"
        )

        assert segment.start_time == 0.0
        assert segment.end_time == 5.5
        assert segment.suggested_label == "intro"

    def test_video_scene_detection_format(self):
        """Test VideoSceneDetectionFormat model."""
        from potato.ai.prompt.models_module import VideoSceneDetectionFormat, VideoSegment

        result = VideoSceneDetectionFormat(
            segments=[
                VideoSegment(start_time=0.0, end_time=5.0, suggested_label="intro", confidence=0.9),
                VideoSegment(start_time=5.0, end_time=20.0, suggested_label="action", confidence=0.85),
            ]
        )

        assert len(result.segments) == 2
        assert result.segments[0].suggested_label == "intro"
        assert result.segments[1].start_time == 5.0

    def test_visual_classification_format(self):
        """Test VisualClassificationFormat model."""
        from potato.ai.prompt.models_module import VisualClassificationFormat

        result = VisualClassificationFormat(
            suggested_label="cat",
            confidence=0.89,
            reasoning="The image shows a feline with pointed ears"
        )

        assert result.suggested_label == "cat"
        assert result.confidence == 0.89
        assert "feline" in result.reasoning


class TestAnnotationTypeEnum:
    """Tests for the extended Annotation_Type enum."""

    def test_image_annotation_type_exists(self):
        """Test that IMAGE_ANNOTATION type exists."""
        from potato.ai.ai_endpoint import Annotation_Type

        assert hasattr(Annotation_Type, "IMAGE_ANNOTATION")
        assert Annotation_Type.IMAGE_ANNOTATION.value == "image_annotation"

    def test_video_annotation_type_exists(self):
        """Test that VIDEO_ANNOTATION type exists."""
        from potato.ai.ai_endpoint import Annotation_Type

        assert hasattr(Annotation_Type, "VIDEO_ANNOTATION")
        assert Annotation_Type.VIDEO_ANNOTATION.value == "video_annotation"


class TestClassRegistry:
    """Tests for the CLASS_REGISTRY with visual formats."""

    def test_visual_formats_registered(self):
        """Test that visual format classes are registered."""
        from potato.ai.prompt.models_module import CLASS_REGISTRY

        assert "visual_detection" in CLASS_REGISTRY
        assert "visual_classification" in CLASS_REGISTRY
        assert "video_scene_detection" in CLASS_REGISTRY
        assert "video_keyframe_detection" in CLASS_REGISTRY
        assert "video_tracking_suggestion" in CLASS_REGISTRY

    def test_model_manager_can_get_visual_formats(self):
        """Test that ModelManager can retrieve visual format classes directly from registry."""
        from potato.ai.prompt.models_module import CLASS_REGISTRY, VisualDetectionFormat

        # Test that we can get the class directly from the registry
        model_class = CLASS_REGISTRY.get("visual_detection")
        assert model_class == VisualDetectionFormat


class TestBaseVisualAIEndpoint:
    """Tests for BaseVisualAIEndpoint utilities."""

    def test_create_url_image_data_utility(self):
        """Test create_url_image_data static method."""
        from potato.ai.visual_ai_endpoint import BaseVisualAIEndpoint

        img_data = BaseVisualAIEndpoint.create_url_image_data("https://example.com/image.jpg")

        assert img_data.source == "url"
        assert img_data.data == "https://example.com/image.jpg"

    @patch('builtins.open', create=True)
    def test_encode_image_to_base64(self, mock_open):
        """Test encode_image_to_base64 static method."""
        from potato.ai.visual_ai_endpoint import BaseVisualAIEndpoint

        # Mock file content
        mock_open.return_value.__enter__.return_value.read.return_value = b"fake image data"

        with patch('mimetypes.guess_type', return_value=('image/jpeg', None)):
            # This would need PIL installed, so we'll mock it
            with patch('potato.ai.visual_ai_endpoint.Image', create=True):
                img_data = BaseVisualAIEndpoint.encode_image_to_base64("/path/to/image.jpg")

        assert img_data.source == "base64"
        assert img_data.mime_type == "image/jpeg"


class TestPromptTemplates:
    """Tests for visual annotation prompt templates."""

    def test_image_annotation_prompts_exist(self):
        """Test that image annotation prompts are loaded."""
        import os
        import json

        prompt_path = os.path.join(
            os.path.dirname(__file__),
            "../../potato/ai/prompt/image_annotation.json"
        )

        if os.path.exists(prompt_path):
            with open(prompt_path, 'r') as f:
                prompts = json.load(f)

            assert "detection" in prompts
            assert "pre_annotate" in prompts
            assert "hint" in prompts
            assert "prompt" in prompts["detection"]
            assert "output_format" in prompts["detection"]

    def test_video_annotation_prompts_exist(self):
        """Test that video annotation prompts are loaded."""
        import os
        import json

        prompt_path = os.path.join(
            os.path.dirname(__file__),
            "../../potato/ai/prompt/video_annotation.json"
        )

        if os.path.exists(prompt_path):
            with open(prompt_path, 'r') as f:
                prompts = json.load(f)

            assert "scene_detection" in prompts
            assert "hint" in prompts
            assert "prompt" in prompts["scene_detection"]


class TestEndpointFactory:
    """Tests for AIEndpointFactory with visual endpoints."""

    def test_visual_endpoints_can_be_registered(self):
        """Test that visual endpoints can be registered."""
        from potato.ai.ai_endpoint import AIEndpointFactory

        # Visual endpoints should be registered on import
        # We just verify the factory exists and has the register method
        assert hasattr(AIEndpointFactory, "register_endpoint")
        assert hasattr(AIEndpointFactory, "_endpoints")

    def test_yolo_endpoint_registration(self):
        """Test YOLO endpoint can be registered if available."""
        from potato.ai.ai_endpoint import AIEndpointFactory

        try:
            from potato.ai.yolo_endpoint import YOLOEndpoint
            AIEndpointFactory.register_endpoint("yolo_test", YOLOEndpoint)
            assert "yolo_test" in AIEndpointFactory._endpoints
        except ImportError:
            pytest.skip("ultralytics not installed")

    def test_ollama_vision_endpoint_registration(self):
        """Test Ollama Vision endpoint can be registered if available."""
        from potato.ai.ai_endpoint import AIEndpointFactory

        try:
            from potato.ai.ollama_vision_endpoint import OllamaVisionEndpoint
            AIEndpointFactory.register_endpoint("ollama_vision_test", OllamaVisionEndpoint)
            assert "ollama_vision_test" in AIEndpointFactory._endpoints
        except ImportError:
            pytest.skip("ollama not installed")


class TestYOLOEndpointMocked:
    """Tests for YOLOEndpoint with mocked YOLO."""

    def test_yolo_endpoint_initialization(self):
        """Test YOLO endpoint initializes correctly."""
        try:
            # Import ultralytics to check if available
            import ultralytics
        except ImportError:
            pytest.skip("ultralytics not installed")

        # Now mock YOLO and test
        with patch('ultralytics.YOLO') as mock_yolo:
            mock_model = MagicMock()
            mock_yolo.return_value = mock_model

            from potato.ai.yolo_endpoint import YOLOEndpoint

            config = {
                "ai_config": {
                    "model": "yolov8n.pt",
                    "confidence_threshold": 0.5
                }
            }

            endpoint = YOLOEndpoint(config)
            assert endpoint.confidence_threshold == 0.5

    def test_yolo_parse_prompt_for_labels(self):
        """Test YOLO label parsing from prompt."""
        try:
            import ultralytics
        except ImportError:
            pytest.skip("ultralytics not installed")

        from potato.ai.yolo_endpoint import YOLOEndpoint

        # Test without initialization - _parse_prompt_for_labels is a static-like method
        labels = YOLOEndpoint._parse_prompt_for_labels(None, "detect: person, car, dog")
        assert "person" in labels
        assert "car" in labels
        assert "dog" in labels

        labels = YOLOEndpoint._parse_prompt_for_labels(None, "labels: [cat, bird]")
        assert "cat" in labels
        assert "bird" in labels

        labels = YOLOEndpoint._parse_prompt_for_labels(None, "find person and car")
        assert "person" in labels
        assert "car" in labels


class TestOllamaVisionEndpointMocked:
    """Tests for OllamaVisionEndpoint with mocked client."""

    def test_ollama_vision_query_with_image(self):
        """Test Ollama Vision query with image."""
        try:
            import ollama
        except ImportError:
            pytest.skip("ollama not installed")

        # Mock ollama module
        with patch('ollama.Client') as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_client.list.return_value = {"models": []}
            mock_client.chat.return_value = {
                "message": {
                    "content": '{"detections": [{"label": "cat", "bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}, "confidence": 0.9}]}'
                }
            }

            from potato.ai.ollama_vision_endpoint import OllamaVisionEndpoint
            from potato.ai.ai_endpoint import ImageData
            from potato.ai.prompt.models_module import VisualDetectionFormat

            config = {
                "ai_config": {
                    "model": "llava:latest",
                    "max_tokens": 500
                }
            }

            endpoint = OllamaVisionEndpoint(config)

            img_data = ImageData(source="base64", data="SGVsbG8=")
            result = endpoint.query_with_image("detect objects", img_data, VisualDetectionFormat)

            assert "detections" in result or hasattr(result, "detections")


class TestCoordinateNormalization:
    """Tests for coordinate normalization in visual outputs."""

    def test_bbox_coordinates_normalized(self):
        """Test that bounding box coordinates are in 0-1 range."""
        from potato.ai.prompt.models_module import BoundingBox

        # Valid normalized coordinates
        bbox = BoundingBox(x=0.0, y=0.0, width=1.0, height=1.0)
        assert 0 <= bbox.x <= 1
        assert 0 <= bbox.y <= 1
        assert 0 <= bbox.width <= 1
        assert 0 <= bbox.height <= 1

    def test_detection_with_normalized_bbox(self):
        """Test detection with properly normalized bbox."""
        from potato.ai.prompt.models_module import Detection, BoundingBox

        # Simulate a detection from the AI
        detection = Detection(
            label="person",
            bbox=BoundingBox(x=0.25, y=0.1, width=0.15, height=0.6),
            confidence=0.92
        )

        # Verify coordinates
        assert 0 <= detection.bbox.x <= 1
        assert 0 <= detection.bbox.y <= 1
        assert 0 <= detection.bbox.x + detection.bbox.width <= 1
        assert 0 <= detection.bbox.y + detection.bbox.height <= 1
