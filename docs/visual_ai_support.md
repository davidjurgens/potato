# Visual AI Support for Image and Video Annotation

Potato provides AI-powered assistance for image and video annotation tasks using various vision models including YOLO for object detection and VLLMs (Vision-Language Models) like GPT-4o, Claude, and Ollama vision models.

## Overview

Visual AI support enables:

- **Object Detection**: Automatically detect and locate objects in images using YOLO or VLLMs
- **Pre-annotation**: Auto-detect all objects for human review
- **Classification**: Classify images or regions within images
- **Hints**: Get guidance without revealing exact locations
- **Scene Detection**: Identify temporal segments in videos
- **Keyframe Detection**: Find significant moments in videos
- **Object Tracking**: Track objects across video frames

## Supported Endpoints

### YOLO Endpoint
Best for fast, accurate object detection using local inference.

```yaml
ai_support:
  enabled: true
  endpoint_type: "yolo"
  ai_config:
    model: "yolov8m.pt"  # or yolov8n, yolov8l, yolov8x, yolo-world
    confidence_threshold: 0.5
    iou_threshold: 0.45
```

Supported models:
- YOLOv8 (n/s/m/l/x variants)
- YOLO-World (open-vocabulary detection)
- Custom trained models

### Ollama Vision Endpoint
For local vision-language model inference.

```yaml
ai_support:
  enabled: true
  endpoint_type: "ollama_vision"
  ai_config:
    model: "llava:latest"  # or llava-llama3, bakllava, llama3.2-vision, qwen2.5-vl
    base_url: "http://localhost:11434"
    max_tokens: 500
    temperature: 0.1
```

Supported models:
- LLaVA (7B, 13B, 34B)
- LLaVA-LLaMA3
- BakLLaVA
- Llama 3.2 Vision (11B, 90B)
- Qwen2.5-VL
- Moondream

### OpenAI Vision Endpoint
For cloud-based vision analysis using GPT-4o.

```yaml
ai_support:
  enabled: true
  endpoint_type: "openai_vision"
  ai_config:
    api_key: "${OPENAI_API_KEY}"
    model: "gpt-4o"  # or gpt-4o-mini
    max_tokens: 1000
    detail: "auto"  # low, high, or auto
```

### Anthropic Vision Endpoint
For Claude with vision capabilities.

```yaml
ai_support:
  enabled: true
  endpoint_type: "anthropic_vision"
  ai_config:
    api_key: "${ANTHROPIC_API_KEY}"
    model: "claude-sonnet-4-20250514"
    max_tokens: 1024
```

## Configuration

### Image Annotation with AI Support

```yaml
annotation_schemes:
  - annotation_type: image_annotation
    name: object_detection
    description: "Detect and label objects in the image"
    tools:
      - bbox
      - polygon
    labels:
      - name: "person"
        color: "#FF6B6B"
      - name: "car"
        color: "#4ECDC4"
      - name: "dog"
        color: "#45B7D1"

    # AI Support Configuration
    ai_support:
      enabled: true
      features:
        detection: true      # "Detect" button - find objects
        pre_annotate: true   # "Auto" button - detect all
        classification: false # "Classify" button - classify region
        hint: true           # "Hint" button - get guidance

# Global AI configuration
ai_support:
  enabled: true
  endpoint_type: "yolo"  # or ollama_vision, openai_vision, etc.
  ai_config:
    model: "yolov8m.pt"
    confidence_threshold: 0.5
```

### Video Annotation with AI Support

```yaml
annotation_schemes:
  - annotation_type: video_annotation
    name: scene_segmentation
    description: "Segment video into scenes"
    mode: segment
    labels:
      - name: "intro"
        color: "#4ECDC4"
      - name: "action"
        color: "#FF6B6B"
      - name: "outro"
        color: "#45B7D1"

    ai_support:
      enabled: true
      features:
        scene_detection: true     # Detect scene boundaries
        frame_classification: false
        keyframe_detection: false
        tracking: false
        pre_annotate: true        # Auto-segment entire video
        hint: true

ai_support:
  enabled: true
  endpoint_type: "ollama_vision"
  ai_config:
    model: "llava:latest"
    max_frames: 10  # Frames to sample for video analysis
```

### Using Different Endpoints for Visual and Text Tasks

You can configure a separate endpoint for visual tasks:

```yaml
ai_support:
  enabled: true
  endpoint_type: "openai"  # For text annotations
  ai_config:
    api_key: "${OPENAI_API_KEY}"
    model: "gpt-4o-mini"

  # Separate visual endpoint
  visual_endpoint_type: "yolo"
  visual_ai_config:
    model: "yolov8m.pt"
    confidence_threshold: 0.5
```

## AI Features

### Detection
Finds objects matching the configured labels and draws suggestion bounding boxes. Suggestions appear as dashed overlays that can be accepted or rejected.

### Pre-annotation (Auto)
Automatically detects all objects in the image/video and creates suggestions for human review. Useful for speeding up annotation of large datasets.

### Classification
Classifies a selected region or the entire image. Returns a suggested label with confidence score and reasoning.

### Hints
Provides guidance without revealing exact answers. Good for training annotators or when you want human judgment with AI assistance.

### Scene Detection (Video)
Analyzes video frames to identify scene boundaries and suggests temporal segments with labels.

### Keyframe Detection (Video)
Identifies significant moments in a video that would make good annotation points.

### Object Tracking (Video)
Suggests object positions across frames for consistent tracking annotation.

## Using AI Suggestions

1. Click the AI assistance button (Detect, Auto, Hint, etc.)
2. Wait for suggestions to appear as dashed overlays
3. **Accept a suggestion**: Double-click the suggestion overlay
4. **Reject a suggestion**: Right-click the suggestion overlay
5. **Accept all**: Click "Accept All" in the toolbar
6. **Clear all**: Click "Clear" to remove all suggestions

## Requirements

### For YOLO endpoint:
```bash
pip install ultralytics opencv-python
```

### For Ollama Vision:
1. Install Ollama: https://ollama.ai
2. Pull a vision model: `ollama pull llava`
3. Start Ollama server (runs on http://localhost:11434 by default)

### For OpenAI/Anthropic Vision:
- Set API key in environment or config
- Ensure you have access to vision-capable models

## Example Project

See `project-hub/simple_examples/configs/image-ai-detection.yaml` for a complete working example.

## Troubleshooting

### "No visual AI endpoint configured"
Ensure you have:
1. Set `ai_support.enabled: true`
2. Set a valid `endpoint_type` that supports vision (yolo, ollama_vision, openai_vision, anthropic_vision)
3. Installed required dependencies for your chosen endpoint

### "Could not find image URL"
The annotation system looks for image URLs in these fields:
- `image`, `image_url`, `img`, `url`, `path`, `src`
- Or in the `text` field if it's a valid image URL

Ensure your data files have the image URL in one of these fields.

### YOLO not detecting expected objects
- Try lowering `confidence_threshold`
- Ensure your labels match YOLO's class names (or use YOLO-World for custom vocabularies)
- Check that the model file exists and is valid

### Ollama Vision errors
- Verify Ollama is running: `curl http://localhost:11434/api/tags`
- Ensure you've pulled a vision model: `ollama list`
- Check model supports vision (llava, bakllava, llama3.2-vision, etc.)

## API Reference

### Get AI Suggestion
```http
GET /api/get_ai_suggestion?annotationId={id}&aiAssistant={type}
```

**Parameters:**
- `annotationId`: Index of the annotation scheme
- `aiAssistant`: Type of assistance (detection, pre_annotate, hint, scene_detection, etc.)

**Response:**
```json
{
  "detections": [
    {
      "label": "person",
      "bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.5},
      "confidence": 0.95
    }
  ]
}
```

For hints:
```json
{
  "hint": "Look for objects in the lower right corner",
  "suggestive_choice": "Focus on overlapping regions"
}
```

For video segments:
```json
{
  "segments": [
    {
      "start_time": 0.0,
      "end_time": 5.5,
      "suggested_label": "intro",
      "confidence": 0.85
    }
  ]
}
```
