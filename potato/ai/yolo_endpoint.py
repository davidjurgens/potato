"""
YOLO AI Endpoint for Object Detection

This module provides integration with YOLO models (via ultralytics) for
local object detection inference. Supports YOLOv8 and YOLO-World models.
"""

import base64
import logging
import os
import tempfile
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from .ai_endpoint import AIEndpointRequestError, ImageData, VisualAnnotationInput, ModelCapabilities
from .visual_ai_endpoint import BaseVisualAIEndpoint

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "yolov8m.pt"


class YOLOEndpoint(BaseVisualAIEndpoint):
    """
    YOLO endpoint for object detection using ultralytics.

    Supports:
    - YOLOv8 models (yolov8n, yolov8s, yolov8m, yolov8l, yolov8x)
    - YOLO-World models for open-vocabulary detection
    - Custom trained models

    Configuration options:
    - model: Model name or path (default: yolov8m.pt)
    - confidence_threshold: Minimum detection confidence (default: 0.5)
    - iou_threshold: IOU threshold for NMS (default: 0.45)
    - device: Device to run on (default: auto - uses GPU if available)
    - classes: List of class indices to detect (optional)
    """

    # Capabilities declaration for YOLO detection models
    # YOLO excels at object detection with precise bounding boxes but cannot generate text
    CAPABILITIES = ModelCapabilities(
        text_generation=False,  # YOLO doesn't generate text
        vision_input=True,
        bounding_box_output=True,  # YOLO's primary strength
        text_classification=False,
        image_classification=True,  # Can classify detected objects
        rationale_generation=False,  # Cannot explain reasoning
        keyword_extraction=False,  # Not applicable
    )

    def _initialize_client(self) -> None:
        """Initialize the YOLO model."""
        try:
            from ultralytics import YOLO
        except ImportError:
            raise AIEndpointRequestError(
                "ultralytics is required for YOLO detection. "
                "Install it with: pip install ultralytics"
            )

        model_name = self.model
        self.confidence_threshold = self.ai_config.get("confidence_threshold", 0.5)
        self.iou_threshold = self.ai_config.get("iou_threshold", 0.45)
        self.device = self.ai_config.get("device", None)  # None = auto-detect
        self.classes = self.ai_config.get("classes", None)  # None = all classes

        # YOLO-World specific: custom vocabulary
        self.custom_classes = self.ai_config.get("custom_classes", None)

        try:
            logger.info(f"Loading YOLO model: {model_name}")
            self.yolo_model = YOLO(model_name)

            # Set custom classes for YOLO-World models
            if self.custom_classes and hasattr(self.yolo_model, "set_classes"):
                logger.info(f"Setting custom classes: {self.custom_classes}")
                self.yolo_model.set_classes(self.custom_classes)

            logger.info(f"YOLO model loaded successfully")

        except Exception as e:
            raise AIEndpointRequestError(f"Failed to load YOLO model: {e}")

    def _get_default_model(self) -> str:
        """Get the default YOLO model."""
        return DEFAULT_MODEL

    def query(self, prompt: str, output_format: Type[BaseModel]) -> Any:
        """
        Standard query method - not typically used for YOLO.

        YOLO doesn't process text prompts in the traditional sense.
        Use query_with_image() instead.
        """
        logger.warning("YOLO endpoint doesn't support text-only queries. Use query_with_image().")
        return {"error": "YOLO requires image input. Use query_with_image() instead."}

    def query_with_image(
        self,
        prompt: str,
        image_data: Union[ImageData, List[ImageData]],
        output_format: Type[BaseModel]
    ) -> Any:
        """
        Run YOLO detection on image(s).

        Args:
            prompt: Text description (used for filtering labels if provided)
            image_data: Single ImageData or list of ImageData
            output_format: Pydantic model for output (typically VisualDetectionFormat)

        Returns:
            Detection results with normalized bounding boxes

        Raises:
            AIEndpointRequestError: If detection fails
        """
        try:
            # Handle single image or list
            images = [image_data] if isinstance(image_data, ImageData) else image_data

            all_detections = []

            for idx, img_data in enumerate(images):
                detections = self._detect_single_image(img_data, prompt)
                all_detections.append({
                    "frame_index": idx,
                    "detections": detections
                })

            # If single image, return flat detections
            if len(images) == 1:
                return {"detections": all_detections[0]["detections"]}

            # For multiple images (video frames), return per-frame results
            return {"frames": all_detections}

        except AIEndpointRequestError:
            raise
        except Exception as e:
            logger.error(f"YOLO detection failed: {e}")
            raise AIEndpointRequestError(f"YOLO detection failed: {e}")

    def _detect_single_image(self, image_data: ImageData, prompt: str = "") -> List[Dict[str, Any]]:
        """
        Run detection on a single image.

        Args:
            image_data: ImageData to process
            prompt: Optional text for label filtering

        Returns:
            List of detection dictionaries
        """
        import numpy as np

        # Convert image data to format YOLO can process
        img = self._prepare_image(image_data)

        # Parse prompt for label filtering
        filter_labels = self._parse_prompt_for_labels(prompt)
        logger.debug(f"Filter labels from prompt: {filter_labels}")

        # Run inference
        logger.debug(f"Running YOLO inference with conf={self.confidence_threshold}, iou={self.iou_threshold}")
        results = self.yolo_model(
            img,
            conf=self.confidence_threshold,
            iou=self.iou_threshold,
            device=self.device,
            classes=self.classes,
            verbose=False
        )

        detections = []

        for result in results:
            if result.boxes is None:
                logger.debug("No boxes in result")
                continue

            boxes = result.boxes
            img_height, img_width = result.orig_shape
            logger.debug(f"Image size: {img_width}x{img_height}, found {len(boxes)} boxes")

            for i in range(len(boxes)):
                # Get box coordinates (xyxy format)
                box = boxes.xyxy[i].cpu().numpy()
                confidence = float(boxes.conf[i].cpu().numpy())
                class_id = int(boxes.cls[i].cpu().numpy())

                # Get class name
                class_name = result.names.get(class_id, f"class_{class_id}")
                logger.debug(f"Detection {i}: class={class_name}, conf={confidence:.3f}")

                # Filter by label if specified
                if filter_labels and class_name.lower() not in [l.lower() for l in filter_labels]:
                    logger.debug(f"  -> Filtered out (not in {filter_labels})")
                    continue

                # Normalize coordinates to 0-1 range
                x1, y1, x2, y2 = box
                normalized_box = {
                    "x": float(x1 / img_width),
                    "y": float(y1 / img_height),
                    "width": float((x2 - x1) / img_width),
                    "height": float((y2 - y1) / img_height)
                }

                detections.append({
                    "label": class_name,
                    "bbox": normalized_box,
                    "confidence": round(confidence, 4)
                })

        return detections

    def _prepare_image(self, image_data: ImageData) -> Any:
        """
        Prepare image data for YOLO processing.

        Args:
            image_data: ImageData object

        Returns:
            Image in format suitable for YOLO (numpy array or PIL Image)
        """
        try:
            from PIL import Image
            import io
        except ImportError:
            raise AIEndpointRequestError("PIL is required for image processing")

        if image_data.source == "base64":
            # Decode base64 to PIL Image
            img_bytes = base64.b64decode(image_data.data)
            img = Image.open(io.BytesIO(img_bytes))
            return img

        elif image_data.source == "url":
            # Download and convert to PIL Image
            import requests
            response = requests.get(image_data.data, timeout=30)
            response.raise_for_status()
            img = Image.open(io.BytesIO(response.content))
            return img

        else:
            raise AIEndpointRequestError(f"Unknown image source type: {image_data.source}")

    def _parse_prompt_for_labels(self, prompt: str) -> List[str]:
        """
        Extract label names from prompt for filtering.

        Looks for patterns like:
        - "Labels to detect: person, car, dog"
        - "Available labels: person, car, dog"
        - "detect: person, car, dog"
        - "labels: [person, car]"

        Args:
            prompt: Text prompt

        Returns:
            List of label names to filter by (empty for no filtering)
        """
        if not prompt:
            return []

        # Look for explicit label specifications
        import re

        # Pattern: "Labels to detect: label1, label2" or "Available labels: label1, label2"
        # Must match the full phrase to avoid matching "Detect objects..."
        match = re.search(r"(?:labels to detect|available labels|labels)[:\s]+([^\n]+)", prompt, re.IGNORECASE)
        if match:
            labels_str = match.group(1)
            # Clean up and split - handle comma-separated, possibly with "..."
            labels_str = labels_str.replace("[", "").replace("]", "").replace("...", "")
            # Split by comma and clean up
            labels = [l.strip() for l in labels_str.split(",")]
            # Filter out empty strings and common non-label words
            stop_words = {'any', 'objects', 'in', 'this', 'image', 'that', 'match', 'the', 'specified', ''}
            labels = [l for l in labels if l.lower() not in stop_words and l]
            logger.debug(f"Parsed labels from prompt: {labels}")
            return labels

        return []

    def set_custom_classes(self, classes: List[str]) -> None:
        """
        Set custom classes for YOLO-World models.

        Args:
            classes: List of class names to detect
        """
        if hasattr(self.yolo_model, "set_classes"):
            self.yolo_model.set_classes(classes)
            self.custom_classes = classes
            logger.info(f"Updated YOLO-World classes: {classes}")
        else:
            logger.warning("Model does not support custom classes (not YOLO-World)")

    def detect(
        self,
        image_path_or_data: Union[str, ImageData],
        confidence_threshold: Optional[float] = None,
        labels: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Convenience method for direct detection.

        Args:
            image_path_or_data: Path to image file or ImageData
            confidence_threshold: Override default confidence threshold
            labels: Labels to filter by

        Returns:
            List of detections
        """
        # Prepare image data
        if isinstance(image_path_or_data, str):
            if image_path_or_data.startswith(("http://", "https://")):
                image_data = self.create_url_image_data(image_path_or_data)
            else:
                image_data = self.encode_image_to_base64(image_path_or_data)
        else:
            image_data = image_path_or_data

        # Temporarily override confidence if specified
        original_conf = self.confidence_threshold
        if confidence_threshold is not None:
            self.confidence_threshold = confidence_threshold

        try:
            prompt = f"detect: {', '.join(labels)}" if labels else ""
            return self._detect_single_image(image_data, prompt)
        finally:
            self.confidence_threshold = original_conf

    def health_check(self) -> bool:
        """
        Check if the YOLO model is loaded and working.

        Returns:
            True if model is ready, False otherwise
        """
        try:
            # Create a small test image
            import numpy as np
            test_img = np.zeros((100, 100, 3), dtype=np.uint8)

            # Run inference
            self.yolo_model(test_img, verbose=False)
            return True
        except Exception as e:
            logger.error(f"YOLO health check failed: {e}")
            return False
