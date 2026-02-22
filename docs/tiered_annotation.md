# Tiered Annotation (ELAN-style Hierarchical Annotation)

Tiered annotation provides a hierarchical multi-tier annotation interface for audio and video content. This schema is inspired by [ELAN](https://archive.mpi.nl/tla/elan), a widely-used tool for linguistic annotation, and supports parent-child relationships between annotation tiers.

## Overview

Use tiered annotation when you need to:

- Create hierarchical annotations (e.g., utterance → word → phoneme)
- Annotate at multiple levels of granularity simultaneously
- Maintain relationships between annotations at different levels
- Export to ELAN (EAF) or Praat (TextGrid) formats

## Quick Start

```yaml
annotation_schemes:
  - annotation_type: tiered_annotation
    name: linguistic_tiers
    description: "Multi-tier linguistic annotation"
    source_field: audio_url
    media_type: audio

    tiers:
      # Independent tier - directly time-aligned
      - name: utterance
        tier_type: independent
        labels:
          - name: Speaker_A
            color: "#4ECDC4"
          - name: Speaker_B
            color: "#FF6B6B"

      # Dependent tier - child of utterance
      - name: word
        tier_type: dependent
        parent_tier: utterance
        constraint_type: time_subdivision
        labels:
          - name: Word
            color: "#95E1D3"
```

## Configuration Reference

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `annotation_type` | string | Must be `"tiered_annotation"` |
| `name` | string | Unique schema identifier |
| `description` | string | Display description |
| `source_field` | string | Field name containing media URL |
| `tiers` | list | List of tier definitions |

### Optional Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `media_type` | string | `"audio"` | `"audio"` or `"video"` |
| `tier_height` | int | `50` | Height of each tier row in pixels |
| `show_tier_labels` | bool | `true` | Show tier name labels |
| `collapsed_tiers` | list | `[]` | Tier names to start collapsed |
| `zoom_enabled` | bool | `true` | Enable zoom controls |
| `playback_rate_control` | bool | `true` | Show playback speed controls |
| `overview_height` | int | `40` | Height of waveform overview |

### Tier Definition

Each tier in the `tiers` list can have:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique tier identifier |
| `tier_type` | string | No | `"independent"` (default) or `"dependent"` |
| `parent_tier` | string | For dependent | Name of parent tier |
| `constraint_type` | string | No | Constraint relationship (see below) |
| `description` | string | No | Tier description/tooltip |
| `labels` | list | No | Available annotation labels |
| `linguistic_type` | string | No | ELAN linguistic type (for export) |

### Label Definition

Each label can have:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Label text (required) |
| `color` | string | Hex color code (e.g., `"#4ECDC4"`) |
| `tooltip` | string | Hover tooltip text |
| `description` | string | Extended description |

## Constraint Types

Constraint types define how child annotations relate to their parent:

### `time_subdivision`

Children must partition the parent's time span with no gaps. Each child annotation starts where the previous one ends.

**Use case:** Word → phoneme segmentation where phonemes are contiguous

```yaml
- name: phoneme
  tier_type: dependent
  parent_tier: word
  constraint_type: time_subdivision
```

### `included_in`

Children must be within parent bounds but may have gaps between them.

**Use case:** Utterance → word where pauses between words are allowed

```yaml
- name: word
  tier_type: dependent
  parent_tier: utterance
  constraint_type: included_in
```

### `symbolic_association`

Children are linked to parent without independent time alignment. The child shares the parent's time span.

**Use case:** Glosses or translations that apply to the whole parent segment

```yaml
- name: translation
  tier_type: dependent
  parent_tier: utterance
  constraint_type: symbolic_association
```

### `symbolic_subdivision`

Children subdivide the parent symbolically (ordered but without explicit times).

**Use case:** Morpheme analysis where exact boundaries aren't needed

```yaml
- name: morpheme
  tier_type: dependent
  parent_tier: word
  constraint_type: symbolic_subdivision
```

## Complete Example

```yaml
annotation_schemes:
  - annotation_type: tiered_annotation
    name: discourse_annotation
    description: "Multi-level discourse annotation"
    source_field: audio_url
    media_type: audio

    tiers:
      # Level 1: Turn-taking
      - name: turn
        tier_type: independent
        description: "Speaker turns"
        labels:
          - name: Speaker_1
            color: "#4ECDC4"
            tooltip: "Primary speaker"
          - name: Speaker_2
            color: "#FF6B6B"
            tooltip: "Secondary speaker"
          - name: Overlap
            color: "#F39C12"
            tooltip: "Overlapping speech"

      # Level 2: Utterances within turns
      - name: utterance
        tier_type: dependent
        parent_tier: turn
        constraint_type: time_subdivision
        description: "Individual utterances"
        labels:
          - name: Statement
            color: "#95E1D3"
          - name: Question
            color: "#DDA0DD"
          - name: Backchannel
            color: "#87CEEB"

      # Level 3: Words within utterances
      - name: word
        tier_type: dependent
        parent_tier: utterance
        constraint_type: included_in
        description: "Word transcription"
        labels:
          - name: Word
            color: "#FFEAA7"

      # Independent tier for non-verbal
      - name: gesture
        tier_type: independent
        description: "Non-verbal gestures"
        labels:
          - name: Nod
            color: "#98D8C8"
          - name: Point
            color: "#C0C0C0"

    tier_height: 45
    show_tier_labels: true
    zoom_enabled: true
    playback_rate_control: true
```

## User Interface

### Timeline View

The annotation interface displays:

1. **Media Player**: Audio or video player at the top
2. **Tier Toolbar**: Active tier selector, label buttons, playback controls
3. **Timeline**: Multi-row display with one row per tier
4. **Annotation List**: Expandable list of all annotations

### Creating Annotations

1. Select the target tier from the dropdown
2. Select a label from the label buttons
3. Click and drag on the tier's timeline to create the annotation

For dependent tiers:
- You must first create a parent annotation
- Child annotations must satisfy the constraint type
- The system will validate and show errors for invalid placements

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Space` | Play/Pause |
| `,` | Step backward 0.1 seconds |
| `.` | Step forward 0.1 seconds |
| `Delete`/`Backspace` | Delete selected annotation |
| `Escape` | Deselect annotation |

### Selecting and Editing

- Click an annotation to select it
- The media will seek to the annotation's start time
- Use the annotation list panel to view all annotations
- Delete with keyboard or the delete button in the list

## Export Formats

### ELAN (EAF)

Export to ELAN Annotation Format for use in ELAN:

```bash
python -m potato.export --format eaf --input annotations.json --output ./eaf_output/
```

The EAF export:
- Preserves tier hierarchy and constraint types
- Generates valid EAF 3.0 XML
- Includes media file references
- Creates ELAN linguistic types

### Praat (TextGrid)

Export to Praat TextGrid format:

```bash
python -m potato.export --format textgrid --input annotations.json --output ./textgrid_output/
```

The TextGrid export:
- Creates interval tiers for each annotation tier
- Fills gaps with empty intervals
- Supports both long and short TextGrid formats

**Note:** TextGrid doesn't support hierarchical relationships, so the export flattens the structure while preserving all annotations.

## Instance Display Configuration

To display the media player, configure the instance display:

```yaml
instance_display:
  - field_name: audio_url
    display_type: audio
    label: "Audio"
```

For video:

```yaml
instance_display:
  - field_name: video_url
    display_type: video
    label: "Video"
```

## Data Format

### Input Data

```json
[
  {
    "id": "sample_001",
    "text": "Sample description",
    "audio_url": "https://example.com/audio.wav"
  }
]
```

### Output Format

Annotations are stored as JSON with tier-organized structure:

```json
{
  "annotations": {
    "utterance": [
      {
        "id": "ann_1234_a1",
        "tier": "utterance",
        "start_time": 1500,
        "end_time": 3200,
        "label": "Speaker_A",
        "color": "#4ECDC4"
      }
    ],
    "word": [
      {
        "id": "ann_1234_a2",
        "tier": "word",
        "start_time": 1500,
        "end_time": 2000,
        "label": "Content",
        "parent_id": "ann_1234_a1"
      }
    ]
  },
  "time_slots": {
    "ts1": 1500,
    "ts2": 2000,
    "ts3": 3200
  }
}
```

**Time values are in milliseconds.**

## Troubleshooting

### "No parent annotation covers this time range"

This error occurs when creating a dependent tier annotation outside any parent annotation. Solution:
1. Create a parent annotation first
2. Ensure the child annotation is within the parent's time bounds

### Waveform not displaying

The waveform visualization requires:
1. Peaks.js library (included automatically)
2. Web Audio API support in the browser
3. CORS-enabled media files for cross-origin resources

If the waveform doesn't load, the timeline will still work for annotation.

### Export issues

For EAF export, ensure:
- All tier names are valid identifiers (no special characters)
- Parent-child relationships are consistent

For TextGrid export:
- Overlapping annotations on the same tier will be merged or may cause issues
- Very small gaps between annotations may be filled

## Related Documentation

- [Audio Annotation](audio_annotation.md) - Single-tier audio annotation
- [Video Annotation](video_annotation.md) - Video annotation with segments
- [Export Formats](export_formats.md) - Available export formats
