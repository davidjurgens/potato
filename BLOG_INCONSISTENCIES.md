# Blog Post Inconsistencies Report

This document lists inconsistencies between the blog posts on potatoannotator.com and the actual Potato codebase. These issues need to be addressed by the blog authors.

---

## CRITICAL: Systemic Issues Across Multiple Posts

These errors appear in **many or all** blog posts and should be fixed globally:

### 1. Non-existent `server:` Configuration Block
**Appears in:** Nearly all blog posts
**Blog shows:**
```yaml
server:
  port: 8000
  host: 0.0.0.0
```
**Actual:** Port is set via CLI flag `-p 8000`, not in YAML config. There is no `server:` config section.

### 2. Wrong Data File Field Mapping
**Appears in:** Nearly all blog posts
**Blog shows:**
```yaml
data_files:
  - path: data/items.json
    text_field: text
    image_field: image_url
    audio_field: audio_path
```
**Actual:** Field mapping uses the `item_properties` section:
```yaml
data_files:
  - data/items.json

item_properties:
  id_key: id
  text_key: text
```

### 3. Wrong Task Name Key
**Appears in:** Many blog posts
**Blog shows:** `task_name: "My Task"`
**Actual:** `annotation_task_name: "My Task"`

### 4. Non-existent `output:` Configuration Block
**Appears in:** Many blog posts
**Blog shows:**
```yaml
output:
  path: annotations/
  format: jsonl
```
**Actual:**
```yaml
output_annotation_dir: annotation_output/
output_annotation_format: json  # or csv, tsv
```

### 5. Non-existent Top-Level `keyboard_shortcuts:` Block
**Appears in:** Many blog posts
**Blog shows:**
```yaml
keyboard_shortcuts:
  submit: "Enter"
  skip: "s"
  undo: "ctrl+z"
```
**Actual:** Keyboard shortcuts are configured per-annotation-scheme using `sequential_key_binding: true` or per-label `key_value`.

---

## Blog-Specific Issues

### introducing-potato-2-0

| Issue | Blog Shows | Actual |
|-------|------------|--------|
| AI config key | `ai_assistance:` | `ai_support:` |
| AI provider key | `provider: openai` | `endpoint_type: openai` |
| AI features list | `features: [suggestions, keyword_highlighting, quality_hints]` | `ai_config.include.all: true` |
| Active learning sampling | Claims "Uncertainty Sampling", "Diversity Sampling", "Custom Strategies" | Uses sklearn classifiers directly, not named strategies |

### video-frame-annotation

| Issue | Blog Shows | Actual |
|-------|------------|--------|
| Video config section | `video: enabled: true, display_width: 854` | Use `annotation_type: video_annotation` in annotation_schemes |
| Annotation type | `annotation_type: video_segments` | `annotation_type: video_annotation` |
| Thumbnail options | `show_thumbnail_strip: true, thumbnail_count: 10` | Not implemented |
| Bounding box interpolation | Claims interpolation support | Not implemented in video annotation |

### getting-started-5-minutes

| Issue | Blog Shows | Actual |
|-------|------------|--------|
| Server config | `server: port: 8000` | Use `-p 8000` CLI flag |
| Output path | `annotation_output/` hardcoded | Configurable via `output_annotation_dir` |

### image-classification-tutorial

| Issue | Blog Shows | Actual |
|-------|------------|--------|
| Image config section | `image: enabled: true, display_size: large, enable_zoom: true` | Use `annotation_type: image_annotation` in annotation_schemes |
| Layout option | `layout: side_by_side` | Not a config option |
| Batch annotation | `layout: grid, grid_size: [3, 3]` | Not implemented |

### bounding-box-annotation

| Issue | Blog Shows | Actual |
|-------|------------|--------|
| Annotation type | `annotation_type: bounding_box` | `annotation_type: image_annotation` with `tools: [bbox]` |
| Pre-annotation | `pre_annotation: enabled: true, field: predictions` | Not implemented as described |
| Grid snapping | `polygon_settings: snap_to_edge: true` | Not implemented |
| Validation rules | `validation: min_boxes: 1, min_size: 10` | Use `min_annotations` in annotation_schemes |

### audio-transcription-task

| Issue | Blog Shows | Actual |
|-------|------------|--------|
| Audio config section | `audio: enabled: true, display: waveform, waveform_color: "#6366F1"` | Use `annotation_type: audio_annotation` in annotation_schemes |
| Color customization | `waveform_color`, `progress_color` | Not configurable via YAML |
| Pre-fill transcripts | `pre_fill_from: asr_transcript` | Not implemented |

### llm-integration-guide

| Issue | Blog Shows | Actual |
|-------|------------|--------|
| Config key | `ai_assistance:` | `ai_support:` |
| Provider key | `provider: openai` | `endpoint_type: openai` |
| API key format | `api_key_env: OPENAI_API_KEY` | `api_key: "${OPENAI_API_KEY}"` |
| Google provider | `provider: google` | `endpoint_type: gemini` |
| Custom provider | `provider: custom, request_format: openai` | Not implemented |
| Privacy config | `privacy: local_only: true, anonymize: enabled: true` | Not implemented |
| Caching backend | `caching: backend: redis` | Only disk caching via `cache_config.disk_cache` |
| Rate limiting | `rate_limiting: requests_per_minute: 60` | Not implemented |
| Batching | `batching: batch_size: 10` | Not implemented |

### active-learning-efficiency

| Issue | Blog Shows | Actual |
|-------|------------|--------|
| Strategy option | `strategy: uncertainty_sampling` | No `strategy` field; uses classifier directly |
| Model config | `model: type: sklearn, name: logistic_regression` | Use `classifier_name: "sklearn.linear_model.LogisticRegression"` |
| Batch size | `batch_size: 10, initial_random: 100` | Use `max_instances_to_reorder`, `random_sample_percent` |
| Stopping criteria | `stopping_criteria: max_annotations: 2000, target_accuracy: 0.90` | Not implemented |
| API endpoints | `/api/active-learning/metrics`, `/retrain`, `/next-batch` | Not implemented |

### prolific-integration

| Issue | Blog Shows | Actual |
|-------|------------|--------|
| Platform config | `crowdsourcing: platform: prolific` | `login: type: url_direct` or `login: type: prolific` |
| Participant ID | `participant_id_param: PROLIFIC_PID` | `login: url_argument: PROLIFIC_PID` |
| User management | `user_management: create_on_first_visit: true` | Handled automatically |
| Flow stages | `crowdsourcing: flow: stages: [consent, instructions, training]` | Use `phases:` section |
| Bonuses | `crowdsourcing: bonuses: enabled: true, criteria: {...}` | Not implemented |

### building-ner-task

| Issue | Blog Shows | Actual |
|-------|------------|--------|
| Display config | `display: text_display: html, enable_tooltips: true` | Not a config section |
| Validation | `validation: min_annotations: 0` | Use `min_spans` in annotation scheme if available |
| Quality control | `quality_control: enable_overlap_check: true` | Not implemented |
| Pre-annotation | `pre_annotation: enabled: true, field: predicted_entities` | Not implemented as described |

### polygon-annotation-guide

| Issue | Blog Shows | Actual |
|-------|------------|--------|
| Annotation type | `annotation_type: polygon` | `annotation_type: image_annotation` with `tools: [polygon]` |
| Polygon settings | `polygon_settings: min_vertices: 3, auto_close_distance: 10` | Not a separate config section |
| SAM pre-annotation | Claims SAM integration | Not implemented |
| Instance segmentation | `instance_segmentation: enabled: true, assign_instance_ids: true` | Not implemented |

### speaker-diarization-annotation

| Issue | Blog Shows | Actual |
|-------|------------|--------|
| Audio config | `audio: enabled: true, display: waveform, enable_regions: true` | Use `annotation_type: audio_annotation` |
| Annotation type | `annotation_type: audio_segments` | `annotation_type: audio_annotation` |
| Overlap handling | `allow_overlap: true, overlap_settings: visual_style: striped` | Not implemented as described |
| Merge/split | `keyboard_shortcuts: merge_segments: "m", split_segment: "/"` | Not implemented |

### quality-control-strategies

| Issue | Blog Shows | Actual |
|-------|------------|--------|
| Entire section | `quality_control: attention_checks: {...}, gold_standards: {...}` | This comprehensive QC system does not exist |
| Attention checks | `attention_checks: frequency: 10, failure_handling: {...}` | Limited attention check support via surveyflow |
| Gold standards | `gold_standards: enabled: true, min_accuracy: 0.8` | Not implemented |
| Agreement metrics | `agreement: metrics: [cohens_kappa, fleiss_kappa]` | Not implemented in config |
| Pattern detection | `patterns: detect_alternating: true, detect_rapid_submit: true` | Not implemented |

### custom-html-templates

| Issue | Blog Shows | Actual |
|-------|------------|--------|
| Display config | `display: text_display: custom, custom_template: path` | Use `html_layout: "path/to/template.html"` |
| Custom CSS | `display: custom_css: templates/styles.css` | Not a config option |
| Security policy | `display: security: allow_inline_scripts: true` | Not implemented |
| Template vars | `display: template_vars: {custom_var: value}` | Not this format |
| JavaScript API | Claims `window.Potato.setAnnotation()`, `window.Potato.getAnnotations()` | This API does not exist |

### data-format-guide

| Issue | Blog Shows | Actual |
|-------|------------|--------|
| Field mapping | `data_files: [{path: x, id_field: id, text_field: text}]` | Use `item_properties` section |
| Pre-annotations | `pre_annotation: enabled: true, field: pre_annotations` | Not implemented as described |

### exporting-to-huggingface

| Issue | Blog Shows | Actual |
|-------|------------|--------|
| CLI command | `potato export --format huggingface` | This command does not exist |
| HuggingFace config | `output: huggingface: enabled: true, features: {...}` | Not implemented |
| Export splits | `splits: train: 0.8, validation: 0.1, test: 0.1` | Not implemented |

### keyword-highlighting-setup

| Issue | Blog Shows | Actual |
|-------|------------|--------|
| Highlighting config | `highlighting: enabled: true, keywords: [...]` | Use `ai_support` for AI-based highlighting or annotation scheme features |
| Regex patterns | `highlighting: patterns: [{pattern: "\\d+", color: "#FEF3C7"}]` | Not implemented |
| AI highlighting | `highlighting: ai: provider: openai` | AI highlighting uses `ai_support` config, not `highlighting` |

### sentiment-analysis-tutorial

| Issue | Blog Shows | Actual |
|-------|------------|--------|
| Display highlights | `display: highlight_urls: true, highlight_mentions: true` | Not a config section |
| Guidelines | `guidelines: labels: {Positive: "...", Negative: "..."}` | Not a config section |
| User management | `user_management: instances_per_annotator: 100` | Use `automatic_assignment` or assignment strategy |
| Inter-annotator | `inter_annotator: overlap_ratio: 0.2` | Not this config format |

### multi-object-tracking

| Issue | Blog Shows | Actual |
|-------|------------|--------|
| Annotation type | `annotation_type: mot_tracking` | Not implemented |
| Tracking config | `tracking: auto_increment_id: true, interpolation: linear` | Not implemented |
| Occlusion handling | `occlusion_handling: enabled: true, visibility_levels: [...]` | Not implemented |
| Frame attributes | `frame_attributes: [{name: pose, type: radio}]` | Not implemented |

### medical-imaging-annotation

| Issue | Blog Shows | Actual |
|-------|------------|--------|
| DICOM viewer | Claims DICOM viewer with multi-slice navigation | Not implemented |
| WSI support | Claims whole slide image support with zoom levels | Not implemented |
| Security config | `security: hipaa_mode: true, audit_logging: true` | Not implemented |

### label-studio-migration

| Issue | Blog Shows | Actual |
|-------|------------|--------|
| Migration script | Claims official migration support | No official migration tool |
| Quality control | Same issues as quality-control-strategies blog | Not implemented |

---

## Summary of Non-Existent Features Claimed in Blogs

The following features are described in blogs but **do not exist** in Potato:

1. **`potato export` CLI command** - No export functionality
2. **HuggingFace dataset export** - Not implemented
3. **`server:` YAML config block** - Port is CLI flag only
4. **`quality_control:` comprehensive system** - No attention checks, gold standards, agreement metrics as described
5. **`pre_annotation:` config for model predictions** - Not implemented as described
6. **`window.Potato` JavaScript API** - Does not exist
7. **Multi-object tracking (`mot_tracking`)** - Not implemented
8. **DICOM/medical imaging viewer** - Not implemented
9. **Whole slide image (WSI) support** - Not implemented
10. **Bounding box interpolation in video** - Not implemented
11. **SAM (Segment Anything) integration** - Not implemented
12. **Redis/memory caching for AI** - Only disk caching exists
13. **Rate limiting and batching for AI** - Not implemented
14. **Privacy/anonymization config** - Not implemented
15. **Stopping criteria for active learning** - Not implemented
16. **Bonus payment configuration** - Not implemented
17. **Pattern detection for quality control** - Not implemented

---

## Recommendations

### For Blog Authors:

1. **Use actual config key names** - Replace `ai_assistance` with `ai_support`, `task_name` with `annotation_task_name`, etc.

2. **Remove `server:` blocks** - Port configuration is via `-p` CLI flag only

3. **Fix data file mapping** - Use `item_properties` section instead of inline field names

4. **Remove non-existent features** - Either remove claims about features that don't exist, or mark them as "coming soon" / "proposed"

5. **Test all YAML examples** - Run each example against actual Potato to verify it works

6. **Link to actual documentation** - Reference the official docs at potato-annotation.readthedocs.io

### For Potato Development Team:

Consider which claimed features would be valuable to actually implement:
- HuggingFace export could be useful
- Comprehensive quality control system could be valuable
- Pre-annotation support would help with model-assisted labeling
