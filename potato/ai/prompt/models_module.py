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


class SegmentationMask(BaseModel):
    """One pixel-level mask, in the RLE shape the client and exporters share.

    `rle` is Potato's own run-length form -- {"counts": [...], "size": [h, w]}
    -- deliberately NOT a base64 PNG or a polygon. It is what
    `cv_utils.normalize_annotation_object` already reads, so an accepted mask
    reaches every exporter with no conversion step to get wrong.
    """
    #: Must match a label in the schema config, or the accept path rejects it.
    label: str
    #: {"counts": [int, ...], "size": [height, width]}
    rle: dict
    confidence: Optional[float] = None


class VisualSegmentationFormat(BaseModel):
    """Segmentation results for an image.

    Example output:
    {
        "masks": [
            {"label": "road", "rle": {"counts": [0, 120, 45], "size": [480, 640]},
             "confidence": 0.94}
        ]
    }
    """
    masks: List[SegmentationMask]


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


class AnnotationCritiqueFormat(BaseModel):
    """A vision model's verdict on ONE annotated region.

    This is a judge output, not an annotation: nothing here becomes geometry.
    The model is shown a crop with the annotator's own outline drawn on it and
    asked whether the outlined thing matches its label and whether the outline
    fits. See :mod:`potato.ai.critique` for the parsing and confidence gating
    -- every field here is treated as advisory and re-validated, because open
    models return verdict strings and labels outside the allowed vocabulary
    often enough that trusting the schema alone would manufacture findings.

    Example output:
    {
        "verdict": "wrong_label",
        "suggested_label": "dog",
        "boundary": "tight",
        "confidence": 0.82,
        "rationale": "The outlined animal has a long snout and floppy ears."
    }
    """
    verdict: str
    suggested_label: Optional[str] = None
    boundary: Optional[str] = None
    confidence: float = 0.0
    rationale: Optional[str] = None


class MissedObjectEntry(BaseModel):
    """One object the model believes was left unannotated.

    ``bbox`` is normalized and approximate. Vision-language models localize
    poorly, so this is a hint about where to look, never an acceptable
    annotation -- accepting it would put a guessed coordinate in the dataset.
    """
    label: str
    bbox: Optional[BoundingBox] = None
    confidence: float = 0.0
    rationale: Optional[str] = None


class MissedObjectsFormat(BaseModel):
    """Whole-image "what did the annotator miss?" result.

    An empty list is the expected answer for careful work, and the prompt says
    so -- without that, models pad the list to look useful.
    """
    missed: List[MissedObjectEntry]


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

# ============================================================================
# Option Highlighting Output Format
# ============================================================================

class OptionHighlightFormat(BaseModel):
    """LLM response for option highlighting.

    Used to identify the most likely correct options for a discrete annotation task.
    The highlighted options are shown at full opacity while others are dimmed.

    Example output:
    {
        "highlighted_options": ["positive", "neutral"],
        "confidence": 0.85
    }
    """
    highlighted_options: List[str]  # Top-k most likely option names/values
    confidence: Optional[float] = None  # Optional overall confidence score (0-1)


CLASS_REGISTRY = {
    # Text annotation formats
    "default_hint": GeneralHintFormat,
    "default_keyword": GeneralKeywordFormat,
    "default_random": GeneralRandomFormat,  # Keep for backwards compatibility
    "default_rationale": GeneralRationaleFormat,

    # Option highlighting format
    "option_highlight": OptionHighlightFormat,

    # Visual annotation formats - Image
    "visual_detection": VisualDetectionFormat,
    "visual_segmentation": VisualSegmentationFormat,
    "visual_classification": VisualClassificationFormat,

    # Judge formats -- these critique annotations rather than producing them
    "annotation_critique": AnnotationCritiqueFormat,
    "missed_objects": MissedObjectsFormat,

    # Visual annotation formats - Video
    "video_scene_detection": VideoSceneDetectionFormat,
    "video_keyframe_detection": VideoKeyframeDetectionFormat,
    "video_tracking_suggestion": VideoTrackingSuggestionFormat,
    "multi_frame_detection": MultiFrameDetectionFormat,
}