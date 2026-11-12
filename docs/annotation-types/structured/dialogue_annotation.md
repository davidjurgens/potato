# Dialogue and List Annotation

Potato supports annotation of multi-item data where each instance contains a list of text elements. This is commonly used for:
- **Dialogue annotation**: Conversations with multiple turns
- **Pairwise comparison**: Comparing two or more text variants
- **Multi-document tasks**: Rating or labeling multiple related texts

## Data Format

### Input Data

Multi-item data is represented as a list of strings in the `text` field:

```json
{"id": "conv_001", "text": ["Tom: Isn't this awesome?!", "Sam: Yes! I like you!", "Tom: Great!", "Sam: Awesome! Let's party!"]}
{"id": "conv_002", "text": ["Tom: I am so sorry for that", "Sam: No worries", "Tom: Thanks for your understanding!"]}
```

Each string in the list represents one item (e.g., a dialogue turn, a document variant, etc.).

## Configuration

### Basic Setup

```yaml
# Data configuration
data_files:
  - data/dialogues.json

item_properties:
  id_key: id
  text_key: text

# Configure list display
list_as_text:
  text_list_prefix_type: none  # No prefix since speaker names are in text
  alternating_shading: true    # Shade every other turn for readability

# Annotation schemes
annotation_schemes:
  - annotation_type: radio
    name: sentiment
    description: "What is the overall sentiment of this conversation?"
    labels:
      - positive
      - neutral
      - negative
```

### Display Options

The `list_as_text` configuration controls how list items are displayed:

```yaml
list_as_text:
  text_list_prefix_type: alphabet  # Prefix type for items
  horizontal: false                # Layout direction
  alternating_shading: false       # Shade alternate turns
```

#### Prefix Types

| Option | Example | Best For |
|--------|---------|----------|
| `alphabet` | A. B. C. | Pairwise comparisons, options |
| `number` | 1. 2. 3. | Sequential turns, ordered lists |
| `bullet` | • • • | Unordered items |
| `none` | (no prefix) | Dialogue with speaker names in text |

#### Layout Options

| Option | Description |
|--------|-------------|
| `horizontal: false` | Vertical layout (default) - items stacked vertically |
| `horizontal: true` | Side-by-side layout - for pairwise comparison |
| `alternating_shading: true` | Shades every other turn for dialogue readability |

## Threaded conversations

Discussions branch. A forum thread, a GitHub review, a mailing list, a Wikipedia
talk page, a Reddit thread — in all of them a reply answers *a specific message*,
not simply the one above it, and a flat list hides who is answering whom.

Turn on `indent_replies` and the `dialogue` display renders the reply structure:

```yaml
- key: thread
  type: dialogue
  label: "Discussion"
  span_target: true
  display_options:
    indent_replies: true
    show_reply_lines: true
    show_timestamps: true
    timestamp_format: relative
    turn_meta_fields: [score]
```

All the data needs is a way to say what each turn replies to:

```json
{"thread": [
  {"id": "m1", "speaker": "ana", "text": "Anyone tried the new API?"},
  {"id": "m2", "speaker": "ben", "text": "Yes, works fine.", "reply_to": "m1"},
  {"id": "m3", "speaker": "cy",  "text": "Not for me.",      "reply_to": "m2"},
  {"id": "m4", "speaker": "dee", "text": "Same here.",       "reply_to": "m1"}
]}
```

Nesting depth is **derived from `reply_to`** — nothing has to precompute it. The
identity of a turn is read from `turn_id`, `step_id`, or `id`, whichever is
present, so data shaped for Potato's turn annotations, for its trace displays, or
written by hand all work unchanged. A turn whose parent is missing from the
rendered set, and a reply cycle, both resolve to depth 0 rather than failing.

If your data *does* carry a depth (because it was sliced out of a larger thread
whose parents are not present), an explicit `depth` on any turn is used as-is.

### Threading options

| Option | Default | Description |
|---|---|---|
| `indent_replies` | `false` | Indent each turn by its reply depth |
| `max_indent_depth` | `6` | Cap the visual indent; the true depth is still reported |
| `show_reply_lines` | `true` | Vertical thread guides between nested turns |
| `show_timestamps` | `false` | Show each turn's time |
| `timestamp_format` | `relative` | `relative` (`+2h` from the first turn), `absolute`, or `epoch` |
| `turn_meta_fields` | `null` | Metadata keys to surface as per-turn chips |
| `meta_key` | `meta` | Where per-turn metadata lives on each turn |
| `depth_key` | `depth` | Where an explicit depth lives, if any |
| `reply_to_key` | `reply_to` | Where the parent reference lives |

The last three exist so a source that calls its metadata `attributes` or its
parent link `in_reply_to` works without being renamed first.

### Annotating a threaded conversation

A thread supports the full range of annotation at once, on the same field:

```yaml
annotation_schemes:
  # the whole thread
  - annotation_type: radio
    name: outcome
    description: "How does this thread resolve?"
    labels: [consensus, unresolved, escalated]

  # one label per comment
  - annotation_type: radio
    name: comment_type
    description: "Type"
    labels: [proposal, objection, support, question]
    turn_level: true
    turn_binding: {field: thread}

  # one rating per comment
  - annotation_type: likert
    name: persuasiveness
    description: "Persuasiveness"
    size: 5
    turn_level: true
    turn_binding: {field: thread}

  # a note per comment, tucked into a drawer
  - annotation_type: text
    name: comment_note
    description: "Note"
    turn_level: true
    turn_binding: {field: thread, placement: drawer}

  # spans anywhere in the thread
  - annotation_type: span
    name: evidence
    labels: [claim, evidence, concession]

  # links between spans in DIFFERENT comments
  - annotation_type: span_link
    name: argument_links
    span_schema: evidence
    link_types:
      - {name: rebuts, directed: true}
```

Per-comment schemes accept `radio`, `multiselect`, `likert`, `slider`, `select`,
`text`, and `number` — see
[turn-level annotation](../../agent-evaluation/turn_level_annotation.md) for the
binding filters (by speaker, agent, step type, tool, or turn range).

!!! info "Spans and per-comment widgets coexist"
    Span offsets are measured against the field's text with the per-turn widget
    subtrees excluded, so adding widgets to a comment never shifts a span. Spans
    are scoped to the field rather than to a turn, which is also what lets a
    `span_link` join two spans in different comments.

### Why the threading chrome is invisible to spans

Indentation, timestamps, depth badges, and metadata chips are drawn entirely as
CSS pseudo-element content from data attributes. None of them adds a text node,
so none of them changes the text that span offsets are measured against.

This is a hard constraint, not a stylistic choice. If you extend the display,
keep new decoration in `::before`/`::after` `content` or add
`data-span-offset-skip` to the element — do not introduce elements containing
text inside a span target. `tests/unit/test_dialogue_span_contract.py` enforces
it.

### Dialogue with Alternating Shading

For conversations, use `alternating_shading` to visually distinguish turns:

```yaml
list_as_text:
  text_list_prefix_type: none
  alternating_shading: true
```

This displays dialogue turns with alternating background colors and left borders, making it easy to follow the conversation flow.

### Pairwise Comparison Layout

For comparing two or more text variants, use horizontal layout:

```yaml
list_as_text:
  text_list_prefix_type: alphabet
  horizontal: true
```

This displays options side-by-side in styled containers, each with a distinct left border color.

## Example Configurations

### Dialogue Annotation

```yaml
annotation_task_name: Dialogue Analysis

data_files:
  - data/dialogues.json

item_properties:
  id_key: id
  text_key: text

list_as_text:
  text_list_prefix_type: none
  alternating_shading: true

annotation_schemes:
  - annotation_type: span
    name: certainty
    description: Highlight phrases that express certainty or uncertainty
    labels:
      - certain
      - uncertain
    sequential_key_binding: true

  - annotation_type: radio
    name: sentiment
    description: What kind of sentiment does the conversation hold?
    labels:
      - positive
      - neutral
      - negative
    sequential_key_binding: true
```

### Pairwise Text Comparison

```yaml
annotation_task_name: Text Comparison

data_files:
  - data/pairs.json

item_properties:
  id_key: id
  text_key: text

list_as_text:
  text_list_prefix_type: alphabet
  horizontal: true

annotation_schemes:
  - annotation_type: radio
    name: preference
    description: Which text is better?
    labels:
      - A is better
      - B is better
      - Equal
```

## Working Example

A complete working example is available in the [potato-showcase](https://github.com/davidjurgens/potato-showcase) repository under `dialogue_analysis/`:

```bash
# Clone the showcase repo for paper-specific examples
git clone https://github.com/davidjurgens/potato-showcase.git
cd potato-showcase/dialogue_analysis/configs
python ../../../potato/flask_server.py start dialogue-analysis.yaml -p 8000
```

Then open [http://localhost:8000](http://localhost:8000) in your browser.

**Sample data format** (`data_files/dialogue-example.json`):
```json
{"id":"1","text":["Tom: Isn't this awesome?!", "Sam: Yes! I like you!", "Tom: great!", "Sam: Awesome! Let's party!"]}
{"id":"2","text":["Tom: I am so sorry for that", "Sam: No worries", "Tom: thanks for your understanding!"]}
```

## Tips

1. **Speaker Names**: Include speaker names in the text (e.g., "Tom: Hello") when using `text_list_prefix_type: none` for dialogue.

2. **Span Annotation**: When using span annotation with dialogue data, annotators can highlight text within any of the displayed turns.

3. **Prefix Choice**:
   - Use `none` for dialogue where speaker names are embedded in text
   - Use `number` when sequence order matters
   - Use `alphabet` for pairwise/comparison tasks

4. **Readability**: Enable `alternating_shading` for long dialogues to help annotators track which turn they're reading.

5. **Comparison Tasks**: Use `horizontal: true` with `alphabet` prefixes for side-by-side comparison of two text variants.
