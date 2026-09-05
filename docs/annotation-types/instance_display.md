# Instance Display Configuration

Instance display separates **what content to show annotators** from **what annotations to collect**, so any combination of content types (images, videos, audio, text) can sit alongside any annotation schemes (radio buttons, checkboxes, spans, and the rest).

## Why Use Instance Display?

To show an image and classify it with radio buttons, declare the image under `instance_display` and the question under `annotation_schemes`. The `image_annotation` schema is for drawing on an image, not for displaying one.

With `instance_display`, you can explicitly configure what content to display:

```yaml
# OLD (deprecated workaround)
annotation_schemes:
  - annotation_type: image_annotation
    name: image_display
    min_annotations: 0  # Just to show the image
    tools: [bbox]
    labels: [unused]
  - annotation_type: radio
    name: category
    labels: [A, B, C]

# NEW (recommended)
instance_display:
  fields:
    - key: image_url
      type: image

annotation_schemes:
  - annotation_type: radio
    name: category
    labels: [A, B, C]
```

## Basic Configuration

Add an `instance_display` section to your YAML configuration:

```yaml
instance_display:
  fields:
    - key: "image_url"           # Field name in your data JSON
      type: "image"              # Content type
      label: "Image to classify" # Optional header
      display_options:
        max_width: 600
        zoomable: true

  layout:
    direction: "vertical"        # vertical or horizontal
    gap: "20px"
```

A display's own options may also be written at the field's top level, which is
how `describe_display_type` lists them:

```yaml
    - key: "image_url"
      type: "image"
      max_width: 600
      zoomable: true
```

Only options the display declares are read this way, so an unrelated key is
still ignored. When an option appears in both places, `display_options` wins.

## Supported Display Types

| Type | Description | Span Target |
|------|-------------|-------------|
| `text` | Plain text content | Yes |
| `html` | Sanitized HTML content | No |
| `image` | Image display with zoom | No |
| `video` | Video player | No |
| `audio` | Audio player | No |
| `audio_dialogue` | **Diarized transcript synced to audio**: speaker bubbles, per-turn playback, per-turn ratings, spans, cross-turn linking | Yes |
| `gallery` | Scrollable image gallery with captions | No |
| `depth_map` | **Depth map**: near/far window, colormap, overlay on RGB, and the distance in metres under the cursor | No |
| `dialogue` | Conversation turns | Yes |
| `conversation_tree` | Conversation tree with collapsible branching nodes | No |
| `multi_agent_discussion` | Multi-agent discussion with agent legend, colors, addressees, and filtering | Yes |
| `interactive_chat` | Interactive agent chat with post-interaction trace display | Yes |
| `pairwise` | Side-by-side comparison | No |
| `code` | Syntax-highlighted source code | Yes |
| `spreadsheet` | Tabular data (Excel/CSV) | Yes (row/cell) |
| `document` | Rich documents (Word, Markdown, HTML) | Yes |
| `pdf` | PDF documents with page controls | Yes |
| `agent_trace` | Agent trace as vertical step cards (Thought/Action/Observation) | No |
| `coding_trace` | Coding agent trace with diffs, terminal blocks, file tree | Yes |
| `eval_trace` | One trace split into three panes: reasoning \| function calls \| final answer | Yes |
| `cot_trace` | Long chain-of-thought trace: step cards with a sticky progress rail for process-reward verification | No |
| `web_agent_trace` | Web agent trace with screenshots, SVG click/scroll overlays, step navigation | No |
| `live_agent` | Live AI agent viewer with real-time screenshots and intervention controls | No |
| `live_coding_agent` | Live coding agent viewer with real-time streaming and intervention controls | No |

For speech and dialogue over audio, see [Audio Dialogue](multimedia/audio_dialogue.md) and [Transcript Format Support](multimedia/transcript_formats.md). For detailed configuration of document formats (`code`, `spreadsheet`, `document`, `pdf`), see the [Extended Format Support](format_support.md) guide. For agent-trace displays (`agent_trace`, `coding_trace`, `eval_trace`, `cot_trace`, `web_agent_trace`, `live_agent`, `live_coding_agent`), see the [Agent Evaluation](../agent-evaluation/agent_traces.md) guides — `eval_trace` has its own [three-pane eval guide](../agent-evaluation/eval_trace.md).

## Display Type Options

The sections below cover the options authors reach for most often. They are not
the whole set — `pdf` alone takes twenty-two. The registry is the complete list,
and it is generated from the renderers, so it cannot fall behind them:

```python
from potato.server_utils.displays.registry import display_registry

for display in display_registry.list_displays():
    print(display["name"], sorted(display["optional_fields"]))
```

An option name Potato does not recognise is now a configuration error rather
than a silently ignored key, and the message suggests the nearest real one:

```
instance_display.fields[0].display_options.speeker_key is not an option for
display type 'multi_agent_discussion', so it would be ignored silently.
Did you mean 'speaker_key'? Accepted options: ...
```

That check found four dead keys in Potato's own example configs, so it is worth
running `potato validate` over an existing project after upgrading.

### Text Display

```yaml
- key: "text"
  type: "text"
  label: "Document"
  display_options:
    collapsible: false           # Make content collapsible
    collapsed_by_default: false  # Start collapsed (needs collapsible)
    max_height: 400              # Max height in pixels before scrolling
    preserve_whitespace: true    # Preserve line breaks and spacing
```

`collapsed_by_default` keeps a long case file out of the way until the annotator
asks for it, rather than pushing the questions down the page on every item.

### Image Display

```yaml
- key: "image_url"
  type: "image"
  label: "Image"
  display_options:
    max_width: 800            # Max width (number or CSS string)
    max_height: 600           # Max height
    zoomable: true            # Enable zoom controls
    alt_text: "Description"   # Alt text for accessibility
    object_fit: "contain"     # CSS object-fit property
```

### Video Display

```yaml
- key: "video_url"
  type: "video"
  label: "Video"
  display_options:
    max_width: 800
    max_height: 450
    controls: true            # Show video controls
    autoplay: false           # Auto-play on load
    loop: false               # Loop playback
    muted: false              # Start muted
```

### Audio Display

```yaml
- key: "audio_url"
  type: "audio"
  label: "Audio"
  display_options:
    controls: true            # Show audio controls
    autoplay: false
    loop: false
    show_waveform: false      # Show waveform visualization
```

### Audio Dialogue Display

For a **diarized transcript played against its audio** — podcasts, interviews, meetings,
call-center recordings — use `audio_dialogue` rather than `audio` or `dialogue`. Turns
render as colored speaker bubbles; each has a ▶ that plays just that turn, and a sticky
transport bar plays the whole recording while highlighting and auto-scrolling the active
turn. Undiarized turns can be assigned a speaker by the annotator.

```yaml
- key: "conversation"
  type: "audio_dialogue"
  label: "Transcript"
  span_target: true              # enable span highlighting inside turns
  display_options:
    speakers:
      - {id: host,  name: Host,  color: "#7c3aed", side: left}
      - {id: guest, name: Guest, color: "#059669", side: right}
```

The transcript may be inline, or a path to a sidecar file in any of
[21 supported formats](multimedia/transcript_formats.md) — Whisper, WhisperX, cloud ASR,
SRT/WebVTT, YouTube captions, TextGrid/EAF:

```json
{"id": "int_001",
 "conversation": {"audio": "media/int_001.mp3", "transcript": "media/int_001.srt"}}
```

See [Audio Dialogue](multimedia/audio_dialogue.md) for every option, per-turn ratings,
cross-turn linking, and speaker assignment.

### Dialogue Display

For text-only conversations with no audio:

```yaml
- key: "conversation"
  type: "dialogue"
  label: "Conversation"
  display_options:
    alternating_shading: true    # Alternate background colors
    speaker_extraction: true     # Extract "Speaker:" from text
    show_turn_numbers: false     # Show turn numbers
    max_height: 600              # Cap the height and scroll inside it
```

A long agent trace otherwise pushes the annotation form off the bottom of the
page. `max_height` scrolls the container rather than clipping it, and takes a
number of pixels or any CSS length.

Data format for dialogue (each line in JSONL file):
```json
{"id": "conv_001", "conversation": ["Speaker A: Hello there!", "Speaker B: Hi, how are you?"]}
```

Or with structured data:
```json
{"id": "conv_001", "conversation": [{"speaker": "Alice", "text": "Hello there!"}, {"speaker": "Bob", "text": "Hi, how are you?"}]}
```

#### Threaded conversations

When each turn names the turn it replies to, `dialogue` renders the reply
structure — nesting depth is derived from `reply_to`, so nothing has to
precompute it:

```yaml
- key: "thread"
  type: "dialogue"
  label: "Discussion"
  display_options:
    indent_replies: true         # indent by reply depth
    max_indent_depth: 6          # cap the visual indent
    show_reply_lines: true       # vertical thread guides
    show_timestamps: true        # per-turn times
    timestamp_format: relative   # relative | absolute | epoch
    turn_meta_fields: [score]    # per-turn metadata chips
    meta_key: meta               # where that metadata lives
    depth_key: depth             # explicit depth, when the data has one
    reply_to_key: reply_to       # where the parent reference lives
```

```json
{"id": "t1", "thread": [
  {"id": "m1", "speaker": "ana", "text": "Anyone tried the new API?"},
  {"id": "m2", "speaker": "ben", "text": "Yes, works fine.", "reply_to": "m1"},
  {"id": "m3", "speaker": "cy", "text": "Not for me.", "reply_to": "m2"}
]}
```

The indentation, timestamps, and chips are drawn as CSS pseudo-element content,
so they do not affect span offsets. See
[Dialogue Annotation](structured/dialogue_annotation.md) for the full guide and
[ConvoKit](../integrations/convokit.md) for importing conversational corpora.

### Pairwise Display

```yaml
- key: "comparison"
  type: "pairwise"
  label: "Compare Options"
  display_options:
    cell_width: "auto"          # Cell width; "auto" splits the row evenly
    show_labels: true           # Show A/B labels
    labels: ["Option A", "Option B"]  # Custom labels
    vertical_on_mobile: true    # Stack vertically on mobile
```

## Layout Options

Control how multiple fields are arranged:

```yaml
instance_display:
  layout:
    direction: horizontal  # horizontal or vertical
    gap: 24px              # Space between fields
```

## Span Annotation Support

Text-based display types (`text`, `dialogue`) can be targets for span annotation. Mark a field as a span target:

```yaml
instance_display:
  fields:
    - key: "document"
      type: "text"
      span_target: true  # Enable span annotation on this field

annotation_schemes:
  - annotation_type: span
    name: entities
    labels: [PERSON, LOCATION, ORG]
```

### Multiple Span Targets

You can have multiple text fields that support span annotation:

```yaml
instance_display:
  fields:
    - key: "source_text"
      type: "text"
      label: "Source Document"
      span_target: true

    - key: "summary"
      type: "text"
      label: "Summary"
      span_target: true

annotation_schemes:
  - annotation_type: span
    name: factual_errors
    labels: [contradiction, unsupported, fabrication]
```

When multiple span targets are used, annotations are stored with field association:

```json
{
  "factual_errors": {
    "source_text": [],
    "summary": [
      {"start": 45, "end": 67, "label": "unsupported"}
    ]
  }
}
```

## Linking Annotation Schemas to Display Fields

For media annotation schemas (image_annotation, video_annotation, audio_annotation), you can link them to display fields using `source_field`:

```yaml
instance_display:
  fields:
    - key: "image_url"
      type: "image"

annotation_schemes:
  - annotation_type: image_annotation
    source_field: "image_url"  # Links to display field
    tools: [bbox]
    labels: [person, car]
```

Name it when there is more than one image field, or when the field the scheme
should draw on is not the one it would otherwise find. With a single image
field, `image_annotation` picks it up on its own.

## Example: Image Classification

A complete example showing image classification:

```yaml
annotation_task_name: "Image Classification"

data_files:
  - data/images.json

item_properties:
  id_key: id
  text_key: image_url

task_dir: .
output_annotation_dir: annotation_output

instance_display:
  fields:
    - key: image_url
      type: image
      label: "Image to Classify"
      display_options:
        max_width: 600
        zoomable: true

    - key: context
      type: text
      label: "Additional Context"
      display_options:
        collapsible: true

annotation_schemes:
  - annotation_type: radio
    name: category
    description: "What category best describes this image?"
    labels:
      - nature
      - urban
      - people
      - objects

user_config:
  allow_all_users: true
```

Sample data file (`data/images.json`) in JSONL format (one JSON object per line):
```json
{"id": "img_001", "image_url": "https://example.com/image1.jpg", "context": "Taken in summer 2023"}
{"id": "img_002", "image_url": "https://example.com/image2.jpg", "context": "Winter landscape"}
```

## Example: Multi-Modal Annotation

Video alongside a transcript with span annotation:

```yaml
annotation_task_name: "Video Analysis"

instance_display:
  layout:
    direction: horizontal
    gap: 24px

  fields:
    - key: video_url
      type: video
      label: "Video"
      display_options:
        max_width: "45%"

    - key: transcript
      type: text
      label: "Transcript"
      span_target: true

annotation_schemes:
  - annotation_type: radio
    name: sentiment
    labels: [positive, neutral, negative]

  - annotation_type: span
    name: highlights
    labels:
      - key_point
      - question
      - supporting_evidence
```

## Backwards Compatibility

- Existing configs without `instance_display` continue to work unchanged
- The `text_key` from `item_properties` is still used as fallback
- Legacy media detection via annotation schemes still works

## Migration from Display-Only Patterns

If you were using annotation schemas just to display content:

**Before (deprecated):**
```yaml
annotation_schemes:
  - annotation_type: image_annotation
    name: image_display
    min_annotations: 0
    tools: [bbox]
    labels: [unused]
```

**After (recommended):**
```yaml
instance_display:
  fields:
    - key: image_url
      type: image
```

You will see a deprecation warning in the logs when using the old pattern.

## Troubleshooting

### Missing Field Error

If you see an error like:
```
InstanceDisplayError: Display field 'image_url' not found in instance data.
Available fields: ['id', 'text', 'other_field']
```

This means your data doesn't have the field specified in `instance_display.fields`. Check:
1. The `key` matches exactly with your data field name
2. Your data file includes the required field
3. There are no typos in field names

### Image Not Displaying

1. Check that the URL is accessible (try opening it in a browser)
2. Ensure the URL is complete (includes http:// or https://)
3. Check browser console for CORS errors

### Span Annotation Not Working

1. Verify the field has `span_target: true`
2. Ensure the field type supports span annotation (`text` or `dialogue`)
3. Check that a `span` annotation scheme is defined

## Advanced Features

### Per-Turn Dialogue Ratings

You can add inline rating widgets to individual dialogue turns, allowing annotators to rate specific speakers' turns directly within the conversation view.

```yaml
instance_display:
  fields:
    - key: conversation
      type: dialogue
      label: "Conversation"
      display_options:
        show_turn_numbers: true
        per_turn_ratings:
          speakers: ["Agent"]          # Only show ratings for these speakers
          schema_name: "turn_quality"  # Name for the stored annotation data
          scheme:
            type: likert
            size: 5                    # Number of rating points (1-5)
            labels: ["Poor", "Excellent"]  # Min and max labels
```

**How it works:**
- Rating circles appear inline below each matching speaker's turn
- Clicking a value selects it (clicking again deselects)
- Ratings fill up to the selected value (1-2-3 all highlight if you click 3)
- All per-turn ratings are stored as a single JSON object: `{"0": 4, "2": 5, "4": 3}` where keys are turn indices
- The data is saved under the `schema_name` specified in the config

**Data format for per-turn ratings:**
```json
{
  "turn_quality": "{\"0\": 4, \"2\": 5, \"4\": 3}"
}
```

### Custom Layouts with Instance Display

Instance display works alongside custom layout files for maximum flexibility. The display content (images, text, dialogues) renders separately above the annotation forms, which you can fully customize with CSS:

```yaml
# Display content
instance_display:
  layout:
    direction: horizontal
    gap: 20px
  fields:
    - key: image_url
      type: image
    - key: notes
      type: text

# Custom annotation layout
task_layout: layouts/custom_task_layout.html

# Annotation schemes (rendered by custom layout)
annotation_schemes:
  - annotation_type: radio
    name: category
    labels: [A, B, C]
```

See the [Layout Customization Guide](../configuration/layout_customization.md) for details on creating custom layouts.

### Example Projects

Ready-to-run examples demonstrating advanced instance display usage:

```bash
# Content moderation with image + text side by side
python potato/flask_server.py start examples/custom-layouts/content-moderation/config.yaml -p 8000

# Dialogue QA with per-turn ratings
python potato/flask_server.py start examples/custom-layouts/dialogue-qa/config.yaml -p 8000

# Medical review with horizontal image + notes
python potato/flask_server.py start examples/custom-layouts/medical-review/config.yaml -p 8000
```

See `examples/custom-layouts/` for the complete source of each example.
