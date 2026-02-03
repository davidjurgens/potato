from typing import Optional, Type, Union, Dict, List
from pydantic import BaseModel


class GeneralHintFormat(BaseModel):
    hint: str
    suggestive_choice: Union[str, int]


class LabelKeywords(BaseModel):
    """Keywords/phrases associated with a specific label."""
    label: str
    keywords: List[str]


class GeneralKeywordFormat(BaseModel):
    """Simplified keyword format: list of label -> keywords mappings.

    Example output:
    {
        "label_keywords": [
            {"label": "positive", "keywords": ["great", "love it", "excellent"]},
            {"label": "negative", "keywords": ["terrible", "awful"]}
        ]
    }
    """
    label_keywords: List[LabelKeywords]


class GeneralRandomFormat(BaseModel):
    """Deprecated: Use GeneralRationaleFormat instead."""
    random: str


class LabelRationale(BaseModel):
    """Rationale/reasoning for why a specific label might apply."""
    label: str
    reasoning: str


class GeneralRationaleFormat(BaseModel):
    """Rationale format: explanations for how each label might apply to the text.

    Example output:
    {
        "rationales": [
            {"label": "positive", "reasoning": "The phrase 'excellent quality' suggests satisfaction"},
            {"label": "negative", "reasoning": "The mention of 'delayed shipping' indicates frustration"}
        ]
    }
    """
    rationales: List[LabelRationale]


# ============================================================================
# Visual Annotation Output Formats
# ============================================================================

class BoundingBox(BaseModel):
    """Normalized bounding box coordinates (0-1 range).

    x, y: top-left corner position
    width, height: box dimensions
    All values are normalized to image dimensions (0-1).
    """
    x: float
    y: float
    width: float
    height: float


class Detection(BaseModel):
    """Single object detection result.

    Example:
    {
        "label": "person",
        "bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.5},
        "confidence": 0.95
    }
    """
    label: str
    bbox: BoundingBox
    confidence: float


class VisualDetectionFormat(BaseModel):
    """Object detection results for an image.

    Example output:
    {
        "detections": [
            {"label": "car", "bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.2}, "confidence": 0.92},
            {"label": "person", "bbox": {"x": 0.5, "y": 0.3, "width": 0.1, "height": 0.4}, "confidence": 0.87}
        ]
    }
    """
    detections: List[Detection]


class VisualClassificationFormat(BaseModel):
    """Classification result for an image or region.

    Example output:
    {
        "suggested_label": "cat",
        "confidence": 0.89,
        "reasoning": "The image shows a feline with pointed ears and whiskers"
    }
    """
    suggested_label: str
    confidence: float
    reasoning: Optional[str] = None


class VideoSegment(BaseModel):
    """Temporal segment in a video.

    Times are in seconds.
    """
    start_time: float
    end_time: float
    suggested_label: str
    confidence: float
    description: Optional[str] = None


class VideoSceneDetectionFormat(BaseModel):
    """Scene/segment detection results for a video.

    Example output:
    {
        "segments": [
            {"start_time": 0.0, "end_time": 5.5, "suggested_label": "intro", "confidence": 0.9},
            {"start_time": 5.5, "end_time": 15.0, "suggested_label": "action", "confidence": 0.85}
        ]
    }
    """
    segments: List[VideoSegment]


class VideoKeyframe(BaseModel):
    """Keyframe annotation for a video.

    timestamp: Time in seconds
    """
    timestamp: float
    suggested_label: str
    confidence: float
    reason: Optional[str] = None


class VideoKeyframeDetectionFormat(BaseModel):
    """Keyframe detection results for a video.

    Example output:
    {
        "keyframes": [
            {"timestamp": 2.5, "suggested_label": "scene_change", "confidence": 0.95, "reason": "Major visual transition"},
            {"timestamp": 8.0, "suggested_label": "action_peak", "confidence": 0.82, "reason": "Key moment in action"}
        ]
    }
    """
    keyframes: List[VideoKeyframe]


class TrackPosition(BaseModel):
    """Object position in a single frame for tracking."""
    frame_index: int
    bbox: BoundingBox
    confidence: float


class ObjectTrack(BaseModel):
    """Tracked object across multiple frames."""
    track_id: int
    label: str
    positions: List[TrackPosition]


class VideoTrackingSuggestionFormat(BaseModel):
    """Object tracking suggestions for a video.

    Example output:
    {
        "tracks": [
            {
                "track_id": 1,
                "label": "person",
                "positions": [
                    {"frame_index": 0, "bbox": {"x": 0.1, "y": 0.2, "width": 0.15, "height": 0.3}, "confidence": 0.9},
                    {"frame_index": 1, "bbox": {"x": 0.12, "y": 0.22, "width": 0.15, "height": 0.3}, "confidence": 0.88}
                ]
            }
        ]
    }
    """
    tracks: List[ObjectTrack]


class FrameDetections(BaseModel):
    """Detections for a single video frame."""
    frame_index: int
    detections: List[Detection]


class MultiFrameDetectionFormat(BaseModel):
    """Detection results across multiple video frames.

    Used when running detection on sampled video frames.
    """
    frames: List[FrameDetections]


# ============================================================================
# Class Registry
# ============================================================================

CLASS_REGISTRY = {
    # Text annotation formats
    "default_hint": GeneralHintFormat,
    "default_keyword": GeneralKeywordFormat,
    "default_random": GeneralRandomFormat,  # Keep for backwards compatibility
    "default_rationale": GeneralRationaleFormat,

    # Visual annotation formats - Image
    "visual_detection": VisualDetectionFormat,
    "visual_classification": VisualClassificationFormat,

    # Visual annotation formats - Video
    "video_scene_detection": VideoSceneDetectionFormat,
    "video_keyframe_detection": VideoKeyframeDetectionFormat,
    "video_tracking_suggestion": VideoTrackingSuggestionFormat,
    "multi_frame_detection": MultiFrameDetectionFormat,
}